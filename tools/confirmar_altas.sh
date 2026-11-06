#!/bin/sh
# Desde el host: confirma sólo los pendientes de un alta forzada.
# Conserva el relevamiento completo de hoy y usa la misma promoción de la cadena.
set -eu
TOOLS=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sh "$TOOLS/envio_ar_chrome.sh" --pendientes
docker exec -w /app/worker franquicia400-weboffers-worker-1 \
    timeout -s KILL 300 python /app/tools/confirmar_altas.py
