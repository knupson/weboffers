#!/bin/sh
# Historia diaria automática de Franquicia 400 (17/11, opción A de Alejandro): la genera EN LA VM, la deja en la
# lista pública y la encola en la cola de Meta como tipo "historia"; meta_publicar.py (cron cada 5 min) la publica
# en Instagram y Facebook por la API Graph. Nunca por Business Suite ni Chrome (regla número uno de redes-proyectos).
# La API no pone sticker de enlace: el sitio va escrito en el video (composición Historia).
#
# Cron de la VM (lunes a viernes, 11:45 ART; publica 12:30, esqueleto semanal de la skill redes-proyectos):
#   45 11 * * 1-5 sh /opt/docker/franquicia400/tools/generar_y_encolar_historia.sh >> /home/claude/logs/historia-$(date +\%F).log 2>&1
# A mano:  sh generar_y_encolar_historia.sh           (12:30 de hoy; si ya pasó, en la próxima pasada)
#          sh generar_y_encolar_historia.sh --ahora   (próxima pasada de meta_publicar)
# Marcadores: HISTORIA_AUTO_INICIO, HISTORIA_AUTO_YA_ENCOLADA, HISTORIA_AUTO_FALLA <motivo>, HISTORIA_AUTO_ENCOLADA.
set -eu
R=/home/claude/reel
COLA=/home/claude/franquicia400-meta/cola_meta.json
LISTA=/opt/docker/blackseam/lista/descargas/redes
URL_BASE=https://lista.blackseam.knunet.com/descargas/redes
TS() { TZ=America/Argentina/Buenos_Aires date '+%Y-%m-%d %H:%M:%S'; }
HOY=$(TZ=America/Argentina/Buenos_Aires date +%F)
ID="historia-$(TZ=America/Argentina/Buenos_Aires date +%d-%m)"
AHORA=$(TZ=America/Argentina/Buenos_Aires date +%Y-%m-%dT%H:%M:00-03:00)
CUANDO="${HOY}T12:30:00-03:00"
if [ "${1:-}" = "--ahora" ] || [ "$(TZ=America/Argentina/Buenos_Aires date +%H%M)" -ge 1230 ]; then
    CUANDO="$AHORA"
fi
falla() { echo "$(TS) HISTORIA_AUTO_FALLA $*"; exit 1; }
MP4="$R/out/historia-$HOY-final.mp4"
URL="$URL_BASE/f400-$ID/$ID.mp4"

echo "$(TS) HISTORIA_AUTO_INICIO id=$ID cuando=$CUANDO"
if python3 -c 'import json,sys; sys.exit(0 if any(e.get("id") == sys.argv[2] for e in json.load(open(sys.argv[1]))) else 1)' "$COLA" "$ID"; then
    echo "$(TS) HISTORIA_AUTO_YA_ENCOLADA id=$ID"
    exit 0
fi

if [ ! -s "$MP4" ]; then
    sh "$R/codigo/hacer_reel_vm.sh" --historia || falla "hacer_reel_vm.sh --historia salió con error"
fi
[ -s "$MP4" ] || falla "no está la historia de hoy ($MP4)"
TAM=$(stat -c %s "$MP4")
[ "$TAM" -lt 100000000 ] || falla "la historia pesa $TAM bytes (tope de Meta: 100 MB)"

DESTINO="$LISTA/f400-$ID"
mkdir -p "$DESTINO"
cp "$MP4" "$DESTINO/$ID.mp4"
CODIGO=$(curl -s -o /dev/null -I -m 30 -w '%{http_code}' "$URL" || true)
[ "$CODIGO" = "200" ] || falla "la URL pública no responde 200 ($CODIGO): $URL"

python3 - "$COLA" "$ID" "$CUANDO" "$URL" <<'PY'
import json, os, sys
cola_path, pid, cuando, url = sys.argv[1:]
cola = json.load(open(cola_path, encoding="utf-8"))
cola = [e for e in cola if e.get("id") != pid] + [
    {"id": pid, "cuando": cuando, "tipo": "historia", "destinos": ["ig", "fb"], "media": [url],
     "texto_ig": "", "texto_fb": ""}]
cola.sort(key=lambda e: e.get("cuando", ""))
tmp = cola_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cola, f, ensure_ascii=False, indent=1)
os.replace(tmp, cola_path)
PY
echo "$(TS) HISTORIA_AUTO_ENCOLADA id=$ID cuando=$CUANDO url=$URL"
