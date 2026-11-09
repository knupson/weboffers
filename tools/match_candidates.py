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
from variants import variant_conflicts
from tools.apply_candidates import candidate_summary  # noqa: E402
from tools.identifier_gate import ML_FIELDS  # noqa: E402

DEFAULT_OUTPUT = "/app/output/match-results.json"
VARIANTS = set("hero lightspeed signature music paperwhite colorsoft scribe floodlight ".split()) | set("core neo go mini pro plus max ultra lite se fe x s air kit bundle combo pack refurbished renewed reacondicionado usado".split())
# «Stinger 2 Core» es edición; «8-Core»/«Octa Core» son núcleos de CPU.
CORE_SPEC_RE = re.compile(r"\b(?:\d+\s*-\s*cores?|(?:dual|quad|hexa|octa|deca)[ -]+cores?"
                          r"|\d+\s+cores|\d+\s+core(?=.{0,30}\b(?:processor|procesador|cpu)\b))\b")
UNIT_RE = re.compile(r'\b(\d+(?:[.,]\d+)?)\s*-?\s*(tb|gb|mb|mah|mm|inches|inch|in|pulgadas|pulgada|pulg|w|\")(?=$|[^a-z])')
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
    ("Audio y video", "audio|television|headphones|earbuds|speaker|speakers|loudspeaker|soundbar|microphone|voice recorder|tv box"),
    ("Componentes", "components|componentes|processor|cpu|gpu|motherboard|ram|computer memory|cooling|power supplies"),
    ("Gaming", "gaming|video games|videogames|controller|gamepad|playstation|xbox|nintendo|racing wheel"),
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
        elif suffix in ('"', "inches", "inch", "pulgadas", "pulgada", "pulg"):
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


def memory_text(value):
    """En «4+64GB» el primer número es RAM y el segundo almacenamiento."""
    return re.sub(r"\b(\d+)\s*\+\s*(\d+)\s*(gb|tb)\b", r"\1\3 RAM \2\3", ascii_text(value))


def quantities(value):
    result = {}
    for amount, unit in re.findall(r"\b(\d+(?:\.\d+)?)(gb|mb|mah|mm|in|w)\b", normalize(memory_text(value))):
        result.setdefault(unit, set()).add(float(amount))
    return result


def ram_quantities(value):
    """Conserva el rol de la memoria: 4 GB de RAM no equivalen a 4 GB de disco."""
    text = normalize(memory_text(re.sub(r"[,;•|]", " separador ", value)))
    matches = re.findall(r"\b(\d+(?:\.\d+)?gb)\s+(?:de )?ram\b|\bram\s+(\d+(?:\.\d+)?gb)\b"
                         r"(?!\s*(?:ssd|hdd|storage|rom|almacenamiento)\b)", text)
    return {float((left or right)[:-2]) for left, right in matches}


def own_description(value):
    """La compatibilidad nombra otros productos, no el modelo ni el paquete vendido."""
    return re.split(r"\b(?:for|para|compatible (?:with|con))\b", ascii_text(value), maxsplit=1)[0]


def pack_description(value):
    """Extrae unidades vendidas y retira sólo expresiones de cantidad inequívocas.

    No infiere una unidad del silencio ni confunde generaciones, RAM o conectores
    con cantidades. «Kit»/«bundle» sin cantidad conserva su duda de variante.
    """
    counts = set()
    pattern = (r"\b(?:pack|kit|paquete|set)\s*(?:of\s*|de\s*|x\s*)?(\d+)\b"
               r"(?:\s*(?:unidades|units))?"
               r"|\b(\d+)(?:\s*-\s*(?:pack|units?|unidades|cameras?|camaras?)"
               r"|\s+(?:pack|units?|unidades|cameras|camaras|camera(?=\s+system\b)))\b"
               r"(?:\s+system)?|\b(twin\s+pack|duo)\b")

    def take(match):
        counts.add(int(match[1] or match[2] or 2))
        return " "

    return counts, re.sub(pattern, take, ascii_text(value))


