"""Anula confirmaciones de envío a Argentina erróneas (05/11: el relevamiento con Chrome leyó el envío de productos
patrocinados de la misma página). Corre DENTRO del worker:
  python /app/tools/anular_envios.py slug1 slug2 ...
Guarda copia de amazon-prices.json y aparta ar-chrome-<hoy>.json (contaminado) a ar-chrome-<hoy>.invalido.json.
"""
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

out = "/app/output"
hoy = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
p = os.path.join(out, "amazon-prices.json")
shutil.copy2(p, os.path.join(out, f"amazon-prices.antes-anular-{datetime.now():%H%M%S}.json"))
d = json.load(open(p, encoding="utf-8"))
for slug in sys.argv[1:]:
    quitado = (d.get("arShipping") or {}).pop(slug, None)
    (d.get("items", {}).get(slug) or {}).pop("shipsToAr", None)
    print("anulado", slug, quitado)
json.dump(d, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
os.replace(p + ".tmp", p)
chrome = os.path.join(out, f"ar-chrome-{hoy}.json")
if os.path.exists(chrome):
    os.replace(chrome, os.path.join(out, f"ar-chrome-{hoy}.invalido.json"))
    print("apartado", chrome)
