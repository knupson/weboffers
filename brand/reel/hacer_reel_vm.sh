#!/bin/sh
# Genera el Reel del día en la VM docker con los precios y fotos que publicó el deployer hoy.
# Uso (en la VM): sh hacer_reel_vm.sh            Reel (hacer_reel.py)
#                 sh hacer_reel_vm.sh --historia Historia del día (hacer_historia.py, 17/11)
#   /home/claude/reel/codigo     brand/reel de main (lo copia tools/reel_a_vm.sh o git archive)
#   /home/claude/reel/voz        es_AR-daniela-high.onnx + .onnx.json
#   /home/claude/reel/historial.json  historial persistente (sin repetir los últimos 6 Reels)
#   /home/claude/reel/historial-historias.json  sin repetir las últimas 10 historias
#   /home/claude/reel/out        salida: duelo-AAAA-MM-DD-final.mp4 y .txt / historia-AAAA-MM-DD-final.mp4 y .json
set -eu
R=/home/claude/reel
TS() { TZ=America/Argentina/Buenos_Aires date '+%Y-%m-%d %H:%M:%S'; }
echo "$(TS) REEL_INICIO"
rm -rf "$R/datos" && mkdir -p "$R/datos/data" "$R/datos/public" "$R/out"
# Precios del día y fotos: los mismos que usó el último deploy (nunca precios viejos: hacer_reel valida la fecha).
docker cp franquicia400-weboffers-deployer-1:/work/data/. "$R/datos/data/"
docker cp franquicia400-weboffers-deployer-1:/work/public/products "$R/datos/public/"
[ -f "$R/historial.json" ] || cp "$R/codigo/historial.json" "$R/historial.json"
[ -f "$R/historial-historias.json" ] || echo '[]' > "$R/historial-historias.json"
SCRIPT=hacer_reel.py
if [ "${1:-}" = "--historia" ]; then SCRIPT=hacer_historia.py; shift; fi
docker build -q -t franquicia400-reel "$R/codigo" >/dev/null
echo "$(TS) REEL_IMAGEN_OK"
docker run --rm \
  -v "$R/datos/data:/repo/data:ro" \
  -v "$R/datos/public/products:/repo/public/products:ro" \
  -v "$R/voz:/voz:ro" \
  -v "$R/historial.json:/repo/brand/reel/historial.json"   -v "$R/historial-historias.json:/repo/brand/reel/historial-historias.json" \
  -v "$R/out:/repo/brand/reel/out" \
  franquicia400-reel python3 "$SCRIPT" "$@"
echo "$(TS) REEL_FIN codigo=$?"
