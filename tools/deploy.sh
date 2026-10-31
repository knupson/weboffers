#!/usr/bin/env bash
# Despliegue manual desde Windows (Git Bash). Baja los precios de ML y Amazon del Pi y publica.
set -euo pipefail
cd "$(dirname "$0")/.."

# Si falla la descarga se usa el archivo que ya haya en data/.
# Los archivos son de root (los escribe el contenedor), por eso se leen con docker exec y no con scp.
for f in ml-prices.json amazon-prices.json; do
  if ssh pi4 "docker exec franquicia400-weboffers-worker-1 cat /app/output/$f" > "data/$f.tmp" \
    && [ -s "data/$f.tmp" ]; then
    mv "data/$f.tmp" "data/$f"
  else
    rm -f "data/$f.tmp"
    echo "No se pudo bajar $f del Pi; se usa el local (si existe)."
  fi
done

npm run build
npx wrangler deploy
