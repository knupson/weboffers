#!/bin/sh
# Relevamiento diario del envío a Argentina con el Chrome de la VM (contexto anónimo, sin cuenta). 05/11.
# Cron (VM docker, hora ART), antes de la corrida de Amazon de las 04:00:
#   30 3 * * * sh /opt/docker/franquicia400/tools/envio_ar_chrome.sh
# Deja /app/output/ar-chrome-AAAA-MM-DD.json en el worker; amazon_prices.py lo usa antes que el servicio amazon-ar.
# Log: /home/claude/logs/envio_ar_chrome.log (el vigía lo puede leer).
set -eu
exec >> /home/claude/logs/envio_ar_chrome.log 2>&1
HOY=$(TZ=America/Argentina/Buenos_Aires date +%F)
W=franquicia400-weboffers-worker-1
echo "$(date '+%F %T') ENVIO_AR_CHROME inicio"
ASINS=$(docker exec "$W" python3 -c "
import json
c = json.load(open('/app/data/catalog.json', encoding='utf-8'))
print(' '.join(p['asin'] for p in c if p.get('verified') and p.get('asin') and p.get('store') == 'US' and (p.get('ml') or {}).get('catalogId')))")
docker cp /opt/docker/franquicia400/tools/envio_ar_chrome.py chrome-claude:/tmp/envio_ar_chrome.py
TMP=$(mktemp)
# shellcheck disable=SC2086
docker exec chrome-claude timeout 3000 python3 /tmp/envio_ar_chrome.py $ASINS > "$TMP"
docker cp "$TMP" "$W:/app/output/ar-chrome-$HOY.json"
rm -f "$TMP"
docker exec "$W" python3 -c "
import json
d = json.load(open('/app/output/ar-chrome-$HOY.json'))
it = d['items'].values()
print('ENVIO_AR_CHROME_OK', len(d['items']), 'productos en', d['segundos'], 's: envia', sum(1 for x in it if x['ships'] is True),
      'gratis', sum(1 for x in d['items'].values() if x['free'] is True), 'no_envia', sum(1 for x in d['items'].values() if x['ships'] is False),
      'sin_dato', sum(1 for x in d['items'].values() if x['ships'] is None))"