def product_types(value, category=""):
    """Tipos explícitos del producto propio, con sinónimos de ambos idiomas.

    Las frases compuestas se consumen primero: «cámara web» es webcam. Los
    earbuds pueden describirse también como auriculares sin cambiar de tipo.
    """
    text = normalize(own_description(value))
    text = re.sub(r"\b(?:(?:voice|touch|app) control|control (?:por voz|de voz|tactil))\b", " ", text)
    # En teléfonos/tablets «4 speakers» enumera componentes internos.
    if category_for(category) in {"Celulares", "Tablets y lectores"} or CORE_SPEC_RE.search(text):
        text = re.sub(r"\b\d+\s+(?:speakers?|parlantes?|altavoces)\b", " ", text)
    camera_kind = re.search(r"\b(webcams?|camaras? web|cameras?|camaras?)\b", text)
    groups = {
        "webcam": r"\b(?:webcams?|camaras? web)\b",
        "keyboard": r"\b(?:keyboards?|teclados?)\b",
        "mouse": r"\b(?:mouse|mice|raton|ratones)\b",
        "earbuds": r"\b(?:earbuds?|in ear)\b",
        "headphones": r"\b(?:headsets?|headphones?)\b",
        "audio": r"\bauriculares\b",
        "speaker": r"\b(?:speakers?|parlantes?|altavoces|altavoz)\b",
        "camera": r"\b(?:cameras?|camaras?)\b",
        "monitor": r"\b(?:monitors?|monitores)\b",
        "router": r"\b(?:routers?)\b",
        "tablet": r"\b(?:tablets?|tabletas?)\b",
        "phone": r"\b(?:phones?|smartphones?|celular|celulares)\b",
        "watch": r"\b(?:watch|watches|smartwatch|smartwatches|reloj|relojes)\b",
        "charger": r"\b(?:chargers?|cargador|cargadores)\b",
        "case": r"\b(?:cases?|fundas?)\b",
        "cable": r"\b(?:cables?)\b",
        "stand": r"\b(?:stands?|soportes?)\b",
        "controller": r"\b(?:controllers?|control(?:es)?|joysticks?|gamepads?)\b",
    }
    found = set()
    for kind, pattern in groups.items():
        if re.search(pattern, text):
            found.add(kind)
            text = re.sub(pattern, " ", text)
    if found & {"earbuds", "headphones"}:
        found.discard("audio")
    if {"camera", "webcam"} <= found:
        # Una cámara de acción puede ofrecer modo webcam y una webcam incluir
        # una cámara: el primer tipo declarado identifica el dispositivo vendido.
        found.discard("camera" if "web" in camera_kind[0] else "webcam")
    return found


def model_tokens(value):
    text = pack_description(value)[1]
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
        # «5th» y «5ta» son la misma generación, no códigos contradictorios.
        if (re.fullmatch(r"\d+(?:st|nd|rd|th|er|ra|ta|to|a|o)", token)
                and re.search(r"\b" + re.escape(raw) + r"\s+gen(?:eration|eracion)?\b", text)):
            continue
        # Plataformas y especificaciones compartidas no prueban identidad.
        if re.fullmatch(r"(?:ps[345]|4k|8k|\d+(?:mp|fps|ms|x|axis|eje)|f\d+|hdr\d+|\d+x\d+)", token):
            continue
        if quantities(raw) or re.fullmatch(r"(?:pcie|usb|ddr|wifi|wi-fi|bluetooth|bt|gen)\d+[a-z]*", token):
            continue
        if re.fullmatch(r"\d+(?:hz|khz|mhz|ghz|k|p|mbps|gbps)", token):
            continue
        # Duración, protección y canales de audio son especificaciones, no códigos.
        if re.fullmatch(r"(?:\d+(?:hour|hours|hr|hrs|ch)|ip\d{2})", token):
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


