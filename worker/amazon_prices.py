"""Precios diarios de Amazon vía el scraper interno en la red de Docker."""

from datetime import date, datetime, timedelta, timezone
from itertools import groupby
import json
import math
import os
from pathlib import Path
import time

import requests

import publish


ART = timezone(timedelta(hours=-3))
START_HOUR = 4  # 03/11: arranca a las 04:00 para poder ir lento y reintentar antes del deploy de las 07:00
# En la Pi4 el scraper tarda ~13 s por producto: lotes chicos y espera larga (medido el 31/10).
BULK_MAX = 5
AR_SHIPPING_WEEKDAY = 0  # lunes
ARSHIPPING_MAX_DAYS = 14
RETRY_TIMES = ((5, 0), (6, 0), (7, 30))
TIMEOUT = 240
# Medido el 03/11 (lotes de 5, 60 productos por prueba): 30 s, 15 s y 5 s de pausa sin fallas; el techo lo pone el scraper
# (~37 s por lote = ~7,6 productos/min aun sin pausa). Con 5 s y el catalogo entero Amazon corto en el producto 132 y se
# recupero en ~1 min. Paralelo: 2 hilos no suman (el scraper atiende de a uno) y 3 rompen el scraper (ConnectionError).
PAUSE_SECONDS = 15.0
BACKOFF_SECONDS = 120.0  # si un lote vuelve vacio, se espera y se repite ese lote una vez
BACKOFF_MIN_EMPTY = 2
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
    charge_pages(len(asins))
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
    charge_pages(len(asins))
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


def refresh_ar_shipping(candidates, items, today, prices_path=None, no_offer=None):
    """Consulta /ar-shipping en lotes de BULK_MAX agrupados por tienda y guarda shipsToAr por slug.

    Cada lote se pide con el `store` de sus productos (la misma tienda que da el precio).
    Si falla el relevamiento de un producto no se guarda nada para él (queda desconocido);
    `items[slug].shipsToAr` nunca reutiliza días anteriores. Sólo se guarda cuando `ships`
    es un booleano real: None u otro valor es desconocido, nunca "no envía".
    """
    summary = {"relevados": 0, "gratis": 0, "sin_dato": 0}
    shipping_failures = []
    base_url = ar_url()
    if not base_url:
        return summary
    first_call = True
    # Conserva la prioridad global; cada lote sigue usando una sola tienda.
    for store, group in groupby(candidates, key=lambda p: p["store"]):
        store_products = list(group)
        for i in range(0, len(store_products), BULK_MAX):
            chunk = store_products[i:i + BULK_MAX]
            if not first_call:
                pause()
            first_call = False
            fetched = {}
            lote_error = None
            for attempt in range(2):
                lote_error = None
                try:
                    fetched = fetch_ar_shipping(base_url, [p["asin"] for p in chunk], store)
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    fetched = {}
                    lote_error = f"lote_fallido:{type(exc).__name__}"
                unknown = sum(shipping_reason(fetched.get(p["asin"])) is not None for p in chunk)
                if attempt == 0 and (lote_error or unknown >= BACKOFF_MIN_EMPTY):
                    print(f"Amazon AR: lote sin datos; espero {BACKOFF_SECONDS:.0f} s y lo repito.", flush=True)
                    time.sleep(BACKOFF_SECONDS)
                    continue
                break
            for product in chunk:
                summary["relevados"] += 1
                item = fetched.get(product["asin"])
                reason = lote_error or shipping_reason(item)
                if reason:
                    if reason == "sin_ships_booleano" and no_offer is not None:
                        no_offer.append(product["slug"])
                    summary["sin_dato"] += 1
                    shipping_failures.append({"slug": product["slug"], "asin": product["asin"],
                                              "store": store, "motivo": reason})
                    print(f"Amazon AR: sin dato {product['slug']} ({reason}).", flush=True)
                    continue
                free = item.get("free")
                summary["gratis"] += int(item["ships"] is True and free is True)
                items.setdefault(product["slug"], {})["asin"] = product["asin"]
                items[product["slug"]]["shipsToAr"] = {
                    "ships": item["ships"],
                    "free": free if isinstance(free, bool) else None,
                    "checked": today,
                }
    if prices_path is not None:
        write_run_log(prices_path, today, "envio", summary["relevados"] - summary["sin_dato"],
                      summary["relevados"], shipping_failures)
    return summary


