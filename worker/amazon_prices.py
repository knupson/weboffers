"""Precios diarios de Amazon vía el scraper interno en la red de Docker."""

from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time

import requests

import publish


ART = timezone(timedelta(hours=-3))
START_HOUR = 7
BULK_MAX = 10
MAX_AGE_DAYS = 3
TIMEOUT = 60
PAUSE_SECONDS = 3.0
STORE_CURRENCY = {"US": "USD", "ES": "EUR"}


def scraper_url():
    return os.environ.get("AMAZON_SCRAPER_URL", "").strip().rstrip("/")


def pause():
    if PAUSE_SECONDS > 0:
        time.sleep(PAUSE_SECONDS)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def is_valid_amount(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def valid_price(raw_item, store):
    """Devuelve (amount, currency) sólo si el producto está en stock y el precio es válido en la moneda de la tienda."""
    expected_currency = STORE_CURRENCY.get(store)
    if not expected_currency or not isinstance(raw_item, dict) or "error" in raw_item:
        return None
    availability = raw_item.get("availability")
    if not isinstance(availability, dict) or availability.get("is_in_stock") is not True:
        return None
    price = raw_item.get("price")
    if not isinstance(price, dict) or price.get("currency") != expected_currency:
        return None
    amount = price.get("amount")
    if not is_valid_amount(amount):
        return None
    return amount, expected_currency


def keep_previous(prev_item, store, today_date):
    """Conserva el precio previo si es válido y tiene a lo sumo 3 días de antigüedad."""
    expected_currency = STORE_CURRENCY.get(store)
    if not expected_currency or not isinstance(prev_item, dict):
        return None
    if prev_item.get("currency") != expected_currency or not is_valid_amount(prev_item.get("amount")):
        return None
    checked = prev_item.get("checked")
    if not isinstance(checked, str):
        return None
    try:
        age_days = (today_date - date.fromisoformat(checked)).days
    except ValueError:
        return None
    if 0 <= age_days <= MAX_AGE_DAYS:
        return {"amount": prev_item["amount"], "currency": expected_currency, "checked": checked}
    return None


def fetch_bulk(base_url, asins, store):
    resp = requests.get(
        f"{base_url}/products/bulk",
        params={"products": ",".join(asins), "country": store},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        raise ValueError("respuesta sin lista de productos")
    return {item.get("asin"): item for item in products if isinstance(item, dict) and isinstance(item.get("asin"), str)}


def maybe_refresh(catalog, prices_path, now):
    """Consulta precios de Amazon una vez por día desde las 07:00 ART. Devuelve True si corrió."""
    local = now.astimezone(ART)
    today_date = local.date()
    today = today_date.isoformat()
    if local.hour < START_HOUR:
        return False
    previous = load_json(prices_path, None)
    if isinstance(previous, dict) and previous.get("date") == today:
        return False
    base_url = scraper_url()
    if not base_url:
        return False

    old_items = previous.get("items", {}) if isinstance(previous, dict) else {}
    if not isinstance(old_items, dict):
        old_items = {}

    candidates = [
        p for p in catalog
        if p.get("verified") is True and p.get("asin") and p.get("ml") and p.get("store") in STORE_CURRENCY
    ]

    by_store = {}
    for product in candidates:
        by_store.setdefault(product["store"], []).append(product)

    items = {}
    ok = 0
    kept = 0
    missing = 0
    first_call = True

    for store, store_products in by_store.items():
        for i in range(0, len(store_products), BULK_MAX):
            chunk = store_products[i:i + BULK_MAX]
            if not first_call:
                pause()
            first_call = False
            try:
                fetched = fetch_bulk(base_url, [p["asin"] for p in chunk], store)
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                print(f"Amazon: falló lote {store} ({type(exc).__name__}); se intenta conservar previos.", flush=True)
                fetched = {}

            for product in chunk:
                slug = product["slug"]
                parsed = valid_price(fetched.get(product["asin"]), store)
                if parsed is not None:
                    amount, currency = parsed
                    items[slug] = {"amount": amount, "currency": currency, "checked": today}
                    ok += 1
                else:
                    retained = keep_previous(old_items.get(slug), store, today_date)
                    if retained is not None:
                        items[slug] = retained
                        kept += 1
                    else:
                        missing += 1

    publish.write_atomic(prices_path, {"generatedAt": now.isoformat(), "date": today, "items": items})
    print(f"Amazon: precios actualizados, ok={ok}, previos={kept}, faltantes={missing}.", flush=True)
    if candidates and ok == 0:
        print(f"AMAZON_SCRAPER_FAIL ningún precio válido sobre {len(candidates)} candidatos (previos={kept}, faltantes={missing}).", flush=True)
    return True
