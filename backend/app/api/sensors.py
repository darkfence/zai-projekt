"""Rejestracja, lista i wyrejestrowanie czujników (administrator)."""
from flask import jsonify

from ..errors import ApiError
from ..extensions import db
from ..models import Series, Sensor
from ..security import admin_required, new_secret, sha256_hex
from ..validation import Validator, json_body
from . import MAX_DB_ID, api, location


def get_sensor_or_404(sensor_id: int) -> Sensor:
    sensor = db.session.get(Sensor, sensor_id) if sensor_id <= MAX_DB_ID else None
    if sensor is None:
        raise ApiError(404, f"Czujnik {sensor_id} nie istnieje.")
    return sensor


@api.get("/sensors")
@admin_required
def list_sensors():
    return jsonify([s.to_dict() for s in Sensor.query.order_by(Sensor.id).all()])


@api.get("/sensors/<int:sensor_id>")
@admin_required
def get_sensor(sensor_id: int):
    return jsonify(get_sensor_or_404(sensor_id).to_dict())


@api.post("/sensors")
@admin_required
def register_sensor():
    v = Validator(json_body())
    name = v.string("name", min_len=1, max_len=100)
    series_id = v.ident("seriesId")
    v.raise_if_any()
    series = db.session.get(Series, series_id) if series_id <= MAX_DB_ID else None
    if series is None:
        raise ApiError(422, f"Seria {series_id} nie istnieje.",
                       errors=[{"field": "seriesId", "message": "Wskazana seria nie istnieje."}])

    api_key = new_secret()  # ujawniany jednorazowo, w bazie tylko skrót
    sensor = Sensor(name=name, series_id=series.id, api_key_hash=sha256_hex(api_key))
    db.session.add(sensor)
    db.session.commit()
    resp = jsonify({**sensor.to_dict(), "apiKey": api_key})
    resp.status_code = 201
    resp.headers["Cache-Control"] = "no-store"
    return location(resp, f"/api/sensors/{sensor.id}")


@api.delete("/sensors/<int:sensor_id>")
@admin_required
def unregister_sensor(sensor_id: int):
    db.session.delete(get_sensor_or_404(sensor_id))  # wyniki w InfluxDB pozostają
    db.session.commit()
    return "", 204
