#!/usr/bin/env bash
# Despliegue manual: lo hace el deployer de la VM, por el MISMO camino que el automático (05/11).
# Antes compilaba en la PC con data/catalog.json y sin catalog-auto.json: las altas automáticas no se publicaban.
# Uso (Git Bash, raíz del repo): bash tools/deploy.sh   (requiere el código ya pusheado a main)
set -euo pipefail
ssh docker "docker exec franquicia400-weboffers-deployer-1 node /app/deploy.mjs --ahora"
