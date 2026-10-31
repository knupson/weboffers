#!/usr/bin/env bash
# Despliegue manual desde Windows (Git Bash). Baja los precios de ML del Pi y publica.
set -euo pipefail
cd "$(dirname "$0")/.."

# Si falla la descarga se usa el ml-prices.json que ya haya en data/.
# El archivo es de root (lo escribe el contenedor), por eso se lee con docker exec y no con scp.
if ssh pi4 'docker exec franquicia400-weboffers-worker-1 cat /app/output/ml-prices.json' > data/ml-prices.json.tmp \
  && [ -s data/ml-prices.json.tmp ]; then
  mv data/ml-prices.json.tmp data/ml-prices.json
else
  rm -f data/ml-prices.json.tmp
  echo "No se pudo bajar ml-prices.json del Pi; se usa el local (si existe)."
fi

npm run build
npx wrangler deploy
