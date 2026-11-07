"""Fichas de catálogo de Mercado Libre, opcionales y con vigencia de siete días."""
from datetime import date, datetime
from pathlib import Path
import re

import ml_prices
import publish

NOISE = {"PACKAGE_DATA_SOURCE", "GTIN", "SELLER_SKU", "MPN"}


def market_specific(attribute_id):
    """Voltaje y enchufe son de la versión que se vende en Argentina; la que se trae de Amazon
    puede ser otra (07/11: «Voltaje 220V» del Pioneer DDJ-FLX4 al lado de «Tensión: mirala en Amazon»)."""
    return attribute_id == "VOLTAGE" or "PLUG" in attribute_id
QUANTITY = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(GB|TB)\b(?!\s*/)", re.I)  # GB/s es velocidad, no capacidad


def quantities(text):
    return {f"{float(number.replace(',', '.')):g}{unit.upper()}" for number, unit in QUANTITY.findall(text)}


def checked_kind(key):
    """Qué atributos se contrastan con los nombres (07/11, falsos positivos con datos reales):
    - máximos soportados (microSD de 2 TB) y velocidades no son la capacidad del producto;
    - la RAM sólo se contrasta si el nombre trae dos cantidades (p. ej. «128GB 4GB»): con una sola, es el almacenamiento."""
    if "MAX_" in key or "SPEED" in key:
        return None
    if "RAM" in key:
        return "ram"
    if any(part in key for part in ("CAPACITY", "INTERNAL_MEMORY", "STORAGE")):
        return "storage"
    return None


def conflict(product_name, sheet):
    own = quantities(product_name)
    ml_name = quantities(sheet.get("name", ""))
    # Si los dos nombres traen cantidades y no comparten ninguna, el catálogo es otro producto (2TB vs 1TB).
    if own and ml_name and own.isdisjoint(ml_name):
        return f"nombre de ML {sorted(ml_name)} no coincide con {sorted(own)}"
    # Base: el nombre de nuestro producto; el de ML sólo si el nuestro no trae cantidades.
    names = own or ml_name
    for attribute in sheet.get("rawAttributes", []):
        key = attribute.get("id", "").upper()
        kind = checked_kind(key)
        values = quantities(attribute.get("value_name") or "")
        if not names or kind is None or (kind == "ram" and len(names) < 2):
            continue
        if values - names:
            return f"{key}: {attribute.get('value_name')} no coincide con los nombres"
    return None


def log(now, message):
    print(f"{now.astimezone(ml_prices.ART):%Y-%m-%d %H:%M:%S} {message}", flush=True)


def refresh(catalog, output_path, now):
    previous = ml_prices.load_json(output_path, {})
    items = dict(previous.get("items") or {})
    today = now.astimezone(ml_prices.ART).date()
    rejected = set()
    fetched = 0
    for product in catalog:
        catalog_id = (product.get("ml") or {}).get("catalogId")
        if not catalog_id or catalog_id in rejected:
            continue
        sheet = items.get(catalog_id)
        try:
            age = (today - date.fromisoformat(sheet["fetched"])).days if sheet else -1
            fresh = 0 <= age <= 7 and "rawAttributes" in sheet
        except (ValueError, KeyError, TypeError):
            fresh = False
        try:
            if not fresh:
                if not ml_prices.is_configured():
                    continue
                if not re.fullmatch(r"[A-Za-z0-9]+", str(catalog_id)):
                    raise ValueError("catalogId inválido")
                fetched += 1
                try:
                    body = ml_prices.get_json(f"/products/{catalog_id}")
                    raw = body.get("attributes") or []
                    sheet = {
                        "fetched": today.isoformat(), "name": body["name"],
                        "rawAttributes": raw,
                        "attributes": [[a["name"], a["value_name"]] for a in raw
                                       if a.get("name") and a.get("value_name") and a.get("id") not in NOISE
                                       and not a.get("id", "").startswith("PACKAGE_")
                                       and not market_specific(a.get("id", ""))],
                        "mainFeatures": [f["text"] for f in body.get("main_features", []) if f.get("text")],
                    }
                finally:
                    ml_prices.pause()
            reason = conflict(product.get("name", ""), sheet)
            if reason:
                items.pop(catalog_id, None)
                rejected.add(catalog_id)
                log(now, f"FICHA_DESCARTADA {product['slug']} {reason}")
            else:
                items[catalog_id] = sheet
        except Exception as exc:
            # Una falla de consulta conserva la copia previa; el render controla su vigencia.
            log(now, f"FICHA_ERROR {product['slug']} {type(exc).__name__}: {exc}")
            if sheet and conflict(product.get("name", ""), sheet):
                items.pop(catalog_id, None)
                rejected.add(catalog_id)
                log(now, f"FICHA_DESCARTADA {product['slug']} copia previa inconsistente")
    publish.write_atomic(Path(output_path), {"generatedAt": now.isoformat(), "items": items})
    # Una línea por pasada (el worker corre cada hora): consultadas, vigentes y descartadas.
    log(now, f"FICHAS_OK consultadas={fetched} vigentes={len(items)} descartadas={len(rejected)}")


def refresh_optional(catalog, output_path, now):
    try:
        refresh(catalog, output_path, now)
    except Exception as exc:
        log(now, f"FICHAS_ERROR {type(exc).__name__}: {exc}")
