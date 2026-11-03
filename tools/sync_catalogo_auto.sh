#!/usr/bin/env bash
# Git Bash, desde Windows: absorbe las altas de la Pi4 sin credenciales Git remotas.
set -euo pipefail
cd "$(dirname "$0")/.."
sync_dir="$(mktemp -d)"
trap 'rm -rf -- "$sync_dir"' EXIT
ssh pi4 'cd /home/claude/franquicia400/worker/output && if [ -d products ]; then tar -cf - catalog-auto.json products; else tar -cf - catalog-auto.json; fi' | tar -xf - -C "$sync_dir"
python tools/sync_catalogo_auto.py "$sync_dir"