def shipping_reason(item):
    if not isinstance(item, dict):
        return "no_vino_en_respuesta"
    if "error" in item:
        return "error:" + str(item["error"])[:60]
    if not isinstance(item.get("ships"), bool):
        return "sin_ships_booleano"
    return None


def fresh_shipping_date(checked, today):
    try:
        parsed = date.fromisoformat(checked)
        return parsed.isoformat() == checked and 0 <= (today - parsed).days <= ARSHIPPING_MAX_DAYS
    except (TypeError, ValueError):
        return False


def merge_ar_shipping(previous, items, today):
    """Conserva relevamientos reales hasta 14 días ART y actualiza con los de hoy."""
    shipping = dict(previous.get("arShipping") or {}) if isinstance(previous, dict) else {}
    for slug, item in items.items():
        ar = item.get("shipsToAr")
        if isinstance(ar, dict) and isinstance(ar.get("ships"), bool) and ar.get("checked") == today.isoformat():
            shipping[slug] = ar
    valid = {}
    for slug, ar in shipping.items():
        if not isinstance(ar, dict) or not isinstance(ar.get("ships"), bool):
            continue
        try:
            checked = date.fromisoformat(ar["checked"])
        except (KeyError, TypeError, ValueError):
            continue
        if checked.isoformat() == ar["checked"] and 0 <= (today - checked).days <= ARSHIPPING_MAX_DAYS:
            valid[slug] = {
                "ships": ar["ships"],
                "free": ar.get("free") if isinstance(ar.get("free"), bool) else None,
                "checked": ar["checked"],
            }
    return valid


# El sitio es de productos de USD 100 a 400 con envío gratis (franquicia): debajo de 100 Amazon cobra el envío a
# Argentina y arriba de 400 se pasa la franquicia. 03/11: 47 de 160 estaban debajo de 100 y ninguno tenía envío gratis;
# se pedían todos los días para nada. Con margen, para no perder los que rozan el límite; los lunes se revisan todos.
RANGE_MIN, RANGE_MAX = 100.0, 400.0
RANGE_MARGIN = 0.9


def price_usd(item, eur_usd=None):
    amount = item.get("amount") if isinstance(item, dict) else None
    if not is_valid_amount(amount):
        return None
    rate = eur_usd if is_valid_amount(eur_usd) else 1.08
    return amount * rate if item.get("currency") == "EUR" else amount


def out_of_range_memory(previous, items, eur_usd=None, without_ml=()):
    """Conserva exclusiones y agrega los precios fuera de rango consultados hoy."""
    previous = previous if isinstance(previous, dict) else {}
    last = {**(previous.get("outOfRange") or {}), **(previous.get("items") or {}), **items}
    memory = {}
    for slug, item in last.items():
        if not isinstance(item, dict):
            continue
        amount = price_usd(item, eur_usd)
        if amount is not None and not (RANGE_MIN <= amount <= RANGE_MAX):
            memory[slug] = {k: item[k] for k in ("amount", "currency") if k in item}
        elif slug not in items and item.get("motivo") == "sin_ml_local":
            memory[slug] = item
    for slug in without_ml:
        memory[slug] = {**memory.get(slug, {}), "motivo": "sin_ml_local"}
    return memory


def in_range(candidates, previous, today_date, eur_usd=None, ml_prices=None):
    """Saltea precios fuera de rango y productos sin ML local; los lunes revisa todos."""
    if today_date.weekday() == AR_SHIPPING_WEEKDAY:
        return candidates, 0
    previous = previous if isinstance(previous, dict) else {}
    last = {**(previous.get("outOfRange") or {}), **(previous.get("items") or {})}
    use_ml = isinstance(ml_prices, dict) and ml_prices.get("date") == (today_date - timedelta(days=1)).isoformat()
    keep = []
    for p in candidates:
        item = last.get(p["slug"]) or {}
        amount = price_usd(item, eur_usd)
        if use_ml and p["slug"] in (ml_prices.get("absent") or []):
            continue
        if item.get("motivo") == "sin_ml_local":
            continue
        if amount is not None and not (RANGE_MIN * RANGE_MARGIN <= amount <= RANGE_MAX / RANGE_MARGIN):
            continue
        keep.append(p)
    return keep, len(candidates) - len(keep)


