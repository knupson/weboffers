#!/usr/bin/env bash
# Despliegue manual desde Windows (Git Bash). Baja los precios de ML y Amazon de la VM y publica.
set -euo pipefail
cd "$(dirname "$0")/.."

# Descargar ambos antes de reemplazar los archivos locales.
trap 'rm -f data/ml-prices.json.tmp data/amazon-prices.json.tmp' EXIT
for f in ml-prices.json amazon-prices.json; do
  if ! ssh docker "docker exec franquicia400-weboffers-worker-1 cat /app/output/$f" > "data/$f.tmp" || [ ! -s "data/$f.tmp" ]; then
    echo "No se pudo bajar $f de la VM; se aborta." >&2
    exit 1
  fi
done
node tools/validate-price-files.mjs data/ml-prices.json.tmp data/amazon-prices.json.tmp
for f in ml-prices.json amazon-prices.json; do
  mv "data/$f.tmp" "data/$f"
done

npm run build
npx wrangler deploy
