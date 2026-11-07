"""Adaptador conservador entre tarjetas y clasificación compartida."""
import re
from amazon_shipping import parse_delivery, PAID_DELIVERY_RE, ES_PAID_RE


def session_is_ar(session):
    return getattr(session, "located", None) == "AR"


def classify_shipping(result):
    if result["ships"] is False:
        return "no_envia"
    if result["ships"] is None:
        return "desconocido"
    return {True: "gratis", False: "pago", None: "envia_costo_desconocido"}[result["free"]]


def delivery_from_card(card, located=False):
    delivery = card.get("delivery")
    if isinstance(delivery, str):
        delivery = {"text": delivery, "location": "Argentina" if located else None}
    result = parse_delivery({**card, "delivery": delivery}, located=located)
    if not located:
        result["ships"], result["free"] = None, None
    text = result.get("text") or ""
    options = (delivery or {}).get("options") or []
    paid = PAID_DELIVERY_RE.search(text) or ES_PAID_RE.search(text) or any(
        re.search(r"[$€]\s*\d|\d[,.]\d{2}\s*€", str(o.get("price_text", ""))) for o in options if isinstance(o, dict))
    if result["ships"] and result["free"] is False and not paid:
        result["free"] = None
    return {**result, "shipping_class": classify_shipping(result)}