def recent_no_offer(previous, today_date):
    """Productos sin oferta para Argentina en los últimos días (05/11): no se reconsultan hasta el lunes.

    Con ubicación AR la página no trae `ships` cuando Amazon no tiene oferta para Argentina
    (confirmado en Chrome el 04/11); pedirlos a diario sólo gasta páginas. El lunes se revisa todo.
    """
    if today_date.weekday() == AR_SHIPPING_WEEKDAY or not isinstance(previous, dict):
        return {}
    memory = {}
    for slug, checked in (previous.get("noArOffer") or {}).items():
        try:
            age = (today_date - date.fromisoformat(checked)).days
        except (TypeError, ValueError):
            continue
        if 0 <= age <= 6:
            memory[slug] = checked
    return memory


def shipping_candidates(candidates, items, previous, today_date, ml_prices, eur_usd=None, monday=False, skip=()):
    known = merge_ar_shipping(previous, items, today_date)
    def confirmed(product):
        ar = known.get(product["slug"])
        if ar is not None:
            return True
        catalog_ar = product.get("shipsToAr") or {}
        return catalog_ar.get("freeShipping") is True and fresh_shipping_date(catalog_ar.get("checked"), today_date)
    selected = [p for p in candidates if monday or (not confirmed(p) and p["slug"] not in skip)]
    ml_items = (ml_prices or {}).get("items") or {}
    def priority(product):
        amount = price_usd(items.get(product["slug"]), eur_usd)
        return not (is_valid_amount((ml_items.get(product["slug"]) or {}).get("price"))
                    and amount is not None and RANGE_MIN <= amount <= RANGE_MAX)
    return sorted(selected, key=priority)


