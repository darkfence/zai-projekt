"""Walidacja treści żądań JSON.

Błędy składniowe (brak pola, zły typ) -> 400, błędy semantyczne (zakres,
format, reguły biznesowe) -> 422. Oba rodzaje zwracają listę `errors`.
"""
import math
import re

from flask import request

from .errors import ApiError

COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def json_body() -> dict:
    """Zwraca treść żądania jako obiekt JSON albo zgłasza 415/400."""
    mimetype = (request.mimetype or "").lower()
    if mimetype != "application/json" and not mimetype.endswith("+json"):
        raise ApiError(415, "Treść żądania musi mieć typ application/json.")
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError(400, "Treść żądania nie jest poprawnym dokumentem JSON.")
    if not isinstance(data, dict):
        raise ApiError(400, "Treść żądania musi być obiektem JSON.")
    return data


def is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Validator:
    """Zbiera błędy pól; `raise_if_any` wybiera 400 lub 422."""

    def __init__(self, data: dict):
        self.data = data
        self.errors: list[dict] = []
        self.syntax = False

    def fail(self, field: str, message: str, *, syntax: bool = False) -> None:
        self.errors.append({"field": field, "message": message})
        self.syntax = self.syntax or syntax

    def string(self, field: str, *, required: bool = True, min_len: int = 0, max_len: int | None = None,
               nullable: bool = False):
        if field not in self.data or (self.data[field] is None and nullable):
            if required and field not in self.data:
                self.fail(field, "Pole jest wymagane.", syntax=True)
            return None
        value = self.data[field]
        if not isinstance(value, str):
            self.fail(field, "Pole musi być napisem.", syntax=True)
            return None
        value = value.strip()
        if len(value) < min_len:
            self.fail(field, f"Pole musi mieć co najmniej {min_len} znak(ów).")
        elif max_len is not None and len(value) > max_len:
            self.fail(field, f"Pole może mieć co najwyżej {max_len} znaków.")
        return value

    def number(self, field: str, *, required: bool = True):
        if field not in self.data:
            if required:
                self.fail(field, "Pole jest wymagane.", syntax=True)
            return None
        value = self.data[field]
        if not is_number(value):
            self.fail(field, "Pole musi być skończoną liczbą.", syntax=True)
            return None
        return float(value)

    def ident(self, field: str):
        """Identyfikator: liczba całkowita lub napis z cyframi."""
        if field not in self.data:
            self.fail(field, "Pole jest wymagane.", syntax=True)
            return None
        value = self.data[field]
        if isinstance(value, bool):
            value = None
        elif isinstance(value, int):
            return value
        elif isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        self.fail(field, "Pole musi być identyfikatorem (liczbą całkowitą).", syntax=True)
        return None

    def raise_if_any(self) -> None:
        if self.errors:
            raise ApiError(400 if self.syntax else 422, "Dane wejściowe są niepoprawne.", errors=self.errors)


def validate_series_input(data: dict) -> dict:
    v = Validator(data)
    name = v.string("name", min_len=1, max_len=100)
    min_value = v.number("minValue")
    max_value = v.number("maxValue")
    color = v.string("color")
    if color is not None and not COLOR_RE.match(color):
        v.fail("color", "Kolor musi mieć format #RRGGBB.")
    icon = v.string("icon", required=False, max_len=50, nullable=True)
    unit = v.string("unit", required=False, max_len=20, nullable=True)
    if min_value is not None and max_value is not None and min_value >= max_value:
        v.fail("maxValue", "Wartość maxValue musi być większa od minValue.")
    v.raise_if_any()
    return {
        "name": name,
        "min_value": min_value,
        "max_value": max_value,
        "color": color.lower(),
        "icon": icon or None,
        "unit": unit or None,
    }
