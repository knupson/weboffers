#!/usr/bin/env python3
"""Busca candidatos de Mercado Libre para productos verificados sin catalogId.

Sólo lee la API y escribe la revisión manual en output/ml-candidates.json.
No modifica data/catalog.json: el catalogId se copia a mano después de revisar.

Host (Pi): python3 tools/ml_catalog_map.py
Contenedor: docker compose -p franquicia400 exec weboffers-worker python /app/tools/ml_catalog_map.py --output /app/output/ml-candidates.json
Requiere ML_CLIENT_ID y ML_CLIENT_SECRET en el entorno.
"""
import argparse
import json
from pathlib import Path
import sys

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

import ml_prices  # noqa: E402
import publish  # noqa: E402

CANDIDATES_PER_PRODUCT = 5


def build_query(product):
    brand = (product.get("brand") or "").strip()
    name = product["name"].strip()
    return name if brand and brand.lower() in name.lower() else f"{brand} {name}".strip()


def candidates_for(product):
    found = []
    for result in ml_prices.search_products(build_query(product))[:CANDIDATES_PER_PRODUCT]:
        try:
            min_price = ml_prices.min_new_price(ml_prices.fetch_items(result["id"]))
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            print(f"  candidato {result.get('id')} sin precio ({type(exc).__name__})", flush=True)
            min_price = None
        found.append({"id": result.get("id"), "name": result.get("name"), "minPrice": min_price})
        ml_prices.pause()
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog.json"))
    parser.add_argument("--output", default=str(ROOT / "worker" / "output" / "ml-candidates.json"))
    args = parser.parse_args()
    if not ml_prices.is_configured():
        print("Faltan ML_CLIENT_ID o ML_CLIENT_SECRET en el entorno.", flush=True)
        return 1
    ml_prices.get_token()  # Falla rápido si las credenciales no sirven.
    catalog = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    review = []
    for product in catalog:
        ml = product.get("ml") or {}
        if not product.get("verified") or ml.get("catalogId"):
            continue
        print(f"Buscando: {product['slug']}", flush=True)
        try:
            candidates = candidates_for(product)
        except requests.RequestException as exc:
            print(f"  búsqueda fallida ({type(exc).__name__})", flush=True)
            candidates = []
        review.append({"slug": product["slug"], "name": product["name"],
                       "mlPriceNow": ml.get("price"), "candidates": candidates})
        ml_prices.pause()
    publish.write_atomic(args.output, review)
    print(f"Revisión escrita en {args.output}: productos={len(review)}.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
