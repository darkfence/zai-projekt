#!/usr/bin/env bash
# Wdrożenie bieżącego commita na VPS: archiwum git → /opt/zai-projekt → docker compose up.
#   scripts/deploy.sh [host-ssh]   (domyślnie: zai-projekt)
# Plik .env i katalog certbot/ na serwerze nie są nadpisywane.
set -euo pipefail
HOST="${1:-zai-projekt}"
DIR=/opt/zai-projekt
cd "$(dirname "$0")/.."
REV=$(git rev-parse --short HEAD)
echo "Wdrażanie ${REV} na ${HOST}:${DIR}"
git archive --format=tar HEAD | ssh "$HOST" "mkdir -p ${DIR} && tar -x -C ${DIR} && echo ${REV} > ${DIR}/REVISION"
ssh "$HOST" "cd ${DIR} && docker compose up -d --build --remove-orphans && docker image prune -f >/dev/null && docker compose ps"