def variant_words(value, textual_model=""):
    value = pack_description(value)[1]
    value = CORE_SPEC_RE.sub(" ", value)
    owned = own_description(value)
    text = owned.split("|", 1)[0]
    text = re.sub(r"\bultra[ -](?:portable|slim|hd)\b|\bpro[ -]level\b", "", text)
    words = normalize(text).split()
    model_words = set(normalize(textual_model).split()) - VARIANTS
    anchors = [i for i, word in enumerate(words) if model_tokens(word) or word in model_words
               or (word.isdigit() and len(word) <= 4)]
    found = {word for i, word in enumerate(words) if word in VARIANTS and any(abs(i - j) <= 3 for j in anchors)}
    # Estado y cantidad del paquete importan aunque estén lejos del modelo.
    found.update(set(words) & {"hero", "lightspeed", "signature", "music", "paperwhite", "colorsoft", "scribe", "floodlight"})
    found.update(set(normalize(value).split()) & {"kit", "bundle", "combo", "pack"})
    found.update("propio " + word for word in set(normalize(owned).split()) & {"kit", "bundle", "combo", "pack"})
    found.update(set(normalize(value).split()) & {"refurbished", "renewed", "reacondicionado", "usado"})
    found.update(re.findall(r"\b\d+ pack\b", normalize(value)))
    if re.search(r"\b(?:lens|lente)\b", normalize(value)):
        found.discard("fe")
    for negated in re.findall(r"\b(?:non|no|sin)[ -]+(pro|plus|ultra|mini|kit)\b", owned):
        found.discard(negated)
        found.add("non " + negated)
    return found


def textual_model_matches(model, title, name):
    """Un modelo textual completo puede cambiar el orden de sus palabras en la ficha."""
    words = normalize(model).split()
    generic = set("otros other generic generico wireless controller headphones headset tablet camera digital gaming ultra hd boombox".split())
    if not words or all(word in generic for word in words):
        return False
    a, b = normalize(own_description(title)), normalize(own_description(name))
    if len(words) > 1:
        def contains(source):
            tokens = source.split()
            return any(sorted(tokens[i:i + len(words)]) == sorted(words)
                       for i in range(len(tokens) - len(words) + 1))
        return contains(a) and contains(b)
    # Nombres cortos requieren un calificador explícito igual: «Brio 4K», nunca «Brio 500».
    if len(words[0]) == 4 and words[0].isalpha():
        pattern = r"\b" + re.escape(words[0]) + r"\s+(\d+[a-z]*)\b"
        left, right = re.search(pattern, a), re.search(pattern, b)
        return bool(left and right and left[1] == right[1])
    pattern = r"\b" + re.escape(words[0]) + r"\b"
    return len(words[0]) >= 5 and bool(re.search(pattern, a) and re.search(pattern, b))


def identity_qualifiers(value, textual_model):
    """Calificadores del producto propio, sin completar silencios con atributos ML.

    Los números de generación conservan su rol; pulgadas, memoria y potencia no
    son versiones. Los signos + sólo califican un modelo, nunca sumas de RAM o
    nombres ajenos (por ejemplo, una plataforma mencionada en la descripción).
    """
    text = own_description(memory_text(pack_description(value)[1]))
    text = CORE_SPEC_RE.sub(" ", text)
    # «International Version» describe la región, no una generación numérica.
    text = re.sub(r"\binternational version\b", " ", text)
    text = UNIT_RE.sub(" ", text)
    text = re.sub(r"\bultra[ -](?:portable|slim|hd)\b|\bpro[ -]level\b", "", text)
    text = re.sub(r"\b(?:with (?:a )?clock|con reloj)\b", " clock ", text)
    text = re.sub(r"\b(?:ninos|infantil)\b", " kids ", text)
    text = re.sub(r"\b(?:full hd|fullhd)\b", " fhd ", text)
    text = re.sub(r"\b(?:plus|mas)\b", " plus ", text)
    editions = VARIANTS | set("kids xl edge oled active play 4k 8k hd fhd power neo clock".split())
    model_words = set(normalize(textual_model).split())
    # A9+ y A9 Plus son lo mismo; 4+64GB ya fue retirado como memoria.
    text = re.sub(r"\b([a-z0-9]+)\s*\+(?!\s*\d)",
                  lambda m: m[1] + (" plus " if m[1] in model_words or model_tokens(m[1]) else " "), text)
    words = normalize(text).split()
    anchors = [i for i, word in enumerate(words)
               if model_tokens(word) or word in model_words - editions]
    # Un modelo completamente textual puede incluir un calificador (Fire HD).
    anchors += [i for i, word in enumerate(words) if word in model_words & editions]
    result = {"edición": {w for i, w in enumerate(words) if w in editions
                         and any(abs(i - j) <= 3 for j in anchors)}}
    # La resolución puede estar explícita aun cuando sólo el MPN identifica el
    # modelo (p. ej. una webcam); nunca usarla por sí sola para probar identidad.
    result["edición"].update(set(words) & {"4k", "8k", "hd", "fhd"})
    if re.search(r"\b(?:lens|lente)\b", text):
        result["edición"].discard("fe")
    roman = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6",
             "vii": "7", "viii": "8", "ix": "9", "x": "10"}
    # «5th Gen», «5.ª generación», «gen 5» y «Series 5» comparten representación.
    number = r"(\d+|viii|vii|iii|vi|iv|ii|ix|v|i|x)"
    marker = r"(?:gen(?:eracion|eration)?|serie[s]?|version)"
    generations = set()
    for pattern in (rf"\b{number}\s*(?:st|nd|rd|th|er|ra|ta|to|a|o|[.°ªº])*\s*{marker}\b",
                    rf"\b{marker}\s*{number}\b"):
        generations.update(roman.get(n, str(int(n)) if n.isdigit() else n) for n in re.findall(pattern, text))
    # Números/romanos inmediatamente después de una palabra del modelo: Cloud II,
    # Buds 6, Fire HD 8. No confundir WiFi 6, USB 3 o tiempo de batería con modelo.
    for i in anchors:
        if not words[i].isalpha() or words[i] not in model_words:
            continue
        if i + 1 < len(words):
            following = words[i + 1]
            if following.isdigit() or following in roman:
                generations.add(roman.get(following, following))
    result["generación"] = generations
    result["año"] = set(re.findall(r"\b(20\d{2})\s*(?:model|modelo|release)\b", text))
    return result


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


