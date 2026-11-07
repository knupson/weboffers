"""Contrato estable de evidencia diaria; elegible no significa publicable."""
import math


def positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def normalize_product(raw, *, store, identity, stamp, currency, rate, provenance, shipping,
                      located=False, condition=None, known=False, min_usd=100, max_usd=400):
    price = raw.get("price")
    if isinstance(price, dict):
        actual_currency = price.get("currency")
        price = price.get("amount") if actual_currency == currency else None
    price = price if positive(price) else None
    usd = price * rate["value"] if price is not None else None
    reasons = []
    if usd is None:
        reasons.append("sin_precio_validado")
    elif not min_usd <= usd <= max_usd:
        reasons.append("fuera_de_rango")
    if condition != "new":
        reasons.append("condicion_no_confirmada")
    if shipping["shipping_class"] not in ("gratis", "pago", "envia_costo_desconocido"):
        reasons.append("envio_no_confirmado")
    return dict(schema_version=1, store=store, id=identity, date=stamp[:10], observed_at=stamp,
                title=raw.get("title") or raw.get("name"), currency=currency, price=price,
                price_usd=usd, exchange_rate=rate, condition=condition, shipping_text=shipping.get("text"),
                shipping_class=shipping["shipping_class"], located_ar=located,
                has_variations=raw.get("has_variations"), variations_text=raw.get("variations_text"),
                variations=None, known=known, eligible=not reasons, rejection_reasons=reasons,
                provenance=[provenance], raw=raw)
