"""Daemon de actualización del catálogo público."""

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import signal
import time

import creators_api
import ml_prices
import publish
import rates
import telegram


WORKER_DIR = Path(__file__).resolve().parent
stop_requested = False


def request_stop(signum, frame):
    global stop_requested
    stop_requested = True


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else WORKER_DIR / path


def run_once():
    catalog_path = resolve_path(os.environ.get("CATALOG_PATH", "../data/catalog.json"))
    with catalog_path.open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    grouped = {}
    for entry in catalog:
        grouped.setdefault(entry["store"], []).append(entry["asin"])
    current_rates = rates.get_rates()
    items = []
    for store, asins in grouped.items():
        items.extend(creators_api.fetch_items(asins, store))
    mode = "api" if any(creators_api.is_configured(s) for s in grouped) else "offline"
    payload = publish.build_offers(datetime.now(timezone.utc).isoformat(), mode, current_rates, items)
    output = resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json"))
    changed = publish.publish(output, payload, os.environ.get("CF_DEPLOY_HOOK_URL", ""))
    print(f"Publicación completa: modo={mode}, productos={len(items)}, cambios={changed}.", flush=True)
    ml_prices_path = resolve_path(os.environ.get("ML_PRICES_PATH", "output/ml-prices.json"))
    try:
        ml_prices.maybe_refresh(
            catalog,
            ml_prices_path,
            resolve_path(os.environ.get("AMAZON_TOTALS_PATH", "/app/amazon-totals.json")),
            (current_rates or {}).get("mep"),
            datetime.now(timezone.utc),
        )
    except Exception as exc:
        print(f"Falló la actualización de precios de Mercado Libre ({type(exc).__name__}).", flush=True)
    # Telegram después de los precios del día, para publicar el mismo precio y veredicto que el sitio.
    try:
        telegram.maybe_post(ml_prices.merge(catalog, ml_prices_path),
                            resolve_path(os.environ.get("TELEGRAM_STATE_PATH", "output/telegram-state.json")))
    except Exception as exc:
        print(f"Falló la publicación en Telegram ({type(exc).__name__}).", flush=True)
    return payload


def main():
    interval = float(os.environ.get("CHECK_INTERVAL_SECONDS", "3600"))
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("CHECK_INTERVAL_SECONDS debe ser un número positivo")
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    print("Worker iniciado.", flush=True)
    while not stop_requested:
        try:
            run_once()
        except Exception as exc:
            print(f"Falló el ciclo de actualización ({type(exc).__name__}).", flush=True)
        deadline = time.monotonic() + interval
        while not stop_requested and time.monotonic() < deadline:
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    print("Worker detenido.", flush=True)


if __name__ == "__main__":
    main()
