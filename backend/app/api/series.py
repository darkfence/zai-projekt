"""Serie pomiarowe: odczyt publiczny, zmiany wyłącznie dla administratora."""
from flask import jsonify

from ..errors import ApiError
from ..extensions import db
from ..models import Series
from ..security import admin_required
from ..validation import json_body, validate_series_input
from . import MAX_DB_ID, api, location, store


def get_series_or_404(series_id: int) -> Series:
    series = db.session.get(Series, series_id) if series_id <= MAX_DB_ID else None
    if series is None:
        raise ApiError(404, f"Seria {series_id} nie istnieje.")
    return series


@api.get("/series")
def list_series():
    return jsonify([s.to_dict() for s in Series.query.order_by(Series.id).all()])


@api.get("/series/<int:series_id>")
def get_series(series_id: int):
    return jsonify(get_series_or_404(series_id).to_dict())


@api.post("/series")
@admin_required
def create_series():
    fields = validate_series_input(json_body())
    series = Series(**fields)
    db.session.add(series)
    db.session.commit()
    resp = jsonify(series.to_dict())
    resp.status_code = 201
    return location(resp, f"/api/series/{series.id}")


@api.put("/series/<int:series_id>")
@admin_required
def update_series(series_id: int):
    series = get_series_or_404(series_id)
    fields = validate_series_input(json_body())
    current = store().value_range(series.id)
    if current is not None:
        lo, hi = current
        if lo < fields["min_value"] or hi > fields["max_value"]:
            raise ApiError(
                409,
                f"Nowy przedział [{fields['min_value']:g}, {fields['max_value']:g}] wyklucza zapisane wyniki "
                f"(zakres wartości w serii: [{lo:g}, {hi:g}]).",
            )
    for key, value in fields.items():
        setattr(series, key, value)
    db.session.commit()
    return jsonify(series.to_dict())


@api.delete("/series/<int:series_id>")
@admin_required
def delete_series(series_id: int):
    series = get_series_or_404(series_id)
    store().delete_series(series.id)   # najpierw wyniki w InfluxDB
    db.session.delete(series)          # potem seria (kaskadowo jej czujniki)
    db.session.commit()
    return "", 204
