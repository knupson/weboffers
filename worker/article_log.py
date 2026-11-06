"""Formato de una línea por artículo, compartido por Chrome y los workers."""
import json
from datetime import datetime, timedelta, timezone


def value(raw):
    if raw is None:
        return "ausente"
    if isinstance(raw, bool):
        return str(raw).lower()
    return " ".join(str(raw).split())


def chrome_line(slugs, asin, item):
    return (f"CHROME_PRODUCTO slugs={value(','.join(slugs))} asin={value(asin)} "
            f"ships={value(item.get('ships'))} free={value(item.get('free'))} "
            f"precio={value(item.get('precio'))} motivo={value(item.get('motivo') or 'ok')} "
            f"texto={json.dumps(value(item.get('text'))[:160], ensure_ascii=False)}")


def amazon_line(product, source, item=None, reason=None):
    item = item or {}
    return (f"AMAZON_PRODUCTO slug={value(product.get('slug'))} asin={value(product.get('asin'))} "
            f"store={value(product.get('store'))} source={source} "
            f"amount={value(item.get('amount'))} currency={value(item.get('currency'))} "
            f"checked={value(item.get('checked'))} motivo={value(reason or 'ok')}")


def ml_line(product, status, item=None, reason=None):
    item = item or {}
    return (f"ML_PRODUCTO slug={value(product.get('slug'))} price={value(item.get('price'))} "
            f"checked={value(item.get('checked'))} estado={status} motivo={value(reason or 'ok')}")


def alta_line(product, decision, reason=None, item=None):
    """Decisión del alta con evidencia y horario ART, aun fuera de DailyLog."""
    item = item or {}
    stamp = datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M:%S")
    return (f"{stamp} ALTA_PRODUCTO slug={value(product.get('slug'))} asin={value(product.get('asin'))} "
            f"decision={decision} ships={value(item.get('ships'))} free={value(item.get('free'))} "
            f"precio={value(item.get('precio'))} motivo={value(reason or item.get('motivo') or 'ok')} "
            f"texto={json.dumps(value(item.get('text'))[:160], ensure_ascii=False)}")
