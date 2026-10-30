#!/usr/bin/env bash
# Despliegue manual desde Windows (Git Bash). Baja los precios de ML del Pi y publica.
set -euo pipefail
cd "$(dirname "$0")/.."

# Si falla la descarga se usa el ml-prices.json que ya haya en data/.
scp -q pi4:/home/claude/franquicia400/worker/output/ml-prices.json data/ml-prices.json \
  || echo "No se pudo bajar ml-prices.json del Pi; se usa el local (si existe)."

npm run build
npx wrangler deploy
