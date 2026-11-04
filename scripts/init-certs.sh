#!/usr/bin/env bash
# Certyfikat TLS dla NGINX.
#   scripts/init-certs.sh self-signed   – certyfikat samopodpisany (lokalnie / start awaryjny)
#   scripts/init-certs.sh letsencrypt   – certyfikat Let's Encrypt (webroot), wymaga DOMAIN i LETSENCRYPT_EMAIL w .env
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

: "${LETSENCRYPT_EMAIL:?ustaw LETSENCRYPT_EMAIL w .env}"

# NGINX musi wystartować, by obsłużyć wyzwanie ACME – na start certyfikat tymczasowy
if [ ! -s "$LIVE/fullchain.pem" ]; then self_signed; fi
docker compose up -d nginx
rm -rf "certbot/conf/live/${DOMAIN}" "certbot/conf/archive/${DOMAIN}" "certbot/conf/renewal/${DOMAIN}.conf"

STAGING=()
if [ "${LETSENCRYPT_STAGING:-0}" = "1" ]; then STAGING=(--staging); fi

docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  -d "${DOMAIN}" --email "${LETSENCRYPT_EMAIL}" --agree-tos --no-eff-email --non-interactive "${STAGING[@]}"
docker compose exec nginx nginx -s reload
echo "Certyfikat Let's Encrypt dla ${DOMAIN} zainstalowany."
