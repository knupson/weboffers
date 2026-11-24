#!/bin/sh
# Precios de Mercado Libre leídos con el Chrome de la VM (24/11): la API da 403 «PolicyAgent» en /products/{id}/items.
# La cadena (tools/cadena.py) lo corre antes del paso «ml»; también funciona independiente.
# Deja /app/output/ml-chrome-AAAA-MM-DD.json en el worker; ml_prices.fetch_items lo usa antes que la API.
# Log: /home/claude/logs/ml_chrome.log (cada línea con hora ART).
set -eu
if [ "${1:-}" != "--con-horarios" ]; then
    exec python3 -u -c '
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess, sys
p = Path("/home/claude/logs/ml_chrome.log")
p.parent.mkdir(parents=True, exist_ok=True)
with p.open("a", encoding="utf-8") as log:
    child = subprocess.Popen(["sh", sys.argv[1], "--con-horarios", *sys.argv[2:]], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in child.stdout:
        text = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M:%S") + " " + line.rstrip() + "\n"
        log.write(text)
        log.flush()
        print(text, end="", flush=True)
    sys.exit(child.wait())
' "$0" "$@"
fi
shift
export PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}"
W=franquicia400-weboffers-worker-1
INICIO=$(date +%s)
TMP=$(mktemp /tmp/ml-chrome.XXXXXX)
trap 'rm -f "$TMP"' EXIT HUP INT TERM
echo "ML_CHROME inicio modo=$PUBLICACION_MODO"
IDS=$(docker exec -e PUBLICACION_MODO="$PUBLICACION_MODO" -w /app/worker "$W" python3 /app/tools/ml_chrome_listar.py listar)
if [ -z "$IDS" ]; then
    echo "ML_CHROME_OK sin catálogos para leer"
    exit 0
fi
cdp() { docker exec chrome-claude curl -s -m3 http://127.0.0.1:9222/json/version >/dev/null 2>&1; }
if ! cdp; then
    echo "ML_CHROME_REINICIO chrome-claude sin CDP en 127.0.0.1:9222; reinicio el contenedor"
    docker restart chrome-claude >/dev/null
    i=0
    until cdp; do
        i=$((i + 1))
        [ "$i" -ge 40 ] && { echo "ML_CHROME_FALLA CDP sigue cerrado 120 s después del reinicio"; exit 1; }
        sleep 3
    done
fi
docker cp /opt/docker/franquicia400/tools/ml_chrome.py chrome-claude:/tmp/ml_chrome.py
TOPE=${CADENA_TIMEOUT:-3600}
RESTA=$((TOPE - ($(date +%s) - INICIO) - 30))
[ "$RESTA" -ge 1 ] || RESTA=1
set +e
# shellcheck disable=SC2086
docker exec -e ML_CHROME_TOPE=$((RESTA - 90 > 30 ? RESTA - 90 : 30)) chrome-claude timeout -s KILL "$RESTA" python3 /tmp/ml_chrome.py $IDS > "$TMP"
RC=$?
set -e
if [ -s "$TMP" ]; then
    docker exec -e PUBLICACION_MODO="$PUBLICACION_MODO" -i -w /app/worker "$W" python3 /app/tools/ml_chrome_listar.py guardar < "$TMP"
fi
echo "ML_CHROME_FIN código=$RC segundos=$(($(date +%s) - INICIO))"
exit "$RC"
