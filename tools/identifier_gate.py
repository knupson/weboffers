"""Filtro de identificadores fuertes posterior a la aceptación del validador."""
import re


ML_FIELDS = ("GTIN", "UPC", "EAN", "MPN", "PART_NUMBER", "ALPHANUMERIC_MODEL", "MODEL")


def values(raw):
    """Las comas y punto y coma separan alternativas; la barra pertenece al modelo."""
    if isinstance(raw, (list, tuple)):
        return [value for item in raw for value in values(item)]
    return re.split(r"[,;]+", str(raw or ""))


def normalized(ids, fields, barcode=False):
    result = set()
    for field in fields:
        for value in values(ids.get(field)):
            if barcode:
                token = re.sub(r"[^0-9]", "", value).lstrip("0")
                if token:
                    result.add(token)
            else:
                token = re.sub(r"[\s/\-]", "", value.upper())
                if (len(token) >= 5 and re.fullmatch(r"[A-Z0-9]+", token)
                        and re.search(r"[A-Z]", token) and re.search(r"[0-9]", token)):
                    result.add(token)
    return result


LEGO_SET = re.compile(r"(?<!\d)\d{4,6}(?!\d)")


def lego_set_numbers(raw):
    """Números de set (4-6 dígitos) de un campo de modelo; la barra no separa («7/53/54» = 75354)."""
    # Un año (1900-2099) no es un número de set aunque esté en un campo de modelo («Star Wars 2025»).
    return {match for value in values(raw) for match in LEGO_SET.findall(str(value).replace("/", ""))
            if not (len(match) == 4 and 1900 <= int(match) <= 2099)}


def lego_set_match(row):
    """11/11: en LEGO, Amazon trae el set en model_name y un código interno de 7 dígitos en model_number
    (43019 vs 6590610), así que nunca coincidía con el MODEL de ML. Sólo con marca LEGO de los dos lados,
    sólo campos estructurados (nunca el título) y un único número de set en Amazon."""
    if (str(row.get("brand") or "").strip().lower() != "lego"
            or str(row.get("mlBrand") or "").strip().lower() != "lego"):
        return False
    amazon_ids, ml_ids = row.get("amazonIds") or {}, row.get("mlIds") or {}
    # Evidencia contraria: si los dos lados traen código de barras y no coincide ninguno, no es el mismo artículo.
    amazon_barcodes = normalized(amazon_ids, ("gtin", "upc", "ean"), True)
    ml_barcodes = normalized(ml_ids, ("GTIN", "UPC", "EAN"), True)
    if amazon_barcodes and ml_barcodes and not amazon_barcodes & ml_barcodes:
        return False
    amazon = lego_set_numbers(amazon_ids.get("model_name"))
    ml = lego_set_numbers(ml_ids.get("MODEL"))
    if len(amazon) != 1 or amazon != ml:
        return False
    # Revisor 11/11: si el título de Amazon o el nombre de ML nombran OTRO set, el atributo puede estar mal
    # cargado. La cantidad de piezas («2164 Piezas», «1476 pcs») no es un número de set.
    textos = " ".join(str(row.get(key) or "") for key in ("amazonTitle", "mlName", "name"))
    textos = PIECES.sub(" ", textos)
    return lego_set_numbers(textos) <= amazon


PIECES = re.compile(r"\b\d{3,5}\s*(?:piezas|pieces|piece|pcs|pzs|pz|pc)\b", re.I)


def strong_identifier_match(row):
    """No infiere códigos del título ni recorta sufijos regionales."""
    amazon = row.get("amazonIds") or {}
    ml = row.get("mlIds") or {}
    return bool(
        normalized(amazon, ("gtin", "upc", "ean"), True)
        & normalized(ml, ("GTIN", "UPC", "EAN"), True)
        or normalized(amazon, ("model_number", "mpn", "part_number"))
        & normalized(ml, ("MPN", "PART_NUMBER", "ALPHANUMERIC_MODEL", "MODEL"))
        or lego_set_match(row)
    )
