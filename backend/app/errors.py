"""Błędy w formacie Problem Details (RFC 9457)."""
import logging

from flask import Response, json, request
from werkzeug.exceptions import HTTPException

log = logging.getLogger("zai.errors")

TITLES = {
    400: "Niepoprawne żądanie",
    401: "Brak uwierzytelnienia",
    403: "Brak uprawnień",
    404: "Nie znaleziono zasobu",
    405: "Metoda niedozwolona",
    406: "Nieakceptowalny format odpowiedzi",
    409: "Konflikt ze stanem zasobu",
    413: "Zbyt duża treść żądania",
    415: "Nieobsługiwany format treści",
    422: "Dane nie spełniają reguł",
    429: "Zbyt wiele żądań",
    500: "Wewnętrzny błąd serwera",
}


class ApiError(Exception):
    def __init__(self, status: int, detail: str | None = None, *, title: str | None = None,
                 errors: list[dict] | None = None, headers: dict | None = None):
        super().__init__(detail or title or str(status))
        self.status = status
        self.title = title or TITLES.get(status, "Błąd")
        self.detail = detail
        self.errors = errors
        self.headers = headers or {}


def problem(status: int, title: str | None = None, detail: str | None = None,
            errors: list[dict] | None = None, headers: dict | None = None) -> Response:
    body = {"type": "about:blank", "title": title or TITLES.get(status, "Błąd"), "status": status}
    if detail:
        body["detail"] = detail
    body["instance"] = request.path
    if errors:
        body["errors"] = errors
    resp = Response(json.dumps(body, ensure_ascii=False), status=status, mimetype="application/problem+json")
    for k, v in (headers or {}).items():
        resp.headers[k] = v
    return resp


def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return problem(e.status, e.title, e.detail, e.errors, e.headers)

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        headers = {k: v for k, v in e.get_headers() if k.lower() != "content-type"}
        return problem(e.code or 500, TITLES.get(e.code), None, None, headers)

    @app.errorhandler(Exception)
    def _unexpected(e: Exception):
        log.exception("Nieobsłużony wyjątek podczas %s %s", request.method, request.path)
        return problem(500)
