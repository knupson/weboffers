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


def strong_identifier_match(row):
    """No infiere códigos del título ni recorta sufijos regionales."""
    amazon = row.get("amazonIds") or {}
    ml = row.get("mlIds") or {}
    return bool(
        normalized(amazon, ("gtin", "upc", "ean"), True)
        & normalized(ml, ("GTIN", "UPC", "EAN"), True)
        or normalized(amazon, ("model_number", "mpn", "part_number"))
        & normalized(ml, ("MPN", "PART_NUMBER", "ALPHANUMERIC_MODEL", "MODEL"))
    )
