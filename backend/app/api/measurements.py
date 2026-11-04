"""Wyniki pomiarów: zapis wyłącznie przez czujnik, odczyt publiczny."""
import logging
from datetime import timedelta

from flask import current_app, g, jsonify, request

from ..errors import ApiError
from ..extensions import db
from ..measurements_store import parse_measurement_id
from ..security import sensor_required
from ..timeutil import parse_iso, to_ns, utcnow
from ..validation import Validator, json_body
from . import api, location, store

log = logging.getLogger("zai.measurements")

DEFAULT_LIMIT = 1000
MAX_LIMIT = 10000


@api.post("/measurements")
@sensor_required
def create_measurement():
    sensor = g.sensor
    series = sensor.series
    v = Validator(json_body())
    value = v.number("value")
    ts = utcnow()
    if v.data.get("timestamp") is not None:
        ts = parse_iso(v.data["timestamp"])
        if ts is None:
            v.fail("timestamp", "Znacznik czasu musi być w formacie ISO 8601, np. 2026-10-15T08:30:00Z.", syntax=True)
    v.raise_if_any()

    now = utcnow()
    if ts > now + timedelta(seconds=current_app.config["FUTURE_TOLERANCE"]):
        log.warning("Odrzucono wynik z przyszłości: czujnik=%s seria=%s timestamp=%s",
                    sensor.id, series.id, ts.isoformat())
        raise ApiError(422, "Znacznik czasu nie może wyprzedzać czasu serwera o więcej niż 5 minut.",
                       errors=[{"field": "timestamp", "message": "Znacznik czasu z przyszłości."}])
    if not (series.min_value <= value <= series.max_value):
        log.warning("Odrzucono wynik spoza przedziału: czujnik=%s seria=%s wartość=%s przedział=[%s, %s]",
                    sensor.id, series.id, value, series.min_value, series.max_value)
        raise ApiError(
            422,
            f"Wartość {value:g} jest poza przedziałem serii „{series.name}” "
            f"[{series.min_value:g}, {series.max_value:g}].",
            title="Wartość spoza przedziału serii",
            errors=[{"field": "value", "message": "Wartość spoza dopuszczalnego przedziału serii."}],
        )

    point = store().write(series.id, sensor.id, value, to_ns(ts))
    sensor.last_measurement_at = now
    db.session.commit()
    resp = jsonify(point.to_dict())
    resp.status_code = 201
    return location(resp, f"/api/measurements/{point.id}")


def _bad_param(name: str, message: str) -> ApiError:
    return ApiError(400, message, errors=[{"field": name, "message": message}])


@api.get("/measurements")
def list_measurements():
    args = request.args

    series_ids = None
    raw_series = args.get("series", "").strip()
    if raw_series:
        parts = [p.strip() for p in raw_series.split(",") if p.strip()]
        if not parts or not all(p.isdigit() and len(p) <= 10 for p in parts):
            raise _bad_param("series", "Parametr series musi być listą identyfikatorów rozdzielonych przecinkami.")
        series_ids = sorted({int(p) for p in parts})

    bounds = {}
    for name in ("from", "to"):
        raw = args.get(name)
        if raw is None or raw == "":
            bounds[name] = None
            continue
        dt = parse_iso(raw)
        if dt is None:
            raise _bad_param(name, f"Parametr {name} musi być datą w formacie ISO 8601.")
        bounds[name] = to_ns(dt)
    if bounds["from"] is not None and bounds["to"] is not None and bounds["from"] > bounds["to"]:
        raise _bad_param("from", "Parametr from nie może być późniejszy niż to.")

    sort = args.get("sort", "timestamp")
    if sort not in ("timestamp", "-timestamp"):
        raise _bad_param("sort", "Parametr sort przyjmuje wartości timestamp lub -timestamp.")

    raw_limit = args.get("limit", str(DEFAULT_LIMIT))
    if not raw_limit.isdigit() or not (1 <= int(raw_limit) <= MAX_LIMIT):
        raise _bad_param("limit", f"Parametr limit musi być liczbą całkowitą z przedziału 1–{MAX_LIMIT}.")

    points = store().query(series_ids, bounds["from"], bounds["to"], sort == "-timestamp", int(raw_limit))
    return jsonify([p.to_dict() for p in points])


@api.get("/measurements/<measurement_id>")
def get_measurement(measurement_id: str):
    parsed = parse_measurement_id(measurement_id)
    point = store().get(*parsed) if parsed else None
    if point is None:
        raise ApiError(404, f"Wynik {measurement_id} nie istnieje.")
    return jsonify(point.to_dict())
