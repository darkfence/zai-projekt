#!/bin/sh
# Migracje bazy, inicjalizacja InfluxDB i (opcjonalnie) konto administratora przed startem serwera.
set -e

retry() {
  n=0
  until "$@"; do
    n=$((n + 1))
    if [ "$n" -ge 30 ]; then echo "Nie powiodło się: $*" >&2; exit 1; fi
    echo "Oczekiwanie na zależności ($n/30)…" >&2
    sleep 2
  done
}

retry flask db upgrade
retry flask init-influx
if [ -n "$ADMIN_PASSWORD" ]; then
  flask create-admin --if-missing
fi

exec "$@"
