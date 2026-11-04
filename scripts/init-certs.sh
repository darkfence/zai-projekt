#!/usr/bin/env bash
# Certyfikat TLS dla NGINX.
#   scripts/init-certs.sh self-signed   – certyfikat samopodpisany (lokalnie / start awaryjny)
#   scripts/init-certs.sh letsencrypt   – certyfikat Let's Encrypt (webroot); DOMAIN w .env,
#                                         LETSENCRYPT_EMAIL opcjonalny (puste = rejestracja bez e-maila)
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

MODE="${1:-letsencrypt}"
LIVE="certbot/conf/live/${DOMAIN}"
mkdir -p "$LIVE" certbot/www

self_signed() {
  openssl req -x509 -nodes -newkey rsa:2048 -days 30 \
    -keyout "$LIVE/privkey.pem" -out "$LIVE/fullchain.pem" -subj "/CN=${DOMAIN}" >/dev/null 2>&1
  echo "Utworzono certyfikat samopodpisany dla ${DOMAIN}."
}

if [ "$MODE" = "self-signed" ]; then
  self_signed
  exit 0
fi

# NGINX musi wystartować, by obsłużyć wyzwanie ACME – na start certyfikat tymczasowy
if [ ! -s "$LIVE/fullchain.pem" ]; then self_signed; fi
docker compose up -d nginx
rm -rf "certbot/conf/live/${DOMAIN}" "certbot/conf/archive/${DOMAIN}" "certbot/conf/renewal/${DOMAIN}.conf"

EXTRA=()
if [ "${LETSENCRYPT_STAGING:-0}" = "1" ]; then EXTRA+=(--staging); fi
if [ -n "${LETSENCRYPT_EMAIL:-}" ]; then EXTRA+=(--email "${LETSENCRYPT_EMAIL}" --no-eff-email)
else EXTRA+=(--register-unsafely-without-email); fi

docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  -d "${DOMAIN}" --agree-tos --non-interactive "${EXTRA[@]}"
docker compose exec nginx nginx -s reload
echo "Certyfikat Let's Encrypt dla ${DOMAIN} zainstalowany."
