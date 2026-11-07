"""Única forma de consultar a mano el scraper de Amazon (omkarcloud) desde una sesión de Claude.

El hook .claude/hooks/scraper-solo-con-herramienta.mjs bloquea cualquier otra consulta. Motivo (07/11/2026):
consultas armadas a mano que no imprimían el error, un ASIN inventado y una prueba de envío con un
producto de USD 96 (fuera del rango 100-400 del sitio).

Corre DENTRO del worker, leído por stdin (no hace falta instalarlo en la VM):
    ssh docker 'docker exec -i -w /app franquicia400-weboffers-worker-1 python - search query=monitor min_price=100 max_price=400 sort=best_sellers condition=new' < tools/probar_scraper.py
    ssh docker 'docker exec -i -w /app franquicia400-weboffers-worker-1 python - products/details product=B08GTYFC37' < tools/probar_scraper.py

Reglas que aplica solo:
- Siempre imprime HTTP, segundos y, si falla, el cuerpo completo del error.
- Un ASIN (product= / products=) tiene que estar en el catálogo o haber salido en una consulta anterior
  (output/scraper-vistos.json). Si no, no consulta: así no se inventan ASIN.
- Marca cada precio DENTRO / FUERA del rango USD 100-400 y si el producto ya está en el sitio (YA) o no (NUEVO).
"""
import json
import sys
import time
from pathlib import Path

import requests

BASE = "http://weboffers-amazon-scraper:8000"
OUT = Path("/app/output")
VISTOS = OUT / "scraper-vistos.json"
MIN_USD, MAX_USD = 100, 400


def catalogo_asins():
    asins = set()
    for ruta in (Path("/app/data/catalog.json"), OUT / "catalog-auto.json"):
        try:
            asins |= {p.get("asin") for p in json.loads(ruta.read_text(encoding="utf-8")) if p.get("asin")}
        except (OSError, ValueError):
            pass
    return asins


def leer_vistos():
    try:
        return set(json.loads(VISTOS.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return set()


def rango(precio):
    if not isinstance(precio, (int, float)):
        return "SIN_PRECIO"
    return "DENTRO" if MIN_USD <= precio <= MAX_USD else "FUERA_DE_RANGO"


def monto(price):
    return price.get("amount") if isinstance(price, dict) else price


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    endpoint = argv[0].strip("/")
    params = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    params.setdefault("country", "US")
    ya = catalogo_asins()
    vistos = leer_vistos()
    pedidos = [x for k in ("product", "products") for x in params.get(k, "").split(",") if x]
    desconocidos = [a for a in pedidos if a not in ya and a not in vistos]
    if desconocidos:
        print(f"NO_CONSULTADO: ASIN que no están en el catálogo ni salieron de una consulta anterior: {desconocidos}. "
              "Sacalos de una búsqueda (search / categories/products) o del catálogo, nunca de memoria.")
        return 1

    t = time.time()
    try:
        r = requests.get(f"{BASE}/{endpoint}", params=params, timeout=180)
    except requests.RequestException as exc:
        print(f"FALLA_CONEXION {type(exc).__name__}: {exc}")
        return 1
    print(f"HTTP {r.status_code} en {time.time() - t:.1f} s  {endpoint} {params}")
    if r.status_code != 200:
        print(r.text[:3000])
        return 1
    d = r.json()

    lista = d.get("results") or d.get("items") or d.get("deals")
    if isinstance(lista, list):
        nuevos = set()
        print(f"resultados={len(lista)} total_pages={d.get('total_pages')} count={d.get('count')}")
        for x in lista:
            asin = x.get("asin")
            nuevos.add(asin)
            p = monto(x.get("price"))
            envio = x.get("delivery")
            envio = envio.get("text") if isinstance(envio, dict) else envio
            print(f"{'YA' if asin in ya else 'NUEVO'} {asin} USD {p} {rango(p)} | envío: {envio} | {(x.get('title') or '')[:60]}")
        try:
            VISTOS.write_text(json.dumps(sorted((vistos | nuevos) - {None})), encoding="utf-8")
        except OSError as exc:
            print(f"AVISO no pude guardar {VISTOS}: {exc}")
        return 0

    if "title" in d:
        p = monto(d.get("price"))
        print(f"{'YA' if d.get('asin') in ya else 'NUEVO'} {d.get('asin')} USD {p} {rango(p)} | {d.get('title', '')[:80]}")
        if rango(p) != "DENTRO":
            print(f"AVISO: precio {p} fuera de USD {MIN_USD}-{MAX_USD}; no sirve como prueba para el sitio.")
        print("envío:", json.dumps(d.get("delivery"), ensure_ascii=False))
        print("vendedor:", json.dumps(d.get("buybox"), ensure_ascii=False)[:300])
        return 0

    print(json.dumps(d, ensure_ascii=False)[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