def _ids(texto, solo_digitos=False):
    """Identificadores normalizados (sin guiones ni espacios); GTIN/UPC sin ceros a la izquierda."""
    out = set()
    for parte in re.split(r"[,;/\s]+", str(texto or "")):
        tok = re.sub(r"[^0-9a-z]", "", parte.lower())
        if solo_digitos:
            tok = tok.lstrip("0") if tok.isdigit() else ""
        if len(tok) >= 5 and re.search(r"\d", tok):
            out.add(tok)
    return out


def identificador_comun(amazon, attrs):
    """05/11: el número de modelo, UPC o GTIN de la página de Amazon coincide con el MPN, el modelo alfanumérico o
    el GTIN de la ficha de ML: es el mismo producto aunque el título no lo diga."""
    ids = amazon.get("amazonIds") if isinstance(amazon.get("amazonIds"), dict) else {}
    a_mod = _ids(ids.get("model_number")) | _ids(ids.get("model_name"))
    a_gtin = _ids(ids.get("upc"), True) | _ids(ids.get("gtin"), True)
    b_mod = _ids(attrs.get("MPN")) | _ids(attrs.get("ALPHANUMERIC_MODEL")) | _ids(attrs.get("PART_NUMBER"))
    b_gtin = _ids(attrs.get("GTIN"), True) | _ids(attrs.get("UPC"), True) | _ids(attrs.get("EAN"), True)
    return sorted((a_mod & b_mod) | (a_gtin & b_gtin))


