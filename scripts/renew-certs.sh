#!/usr/bin/env bash
# Odnowienie certyfikatów (uruchamiane z crona, np. codziennie o 3:17):
#   17 3 * * * /opt/zai-projekt/scripts/renew-certs.sh >> /var/log/zai-renew.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm certbot renew --webroot -w /var/www/certbot --quiet
docker compose exec -T nginx nginx -s reload
