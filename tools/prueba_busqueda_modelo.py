"""Prueba A/B (05/11, máx. 13 min): buscar en Amazon por MARCA + MODELO de la ficha de ML vs. por el nombre.

Mismos productos de ML que ya se buscaron por nombre (output/discovery-desde-ml.json); mismo validador.
Dentro del worker:  python /app/tools/prueba_busqueda_modelo.py
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, "/app/worker")
sys.path.insert(0, "/app")
import requests  # noqa: E402
import ml_prices  # noqa: E402
import rates  # noqa: E402
from catalog import load_catalog  # noqa: E402
from tools import discover_products as discovery  # noqa: E402
from tools import match_candidates as matching  # noqa: E402

LIMITE_S = 13 * 60
inicio = time.monotonic()
out = Path("/app/output")
mep = (rates.get_rates() or {}).get("mep")
catalogo = load_catalog("/app/data/catalog.json", out / "catalog-auto.json")
existentes = {p.get("asin") for p in catalogo}

viejos = json.loads((out / "discovery-desde-ml.json").read_text(encoding="utf-8"))
ml_info = {}
for row in viejos:
    for c in row.get("ml") or []:
        ml_info.setdefault(c["catalogId"], c)
ids = list(ml_info)

# Resultado ANTERIOR (búsqueda por nombre) por producto de ML, según la re-validación.
antes = json.loads((out / "match-results.json").read_text(encoding="utf-8"))
estado_antes = {}
for estado in ("accepted", "doubtful", "rejected"):
    for r in antes.get(estado, []):
        if r.get("catalogId"):
            estado_antes.setdefault(r["catalogId"], estado if estado != "rejected" else "rejected:" + str(r.get("reason")))


def consulta(pid):
    r = requests.get(f"{ml_prices.API_BASE_URL}/products/{pid}", timeout=30,
                     headers={"Authorization": f"Bearer {ml_prices.get_token()}"})
    attrs = {a.get("id"): (a.get("value_name") or "") for a in (r.json().get("attributes") or [])} if r.ok else {}
    marca, modelo = attrs.get("BRAND", "").strip(), (attrs.get("MODEL") or attrs.get("ALPHANUMERIC_MODEL") or "").strip()
    return (f"{marca} {modelo}".strip() if marca and modelo else None), marca, modelo


filas, probados, sin_modelo = [], [], 0
for pid in ids:
    if time.monotonic() - inicio > LIMITE_S - 120:  # 2 min de margen para validar
        break
    q, marca, modelo = consulta(pid)
    if not q:
        sin_modelo += 1
        continue
    probados.append(pid)
    try:
        res = discovery.fetch_search_results(q, limit=8)
    except requests.RequestException:
        continue
    vistos = set()
    for item in res:
        if item.get("is_sponsored") or not discovery.should_keep_amazon_item(item, existentes, vistos):
            continue
        vistos.add(item["asin"].strip())
        titulo = (item.get("title") or "").strip()
        filas.append({"asin": item["asin"].strip(), "store": "US", "amazonTitle": titulo,
                      "brand": discovery.infer_brand(item) or marca, "amazonCategory": titulo,
                      "amazonPriceUsd": discovery.extract_price_usd(item), "ml": [ml_info[pid]]})

res = matching.match_products(filas, mep, catalogo)
despues = {}
for estado in ("accepted", "doubtful", "rejected"):
    for r in res.get(estado, []):
        despues.setdefault(r.get("catalogId"), estado if estado != "rejected" else "rejected:" + str(r.get("reason")))

print(json.dumps({
    "segundos": round(time.monotonic() - inicio),
    "productos_ml_probados": len(probados), "sin_marca_o_modelo_en_ml": sin_modelo, "pares": len(filas),
    "ANTES_por_nombre": dict(Counter(estado_antes.get(p, "sin_pares").split(":")[0] for p in probados)),
    "AHORA_por_marca_modelo": dict(Counter(despues.get(p, "sin_pares").split(":")[0] for p in probados)),
    "aceptados_ahora": [(r.get("amazonTitle", "")[:60], r.get("mlName", "")[:50]) for r in res.get("accepted", [])],
    "motivos_rechazo_ahora": Counter(r.get("reason") for r in res.get("rejected", [])).most_common(6),
}, ensure_ascii=False, indent=1))