def maybe_refresh(catalog, prices_path, now, eur_usd=None):
    """Consulta precios de Amazon una vez por día desde las 06:00 ART. Devuelve True si corrió."""
    local = now.astimezone(ART)
    today_date = local.date()
    today = today_date.isoformat()
    if local.hour < START_HOUR:
        return False
    previous = load_json(prices_path, None)
    base_url = scraper_url()
    ml_path = Path(os.environ.get("ML_PRICES_PATH", str(Path(prices_path).with_name("ml-prices.json"))))
    ml_prices = load_json(ml_path, None)
    candidates = [
        p for p in catalog
        if p.get("verified") is True and p.get("asin") and p.get("ml") and p.get("store") in STORE_CURRENCY
    ]
    if isinstance(previous, dict) and previous.get("date") == today:
        return retry_missing(previous, candidates, prices_path, local, base_url, eur_usd, ml_prices)
    all_candidates = candidates
    candidates, skipped = in_range(candidates, previous, today_date, eur_usd, ml_prices)
    without_ml = [p["slug"] for p in all_candidates if ml_prices is not None
                  and ml_prices.get("date") == (today_date - timedelta(days=1)).isoformat()
                  and p["slug"] in (ml_prices.get("absent") or [])
                  and today_date.weekday() != AR_SHIPPING_WEEKDAY]
    if skipped:
        print(f"Amazon: {skipped} productos fuera de rango o sin ML local no se consultan hoy (se revisan los lunes).", flush=True)
    if not base_url:
        return False

    configure_budget(prices_path, today)
    # Ritmo que se ajusta solo con el resultado de la corrida anterior (03/11).
    global PAUSE_SECONDS
    pace = next_pace(previous)
    PAUSE_SECONDS = pace["pause_s"]
    items, ok, missing = fetch_prices(base_url, candidates, today)
    run = run_summary(ok, len(candidates))
    pace = adjust_pace(pace, run)

    # Envío a Argentina (03/11): los lunes se releva todo; el resto de los días SÓLO lo que no tiene envío
    # confirmado (catálogo o relevamiento de ≤14 días), porque sin ese dato el producto no se publica (REGLA 0)
    # y pedir todo a diario duplica las páginas a Amazon. Cada relevamiento se conserva 14 días.
    no_offer = recent_no_offer(previous, today_date)
    to_survey = shipping_candidates(candidates, items, previous, today_date, ml_prices, eur_usd,
                                    monday=today_date.weekday() == AR_SHIPPING_WEEKDAY, skip=no_offer)
    new_no_offer = []
    run["envio"] = refresh_ar_shipping(to_survey, items, today, prices_path, no_offer=new_no_offer)
    # Sólo se memoriza "sin oferta" si el relevamiento anduvo para algún producto en esta corrida:
    # si nada trajo `ships`, puede ser un cambio de formato o un freno, no ausencia comercial (auditoría 05/11).
    if run["envio"].get("relevados", 0) > run["envio"].get("sin_dato", 0):
        no_offer.update({slug: today for slug in new_no_offer})

    ar_shipping = merge_ar_shipping(previous, items, today_date)
    publish.write_atomic(prices_path, {"generatedAt": now.isoformat(), "date": today, "items": items,
                                       "arShipping": ar_shipping, "run": run, "pace": pace,
                                       "outOfRange": out_of_range_memory(previous, items, eur_usd, without_ml),
                                       "noArOffer": no_offer})
    print(f"Amazon: resumen {json.dumps(run, ensure_ascii=False)}; ritmo de mañana {pace['pause_s']:.0f} s.", flush=True)
    print(f"Amazon: precios actualizados, ok={ok}, faltantes={missing}.", flush=True)
    write_run_log(prices_path, today, "corrida", ok, len(candidates))
    if candidates and ok == 0:
        print(f"AMAZON_SCRAPER_FAIL ningún precio válido sobre {len(candidates)} candidatos (faltantes={missing}).", flush=True)
    return True


def retry_missing(previous, candidates, prices_path, local, base_url, eur_usd=None, ml_prices=None):
    """Hasta tres reintentos con espera, sólo para precios o envíos pendientes."""
    count = previous.get("retryCount", int(bool(previous.get("retried"))))
    if count >= len(RETRY_TIMES) or not base_url or (local.hour, local.minute) < RETRY_TIMES[count]:
        return False
    last_attempt = previous.get("retryAt")
    if last_attempt and (local - datetime.fromisoformat(last_attempt)).total_seconds() < (3600 if count == 1 else 5400):
        return False
    today = previous["date"]
    configure_budget(prices_path, today)
    items = dict(previous.get("items") or {})
    skip = previous.get("outOfRange") or {}
    pending = [p for p in candidates if not is_valid_amount((items.get(p["slug"]) or {}).get("amount"))
               and p["slug"] not in skip]
    unknown_shipping = shipping_candidates(candidates, items, previous, local.date(), ml_prices, eur_usd,
                                           skip=previous.get("noArOffer") or {})
    unknown_shipping = [p for p in unknown_shipping if (amount := price_usd(items.get(p["slug"]), eur_usd)) is not None and RANGE_MIN <= amount <= RANGE_MAX]
    if not pending and not unknown_shipping:
        return False
    got, ok, _ = fetch_prices(base_url, pending, today) if pending else ({}, 0, 0)
    for slug, item in got.items():
        items[slug] = {**items.get(slug, {}), **item}
    to_survey = shipping_candidates(candidates, items, previous, local.date(), ml_prices, eur_usd,
                                    skip=previous.get("noArOffer") or {})
    to_survey = [p for p in to_survey if (amount := price_usd(items.get(p["slug"]), eur_usd)) is not None
                 and RANGE_MIN <= amount <= RANGE_MAX]
    envio = refresh_ar_shipping(to_survey, items, today, prices_path)
    ar_shipping = merge_ar_shipping(previous, items, local.date())
    run = dict(previous.get("run") or {})
    run["envio"] = {key: (run.get("envio") or {}).get(key, 0) + value for key, value in envio.items()}
    run["reintento"] = {"recuperados": ok, "pendientes": len(pending), "motivos": run_summary(ok, len(pending))["motivos"]}
    publish.write_atomic(prices_path, {**previous, "items": items, "arShipping": ar_shipping, "run": run, "retried": True, "retryCount": count + 1, "retryAt": local.isoformat(),
                                       "outOfRange": out_of_range_memory(previous, items, eur_usd)})
    print(f"Amazon: reintento de faltantes, recuperados={ok} de {len(pending)}, total={len(items)}.", flush=True)
    write_run_log(prices_path, today, "reintento", ok, len(pending))
    return True


