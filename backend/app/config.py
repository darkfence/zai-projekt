"""Konfiguracja aplikacji wczytywana ze zmiennych środowiskowych."""
import os


def _bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")

    # Relacyjna baza konfiguracji (admin, tokeny, serie, czujniki)
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///zai-dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Magazyn wyników pomiarów: "influx" (produkcja) lub "memory" (testy, dev)
    MEASUREMENT_STORE = os.environ.get("MEASUREMENT_STORE", "influx")
    INFLUX_HOST = os.environ.get("INFLUX_HOST", "localhost")
    INFLUX_PORT = int(os.environ.get("INFLUX_PORT", "8086"))
    INFLUX_DB = os.environ.get("INFLUX_DB", "zai")
    INFLUX_USER = os.environ.get("INFLUX_USER", "")
    INFLUX_PASSWORD = os.environ.get("INFLUX_PASSWORD", "")

    # Czas ważności tokenu administratora (s)
    TOKEN_TTL = int(os.environ.get("TOKEN_TTL", "3600"))
    # Dopuszczalne wyprzedzenie znacznika czasu wyniku względem zegara serwera (s)
    FUTURE_TOLERANCE = int(os.environ.get("FUTURE_TOLERANCE", "300"))

    # Nagłówki bezpieczeństwa ustawia NGINX; Flask robi to tylko bez proxy (dev)
    SECURITY_HEADERS = _bool("SECURITY_HEADERS", False)
    # Liczba zaufanych proxy przed aplikacją (NGINX = 1)
    PROXY_COUNT = int(os.environ.get("PROXY_COUNT", "0"))

    # Plik logu błędów (odrzucone wyniki, błędy serwera); puste = tylko stderr
    ERROR_LOG = os.environ.get("ERROR_LOG", "")

    # Opcjonalny katalog ze stroną statyczną (dev bez NGINX)
    STATIC_DIR = os.environ.get("STATIC_DIR", "")
