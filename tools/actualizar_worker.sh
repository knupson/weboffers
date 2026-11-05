#!/usr/bin/env bash
# Copia worker/ del commit actual a la VM docker, reconstruye el worker y amazon-ar, y (opcional) reintenta en Amazon los productos sin precio de hoy.
# Uso (Git Bash, desde la raíz del repo): bash tools/actualizar_worker.sh [--reintentar]
set -euo pipefail
cd "$(dirname "$0")/.."
# El deployer de la VM clona `main`: si main queda atrás, el despliegue diario publica un catálogo viejo (05/11).
git push origin HEAD:main
git archive HEAD worker tools data/catalog.json | ssh docker "tar -x -C /opt/docker/franquicia400"
ssh docker "cd /opt/docker/franquicia400/worker && docker compose -p franquicia400 up -d --build weboffers-worker weboffers-amazon-ar weboffers-deployer 2>&1 | tail -4"
if [ "${1:-}" = "--reintentar" ]; then
  sleep 15
  ssh docker "docker exec -i -w /app/worker franquicia400-weboffers-worker-1 python -" < tools/reintento_amazon.py
fi
