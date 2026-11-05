"""Alta de productos al revés (05/11): de lo que ML vende en Argentina hacia Amazon.

Medido el 05/11: partiendo de los más vendidos de Amazon, 153 candidatos dieron 2 altas (63 sin vendedor local en ML,
p. ej. Canon PowerShot V10 sólo con publicaciones internacionales). Partiendo de ML: 1.871 más vendidos en 468
categorías de tecnología, 1.861 con vendedor nuevo en Argentina, 327 entre USD 100 y 1.000 que no estaban.

Flujo: más vendidos de ML (/highlights, API oficial) con vendedor local nuevo -> nombre del producto (/products/{id})
-> búsqueda en Amazon US con el scraper (/search, sin patrocinados) -> mismo formato que discover_products para que
match_candidates valide el par (marca, modelo, variante, capacidad, precio) con las mismas reglas de siempre.
"""
import time

import requests

import ml_prices
from tools import discover_products as discovery

RAICES = ("MLA1648", "MLA1000", "MLA1051", "MLA1144", "MLA1039")  # Computación, Electrónica, Celulares, Consolas, Cámaras
PROFUNDIDAD = 2
ML_MIN_USD, ML_MAX_USD = 100, 1000   # precio en ML al MEP (suele ser mayor que en Amazon); el rango 100-400 se exige en Amazon
RESULTADOS_AMAZON = 8


def _get(path, **params):
    for intento in range(3):
        r = requests.get(ml_prices.API_BASE_URL + path, params=params,
                         headers={"Authorization": f"Bearer {ml_prices.get_token()}"}, timeout=30)
        if r.status_code == 429 and intento < 2:
            time.sleep(2 * (intento + 1))
            continue
        return r
    return r


def categorias(raiz, profundidad=PROFUNDIDAD):
    r = _get(f"/categories/{raiz}")
    if not r.ok:
        return []
    hijos = r.json().get("children_categories") or []
    out = [raiz]
    if profundidad > 0:
        for h in hijos:
            out += categorias(h["id"], profundidad - 1)
    return out


def mas_vendidos_ml(catalog_ids_existentes):
    """{catalogId: categoria} de los más vendidos que no están en el catálogo."""
    vistos = {}
    for raiz in RAICES:
        for cat in categorias(raiz):
            r = _get(f"/highlights/MLA/category/{cat}")
            if not r.ok:
                continue
            for x in r.json().get("content") or []:
                if x.get("type") == "PRODUCT" and x.get("id") not in catalog_ids_existentes:
                    vistos.setdefault(x["id"], cat)
    return vistos


def candidatos(existing_asins, catalog_ids_existentes, mep, get=None, failures=None, limite=None):
    """Lista en el formato de discover_products: [{asin, amazonTitle, brand, amazonPriceUsd, ml: [...]}]."""
    out, vistos_asin = [], set()
    productos = mas_vendidos_ml(catalog_ids_existentes)
    print(f"Catálogo desde ML: {len(productos)} más vendidos fuera del catálogo.", flush=True)
    for n, pid in enumerate(productos, start=1):
        if limite and n > limite:
            break
        try:
            best = ml_prices.cheapest_new(ml_prices.fetch_items(pid))
        except (requests.RequestException, ValueError, KeyError, TypeError):
            best = None
        if not best or not best[1]:
            continue
        precio, item_id = best
        if not (ML_MIN_USD <= precio / mep <= ML_MAX_USD):
            continue
        r = _get(f"/products/{pid}")
        nombre = (r.json().get("name") or "").strip() if r.ok else ""
        if not nombre:
            continue
        try:
            resultados = discovery.fetch_search_results(nombre, limit=RESULTADOS_AMAZON, **({"get": get} if get else {}))
        except discovery.PageBudgetExhausted:
            break
        except requests.RequestException as exc:
            if failures is not None:
                failures.append({"catalogId": pid, "motivo": f"busqueda_amazon:{type(exc).__name__}"})
            continue
        for item in resultados:
            if item.get("is_sponsored"):
                continue
            if not discovery.should_keep_amazon_item(item, existing_asins, vistos_asin):
                continue
            asin = item["asin"].strip()
            vistos_asin.add(asin)
            out.append({"asin": asin, "store": "US", "amazonTitle": (item.get("title") or "").strip(),
                        # 05/11: la categoría sale del título de Amazon (match_candidates.category_for reconoce sus
                        # palabras); con "ml:<id>" todos quedaban «dudosos: categoría» y no entraba ninguno.
                        "brand": discovery.infer_brand(item), "amazonCategory": (item.get("title") or "").strip(),
                        "amazonPriceUsd": discovery.extract_price_usd(item),
                        "ml": [{"catalogId": pid, "name": nombre, "minPrice": precio, "itemId": item_id}]})
        if n % 25 == 0:
            print(f"Catálogo desde ML: {n}/{len(productos)} revisados, {len(out)} pares para validar.", flush=True)
    return out
