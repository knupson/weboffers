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
# Sin modo explícito, el llamado independiente de confirmar_altas.sh usa alta.
if [ "${PUBLICACION_MODO+x}" != x ]; then
    PUBLICACION_MODO=verificacion
    for arg in "$@"; do
        [ "$arg" != "--pendientes" ] || PUBLICACION_MODO=alta
    done
fi
export PUBLICACION_MODO
HOY=$(TZ=America/Argentina/Buenos_Aires date +%F)
W=franquicia400-weboffers-worker-1
INICIO=$(date +%s)
# F-06: envio_ar_chrome.py anota cada ASIN leído en este archivo (dentro del contenedor) con fsync; si el relevamiento
# se corta (KILL, tope, caída), lo leído se fusiona igual en ar-chrome-AAAA-MM-DD.json y el reintento del día retoma.
PARCIAL="/tmp/ar-chrome-parcial-$HOY.jsonl"
# F-29: un KILL no corre el trap; los temporales de corridas anteriores se limpian al empezar.
find /tmp -maxdepth 1 -name 'ar-chrome-envio.*' -mmin +180 -delete 2>/dev/null || true
TMP=$(mktemp /tmp/ar-chrome-envio.XXXXXX)
trap 'rm -f "$TMP"' EXIT HUP INT TERM
guardar_parcial() {
    # Fusiona lo que un relevamiento cortado dejó leído y borra el parcial sólo si se guardó.
    if docker exec chrome-claude cat "$PARCIAL" > "$TMP" 2>/dev/null && [ -s "$TMP" ]; then
        echo "ENVIO_AR_CHROME_RECUPERO fusiono el relevamiento parcial $PARCIAL"
        docker exec -e PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}" -i -w /app/worker "$W" python3 /app/tools/altas_chrome.py guardar --fecha "$HOY" --jsonl < "$TMP"
        docker exec chrome-claude rm -f "$PARCIAL"
    fi
    : > "$TMP"
}
echo "ENVIO_AR_CHROME inicio"
# Lo que dejó una corrida anterior cortada se fusiona antes de listar: los ASIN ya leídos hoy no se piden de nuevo.
guardar_parcial
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
# F-17: el tope que manda la cadena corre desde que arrancó este script; lo gastado en listar, chequear CDP y
# reiniciar el contenedor se descuenta, con un margen para fusionar lo leído antes de que venza el tope externo.
TOPE=${CADENA_TIMEOUT:-3000}
MARGEN=$((TOPE / 10)); [ "$MARGEN" -le 30 ] || MARGEN=30
RESTA=$((TOPE - ($(date +%s) - INICIO) - MARGEN))
[ "$RESTA" -ge 1 ] || RESTA=1
# shellcheck disable=SC2086
set +e
docker exec -e PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}" -e AR_CHROME_PARCIAL="$PARCIAL" chrome-claude timeout -s KILL "$RESTA" python3 /tmp/envio_ar_chrome.py $ASINS > "$TMP"
RC=$?
set -e
if [ "$RC" -eq 0 ] && [ -s "$TMP" ]; then
    # Fusiona el relevamiento y conserva los otros ASIN del mismo día.
    docker exec -e PUBLICACION_MODO="${PUBLICACION_MODO:-verificacion}" -i -w /app/worker "$W" python3 /app/tools/altas_chrome.py guardar --fecha "$HOY" < "$TMP"
    docker exec chrome-claude rm -f "$PARCIAL"
else
    echo "ENVIO_AR_CHROME_CORTADO código=$RC tras $(($(date +%s) - INICIO)) s; se guarda lo leído hasta el corte"
    guardar_parcial
fi
rm -f "$TMP"
exit "$RC"
