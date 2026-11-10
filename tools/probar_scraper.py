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
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

BASE = "http://weboffers-amazon-scraper:8000"
OUT = Path("/app/output")
VISTOS = OUT / "scraper-vistos.json"
MIN_USD, MAX_USD = 100, 400


def log(*parts):
    stamp = datetime.now(timezone(timedelta(hours=-3))).isoformat()
    text = " ".join(str(part) for part in parts).replace("\r", "\\r").replace("\n", "\\n")
    print(stamp, text, flush=True)


def price_label(item):
    price = item.get("price")
    currency = price.get("currency") if isinstance(price, dict) else item.get("currency")
    currency = currency or "MONEDA_DESCONOCIDA"
    amount = monto(price)
    usd = usd_amount(item)
    return f"{currency} {amount} USD {usd} {rango(usd)}"


def usd_amount(item):
    price = item.get("price")
    currency = price.get("currency") if isinstance(price, dict) else item.get("currency")
    return item.get("price_usd") if item.get("price_usd") is not None else monto(price) if currency == "USD" else None


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
    if isinstance(precio, bool) or not isinstance(precio, (int, float)) or not math.isfinite(precio):
        return "SIN_PRECIO"
    return "DENTRO" if MIN_USD <= precio <= MAX_USD else "FUERA_DE_RANGO"


def monto(price):
    return price.get("amount") if isinstance(price, dict) else price


def main(argv):
    if not argv:
        for line in __doc__.splitlines():
            log(line)
        return 2
    endpoint = argv[0].strip("/")
    params = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
    params.setdefault("country", "US")
    ya = catalogo_asins()
    vistos = leer_vistos()
    pedidos = [x for k in ("product", "products") for x in params.get(k, "").split(",") if x]
    desconocidos = [a for a in pedidos if a not in ya and a not in vistos]
    if desconocidos:
        log(f"NO_CONSULTADO: ASIN que no están en el catálogo ni salieron de una consulta anterior: {desconocidos}. "
              "Sacalos de una búsqueda (search / categories/products) o del catálogo, nunca de memoria.")
        return 1

    t = time.time()
    try:
        base = "http://weboffers-barrido:8002" if endpoint == "barrido/probe" else BASE
        r = requests.get(f"{base}/{endpoint}", params=params, timeout=600 if endpoint == "barrido/probe" else 180)
    except requests.RequestException as exc:
        log(f"FALLA_CONEXION {type(exc).__name__}: {exc}")
        return 1
    log(f"HTTP {r.status_code} en {time.time() - t:.1f} s  {endpoint} {params}")
    if r.status_code != 200:
        log(json.dumps(r.text, ensure_ascii=False))
        return 1
    d = r.json()

    lista = next((d[key] for key in ("results", "items", "deals") if isinstance(d.get(key), list)), None)
    if isinstance(lista, list):
        nuevos = set()
        pagination = d.get("pagination") or d
        log(f"resultados={len(lista)} total_pages={pagination.get('total_pages')} count={pagination.get('total_count', d.get('count'))}")
        # Filtros de la barra lateral de Amazon para esta búsqueda (p. ej. si existe «envía a Argentina»).
        for f in d.get("refinements") or []:
            opciones = [o.get("name") for o in f.get("options") or []]
            log(f"FILTRO {f.get('id')} | {f.get('name')} | {opciones[:8]}")
        for x in lista:
            asin = x.get("asin")
            nuevos.add(asin)
            p = monto(x.get("price"))
            envio = x.get("delivery")
            envio = envio.get("text") if isinstance(envio, dict) else envio
            log(f"{'YA' if asin in ya else 'NUEVO'} {asin} {price_label(x)} | envío: {envio} | {(x.get('title') or '')[:60]}")
        try:
            VISTOS.parent.mkdir(parents=True, exist_ok=True)
            VISTOS.write_text(json.dumps(sorted((vistos | nuevos) - {None})), encoding="utf-8")
        except OSError as exc:
            log(f"AVISO no pude guardar {VISTOS}: {exc}")
        return 0

    if "title" in d:
        p = monto(d.get("price"))
        log(f"{'YA' if d.get('asin') in ya else 'NUEVO'} {d.get('asin')} {price_label(d)} | {d.get('title', '')[:80]}")
        if rango(usd_amount(d)) != "DENTRO":
            log(f"AVISO: precio {p} sin confirmación dentro de USD {MIN_USD}-{MAX_USD}.")
        log("envío:", json.dumps(d.get("delivery"), ensure_ascii=False))
        log("vendedor:", json.dumps(d.get("buybox"), ensure_ascii=False))
        return 0

    log(json.dumps(d, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