def evaluate(amazon, candidate, product, mep):
    """Devuelve estado, motivo y evidencia; una contradicción gana sobre una duda."""
    title = amazon.get("amazonTitle") or ""
    name = product.get("name") or candidate.get("name") or ""
    attrs = attributes(product)
    # 05/11: el color NO es otro producto (Galaxy Tab A11 Silver vs Gris, Echo Spot): sólo diferencias funcionales.
    conflicts = [c for c in variant_conflicts(title, name) if c != "color"]
    if conflicts:
        return "rejected", "variante", {"brand": "", "model": [], "capacity": [], "conflicts": conflicts}
    # 05/11: sin marca informada por Amazon NO se usa la primera palabra del título («Echo Spot» -> marca «Echo»).
    # Se usa la de ML si aparece en el título; si no, queda desconocida y la decide el modelo más abajo.
    brand_ml = attrs.get("BRAND") or ""
    brand = amazon.get("brand") or (brand_ml if brand_ml and normalize(brand_ml) in normalize(title) else "")
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
    shared = a_models & b_models & model_tokens(own_description(title)) & model_tokens(own_description(name + " " + model))
    # Un modelo textual completo sirve si es específico y no contradice códigos.
    textual = normalize(attrs.get("MODEL", ""))
    if (not shared and textual_model_matches(textual, title, name)
            and textual not in {normalize(brand), normalize(brand_ml)}
            and not re.fullmatch(r"(?:axe?|be)\d{3,}", textual)
            and not (a_models and b_models and not shared)):
        shared.add(textual)

    if not brand and brand_ml and shared:
        brand = brand_ml  # marca desconocida en Amazon, pero el modelo coincide: se toma la de ML
    evidence = {"brand": brand_key(brand) if brand_key(brand) == brand_key(attrs.get("BRAND")) else "",
                "model": sorted(shared), "capacity": sorted(f"{n:g}{u}" for u in a_caps.keys() & b_caps.keys() for n in a_caps[u] & b_caps[u])}
    doubts = []
    category = amazon.get("amazonCategory", "")
    a_types, b_types = product_types(title, category), product_types(name, category)
    # «Auriculares» solo no distingue in-ear de vincha; no inventar esa diferencia.
    if a_types == {"audio"} and b_types in ({"earbuds"}, {"headphones"}):
        a_types = b_types
    if b_types == {"audio"} and a_types in ({"earbuds"}, {"headphones"}):
        b_types = a_types
    if a_types and b_types and a_types != b_types:
        return "rejected", "tipo de producto distinto", evidence
    a_pack = pack_description(title)[0]
    b_pack = pack_description(" ".join([name, model, attrs.get("LINE", "")]))[0]
    if a_pack != b_pack:
        if a_pack and b_pack:
            return "rejected", "cantidad del paquete distinta", evidence
        doubts.append("variante de cantidad del paquete sin confirmar")
    if len(a_pack) > 1 or len(b_pack) > 1:
        doubts.append("cantidad del paquete ambigua")
    if re.search(r"\b(?:libro|book|manual|user guide|cookbook|editorial)\b", normalize(name)):
        return "rejected", "libro o manual en lugar del producto", evidence
    if accessory(title) or accessory(name):
        return "rejected", "accesorio", evidence
    # 05/11: combo en un lado y producto solo en el otro (Instax Mini 12 «+ 60 Photo Prints + Accessories» vs la cámara).
    # Sobre el texto en minúsculas SIN normalizar: normalize() borra los «+».
    combo = re.compile(r"\bkit\b.*\b(?:film|prints)\b|\+\s*\d+\s*(?:photo|prints|film|sheets)|\bphoto prints\b|\+\s*accessor|\bstudio\b")
    if bool(combo.search(ascii_text(title).lower())) != bool(combo.search(ascii_text(name).lower())):
        return "rejected", "combo en un solo lado", evidence
    # Compartir el modelo base no vuelve intercambiables las versiones de red celular.
    a_network = set(re.findall(r"\b[345]g\b", normalize(own_description(title))))
    b_network = set(re.findall(r"\b[345]g\b", normalize(own_description(name))))
    if a_network and b_network and a_network != b_network:
        return "rejected", "generación de red distinta", evidence
    if a_network != b_network:
        doubts.append("red celular sin confirmar")
    comun = identificador_comun(amazon, attrs)
    if comun:
        # Un identificador aporta identidad, pero no tapa variantes ni códigos contradictorios.
        evidence["identificador"] = comun
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
    amazon_platforms = platforms(title)
    ml_platforms = platforms(name) | listed_platforms
    if amazon_platforms and ml_platforms and amazon_platforms.isdisjoint(ml_platforms):
        return "rejected", "plataforma distinta entre Amazon y ML", evidence
    if amazon_platforms != ml_platforms and (amazon_platforms or ml_platforms):
        doubts.append("plataforma sin confirmar entre Amazon y ML")
    if listed_platforms and platforms(name) and listed_platforms.isdisjoint(platforms(name)):
        doubts.append("plataforma contradictoria entre nombre y atributos")
    if not evidence["brand"]:
        doubts.append("marca ausente")
    a_ram, b_ram = ram_quantities(title), ram_quantities(name)
    for key in ("RAM", "RAM_MEMORY"):
        b_ram.update(quantities(attrs.get(key, "")).get("gb", set()))
    if a_ram and b_ram and a_ram != b_ram:
        return "rejected", "memoria RAM distinta", evidence
    if (a_ram != b_ram
            and category_for(amazon.get("amazonCategory")) in {"Celulares", "Tablets y lectores"}):
        doubts.append("memoria RAM sin confirmar")
    for unit in a_caps.keys() & b_caps.keys():
        # Si los dos lados informan varios valores (RAM + almacenamiento), tienen que coincidir todos:
        # IdeaPad 1 «8GB RAM, 128GB» vs «4GB 128gB» comparte 128 y es otra configuración.
        if a_caps[unit].isdisjoint(b_caps[unit]) or (len(a_caps[unit]) > 1 and len(b_caps[unit]) > 1
                                                     and a_caps[unit] != b_caps[unit]):
            return "rejected", "capacidad o tamaño distinto", evidence
    if a_caps.keys() != b_caps.keys():
        doubts.append("capacidad o tamaño sin confirmar")
    if re.search(r"\b(?:edition|edicion|anniversary)\b", normalize(title + " " + name)):
        # Ediciones especiales requieren revisión aunque compartan el modelo base.
        doubts.append("edición sin confirmar")
    if family_conflict(a_models, b_models):
        return "rejected", "modelo de otra familia o edición", evidence
    a_qualifiers = identity_qualifiers(title, textual)
    b_qualifiers = identity_qualifiers(name, textual)
    for key in a_qualifiers:
        left, right = a_qualifiers[key], b_qualifiers[key]
        if left != right:
            # Una omisión no prueba una contradicción; dos versiones explícitas sí.
            if left - right and right - left:
                return "rejected", "variante distinta", evidence
            reason = "variante sin confirmar" if key == "edición" else "generación sin confirmar"
            if reason not in doubts:
                doubts.append(reason)
    # «+» y «Plus» ya se compararon con la misma representación arriba.
    variants_differ = (variant_words(title, textual) - {"plus"}
                       != variant_words(name + " " + model + " " + attrs.get("LINE", ""), textual) - {"plus"})
    if a_models and b_models and a_models.isdisjoint(b_models):
        return "rejected", "modelo distinto", evidence
    if a_models & b_models and not shared and not comun:
        doubts.append("modelo propio sin confirmar")
    if not shared and not comun and (not a_models or not b_models):
        doubts.append("modelo ausente")
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
    # 05/11: con marca Y modelo confirmados, la duda sólo de color no frena el alta (el color no cambia el
    # producto). La categoría SÍ frena: apply_candidates exige una categoría válida del catálogo.
    leves = {"color sin confirmar"}
    # La capacidad sin confirmar en un solo lado sólo importa donde la capacidad ES la variante (05/11: Plaud Note Pro
    # 64 GB, MWE Gold 850 W, EVIVA 12" quedaban dudosos siendo el mismo producto).
    if category_for(amazon.get("amazonCategory")) not in {"Almacenamiento", "Celulares", "Tablets y lectores",
                                                          "Monitores", "Componentes", "Mini PCs"}:
        leves = leves | {"capacidad o tamaño sin confirmar"}
    if doubts and evidence["brand"] and (evidence["model"] or comun) and set(doubts) <= leves:
        evidence["dudasLeves"] = doubts
        return "accepted", "", evidence
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


