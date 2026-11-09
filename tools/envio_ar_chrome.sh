#!/bin/sh
# Relevamiento diario del envío a Argentina con el Chrome de la VM (contexto anónimo, sin cuenta). 05/11.
# La cadena tools/cadena.py lo llama desde las 03:30 ART; también funciona independiente.
# Deja /app/output/ar-chrome-AAAA-MM-DD.json en el worker; amazon_prices.py lo usa antes que el servicio amazon-ar.
# Log: /home/claude/logs/envio_ar_chrome.log (el vigía lo puede leer).
set -eu
# Un lector sin pipeline conserva el código de salida y fecha stdout y stderr.
if [ "${1:-}" != "--con-horarios" ]; then
    exec python3 -u -c '
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess, sys
p = Path("/home/claude/logs/envio_ar_chrome.log")
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
HOY=$(TZ=America/Argentina/Buenos_Aires date +%F)
W=franquicia400-weboffers-worker-1
echo "ENVIO_AR_CHROME inicio"
# El modo selecciona el proceso; --pendientes incluye pendientes y no_revisar vencidos en alta.
ASINS=$(docker exec -e PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}" -w /app/worker "$W" python3 /app/tools/altas_chrome.py listar "$@")
if [ -z "$ASINS" ]; then
    echo "ENVIO_AR_CHROME_OK sin productos para relevar"
    exit 0
fi
# 08/11: el contenedor seguía arriba sin ningún proceso de Chrome (CDP 9222 cerrado) y la cadena
# de las 03:30 y la tras-alta fallaron con «Connection refused». Si no hay CDP, se reinicia el contenedor.
cdp() { docker exec -e PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}" chrome-claude curl -s -m3 http://127.0.0.1:9222/json/version >/dev/null 2>&1; }
if ! cdp; then
    echo "ENVIO_AR_CHROME_REINICIO chrome-claude sin CDP en 127.0.0.1:9222; reinicio el contenedor"
    docker restart chrome-claude >/dev/null
    i=0
    until cdp; do
        i=$((i + 1))
        [ "$i" -ge 40 ] && { echo "ENVIO_AR_CHROME_FALLA CDP sigue cerrado 120 s después del reinicio"; exit 1; }
        sleep 3
    done
    echo "ENVIO_AR_CHROME_REINICIO CDP arriba tras $((i * 3)) s"
fi
docker cp /opt/docker/franquicia400/tools/envio_ar_chrome.py chrome-claude:/tmp/envio_ar_chrome.py
docker cp /opt/docker/franquicia400/worker/article_log.py chrome-claude:/tmp/article_log.py
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT HUP INT TERM
# shellcheck disable=SC2086
docker exec -e PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}" chrome-claude timeout -s KILL "${CADENA_TIMEOUT:-3000}" python3 /tmp/envio_ar_chrome.py $ASINS > "$TMP"
# Fusiona el relevamiento y conserva los otros ASIN del mismo día.
docker exec -e PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}" -i -w /app/worker "$W" python3 /app/tools/altas_chrome.py guardar --fecha "$HOY" < "$TMP"
rm -f "$TMP"