# Motivo de cada producto sin precio en la última pasada (03/11: el user pidió saber SIEMPRE por qué falla).
failures = []


def missing_reason(raw, store):
    """Por qué un producto no dio precio válido, en palabras cortas para el log y el registro diario."""
    if not isinstance(raw, dict):
        return "no_vino_en_respuesta"
    if raw.get("error"):
        return "error:" + str(raw.get("error"))[:60]
    availability = raw.get("availability")
    if isinstance(availability, dict) and availability.get("is_in_stock") is not True:
        return "sin_stock"
    price = raw.get("price")
    if not isinstance(price, dict) or not is_valid_amount(price.get("amount")):
        buybox = raw.get("buybox")
        return "sin_precio_ni_vendedor" if not (isinstance(buybox, dict) and buybox.get("seller")) else "sin_precio"
    if price.get("currency") != STORE_CURRENCY.get(store):
        return "moneda:" + str(price.get("currency"))
    if not (isinstance(raw.get("buybox"), dict) and (raw["buybox"].get("seller") or {}).get("name")):
        return "sin_vendedor_ni_stock"
    return "desconocido"


def write_run_log(prices_path, today, kind, ok, total, log_failures=None):
    """Registro diario que sobrevive a la recreación del contenedor: output/amazon-run-AAAA-MM-DD.json."""
    path = Path(prices_path).with_name(f"amazon-run-{today}.json")
    log = load_json(path, {"date": today, "passes": []})
    log["passes"].append({"kind": kind, "at": datetime.now(ART).isoformat(timespec="seconds"),
                          "ok": ok, "total": total, "pause_s": PAUSE_SECONDS, "fallas": list(failures if log_failures is None else log_failures)})
    publish.write_atomic(path, log)


PAUSE_MIN, PAUSE_MAX = 15.0, 60.0
PACE_VERSION = 2  # ritmos guardados con otra version se descartan (03/11: se paso de 60 s a 15 s + reintento por lote)
CLEAN_DAYS_TO_SPEED_UP = 3


