"""Corrige la categoría de las altas automáticas con el dominio de la ficha de ML (05/11).

Dentro del worker, SIN una corrida de catálogo en curso (esa corrida reescribe catalog-auto.json al terminar):
  python /app/tools/corregir_categorias.py
"""
import json
import os
import sys

sys.path.insert(0, "/app/worker")
sys.path.insert(0, "/app")
import requests  # noqa: E402
import ml_prices  # noqa: E402
from tools.crecer_desde_ml import categoria_ml  # noqa: E402

p = "/app/output/catalog-auto.json"
datos = json.load(open(p, encoding="utf-8"))
H = {"Authorization": f"Bearer {ml_prices.get_token()}"}
for x in datos:
    cid = (x.get("ml") or {}).get("catalogId")
    if not cid:
        continue
    r = requests.get(f"{ml_prices.API_BASE_URL}/products/{cid}", headers=H, timeout=20)
    nueva = categoria_ml(r.json().get("domain_id")) if r.ok else ""
    if nueva and nueva != x.get("category"):
        print(f"{x['slug']}: {x.get('category')} -> {nueva}")
        x["category"] = nueva
json.dump(datos, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
os.replace(p + ".tmp", p)