def match_products(products, mep, catalog=(), products_cache=None, on_result=None, journal=None, used_slugs=None):
    if not positive_number(mep):
        raise ValueError("MEP inválido; indicá --mep con un valor positivo.")
    if not isinstance(products, list):
        raise ValueError("La entrada debe ser una lista JSON.")
    result = {"generatedAt": datetime.now(timezone.utc).isoformat(), "mep": mep,
              "accepted": [], "doubtful": [], "rejected": []}
    used = used_slugs if used_slugs is not None else {entry["slug"] for entry in catalog if isinstance(entry, dict) and isinstance(entry.get("slug"), str)}
    if products_cache is not None and (not isinstance(products_cache, dict)
            or any(not isinstance(value, dict) for value in products_cache.values())):
        raise ValueError("El caché debe ser un diccionario de productos ML.")
    from buscar_log import line, check_stop
    cache = journal.data["ficha_ml"] if journal else {}
    cache.update(products_cache or {})
    errors = {}  # Reusar el fallo sólo en este lote; nunca en el diario/caché durable.

    def emit(status, row, definitive=True):
        line("MATCH", asin=row.get("asin"), catalogId=row.get("catalogId"), estado=status,
             motivo=row.get("reason") or "validado", mlPrecio=row.get("mlPrice"), amazonUsd=row.get("amazonPriceUsd"))
        if not definitive:
            line("MATCH", asin=row.get("asin"), estado="error", motivo=",".join(transient))
            if journal:
                journal.append("match_error", row.get("asin"), "error", ",".join(transient), row=row)
            return
        if on_result and on_result(status, row) is False:
            return
        if journal:
            journal.append("match", row.get("asin") or str(row.get("index")), status,
                           row.get("reason", ""), row=row)

    for index, amazon in enumerate(products, 1):
        check_stop()
        if not isinstance(amazon, dict):
            result["rejected"].append({"reason": "producto inválido", "index": index})
            emit("rejected", result["rejected"][-1])
            continue
        chosen = None
        transient = [amazon["_discoveryError"]] if amazon.get("_discoveryError") else []
        failures = []
        candidates = amazon.get("ml")
        for candidate in candidates if isinstance(candidates, list) else []:
            check_stop()
            if not isinstance(candidate, dict):
                line("MATCH_CANDIDATO", asin=amazon.get("asin"), estado="salteado", motivo="candidato_invalido")
                continue
            catalog_id = candidate.get("catalogId")
            if not isinstance(catalog_id, str) or not re.fullmatch(r"[A-Za-z0-9]+", catalog_id):
                failures.append({"catalogId": catalog_id, "reason": "catalogId inválido"})
                line("MATCH_CANDIDATO", asin=amazon.get("asin"), estado="salteado", motivo="catalogId_invalido")
                continue
            if catalog_id not in cache and catalog_id not in errors:
                try:
                    payload = ml_prices.get_json(f"/products/{catalog_id}")
                    if not isinstance(payload, dict):
                        raise ValueError("Ficha ML vacía o inválida")
                    cache[catalog_id] = payload
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    errors[catalog_id] = str(exc) or type(exc).__name__
                    line("MATCH_FICHA", catalogId=catalog_id, estado="error", motivo=str(exc))
                    if journal:
                        journal.append("ficha_ml", catalog_id, "sin_ficha", str(exc), product={})
                finally:
                    ml_prices.pause()
                if journal and catalog_id in cache:
                    journal.append("ficha_ml", catalog_id, "ok", product=cache[catalog_id])
            if catalog_id in errors:
                transient.append(errors[catalog_id])
            product = cache.get(catalog_id, {})
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
                       category=category_for(amazon.get("amazonCategory")) or "", summary=candidate_summary(name, brand, attributes(product)),
                       evidence=evidence, mlName=product.get("name") or candidate.get("name") or "",
                       mlBrand=attributes(product).get("BRAND", ""), mlModel=attributes(product).get("MODEL", ""),
                       amazonPriceUsd=amazon.get("amazonPriceUsd"))
            row["slug"] = unique_slug(brand, evidence, name, used)
            # Conservar la evidencia cruda para el filtro posterior, sin cambiar la decisión.
            row["amazonIds"] = dict(amazon.get("amazonIds") or {})
            row["mlIds"] = {key: value for key, value in attributes(product).items() if key in ML_FIELDS}
            if reason:
                row["reason"] = reason
            result[status].append(row)
            emit(status, row, definitive=not transient or (status == "accepted" and candidate["catalogId"] not in errors))
        else:
            best = max(failures, key=lambda failure: failure.get("score", -1), default={})
            result["rejected"].append({**{key: best.get(key, "") for key in
                                        ("catalogId", "mlName", "mlBrand", "mlModel", "mlPrice", "evidence")},
                                       "category": category_for(amazon.get("amazonCategory")) or "",
                                       "asin": amazon.get("asin"), "amazonTitle": amazon.get("amazonTitle"),
                                       "reason": best.get("reason", "sin candidatos"),
                                       "candidates": failures})
            emit("rejected", result["rejected"][-1], definitive=not transient)
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
