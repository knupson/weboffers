"""Producto del día en el canal de Telegram de Franquicia 400."""

from datetime import datetime, timedelta, timezone
import html
import json
import os
from pathlib import Path

import requests


SITE = "https://ofertas.knunet.com"
ART = timezone(timedelta(hours=-3))
POST_HOUR = 12
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
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pick(catalog, posted):
    """El próximo producto verificado que no salió todavía; con foto primero. Al agotarse, vuelve a empezar."""
    candidates = [p for p in catalog if p.get("verified")]
    fresh = [p for p in candidates if p["slug"] not in posted] or candidates
    fresh.sort(key=lambda p: p.get("image") is None)
    return fresh[0] if fresh else None


def caption(product):
    url = f"{SITE}/productos/{product['slug']}/?utm_source=telegram&utm_medium=canal&utm_campaign=producto-diario"
    ml = product.get("ml")
    lines = [f"<b>{html.escape(product['name'])}</b>", html.escape(product["summary"]), ""]
    if ml:
        precio = f"${ml['price']:,.0f}".replace(",", ".")
        lines.append(f"En Argentina: <b>{precio}</b> en Mercado Libre.")
        if product.get("verdict") == "amazon":
            lines.append(f"Traerlo de {STORES.get(product['store'], 'Amazon')} sale bastante menos puesto en tu casa.")
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
    """Publica un producto por día, a partir de las 12 de Argentina. Devuelve el slug publicado o None."""
    if not is_configured():
        return None
    now = (now or datetime.now(timezone.utc)).astimezone(ART)
    today = now.date().isoformat()
    state = load_state(state_path)
    if state.get("lastDate") == today or now.hour < POST_HOUR:
        return None
    product = pick(catalog, state.get("posted", []))
    if product is None:
        return None
    send(product)
    state["lastDate"] = today
    state["posted"] = (state.get("posted", []) + [product["slug"]])[-200:]
    save_state(state_path, state)
    print(f"Telegram: publicado {product['slug']}.", flush=True)
    return product["slug"]
