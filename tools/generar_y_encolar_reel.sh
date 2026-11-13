#!/bin/sh
# Reel diario automático de Franquicia 400 (13/11): genera el Reel del día EN LA VM, lo deja en la lista pública
# y lo encola en la cola de Meta, sin scp desde la PC. meta_publicar.py (cron cada 5 min) lo publica en IG y FB.
#
# Cron de la VM (18:15 ART, todos los días):
#   15 18 * * * sh /opt/docker/franquicia400/tools/generar_y_encolar_reel.sh >> /home/claude/logs/reel-$(date +\%F).log 2>&1
# A mano:  sh generar_y_encolar_reel.sh            (publica a las 19:00 de hoy)
#          sh generar_y_encolar_reel.sh --ahora    (publica en la próxima pasada de meta_publicar)
#
# Pasos: 1) si el Reel de hoy ya está en la cola, no hace nada; 2) hacer_reel_vm.sh (precios y fotos del último deploy,
# nunca precios viejos); 3) copia el mp4 a la lista de Blackseam y verifica que la URL pública dé 200 (Meta lo descarga
# de ahí); 4) upsert en cola_meta.json con el caption de hacer_reel.py (IG) y su versión para FB (link con UTM).
# Marcadores de log: REEL_AUTO_INICIO, REEL_AUTO_YA_ENCOLADO, REEL_AUTO_FALLA <motivo>, REEL_AUTO_ENCOLADO.
set -eu
R=/home/claude/reel
COLA=/home/claude/franquicia400-meta/cola_meta.json
LISTA=/opt/docker/blackseam/lista/descargas/redes
URL_BASE=https://lista.blackseam.knunet.com/descargas/redes
TS() { TZ=America/Argentina/Buenos_Aires date '+%Y-%m-%d %H:%M:%S'; }
HOY=$(TZ=America/Argentina/Buenos_Aires date +%F)
ID="reel-$(TZ=America/Argentina/Buenos_Aires date +%d-%m)"
if [ "${1:-}" = "--ahora" ]; then
    CUANDO=$(TZ=America/Argentina/Buenos_Aires date +%Y-%m-%dT%H:%M:00-03:00)
else
    CUANDO="${HOY}T19:00:00-03:00"
fi
falla() { echo "$(TS) REEL_AUTO_FALLA $*"; exit 1; }

echo "$(TS) REEL_AUTO_INICIO id=$ID cuando=$CUANDO"
if python3 -c 'import json,sys; sys.exit(0 if any(e.get("id") == sys.argv[2] for e in json.load(open(sys.argv[1]))) else 1)' "$COLA" "$ID"; then
    echo "$(TS) REEL_AUTO_YA_ENCOLADO id=$ID (no se genera otro: consumiría productos del historial)"
    exit 0
fi

sh "$R/codigo/hacer_reel_vm.sh" || falla "hacer_reel_vm.sh salió con error"
MP4="$R/out/duelo-$HOY-final.mp4"
TXT="$R/out/duelo-$HOY.txt"
[ -s "$MP4" ] && [ -s "$TXT" ] || falla "no está el Reel de hoy ($MP4 / $TXT)"

DESTINO="$LISTA/f400-$ID"
mkdir -p "$DESTINO"
cp "$MP4" "$DESTINO/$ID.mp4"
URL="$URL_BASE/f400-$ID/$ID.mp4"
CODIGO=$(curl -s -o /dev/null -I -m 30 -w '%{http_code}' "$URL" || true)
[ "$CODIGO" = "200" ] || falla "la URL pública no responde 200 ($CODIGO): $URL"

python3 - "$COLA" "$ID" "$CUANDO" "$URL" "$TXT" <<'PY'
import json, os, sys
cola_path, pid, cuando, url, txt = sys.argv[1:]
texto_ig = open(txt, encoding="utf-8").read()
# Facebook sí admite links: «link en la bio» pasa a la URL con UTM y quedan 3 hashtags (igual que reel-11-11).
utm = f"https://ofertas.knunet.com/?utm_source=facebook&utm_medium=social&utm_campaign={pid}"
texto_fb = texto_ig.replace("link en la bio.", utm + ".").replace(
    "#amazonargentina #mercadolibre #comprasalexterior #franquicia400 #tecnologia",
    "#amazonargentina #mercadolibre #franquicia400")
if utm not in texto_fb:
    sys.exit("REEL_AUTO_FALLA el caption no trae «link en la bio.»: no se arma el texto de Facebook")
cola = json.load(open(cola_path, encoding="utf-8"))
cola = [e for e in cola if e.get("id") != pid] + [
    {"id": pid, "cuando": cuando, "tipo": "reel", "destinos": ["ig", "fb"], "media": [url],
     "texto_ig": texto_ig, "texto_fb": texto_fb}]
cola.sort(key=lambda e: e.get("cuando", ""))
tmp = cola_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cola, f, ensure_ascii=False, indent=1)
os.replace(tmp, cola_path)
PY
echo "$(TS) REEL_AUTO_ENCOLADO id=$ID cuando=$CUANDO url=$URL"
