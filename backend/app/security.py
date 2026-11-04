"""Hasła (Argon2id), tokeny administratora i klucze API czujników.

* Hasła: argon2-cffi (Argon2id, losowa sól, parametry domyślne biblioteki).
* Tokeny Bearer i klucze API: `secrets.token_urlsafe(32)` (256 bitów, 43 znaki),
  w bazie wyłącznie skrót SHA-256, więc wyciek bazy nie ujawnia sekretów.
"""
import hashlib
import secrets
from datetime import timedelta
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from flask import current_app, g, request

from .errors import ApiError
from .extensions import db
from .models import Admin, AuthToken, Sensor
from .timeutil import as_utc, utcnow

_hasher = PasswordHasher()
# Skrót używany przy nieistniejącym loginie, by czas odpowiedzi był podobny
_DUMMY_HASH = _hasher.hash("dummy-password-for-timing")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def issue_token(admin: Admin) -> tuple[str, int]:
    ttl = current_app.config["TOKEN_TTL"]
    raw = new_secret()
    now = utcnow()
    # sprzątanie wygasłych tokenów tego administratora
    AuthToken.query.filter(AuthToken.admin_id == admin.id, AuthToken.expires_at < now).delete()
    db.session.add(AuthToken(admin_id=admin.id, token_hash=sha256_hex(raw), expires_at=now + timedelta(seconds=ttl)))
    db.session.commit()
    return raw, ttl


def _bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


def _unauthorized(detail: str) -> ApiError:
    return ApiError(401, detail, headers={"WWW-Authenticate": 'Bearer realm="zai"'})


def admin_required(view):
    """Wymaga ważnego, nieunieważnionego tokenu Bearer administratora."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        raw = _bearer_token()
        if raw is None:
            raise _unauthorized("Wymagany nagłówek Authorization: Bearer <token>.")
        token = AuthToken.query.filter_by(token_hash=sha256_hex(raw)).first()
        if token is None or token.revoked_at is not None or as_utc(token.expires_at) <= utcnow():
            raise _unauthorized("Token jest nieprawidłowy, wygasł lub został unieważniony.")
        g.admin = token.admin
        g.token = token
        return view(*args, **kwargs)

    return wrapper


def sensor_required(view):
    """Wymaga klucza API zarejestrowanego czujnika w nagłówku X-API-Key."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        raw = request.headers.get("X-API-Key", "").strip()
        if not raw:
            raise ApiError(401, "Wymagany nagłówek X-API-Key z kluczem czujnika.")
        sensor = Sensor.query.filter_by(api_key_hash=sha256_hex(raw)).first()
        if sensor is None:
            raise ApiError(401, "Klucz API czujnika jest nieprawidłowy lub czujnik został wyrejestrowany.")
        g.sensor = sensor
        return view(*args, **kwargs)

    return wrapper
