"""Minimalny klient HTTP (tylko biblioteka standardowa) wspólny dla narzędzi generatora."""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

USER_AGENT = "zai-sensor-emulator/1.0"


@dataclass
class Response:
    status: int
    body: object
    headers: dict

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def problem_text(self) -> str:
        """Czytelny opis błędu z treści Problem Details (RFC 9457)."""
        if isinstance(self.body, dict):
            parts = [str(self.body.get("title") or "")]
            if self.body.get("detail"):
                parts.append(str(self.body["detail"]))
            for err in self.body.get("errors") or []:
                parts.append(f"{err.get('field')}: {err.get('message')}")
            return " – ".join(p for p in parts if p)
        return str(self.body)[:200]


class ApiClient:
    def __init__(self, base_url: str, *, insecure: bool = False, timeout: float = 15.0):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self.ctx = ssl._create_unverified_context() if insecure else None

    def request(self, method: str, path: str, body=None, headers: dict | None = None) -> Response:
        h = {"Accept": "application/json", "User-Agent": USER_AGENT, **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx) as r:
                return Response(r.status, _decode(r.read()), dict(r.headers))
        except urllib.error.HTTPError as e:
            return Response(e.code, _decode(e.read()), dict(e.headers or {}))


def _decode(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode(errors="replace")
