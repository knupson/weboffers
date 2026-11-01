"""Precios diarios de Amazon vía el scraper interno en la red de Docker."""

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time

import requests

import publish


ART = timezone(timedelta(hours=-3))
START_HOUR = 6
# En la Pi4 el scraper tarda ~13 s por producto: lotes chicos y espera larga (medido el 31/10).
BULK_MAX = 5
TIMEOUT = 240
PAUSE_SECONDS = 3.0
STORE_CURRENCY = {"US": "USD", "ES": "EUR"}


def scraper_url():
    return os.environ.get("AMAZON_SCRAPER_URL", "").strip().rstrip("/")


def ar_url():
    return os.environ.get("AMAZON_AR_URL", "").strip().rstrip("/")


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


def fetch_ar_shipping(base_url, asins, store):
    resp = requests.get(
        f"{base_url}/ar-shipping",
        params={"asins": ",".join(asins), "store": store},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    products = data.get("products") if isinstance(data, dict) else None
    if not isinstance(products, list):
        raise ValueError("respuesta sin lista de productos")
    return {item.get("asin"): item for item in products if isinstance(item, dict) and isinstance(item.get("asin"), str)}


def refresh_ar_shipping(candidates, items, today):
    """Consulta /ar-shipping en lotes de BULK_MAX agrupados por tienda y guarda shipsToAr por slug.

    Cada lote se pide con el `store` de sus productos (la misma tienda que da el precio).
    Si falla el relevamiento de un producto no se guarda nada para él (queda desconocido);
    nunca se reutiliza el valor de días anteriores. `shipsToAr` sólo se guarda cuando `ships`
    es un booleano real: None u otro valor es desconocido, nunca "no envía".
    """
    base_url = ar_url()
    if not base_url:
        return
    by_store = {}
    for product in candidates:
        by_store.setdefault(product["store"], []).append(product)
    first_call = True
    for store, store_products in by_store.items():
        for i in range(0, len(store_products), BULK_MAX):
            chunk = store_products[i:i + BULK_MAX]
            if not first_call:
                pause()
            first_call = False
            try:
                fetched = fetch_ar_shipping(base_url, [p["asin"] for p in chunk], store)
            except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                print(f"Amazon AR: falló lote {store} ({type(exc).__name__}); se omite.", flush=True)
                continue
            for product in chunk:
                item = fetched.get(product["asin"])
                if not isinstance(item, dict) or "error" in item:
                    continue
                ships = item.get("ships")
                if not isinstance(ships, bool):
                    continue  # desconocido: no se guarda nada para este slug
                free = item.get("free")
                items.setdefault(product["slug"], {})["shipsToAr"] = {
                    "ships": ships,
                    "free": free if isinstance(free, bool) else None,
                    "checked": today,
                }


def maybe_refresh(catalog, prices_path, now):
    """Consulta precios de Amazon una vez por día desde las 06:00 ART. Devuelve True si corrió."""
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

    candidates = [
        p for p in catalog
        if p.get("verified") is True and p.get("asin") and p.get("ml") and p.get("store") in STORE_CURRENCY
    ]

    by_store = {}
    for product in candidates:
        by_store.setdefault(product["store"], []).append(product)

    items = {}
    ok = 0
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
                print(f"Amazon: falló lote {store} ({type(exc).__name__}); se omite.", flush=True)
                fetched = {}

            for product in chunk:
                slug = product["slug"]
                parsed = valid_price(fetched.get(product["asin"]), store)
                if parsed is not None:
                    amount, currency = parsed
                    items[slug] = {"amount": amount, "currency": currency, "checked": today}
                    ok += 1
                else:
                    missing += 1

    refresh_ar_shipping(candidates, items, today)

    publish.write_atomic(prices_path, {"generatedAt": now.isoformat(), "date": today, "items": items})
    print(f"Amazon: precios actualizados, ok={ok}, faltantes={missing}.", flush=True)
    if candidates and ok == 0:
        print(f"AMAZON_SCRAPER_FAIL ningún precio válido sobre {len(candidates)} candidatos (faltantes={missing}).", flush=True)
    return True
