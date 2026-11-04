from flask import Blueprint, current_app, request

from ..errors import ApiError
from ..measurements_store import MeasurementStore

api = Blueprint("api", __name__, url_prefix="/api")

_ACCEPTABLE = ["application/json", "application/problem+json"]

# Największa wartość klucza głównego typu INTEGER w PostgreSQL
MAX_DB_ID = 2**31 - 1


@api.before_request
def _negotiate_content():
    """Kod 406, gdy klient akceptuje wyłącznie formaty inne niż JSON."""
    if request.headers.get("Accept") and request.accept_mimetypes.best_match(_ACCEPTABLE) is None:
        raise ApiError(406, "API zwraca wyłącznie application/json.")


def store() -> MeasurementStore:
    return current_app.extensions["measurement_store"]


def location(resp, path: str):
    resp.headers["Location"] = path
    return resp


from . import auth, health, measurements, sensors, series  # noqa: E402,F401
