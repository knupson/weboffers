#!/usr/bin/env python3
"""Compara candidatos Amazon/ML con reglas conservadoras, sin IA."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import unicodedata

import requests

ROOT = Path(__file__).resolve().parent.parent
if (ROOT / "worker").is_dir():
    sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT))

import ml_prices  # noqa: E402
import publish  # noqa: E402
import rates  # noqa: E402

DEFAULT_OUTPUT = "/app/output/match-results.json"
VARIANTS = set("hero lightspeed signature music paperwhite colorsoft scribe floodlight ".split()) | set("mini pro plus max ultra lite se fe x s air kit bundle combo pack refurbished renewed reacondicionado usado".split())
UNIT_RE = re.compile(r'\b(\d+(?:[.,]\d+)?)\s*-?\s*(tb|gb|mb|mah|mm|inches|inch|in|pulgadas|pulgada|w|\")(?=$|[^a-z])')
ALIASES = {"wd": "western digital", "wd black": "western digital", "wdblack": "western digital",
           "hewlett packard": "hp", "hewlett packard hp": "hp", "hp inc": "hp",
           "tp": "tp link", "tplink": "tp link", "gl inet": "glinet", "gl.inet": "glinet",
           "logitech g": "logitech", "soundcore": "anker", "anker soundcore": "anker",
           **{brand: "amazon" for brand in ("kindle", "echo", "fire", "blink", "ring", "eero")}}
# Sólo atributos del producto, nunca memoria máxima soportada, velocidades ni accesorios.
QUANTITY_ATTRS = {"CAPACITY", "STORAGE_CAPACITY", "INTERNAL_MEMORY", "RAM_MEMORY", "RAM",
                  "SCREEN_SIZE", "DISPLAY_SIZE", "CASE_SIZE", "BATTERY_CAPACITY", "POWER"}
# Primero las subcategorías; los departamentos ambiguos no alcanzan para decidir.
CATEGORY_RULES = (
    ("Mini PCs", "mini pc|minipc|mini desktop"),
    ("Almacenamiento", "storage|ssd|solid state|hard drive|flash drive|memory card|microsd|almacenamiento"),
    ("Monitores", "monitor|monitors|monitores"),
    ("Periféricos", "keyboard|keyboards|mouse|mice|peripherals|input devices|webcam|teclado|perifericos"),
    ("Relojes", "smartwatch|smartwatches|smart watch|watches|wearable|relojes"),
    ("Tablets y lectores", "tablet|tablets|e reader|ereader|kindle|ebook reader|tablets y lectores"),
    ("Carga y energía", "power bank|power banks|portable charger|battery pack|chargers|carga y energia"),
    ("Redes", "networking|router|routers|modem|mesh|redes|wireless access"),
    ("Cámaras", "camera|cameras|camcorder|lenses|camaras"),
    ("Audio y video", "audio|television|headphones|earbuds|speaker|speakers|soundbar|microphone"),
    ("Componentes", "components|componentes|processor|cpu|gpu|motherboard|ram|computer memory|cooling|power supplies"),
    ("Gaming", "gaming|video games|videogames|controller|gamepad|playstation|xbox|nintendo"),
    ("Cocina", "kitchen|cocina|dining|coffee maker|cookware"),
    ("Cuidado personal", "personal care|cuidado personal|shaver|toothbrush|hair dryer"),
    ("Herramientas", "tools|herramientas|home improvement"),
    ("Deportes", "sports|fitness|deportes|outdoor recreation"),
    ("Juguetes", "toys|juguetes|toys and games"),
    ("Instrumentos", "musical instruments|instrumentos|guitars|pianos"),
    ("Oficina", "office|oficina|printers|scanners"),
    ("Celulares", "cell phones|cellphones|smartphones|mobile phones|celulares"),
    ("Bebés", "baby|babies|bebes"),
    ("Mascotas", "pet supplies|pets|mascotas"),
    ("Belleza", "beauty|belleza|cosmetics|makeup"),
    ("Auto", "automotive|car electronics|auto"),
    ("Jardín", "garden|gardening|patio|jardin|lawn"),
    ("Salud", "health|salud|medical"),
    ("Hogar", "household|home decor|bedding|furniture|smart home|home automation|vacuum|lighting|hogar|home and kitchen"),
)


def ascii_text(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value or "").lower()) if not unicodedata.combining(c))


def normalize(value):
    text = ascii_text(value).translate(str.maketrans({"”": '"', "“": '"', "″": '"'}))
    text = re.sub(r"(?<=\d)''", '"', text)
    # MB/s y GB/s describen transferencia, no almacenamiento.
    text = re.sub(r"\b[\d.,]+\s*(?:mb|gb)\s*/\s*s\b", " ", text)

    def unit(match):
        amount, suffix = float(match[1].replace(",", ".")), match[2]
        if suffix == "tb":
            amount, suffix = amount * 1000, "gb"
        elif suffix in ('"', "inches", "inch", "pulgadas", "pulgada"):
            suffix = "in"
        return f"{amount:g}{suffix}"

    text = UNIT_RE.sub(unit, text)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.]+", " ", text)).strip()


def brand_key(value):
    text = normalize(value).replace(".", " ")
    text = " ".join(text.split())
    return ALIASES.get(text, text)


def category_for(value):
    text = normalize(value).replace(" & ", " and ")
    for category, keywords in CATEGORY_RULES:
        if normalize(category) == text:
            return category
    for category, keywords in CATEGORY_RULES:
        if any(re.search(r"\b" + re.escape(word) + r"\b", text) for word in keywords.split("|")):
            return category
    return None


def quantities(value):
    result = {}
    for amount, unit in re.findall(r"\b(\d+(?:\.\d+)?)(gb|mb|mah|mm|in|w)\b", normalize(value)):
        result.setdefault(unit, set()).add(float(amount))
    return result


def model_tokens(value):
    text = ascii_text(value)
    text = UNIT_RE.sub(" ", text)
    # Los prefijos de códigos también pueden venir separados por espacios.
    text = re.sub(r"\b(wf|wh|mz|rt|sn)\s+(?=[a-z0-9]*\d)", r"\1-", text)
    tokens = set()
    for raw in re.findall(r"[a-z0-9]+(?:[-_/][a-z0-9]+)*", text):
        token = re.sub(r"[-_/]", "", raw)
        # Sufijos de embalaje no cambian el código base.
        if re.fullmatch(r"[a-z]+\d+[a-z0-9]+/[0-9]+", raw):
            token = raw.split("/")[0]
        if len(token) < 2 or not re.search(r"[a-z]", token) or not re.search(r"\d", token):
            continue
        # Plataformas y especificaciones compartidas no prueban identidad.
        if re.fullmatch(r"(?:ps[345]|4k|8k|\d+(?:mp|fps|ms|x|axis|eje)|f\d+|hdr\d+|\d+x\d+)", token):
            continue
        if quantities(raw) or re.fullmatch(r"(?:pcie|usb|ddr|wifi|wi-fi|bluetooth|bt|gen)\d+[a-z]*", token):
            continue
        if re.fullmatch(r"\d+(?:hz|khz|mhz|ghz|k|p|mbps|gbps)", token):
            continue
        tokens.add(token)
    # Familias numéricas (990 PRO) también identifican un modelo concreto.
    for number, edition in re.findall(r"\b(\d{3,4})\s+(pro|evo|plus|ultra|max|mini)\b", normalize(value)):
        tokens.add(number + edition)
    # Familias comerciales con versión numérica; una marca sola no es modelo.
    for family, version in re.findall(r"\b(ultimate|stealth|go|flip|quest|forerunner|pocket)\s+(\d+[a-z]?)\b", normalize(value)):
        tokens.add(family + version)
    for family, version in re.findall(r"\b(blackshark|wolverine|huntsman)\s+(v\d+)\b", normalize(value)):
        tokens.discard(version)
        tokens.add(family + version)
    return tokens


def family_conflict(left, right):
    shared = left & right
    for a in left:
        for b in right:
            pa, pb = re.match(r"([a-z]*)(\d+)", a), re.match(r"([a-z]*)(\d+)", b)
            if pa and pb and a != b:
                # El código completo compartido puede abreviarse en el nombre ML.
                if (a.startswith(b) and a in shared) or (b.startswith(a) and b in shared):
                    continue
                if pa[1] and pa[1] == pb[1]:
                    return True
                if not pa[1] and not pb[1] and pa[2] == pb[2]:
                    return True
    return False


def variant_words(value):
    text = re.split(r"\b(?:for|para)\b|[|]", ascii_text(value), maxsplit=1)[0]
    text = re.sub(r"\bultra[ -](?:portable|slim)\b|\bpro[ -]level\b", "", text)
    words = normalize(text).split()
    anchors = [i for i, word in enumerate(words) if model_tokens(word) or (word.isdigit() and len(word) <= 4)]
    found = {word for i, word in enumerate(words) if word in VARIANTS and any(abs(i - j) <= 3 for j in anchors)}
    # Estado y cantidad del paquete importan aunque estén lejos del modelo.
    found.update(set(words) & {"hero", "lightspeed", "signature", "music", "paperwhite", "colorsoft", "scribe", "floodlight"})
    found.update(set(normalize(value).split()) & {"kit", "bundle", "combo", "pack", "refurbished", "renewed", "reacondicionado", "usado"})
    found.update(re.findall(r"\b\d+ pack\b", normalize(value)))
    if re.search(r"\b(?:lens|lente)\b", normalize(value)):
        found.discard("fe")
    return found


def attributes(product):
    result = {}
    raw = product.get("attributes")
    for attr in raw if isinstance(raw, list) else []:
        if not isinstance(attr, dict) or not isinstance(attr.get("id"), str):
            continue
        values = []
        if isinstance(attr.get("value"), (str, int, float)):
            values.append(str(attr["value"]))
        if isinstance(attr.get("value_name"), (str, int, float)):
            values.append(str(attr["value_name"]))
        structured = attr.get("value_struct")
        if isinstance(structured, dict) and structured.get("number") is not None:
            values.append(f"{structured['number']}{structured.get('unit') or ''}")
        raw_values = attr.get("values")
        for val in raw_values if isinstance(raw_values, list) else []:
            if isinstance(val, dict) and isinstance(val.get("name"), str):
                values.append(val["name"])
        if values:
            result[attr["id"].upper()] = " ".join(dict.fromkeys(values))
    return result


def positive_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def accessory(value):
    text = normalize(value)
    return bool(re.search(r"\b(?:case|cover|funda|protector|replacement|repuesto|cable|adapter|adaptador)\b.{0,45}\b(?:for|para|compatible)\b|\bcompatible (?:with|con)\b", text))


def evaluate(amazon, candidate, product, mep):
    """Devuelve estado, motivo y evidencia; una contradicción gana sobre una duda."""
    title = amazon.get("amazonTitle") or ""
    name = product.get("name") or candidate.get("name") or ""
    attrs = attributes(product)
    brand = amazon.get("brand") or (title.split()[0] if title.split() else "")
    model = " ".join(attrs.get(key, "") for key in ("MODEL", "ALPHANUMERIC_MODEL"))
    ml_text = " ".join([name, *(value for key, value in attrs.items() if key in QUANTITY_ATTRS)])
    a_models, b_models = model_tokens(title), model_tokens(model + " " + name)
    a_caps, b_caps = quantities(title), quantities(ml_text)
    # En auriculares los mm suelen ser conectores y transductores, no variantes.
    if re.search(r"\b(?:headset|headphones|earbuds)\b", normalize(title)):
        a_caps.pop("mm", None)
        b_caps.pop("mm", None)
    a_models -= model_tokens(brand)
    b_models -= model_tokens(attrs.get("BRAND", ""))
    if brand_key(brand) in {"tp link", "asus", "netgear"}:
        a_models = {token for token in a_models if not re.fullmatch(r"(?:axe?|be)\d{3,}", token)}
        b_models = {token for token in b_models if not re.fullmatch(r"(?:axe?|be)\d{3,}", token)}
    shared = a_models & b_models
    # Un modelo textual completo sirve si es específico y no contradice códigos.
    textual = normalize(attrs.get("MODEL", ""))
    generic_models = {"otros", "other", "generic", "generico", "wireless", "controller", "headphones", "headset", "tablet", "camera", "digital", "gaming"}
    if (not shared and len(textual) >= 5 and textual not in generic_models
            and not re.fullmatch(r"(?:axe?|be)\d{3,}", textual)
            and re.search(r"\b" + re.escape(textual) + r"\b(?! \d)", normalize(title))
            and not (a_models and b_models and not shared)):
        shared.add(textual)

    evidence = {"brand": brand_key(brand) if brand_key(brand) == brand_key(attrs.get("BRAND")) else "",
                "model": sorted(shared), "capacity": sorted(f"{n:g}{u}" for u in a_caps.keys() & b_caps.keys() for n in a_caps[u] & b_caps[u])}
    doubts = []
    if re.search(r"\b(?:libro|book|manual|user guide|cookbook|editorial)\b", normalize(name)):
        return "rejected", "libro o manual en lugar del producto", evidence
    if accessory(title) or accessory(name):
        return "rejected", "accesorio", evidence
    if brand and attrs.get("BRAND") and brand_key(brand) != brand_key(attrs["BRAND"]):
        return "rejected", "marca distinta", evidence
    def connection(text):
        words = set(normalize(text).split())
        return {"wireless" if w in {"wireless", "inalambrico", "inalambricos"} else "wired"
                for w in words & {"wireless", "inalambrico", "inalambricos", "wired", "cableado"}}
    if connection(title) and connection(name) and connection(title).isdisjoint(connection(name)):
        return "rejected", "conectividad distinta", evidence
    def platforms(text):
        text = normalize(text)
        return {key for key, pattern in {"xbox": r"\bxbox\b", "playstation": r"\b(?:playstation|ps[345])\b",
                                        "nintendo": r"\b(?:nintendo|switch)\b"}.items() if re.search(pattern, text)}
    listed_platforms = platforms(attrs.get("COMPATIBLE_DEVICES", ""))
    if listed_platforms and platforms(name) and listed_platforms.isdisjoint(platforms(name)):
        doubts.append("plataforma contradictoria entre nombre y atributos")
    if not evidence["brand"]:
        doubts.append("marca ausente")
    for unit in a_caps.keys() & b_caps.keys():
        if a_caps[unit] != b_caps[unit]:
            return "rejected", "capacidad o tamaño distinto", evidence
    if a_caps.keys() != b_caps.keys():
        doubts.append("capacidad o tamaño sin confirmar")
    if re.search(r"\b(?:edition|edicion|anniversary)\b", normalize(title + " " + name)):
        # Ediciones especiales requieren revisión aunque compartan el modelo base.
        doubts.append("edición sin confirmar")
    if family_conflict(a_models, b_models):
        return "rejected", "modelo de otra familia o edición", evidence
    variants_differ = variant_words(title) != variant_words(name + " " + model + " " + attrs.get("LINE", ""))
    if a_models and b_models and not shared:
        return "rejected", "modelo distinto", evidence
    if not shared and (not a_models or not b_models):
        doubts.append("modelo ausente")
    if re.search(r"\b(?:headset|headphones|earbuds)\b", normalize(title)):
        a_gen = re.findall(r"\bgen(?:eration)? (\d+)\b", normalize(title))
        b_gen = re.findall(r"\bgen(?:eration)? (\d+)\b", normalize(name + " " + model))
        if set(a_gen) != set(b_gen):
            doubts.append("generación sin confirmar")
    # Un número de versión adyacente al modelo textual no puede quedar implícito.
    if textual and re.search(r"\b" + re.escape(textual) + r" \d+\b", normalize(title)) and not shared:
        doubts.append("generación sin confirmar")
    if variants_differ:
        doubts.append("variante distinta")
    colors = {"black": "negro", "white": "blanco", "blue": "azul", "red": "rojo", "green": "verde", "silver": "plata", "gold": "dorado", "pink": "rosa",
              "gray": "gris", "grey": "gris", "purple": "violeta", "plateado": "plata",
              "charcoal": "carbon", "midnight": "medianoche", "ash": "ceniza", "rose": "rosa"}
    def color_words(text):
        text = re.sub(r"\bblue vo[! ]*ce\b", "", ascii_text(text))
        return {colors.get(word, word) for word in normalize(text).split() if word in colors or word in colors.values()}
    def without_brand(text, raw_brand):
        return normalize(text).replace(normalize(raw_brand), " ", 1) if raw_brand else normalize(text)
    a_colors = color_words(without_brand(title, brand))
    b_colors = color_words(without_brand(name, attrs.get("BRAND")) + " " + attrs.get("COLOR", ""))
    if a_colors != b_colors and (a_colors or b_colors):
        doubts.append("color sin confirmar")
    price, usd = candidate.get("minPrice"), amazon.get("amazonPriceUsd")
    if positive_number(price) and positive_number(usd):
        ratio = price / (usd * mep)
        evidence["priceRatio"] = ratio
        if not 0.6 <= ratio <= 6.0:
            return "rejected", "precio fuera de rango", evidence
    else:
        doubts.append("precio ausente o inválido")
    if not category_for(amazon.get("amazonCategory")):
        doubts.append("categoría")
    if not attrs or not product.get("name"):
        doubts.append("atributos o nombre ausentes")
    if not all(isinstance(amazon.get(k), str) and amazon[k].strip() for k in ("asin", "store")) or not candidate.get("itemId"):
        doubts.append("identificadores ausentes")
    return ("doubtful", "; ".join(doubts), evidence) if doubts else ("accepted", "", evidence)


def unique_slug(brand, evidence, name, used):
    base = " ".join([brand, *evidence["model"], *evidence["capacity"]])
    if not evidence["model"]:
        base = name or brand or "producto"
    base = re.sub(r"[^a-z0-9]+", "-", ascii_text(base)).strip("-") or "producto"
    slug, suffix = base, 2
    while slug in used:
        slug, suffix = f"{base}-{suffix}", suffix + 1
    used.add(slug)
    return slug


def match_products(products, mep, catalog=(), products_cache=None):
    if not positive_number(mep):
        raise ValueError("MEP inválido; indicá --mep con un valor positivo.")
    if not isinstance(products, list):
        raise ValueError("La entrada debe ser una lista JSON.")
    result = {"generatedAt": datetime.now(timezone.utc).isoformat(), "mep": mep,
              "accepted": [], "doubtful": [], "rejected": []}
    used = {entry["slug"] for entry in catalog if isinstance(entry, dict) and isinstance(entry.get("slug"), str)}
    if products_cache is not None and (not isinstance(products_cache, dict)
            or any(not isinstance(value, dict) for value in products_cache.values())):
        raise ValueError("El caché debe ser un diccionario de productos ML.")
    cache = dict(products_cache or {})
    for index, amazon in enumerate(products, 1):
        if not isinstance(amazon, dict):
            result["rejected"].append({"reason": "producto inválido", "index": index})
            if index % 50 == 0:
                print(f"Procesados {index}/{len(products)} productos", flush=True)
            continue
        chosen = None
        failures = []
        candidates = amazon.get("ml")
        for candidate in candidates if isinstance(candidates, list) else []:
            if not isinstance(candidate, dict):
                continue
            catalog_id = candidate.get("catalogId")
            if not isinstance(catalog_id, str) or not re.fullmatch(r"[A-Za-z0-9]+", catalog_id):
                failures.append({"catalogId": catalog_id, "reason": "catalogId inválido"})
                continue
            if catalog_id not in cache:
                try:
                    payload = ml_prices.get_json(f"/products/{catalog_id}")
                    cache[catalog_id] = payload if isinstance(payload, dict) else {}
                except (requests.RequestException, ValueError, KeyError, TypeError):
                    cache[catalog_id] = {}
                finally:
                    ml_prices.pause()
            product = cache[catalog_id]
            status, reason, evidence = evaluate(amazon, candidate, product, mep)
            score = bool(evidence["brand"]) + 2 * bool(evidence["model"]) + bool(evidence["capacity"])
            if status == "rejected":
                attrs = attributes(product)
                failures.append({"catalogId": catalog_id, "reason": reason, "evidence": evidence,
                                 "mlName": product.get("name") or candidate.get("name") or "",
                                 "mlBrand": attrs.get("BRAND", ""), "mlModel": attrs.get("MODEL", ""),
                                 "mlPrice": candidate.get("minPrice") if positive_number(candidate.get("minPrice")) else None,
                                 "score": score})
                continue
            # La mejor duda es la que tiene más evidencia; los empates conservan el orden.
            if status == "accepted" or chosen is None or score > chosen[0]:
                chosen = (score, status, reason, evidence, candidate, product)
            if status == "accepted":
                break
        if chosen:
            _, status, reason, evidence, candidate, product = chosen
            name = re.split(r"\s*[|;]\s*|\s+[-–—]\s+(?:env[ií]o|oferta|cuotas|vendido)\b", str(product.get("name") or candidate.get("name") or amazon.get("amazonTitle") or ""), maxsplit=1, flags=re.I)[0].strip()
            brand = amazon.get("brand") or (amazon.get("amazonTitle", "").split() or [""])[0]
            row = {k: amazon.get(k, "") for k in ("asin", "store", "amazonTitle")}
            row.update(catalogId=candidate["catalogId"], itemId=candidate.get("itemId") or "",
                       mlPrice=candidate.get("minPrice") if positive_number(candidate.get("minPrice")) else None, name=name, brand=brand,
                       category=category_for(amazon.get("amazonCategory")) or "", summary="",
                       evidence=evidence, mlName=product.get("name") or candidate.get("name") or "",
                       mlBrand=attributes(product).get("BRAND", ""), mlModel=attributes(product).get("MODEL", ""),
                       amazonPriceUsd=amazon.get("amazonPriceUsd"))
            row["slug"] = unique_slug(brand, evidence, name, used)
            if reason:
                row["reason"] = reason
            result[status].append(row)
        else:
            best = max(failures, key=lambda failure: failure.get("score", -1), default={})
            result["rejected"].append({**{key: best.get(key, "") for key in
                                        ("catalogId", "mlName", "mlBrand", "mlModel", "mlPrice", "evidence")},
                                       "category": category_for(amazon.get("amazonCategory")) or "",
                                       "asin": amazon.get("asin"), "amazonTitle": amazon.get("amazonTitle"),
                                       "reason": best.get("reason", "sin candidatos"),
                                       "candidates": failures})
        if index % 50 == 0:
            print(f"Procesados {index}/{len(products)} productos", flush=True)
    result["summary"] = {key: len(result[key]) for key in ("accepted", "doubtful", "rejected")}
    result["summary"]["byCategory"] = dict(Counter(row["category"] for row in result["accepted"]))
    return result


def default_catalog_path():
    for path in (ROOT / "data" / "catalog.json", Path(os.getenv("CATALOG_PATH") or "/data/catalog.json")):
        if path.exists():
            return path
    raise ValueError("No se encontró data/catalog.json para verificar slugs.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="/app/output/discovery-candidates.json", help="JSON de descubrimiento")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="JSON de resultados")
    parser.add_argument("--mep", type=float, help="Cotización MEP; por defecto se consulta la actual")
    parser.add_argument("--products-cache", help="Detalles ML locales por catalogId; consulta la API sólo para los faltantes")
    parser.add_argument("--limit", type=int, help="Cantidad máxima de productos")
    args = parser.parse_args(argv)
    try:
        mep = args.mep
        if mep is None:
            current = rates.get_rates()
            mep = current.get("mep") if isinstance(current, dict) else None
        if not positive_number(mep):
            raise ValueError("No hay MEP válido; indicá --mep.")
        if args.limit is not None and args.limit < 0:
            raise ValueError("--limit no puede ser negativo.")
        products = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if not isinstance(products, list):
            raise ValueError("La entrada debe ser una lista JSON.")
        catalog = json.loads(default_catalog_path().read_text(encoding="utf-8"))
        cache = json.loads(Path(args.products_cache).read_text(encoding="utf-8")) if args.products_cache else {}
        if not isinstance(cache, dict) or any(not isinstance(value, dict) for value in cache.values()):
            raise ValueError("El caché debe ser un diccionario de productos ML.")
        result = match_products(products[:args.limit] if args.limit is not None else products, mep, catalog, cache)
        publish.write_atomic(args.output, result)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr, flush=True)
        return 1
    counts = result["summary"]
    print(f"Aceptados: {counts['accepted']}; dudosos: {counts['doubtful']}; rechazados: {counts['rejected']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
