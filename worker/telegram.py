"""Producto del día en el canal de Telegram de Franquicia 400."""

from datetime import datetime, timedelta, timezone
import html
import urllib.parse
import json
import math
import os
from pathlib import Path

import requests

import ml_prices
from amazon_prices import fresh_shipping_date


SITE = "https://ofertas.knunet.com"
ART = timezone(timedelta(hours=-3))
POST_HOURS = (12, 20)
STORES = {"US": "Amazon.com", "ES": "Amazon.es"}
DISCLOSURE = "Links de afiliado: si comprás, Amazon o Mercado Libre nos pagan una comisión y a vos te sale lo mismo."


def is_configured():
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def load_state(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"lastDate": None, "posted": []}


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _valid_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _has_amazon_estimate(product):
    """Exige un estimado vigente en ARS calculado con las mismas condiciones que el sitio (`amazonArs`)."""
    return _valid_number(product.get("amazonArs"))


def is_comparable(product, now=None):
    """Misma regla que isComparable en src/lib/data.ts: verificado, con ASIN, precio en ML y estimado de Amazon."""
    asin = product.get("asin")
    ml = product.get("ml")
    today = (now or datetime.now(timezone.utc)).astimezone(ART).date()
    usd = product.get("amazonUsd")
    return bool(
        product.get("verified") is True
        and bool(product.get("image"))
        and isinstance(asin, str)
        and asin.strip()
        and isinstance(ml, dict)
        and _valid_number(ml.get("price"))
        and ml.get("checked") == today.isoformat()
        and _has_amazon_estimate(product)
        and _valid_number(usd) and 100 <= usd <= 400
        and product.get("amazonSource") == "amazon"
        and product.get("amazonChecked") == today.isoformat()
        and product.get("shipsToArToday") is not False
        # REGLA 0 (03/11): sin envío gratis a Argentina confirmado no se publica, igual que en el sitio.
        and (product.get("shipsToAr") or {}).get("freeShipping") is True
        and fresh_shipping_date((product.get("shipsToAr") or {}).get("checked"), today)
    )


def pick(catalog, posted, now=None):
    """El próximo producto comparable que no salió todavía; con foto primero. Al agotarse, vuelve a empezar."""
    candidates = [p for p in catalog if is_comparable(p, now)]
    fresh = [p for p in candidates if p["slug"] not in posted] or candidates
    fresh.sort(key=lambda p: p.get("image") is None)
    return fresh[0] if fresh else None


def _verdict_for_product(product):
    ml = product.get("ml")
    ml_price = ml.get("price") if isinstance(ml, dict) else None
    amazon_ars = product.get("amazonArs")
    if _valid_number(ml_price) and _valid_number(amazon_ars):
        free_shipping = (product.get("shipsToAr") or {}).get("freeShipping")
        return ml_prices.verdict_from_ars(ml_price, amazon_ars, free_shipping)
    return product.get("verdict") if product.get("verdict") in ("amazon", "ml") else "ml"


# 13/11: UTMs comunes de la difusión automática: utm_medium=social, campaña fija por tipo de pieza y el detalle
# (slug o id del Reel) en utm_content, para sumar por campaña en Umami. Antes: utm_medium=canal (hasta el 13/11).
def utm_url(path, source, campaign, content):
    query = urllib.parse.urlencode({"utm_source": source, "utm_medium": "social", "utm_campaign": campaign,
                                    "utm_content": content})
    return f"{SITE}{path}?{query}"


def caption(product):
    url = utm_url(f"/productos/{product['slug']}/", "telegram", "producto-diario", product["slug"])
    ml = product.get("ml")
    lines = [f"<b>{html.escape(product['name'])}</b>", html.escape(product["summary"]), ""]
    if ml:
        precio = f"${ml['price']:,.0f}".replace(",", ".")
        lines.append(f"En Argentina: <b>{precio}</b> en Mercado Libre.")
        verdict = _verdict_for_product(product)
        if verdict == "amazon":
            lines.append(f"Traerlo de {STORES.get(product['store'], 'Amazon')} sale bastante menos puesto en tu casa.")
        elif verdict == "sin_envio":
            lines.append("Traerlo de Amazon saldría menos, pero no confirmamos el envío a Argentina.")
        else:
            lines.append("Traerlo de Amazon no te ahorra: conviene comprarlo acá, llega en días.")
    else:
        lines.append(f"En {STORES.get(product['store'], 'Amazon')}. Mirá cuánto te sale puesto en tu casa:")
    lines += ["Comparación completa y links:", url, "", f"<i>{DISCLOSURE}</i>"]
    return "\n".join(lines)


def send(product):
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat = os.environ["TELEGRAM_CHAT_ID"].strip()
    text = caption(product)
    if product.get("image"):
        photo = SITE + product["image"].replace(".webp", ".jpg")
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendPhoto",
                             data={"chat_id": chat, "photo": photo, "caption": text, "parse_mode": "HTML"}, timeout=20)
    else:
        resp = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                             data={"chat_id": chat, "text": text, "parse_mode": "HTML"}, timeout=20)
    resp.raise_for_status()


def maybe_post(catalog, state_path, now=None):
    """Publica un producto en cada horario de POST_HOURS (Argentina). Devuelve el slug publicado o None."""
    if not is_configured():
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(ART)
    today = now.date().isoformat()
    slots = [h for h in POST_HOURS if now.hour >= h]
    if not slots:
        return None
    slot = f"{today}T{slots[-1]:02d}"
    state = load_state(state_path)
    pending = state.get("attempt")
    if pending:
        # Sin un identificador confirmado no podemos verificar el envío: consumimos ese turno.
        print(f"TELEGRAM_INCIERTO {pending['slug']}", flush=True)
        state["lastSlot"] = max(state.get("lastSlot", ""), pending["slot"])
        state["attempt"] = None
        save_state(state_path, state)
    # Estado viejo (sólo lastDate): el turno de las 12 de ese día ya salió.
    last = state.get("lastSlot") or (f"{state['lastDate']}T{POST_HOURS[0]:02d}" if state.get("lastDate") else "")
    if last >= slot:
        return None
    product = pick(catalog, state.get("posted", []), now)
    if product is None:
        # 11/11: el 10/11 el turno de las 12 salió a las 15:01 sin una línea en el log que dijera por qué.
        print(f"TELEGRAM_SIN_COMPARABLES slot={slot} catalogo={len(catalog)}", flush=True)
        return None
    state["attempt"] = {"estado": "intentando", "slug": product["slug"], "slot": slot}
    save_state(state_path, state)
    print(f"intentando {product['slug']} {slot}", flush=True)
    try:
        send(product)
    except (TimeoutError, requests.exceptions.ReadTimeout):
        raise  # el mensaje pudo haber salido: queda como intento incierto y no se repite
    except Exception:
        # Error claro de la API o sin conexión: no salió, se borra el intento y se reintenta en el ciclo siguiente.
        state["attempt"] = None
        save_state(state_path, state)
        raise
    state["attempt"] = None
    state["lastDate"] = today
    state["lastSlot"] = slot
    state["posted"] = (state.get("posted", []) + [product["slug"]])[-200:]
    save_state(state_path, state)
    print(f"Telegram: publicado {product['slug']}.", flush=True)
    return product["slug"]
