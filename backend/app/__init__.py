"""Fabryka aplikacji Flask – API projektu „Serie pomiarowe” (ZAI 26Z)."""
import logging
import os
import sys

from dotenv import load_dotenv
from flask import Flask, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .config import Config
from .errors import register_error_handlers
from .extensions import db, migrate
from .measurements_store import create_store

SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; object-src 'none'; "
                               "base-uri 'self'; form-action 'self'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


def _configure_logging(app: Flask) -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root = logging.getLogger("zai")
    root.setLevel(logging.INFO)
    if not root.handlers:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        root.addHandler(stream)
        path = app.config.get("ERROR_LOG")
        if path:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            file_handler = logging.FileHandler(path, encoding="utf-8")
            file_handler.setLevel(logging.WARNING)
            file_handler.setFormatter(fmt)
            root.addHandler(file_handler)


def create_app(overrides: dict | None = None) -> Flask:
    load_dotenv()
    app = Flask(__name__, static_folder=None)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    _configure_logging(app)

    if app.config["PROXY_COUNT"]:
        n = app.config["PROXY_COUNT"]
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=n, x_proto=n, x_host=n)

    db.init_app(app)
    migrate.init_app(app, db, directory=os.path.join(os.path.dirname(__file__), "..", "migrations"))

    store = app.config.get("MEASUREMENT_STORE_INSTANCE") or create_store(app.config)
    app.extensions["measurement_store"] = store

    from . import models  # noqa: F401  (rejestracja modeli dla migracji)
    from .api import api
    from .cli import register_cli

    app.register_blueprint(api)
    register_error_handlers(app)
    register_cli(app)

    if app.config["SECURITY_HEADERS"]:
        @app.after_request
        def _security_headers(resp):
            for k, v in SECURITY_HEADERS.items():
                resp.headers.setdefault(k, v)
            return resp

    static_dir = app.config.get("STATIC_DIR")
    if static_dir:
        static_dir = os.path.abspath(static_dir)

        @app.get("/")
        def _index():
            return send_from_directory(static_dir, "index.html")

        @app.get("/<path:filename>")
        def _static(filename):
            return send_from_directory(static_dir, filename)

    return app
