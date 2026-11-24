"""Lista los catálogos de ML que el paso «ml» va a consultar y guarda lo que leyó Chrome (tools/ml_chrome.py), 24/11.

  python /app/tools/ml_chrome_listar.py listar            # un catalogId por línea (stdout)
  python /app/tools/ml_chrome_listar.py guardar < salida  # fusiona en output/ml-chrome-AAAA-MM-DD.json

Usa los mismos salteos que ml_prices.maybe_refresh (motivo_salteo_ml): Chrome no gasta páginas en productos que el
paso «ml» no va a consultar. Lo leído hoy con resultado no se vuelve a pedir.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
import worker
import publicacion
import ml_prices
from amazon_prices import chrome_sin_envio_gratis
from publish import write_atomic
from requisitos import modo_actual


def salida():
    return worker.resolve_path(os.environ.get("ML_PRICES_PATH", "output/ml-prices.json")).parent


def listar():
    output = salida()
    now = datetime.now(ml_prices.ART)
    today = now.date().isoformat()
    catalog = worker.load_catalog(worker.resolve_path(os.environ.get("CATALOG_PATH", "../data/catalog.json")),
                                  output / "catalog-auto.json")
    estado = publicacion.cargar(output)
    modo = modo_actual()
    if modo == "alta":
        catalog = [p for p in catalog if publicacion.motivo_estado(p, estado, today, modo) is None]
    amazon_path = worker.resolve_path(os.environ.get("AMAZON_PRICES_PATH", "output/amazon-prices.json"))
    sin_gratis = chrome_sin_envio_gratis(amazon_path, today)
    amazon_items = ml_prices.load_amazon_prices(amazon_path, now.date())
    rates = worker.rates.get_rates() or {}
    eur_usd = worker.rates.get_eur_usd(rates.get("oficial")) if rates else None
    leidos = ml_prices.load_json(ml_prices.ruta_chrome(output, today), {}).get("items") or {}
    ids, salteados, ya = [], 0, 0
    for product in catalog:
        cid = (product.get("ml") or {}).get("catalogId")
        if not cid or ml_prices.motivo_salteo_ml(product, sin_gratis, amazon_items, estado, today, modo, eur_usd):
            salteados += 1
            continue
        if (leidos.get(cid) or {}).get("results") is not None:
            ya += 1
            continue
        if cid not in ids:
            ids.append(cid)
    print(f"{now:%Y-%m-%d %H:%M:%S} ML_CHROME_LISTA modo={modo} catalogos={len(ids)} salteados={salteados} "
          f"ya_leidos_hoy={ya}", file=sys.stderr, flush=True)
    print("\n".join(ids))


def guardar():
    output = salida()
    today = datetime.now(ml_prices.ART).date().isoformat()
    nuevo = json.load(sys.stdin)
    ruta = ml_prices.ruta_chrome(output, today)
    previo = ml_prices.load_json(ruta, {}) or {}
    items = dict(previo.get("items") or {})
    for cid, item in (nuevo.get("items") or {}).items():
        leido = str(item.get("leido") or "")
        if not leido.startswith(today):
            continue  # un relevamiento que cruzó la medianoche no se mezcla con hoy
        if item.get("results") is None and (items.get(cid) or {}).get("results") is not None:
            continue  # una falla posterior no pisa una lectura buena del mismo día
        items[cid] = item
    write_atomic(ruta, {"date": today, "generado": nuevo.get("generado"), "items": items})
    ok = sum(1 for i in items.values() if i.get("results") is not None)
    print(f"{datetime.now(ml_prices.ART):%Y-%m-%d %H:%M:%S} ML_CHROME_GUARDADO {ruta.name} catalogos={len(items)} "
          f"con_ofertas_leidas={ok} fallas={len(items) - ok}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("listar", "guardar"))
    {"listar": listar, "guardar": guardar}[parser.parse_args().accion]()
