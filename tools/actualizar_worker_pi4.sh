#!/usr/bin/env bash
# Copia worker/ del commit actual a la Pi4, reconstruye el worker y amazon-ar, y (opcional) reintenta en Amazon los productos sin precio de hoy.
# Uso (Git Bash, desde la raíz del repo): bash tools/actualizar_worker_pi4.sh [--reintentar]
set -euo pipefail
cd "$(dirname "$0")/.."
git archive HEAD worker | ssh pi4 "tar -x -C /home/claude/franquicia400"
ssh pi4 "cd /home/claude/franquicia400/worker && docker compose -p franquicia400 up -d --build weboffers-worker weboffers-amazon-ar 2>&1 | tail -4"
if [ "${1:-}" = "--reintentar" ]; then
  sleep 15
  ssh pi4 "docker exec -i -w /app/worker franquicia400-weboffers-worker-1 python -" < tools/reintento_amazon.py
fi
