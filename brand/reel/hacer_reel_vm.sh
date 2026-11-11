#!/bin/sh
# Genera el Reel del día en la VM docker con los precios y fotos que publicó el deployer hoy.
# Uso (en la VM): sh hacer_reel_vm.sh
#   /home/claude/reel/codigo     brand/reel de main (lo copia tools/reel_a_vm.sh o git archive)
#   /home/claude/reel/voz        es_AR-daniela-high.onnx + .onnx.json
#   /home/claude/reel/historial.json  historial persistente (sin repetir los últimos 6 Reels)
#   /home/claude/reel/out        salida: duelo-AAAA-MM-DD-final.mp4 y .txt
set -eu
R=/home/claude/reel
TS() { TZ=America/Argentina/Buenos_Aires date '+%Y-%m-%d %H:%M:%S'; }
echo "$(TS) REEL_INICIO"
rm -rf "$R/datos" && mkdir -p "$R/datos/data" "$R/datos/public" "$R/out"
# Precios del día y fotos: los mismos que usó el último deploy (nunca precios viejos: hacer_reel valida la fecha).
docker cp franquicia400-weboffers-deployer-1:/work/data/. "$R/datos/data/"
docker cp franquicia400-weboffers-deployer-1:/work/public/products "$R/datos/public/"
[ -f "$R/historial.json" ] || cp "$R/codigo/historial.json" "$R/historial.json"
docker build -q -t franquicia400-reel "$R/codigo" >/dev/null
echo "$(TS) REEL_IMAGEN_OK"
docker run --rm \
  -v "$R/datos/data:/repo/data:ro" \
  -v "$R/datos/public/products:/repo/public/products:ro" \
  -v "$R/voz:/voz:ro" \
  -v "$R/historial.json:/repo/brand/reel/historial.json" \
  -v "$R/out:/repo/brand/reel/out" \
  franquicia400-reel python3 hacer_reel.py
echo "$(TS) REEL_FIN codigo=$?"
