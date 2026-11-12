#!/usr/bin/env bash
# Corre la suite de worker/ en la VM docker (nada de tests en la PC: regla de Alejandro, 07/11).
#
# Uso, desde la PC y en la raíz del repo:
#   bash tools/test_worker_vm.sh                 # toda la suite
#   bash tools/test_worker_vm.sh -k dudosos -x   # argumentos extra van a pytest
#
# Copia los archivos versionados (tal como están en el árbol de trabajo) a una carpeta limpia de la VM y corre
# pytest en una imagen derivada del worker con nodejs (tests del deployer: lanzan `node deploy.mjs`) y websockets
# (envio_ar_chrome). 12/11: en la imagen del worker solo faltaban esas dos cosas y fallaban 10 tests.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
DEST=/home/claude/tests-worker
cd "$ROOT"

ssh docker "rm -rf $DEST && mkdir -p $DEST"
git ls-files -z | tar --null -cf - -T - | ssh docker "tar -xf - -C $DEST"

ssh docker bash -s -- "$DEST" "$@" <<'REMOTO'
set -euo pipefail
DEST=$1; shift
BASE=$(docker inspect -f '{{.Config.Image}}' franquicia400-weboffers-worker-1)
# La capa se cachea: sólo se reconstruye si cambia la imagen del worker.
docker build -q -t franquicia400-tests - >/dev/null <<DOCKERFILE
FROM $BASE
RUN apt-get update -qq && apt-get install -y -qq nodejs >/dev/null && rm -rf /var/lib/apt/lists/* \
    && pip install -q pytest websockets
DOCKERFILE
docker run --rm -v "$DEST:/repo" -w /repo -e PYTHONDONTWRITEBYTECODE=1 franquicia400-tests \
    python -m pytest -q -p no:cacheprovider worker "$@"
REMOTO
