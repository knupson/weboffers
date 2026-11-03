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
AR_SHIPPING_WEEKDAY = 0  # lunes
RETRY_AT = (6, 45)  # reintento de faltantes: después de la corrida de las 06:00 y antes del deploy de las 07:00
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
    if isinstance(availability, dict):
        if availability.get("is_in_stock") is not True:
            return None
    else:
        # El scraper a veces no lee la disponibilidad (null) aunque la página tenga precio y vendedor
        # (MX Master 4 el 03/11: USD 118, en stock). Sin dato de stock, vale sólo si hay vendedor en la caja de compra.
        seller = ((raw_item.get("buybox") or {}).get("seller") or {}).get("name") if isinstance(raw_item.get("buybox"), dict) else None
        if not seller:
            return None
    price = raw_item.get("price")
    if not isinstance(price, dict) or price.get("currency") != expected_currency:
        return None
    amount = price.get("amount")
    if not is_valid_amount(amount):
        return None
    return amount, expected_currency


MIN_LIST_RATIO = 0.35


def plausible(parsed, product):
    """Descarta lecturas absurdas del scraper (ej. XM6 a USD 21 el 02/11): menos del 35% del precio de lista."""
    amount, currency = parsed
    lp = product.get("listPrice")
    if not isinstance(lp, dict) or lp.get("currency") != currency or not is_valid_amount(lp.get("amount")):
        return True
    return amount >= MIN_LIST_RATIO * lp["amount"]


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
    base_url = scraper_url()
    candidates = [
        p for p in catalog
        if p.get("verified") is True and p.get("asin") and p.get("ml") and p.get("store") in STORE_CURRENCY
    ]
    if isinstance(previous, dict) and previous.get("date") == today:
        return retry_missing(previous, candidates, prices_path, local, base_url)
    if not base_url:
        return False

    items, ok, missing = fetch_prices(base_url, candidates, today)

    # El envío a Argentina se releva sólo los lunes (03/11): pedirlo a diario duplica las páginas a Amazon y
    # la Pi4 quedó frenada (38 productos sin precio). El resto de la semana vale el envío verificado del catálogo.
    if today_date.weekday() == AR_SHIPPING_WEEKDAY:
        refresh_ar_shipping(candidates, items, today)

    publish.write_atomic(prices_path, {"generatedAt": now.isoformat(), "date": today, "items": items})
    print(f"Amazon: precios actualizados, ok={ok}, faltantes={missing}.", flush=True)
    if candidates and ok == 0:
        print(f"AMAZON_SCRAPER_FAIL ningún precio válido sobre {len(candidates)} candidatos (faltantes={missing}).", flush=True)
    return True


def retry_missing(previous, candidates, prices_path, local, base_url):
    """Segunda pasada del día, una sola vez y sólo para los que quedaron sin precio, antes del deploy de las 07:00."""
    if previous.get("retried") or not base_url or (local.hour, local.minute) < RETRY_AT:
        return False
    today = previous["date"]
    items = dict(previous.get("items") or {})
    pending = [p for p in candidates if p["slug"] not in items]
    got, ok, _ = fetch_prices(base_url, pending, today) if pending else ({}, 0, 0)
    items.update(got)
    publish.write_atomic(prices_path, {**previous, "items": items, "retried": True})
    print(f"Amazon: reintento de faltantes, recuperados={ok} de {len(pending)}, total={len(items)}.", flush=True)
    return True


def fetch_prices(base_url, products, today):
    """Pide precios en lotes por tienda. Devuelve (items, ok, missing); nunca reutiliza precios de otro día."""
    by_store = {}
    for product in products:
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
                if parsed is not None and not plausible(parsed, product):
                    print(f"Amazon: precio descartado por inverosímil {slug} ({parsed[0]} {parsed[1]}).", flush=True)
                    parsed = None
                if parsed is not None:
                    amount, currency = parsed
                    items[slug] = {"amount": amount, "currency": currency, "checked": today}
                    ok += 1
                else:
                    missing += 1
    return items, ok, missing
