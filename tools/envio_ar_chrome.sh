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
    child = subprocess.Popen(["sh", sys.argv[1], "--con-horarios"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in child.stdout:
        text = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M:%S") + " " + line.rstrip() + "\n"
        log.write(text)
        log.flush()
        print(text, end="", flush=True)
    sys.exit(child.wait())
' "$0"
fi
HOY=$(TZ=America/Argentina/Buenos_Aires date +%F)
W=franquicia400-weboffers-worker-1
echo "ENVIO_AR_CHROME inicio"
# Catálogo del repo + altas automáticas (catalog-auto.json): sin estas, un producto nuevo nunca tendría envío (05/11).
ASINS=$(docker exec -w /app/worker "$W" python3 -c "
from catalog import load_catalog
c = load_catalog('/app/data/catalog.json', '/app/output/catalog-auto.json')
slugs = {}
for p in c:
    if p.get('verified') and p.get('asin') and p.get('store') == 'US' and (p.get('ml') or {}).get('catalogId'):
        slugs.setdefault(p['asin'], []).append(p['slug'])
print(' '.join(asin + ':' + ','.join(names) for asin, names in slugs.items()))")
docker cp /opt/docker/franquicia400/tools/envio_ar_chrome.py chrome-claude:/tmp/envio_ar_chrome.py
docker cp /opt/docker/franquicia400/worker/article_log.py chrome-claude:/tmp/article_log.py
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT HUP INT TERM
# shellcheck disable=SC2086
docker exec chrome-claude timeout -s KILL "${CADENA_TIMEOUT:-3000}" python3 /tmp/envio_ar_chrome.py $ASINS > "$TMP"
docker cp "$TMP" "$W:/app/output/ar-chrome-$HOY.json"
rm -f "$TMP"
docker exec "$W" python3 -c "
import json, io
from pathlib import Path
from article_log import chrome_line
from catalog import load_catalog
from worker import DailyLog
d = json.load(open('/app/output/ar-chrome-$HOY.json'))
slugs = {}
for p in load_catalog('/app/data/catalog.json', '/app/output/catalog-auto.json'):
    if p.get('store') == 'US' and p.get('asin'):
        slugs.setdefault(p['asin'], []).append(p['slug'])
log = DailyLog(Path('/app/output/logs'), io.StringIO())
for asin, item in d['items'].items():
    log.write(chrome_line(slugs.get(asin, []), asin, item) + '\n')
it = d['items'].values()
print('ENVIO_AR_CHROME_OK', len(d['items']), 'productos en', d['segundos'], 's: envia', sum(1 for x in it if x['ships'] is True),
      'gratis', sum(1 for x in d['items'].values() if x['free'] is True), 'no_envia', sum(1 for x in d['items'].values() if x['ships'] is False),
      'sin_dato', sum(1 for x in d['items'].values() if x['ships'] is None))"
