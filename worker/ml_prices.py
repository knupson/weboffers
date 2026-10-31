"""Precios de Mercado Libre y veredicto diario frente a Amazon."""

from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import time

import requests

import publish


API_BASE_URL = "https://api.mercadolibre.com"
SITE_ID = "MLA"
ART = timezone(timedelta(hours=-3))
START_HOUR = 7
MAX_AMAZON_AGE_DAYS = 3
MIN_SAVING = 0.10
AMAZON_EXTRA = 0.04
# Pausa entre llamadas para no castigar la API de Mercado Libre.
PAUSE_SECONDS = 0.3
# Afiliados de Mercado Libre (públicos, van en cada link compartido). Igual que src/config.ts.
AFFILIATE = {"matt_word": "ale_benzoni", "matt_tool": "58527537"}
_token_cache = {"value": None, "expires_at": 0.0}


def is_configured():
    return all(os.environ.get(key, "").strip() for key in ("ML_CLIENT_ID", "ML_CLIENT_SECRET"))


def pause():
    time.sleep(PAUSE_SECONDS)


def get_token():
    """Token client_credentials, cacheado en memoria hasta casi su vencimiento."""
    if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["value"]
    response = requests.post(
        API_BASE_URL + "/oauth/token",
        data={"grant_type": "client_credentials",
              "client_id": os.environ["ML_CLIENT_ID"],
              "client_secret": os.environ["ML_CLIENT_SECRET"]},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    expires_in = float(body.get("expires_in", 3600))
    _token_cache.update(value=body["access_token"],
                        expires_at=time.time() + max(60.0, expires_in - 120))
    return _token_cache["value"]


def get_json(path, params=None):
    response = requests.get(
        API_BASE_URL + path,
        params=params,
        headers={"Authorization": f"Bearer {get_token()}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def search_products(query):
    """Catálogo de Mercado Libre por texto. Devuelve la lista de resultados con id y name."""
    return get_json("/products/search", {"status": "active", "site_id": SITE_ID, "q": query}).get("results", [])


def fetch_items(catalog_id):
    if not re.fullmatch(r"[A-Za-z0-9]+", str(catalog_id)):
        raise ValueError("catalogId inválido")
    return get_json(f"/products/{catalog_id}/items").get("results", [])


def cheapest_new(results):
    """(precio, item_id) de la publicación nueva más barata. Sin campo condition se acepta."""
    best = None
    for item in results:
        if not isinstance(item, dict) or item.get("condition") not in (None, "new"):
            continue
        price = item.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            continue
        if math.isfinite(price) and price > 0 and (best is None or price < best[0]):
            item_id = item.get("item_id") or item.get("id")
            best = (price, item_id if isinstance(item_id, str) and re.fullmatch(r"MLA\d+", item_id) else None)
    return best


def min_new_price(results):
    best = cheapest_new(results)
    return best[0] if best else None


def item_url(catalog_id, item_id):
    """Ficha del producto con esa publicación elegida y el código de afiliado."""
    params = f"matt_word={AFFILIATE['matt_word']}&matt_tool={AFFILIATE['matt_tool']}"
    if item_id:
        params = f"pdp_filters=item_id%3A{item_id}&" + params
    return f"https://www.mercadolibre.com.ar/p/{catalog_id}?{params}"


def _js_round(value):
    return math.floor(value + 0.5)


def shipping_for(usd):
    return 0 if usd >= 100 else 45


def amazon_total_usd(usd, shipping_usd=None):
    """Costo total en USD puesto en casa (impuestos + envío + 4% de Amazon), igual que el sitio."""
    if shipping_usd is None:
        shipping_usd = shipping_for(usd)
    excess = max(0.0, usd - 400.0)
    iva_base = usd + shipping_usd + excess * 0.35 + excess * 0.03
    iva = iva_base * 0.21
    calc_total = _js_round((iva_base + iva) * 100) / 100
    return _js_round((calc_total + usd * AMAZON_EXTRA) * 100) / 100


def estimate_from_amazon(usd, mep):
    """Total en ARS al MEP con la misma fórmula que estimateFromAmazon en src/lib/estimate.ts."""
    shipping_usd = shipping_for(usd)
    excess = max(0.0, usd - 400.0)
    iva_base = usd + shipping_usd + excess * 0.35 + excess * 0.03
    iva = iva_base * 0.21
    calc_total = _js_round((iva_base + iva) * 100) / 100
    return int(_js_round((calc_total + usd * AMAZON_EXTRA) * mep))


def verdict_for(total_usd, mep, ml_price, free_shipping):
    """Amazon sólo gana si ahorra al menos 10% y el envío a Argentina es gratis."""
    # round evita que 0.9 se vea como 0.0999... en el borde del 10%.
    saving = round(1 - total_usd * mep / ml_price, 6)
    return "amazon" if free_shipping is True and saving >= MIN_SAVING else "ml"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _is_valid_amount(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _today_art(now=None):
    if isinstance(now, datetime):
        return now.astimezone(ART).date()
    if isinstance(now, date):
        return now
    return datetime.now(ART).date()


def _is_fresh_checked(checked, today_date):
    if not isinstance(checked, str):
        return False
    try:
        age_days = (today_date - date.fromisoformat(checked)).days
    except ValueError:
        return False
    return 0 <= age_days <= MAX_AMAZON_AGE_DAYS


def load_amazon_prices(path, now=None):
    data = load_json(path, {})
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    today_date = _today_art(now)
    return {
        slug: entry
        for slug, entry in items.items()
        if isinstance(entry, dict)
        and entry.get("currency") in ("USD", "EUR")
        and _is_valid_amount(entry.get("amount"))
        and _is_fresh_checked(entry.get("checked"), today_date)
    }


def resolve_amazon_total(product, amazon_items):
    """Devuelve (total_usd, source) desde amazon-prices.json o listPrice oficial. Omite ES sin tasa EUR->USD."""
    if product.get("store") == "ES":
        return None, None
    slug = product.get("slug")
    scraped = amazon_items.get(slug) if isinstance(amazon_items, dict) else None
    if isinstance(scraped, dict) and scraped.get("currency") == "USD" and _is_valid_amount(scraped.get("amount")):
        return amazon_total_usd(scraped["amount"]), "amazon"
    lp = product.get("listPrice")
    if isinstance(lp, dict) and lp.get("currency") == "USD":
        sale = lp.get("sale")
        official = sale if _is_valid_amount(sale) else lp.get("amount")
        if _is_valid_amount(official):
            return amazon_total_usd(official), "oficial"
    return None, None


def maybe_refresh(catalog, prices_path, amazon_prices_path, mep, now):
    """Recalcula precios y veredictos una vez por día desde las 07:00 ART. Devuelve True si corrió."""
    local = now.astimezone(ART)
    today = local.date().isoformat()
    if local.hour < START_HOUR:
        return False
    previous = load_json(prices_path, None)
    if isinstance(previous, dict) and previous.get("date") == today:
        return False
    if not is_configured():
        print("Mercado Libre: faltan ML_CLIENT_ID o ML_CLIENT_SECRET; se omite.", flush=True)
        return False
    old_items = previous.get("items", {}) if isinstance(previous, dict) else {}
    if not isinstance(old_items, dict):
        old_items = {}
    amazon_items = load_amazon_prices(amazon_prices_path, local.date())
    items = {}
    for product in catalog:
        ml = product.get("ml") or {}
        catalog_id = ml.get("catalogId")
        if not product.get("verified") or not catalog_id:
            continue
        slug = product["slug"]
        try:
            best = cheapest_new(fetch_items(catalog_id))
            if best is None:
                raise ValueError("sin publicaciones nuevas")
            price, item_id = best
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            print(f"Mercado Libre: no se pudo consultar {slug} ({type(exc).__name__}); se conserva el valor anterior.", flush=True)
            if slug in old_items:
                items[slug] = old_items[slug]
            pause()
            continue
        price = int(round(price))
        total, source = resolve_amazon_total(product, amazon_items)
        if total is None or mep is None:
            # Sin total de Amazon o sin MEP no hay cálculo: queda el veredicto del catálogo.
            verdict, reason = product.get("verdict"), "existing"
        else:
            free_shipping = (product.get("shipsToAr") or {}).get("freeShipping")
            verdict, reason = verdict_for(total, mep, price, free_shipping), "precio"
        entry = {"price": price, "url": item_url(catalog_id, item_id), "checked": today,
                 "verdict": verdict, "verdictReason": reason}
        if source:
            entry["amazonSource"] = source
        items[slug] = entry
        pause()
    publish.write_atomic(prices_path, {"generatedAt": now.isoformat(), "date": today, "items": items})
    print(f"Mercado Libre: precios actualizados, productos={len(items)}.", flush=True)
    return True


def merge(catalog, prices_path, amazon_prices_path=None, now=None):
    """Catálogo con el precio y veredicto de Mercado Libre del día (igual que mergeMlPrices del sitio)."""
    data = load_json(prices_path, None)
    items = data.get("items") if isinstance(data, dict) else None
    amazon_items = load_amazon_prices(amazon_prices_path, now) if amazon_prices_path else {}
    if not isinstance(items, dict) and not amazon_items:
        return catalog
    items = items if isinstance(items, dict) else {}
    merged = []
    for product in catalog:
        slug = product.get("slug")
        item = items.get(slug)
        price = item.get("price") if isinstance(item, dict) else None
        has_ml = (
            bool(product.get("ml"))
            and not isinstance(price, bool)
            and isinstance(price, (int, float))
            and math.isfinite(price)
        )
        scraped = amazon_items.get(slug)
        if not has_ml and not scraped:
            merged.append(product)
            continue
        out = {**product}
        if has_ml:
            out["ml"] = {**product["ml"], "price": price}
            if item.get("verdict") in ("amazon", "ml"):
                out["verdict"] = item["verdict"]
            if item.get("amazonSource") in ("amazon", "oficial"):
                out["amazonSource"] = item["amazonSource"]
        if scraped and "amazonSource" not in out:
            out["amazonSource"] = "amazon"
        merged.append(out)
    return merged
