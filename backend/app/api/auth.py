"""Logowanie, wylogowanie i zmiana hasła administratora."""
from flask import g, jsonify

from ..errors import ApiError
from ..extensions import db
from ..models import Admin, AuthToken
from ..security import admin_required, hash_password, issue_token, password_needs_rehash, verify_password
from ..timeutil import utcnow
from ..validation import Validator, json_body
from . import api

MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 256


@api.post("/auth/login")
def login():
    v = Validator(json_body())
    username = v.string("username", min_len=1)
    password = v.data.get("password")
    if "password" not in v.data:
        v.fail("password", "Pole jest wymagane.", syntax=True)
    elif not isinstance(password, str) or not password:
        v.fail("password", "Pole musi być niepustym napisem.", syntax=True)
    if v.errors:
        raise ApiError(400, "Wymagane są pola username i password.", errors=v.errors)

    admin = Admin.query.filter_by(username=username).first()
    if not verify_password(admin.password_hash if admin else None, password):
        raise ApiError(401, "Niepoprawna nazwa użytkownika lub hasło.")
    if password_needs_rehash(admin.password_hash):
        admin.password_hash = hash_password(password)
    token, ttl = issue_token(admin)
    resp = jsonify(accessToken=token, tokenType="Bearer", expiresIn=ttl)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@api.post("/auth/logout")
@admin_required
def logout():
    g.token.revoked_at = utcnow()
    db.session.commit()
    return "", 204


@api.put("/auth/password")
@admin_required
def change_password():
    v = Validator(json_body())
    for field in ("currentPassword", "newPassword"):
        if field not in v.data:
            v.fail(field, "Pole jest wymagane.", syntax=True)
        elif not isinstance(v.data[field], str):
            v.fail(field, "Pole musi być napisem.", syntax=True)
    v.raise_if_any()

    admin: Admin = g.admin
    if not verify_password(admin.password_hash, v.data["currentPassword"]):
        raise ApiError(403, "Bieżące hasło jest niepoprawne.")
    new = v.data["newPassword"]
    if len(new) < MIN_PASSWORD_LENGTH:
        v.fail("newPassword", f"Nowe hasło musi mieć co najmniej {MIN_PASSWORD_LENGTH} znaków.")
    elif len(new) > MAX_PASSWORD_LENGTH:
        v.fail("newPassword", f"Nowe hasło może mieć co najwyżej {MAX_PASSWORD_LENGTH} znaków.")
    v.raise_if_any()

    admin.password_hash = hash_password(new)
    # unieważnienie pozostałych sesji administratora (bieżąca pozostaje ważna)
    AuthToken.query.filter(AuthToken.admin_id == admin.id, AuthToken.id != g.token.id,
                           AuthToken.revoked_at.is_(None)).update({"revoked_at": utcnow()})
    db.session.commit()
    return "", 204