def run_summary(ok, total):
    """Resumen de la corrida con motivos, para el aviso de las 7:30 y para ajustar el ritmo."""
    motivos = {}
    for f in failures:
        motivos[f["motivo"]] = motivos.get(f["motivo"], 0) + 1
    vacios = sorted(f["pos"] for f in failures if f["motivo"] == "sin_precio_ni_vendedor")
    # Ráfaga: muchas páginas sin precio ni vendedor y amontonadas en la segunda mitad de la corrida.
    rafaga = len(vacios) >= 5 and vacios[len(vacios) // 2] > total / 2
    return {"ok": ok, "total": total, "fallas": len(failures), "motivos": motivos,
            "primeraFallaPos": min((f["pos"] for f in failures), default=None),
            "rafaga": rafaga, "pause_s": PAUSE_SECONDS}


def next_pace(previous):
    pace = previous.get("pace") if isinstance(previous, dict) else None
    if not isinstance(pace, dict) or not is_valid_amount(pace.get("pause_s")) or pace.get("v") != PACE_VERSION:
        return {"pause_s": PAUSE_SECONDS, "limpios": 0, "v": PACE_VERSION}
    return {"pause_s": min(PAUSE_MAX, max(PAUSE_MIN, float(pace["pause_s"]))), "limpios": int(pace.get("limpios") or 0),
            "v": PACE_VERSION}


def adjust_pace(pace, run):
    """Ráfaga → el doble de pausa mañana; 3 corridas limpias seguidas → 25% menos."""
    if run["rafaga"]:
        return {"pause_s": min(PAUSE_MAX, pace["pause_s"] * 2), "limpios": 0, "v": PACE_VERSION}
    if run["fallas"] == 0:
        limpios = pace["limpios"] + 1
        if limpios >= CLEAN_DAYS_TO_SPEED_UP:
            return {"pause_s": max(PAUSE_MIN, pace["pause_s"] * 0.75), "limpios": 0, "v": PACE_VERSION}
        return {"pause_s": pace["pause_s"], "limpios": limpios, "v": PACE_VERSION}
    return {"pause_s": pace["pause_s"], "limpios": 0, "v": PACE_VERSION}


def fetch_chunk(base_url, chunk, store):
    try:
        return fetch_bulk(base_url, [p["asin"] for p in chunk], store), None
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        print(f"Amazon: falló lote {store} ({type(exc).__name__}); se omite.", flush=True)
        return {}, f"lote_fallido:{type(exc).__name__}"


def empty_count(fetched, lote_error, chunk, store):
    """Productos del lote que volvieron vacíos por corte de Amazon (no los agotados ni los de precio raro)."""
    if lote_error:
        return len(chunk)
    return sum(1 for p in chunk if missing_reason(fetched.get(p["asin"]), store) == "sin_precio_ni_vendedor")


def fetch_prices(base_url, products, today):
    """Pide precios en lotes por tienda. Devuelve (items, ok, missing); nunca reutiliza precios de otro día."""
    by_store = {}
    for product in products:
        by_store.setdefault(product["store"], []).append(product)

    items = {}
    ok = 0
    missing = 0
    first_call = True
    position = 0
    failures.clear()

    for store, store_products in by_store.items():
        for i in range(0, len(store_products), BULK_MAX):
            chunk = store_products[i:i + BULK_MAX]
            if not first_call:
                pause()
            first_call = False
            fetched, lote_error = fetch_chunk(base_url, chunk, store)
            if empty_count(fetched, lote_error, chunk, store) >= BACKOFF_MIN_EMPTY:
                # 03/11: Amazon corta por ráfaga y se recupera en ~1 min; se espera y se repite este lote una vez.
                print(f"Amazon: lote vacío en pos {position + 1}; espero {BACKOFF_SECONDS:.0f} s y lo repito.", flush=True)
                time.sleep(BACKOFF_SECONDS)
                fetched, lote_error = fetch_chunk(base_url, chunk, store)

            for product in chunk:
                position += 1
                slug = product["slug"]
                raw = fetched.get(product["asin"])
                parsed = valid_price(raw, store)
                reason = None
                if parsed is not None and not plausible(parsed, product):
                    print(f"Amazon: precio descartado por inverosímil {slug} ({parsed[0]} {parsed[1]}).", flush=True)
                    parsed = None
                    reason = "precio_inverosimil"
                if parsed is not None:
                    amount, currency = parsed
                    items[slug] = {"asin": product["asin"], "amount": amount, "currency": currency, "checked": today}
                    ok += 1
                else:
                    missing += 1
                    reason = reason or lote_error or missing_reason(raw, store)
                    failures.append({"slug": slug, "asin": product["asin"], "store": store, "pos": position, "motivo": reason})
                    print(f"Amazon: sin precio {slug} (pos {position}, {reason}).", flush=True)
    return items, ok, missing


_budget_path = None
_budget_day = None


def configure_budget(prices_path, today):
    global _budget_path, _budget_day
    _budget_path = Path(prices_path).with_name("amazon-page-budget.json")
    _budget_day = today


def charge_pages(count):
    if _budget_path is None:
        return
    state = load_json(_budget_path, {})
    used = state.get("pages", 0) if state.get("date") == _budget_day else 0
    limit = int(os.environ.get("AMAZON_DAILY_MAX_PAGES", "650"))
    if used + count > limit:
        raise ValueError("Presupuesto diario de páginas de Amazon agotado")
    publish.write_atomic(_budget_path, {"date": _budget_day, "pages": used + count})
