"""Contradicciones explícitas de variante entre títulos, sin consultas de red."""
import re
import unicodedata


def _text(value):
    return "".join(c for c in unicodedata.normalize("NFKD", value.lower()) if not unicodedata.combining(c))


def _attributes(title):
    text = _text(title)
    out = {}
    for key, pattern, factor in (
        ("capacidad", r"\b(\d+(?:[.,]\d+)?)\s*(gb|tb)\b", {"gb": 1, "tb": 1000}),
        ("pulgadas", r'(\d+(?:[.,]\d+)?)\s*-?\s*(inches|inch|pulgadas|pulg|["″])', None),
        ("mm", r"\b(\d+(?:[.,]\d+)?)\s*(mm)\b", None),
    ):
        values = {round(float(n.replace(",", ".")) * (factor[u] if factor else 1), 4) for n, u in re.findall(pattern, text)}
        if values:
            out[key] = values
    groups = {
        "switch": {"clicky": r"\b(clicky|blue|azul)\b", "tactile": r"\b(tactile|tactil|brown|marron)\b", "linear": r"\b(linear|lineal|red|rojo)\b"},
        "conexion": {"wireless": r"\b(wireless|inalambric[oa]s?|sin cable|bluetooth)\b", "wired": r"\b(wired|cablead[oa]|con cable)\b"},
        "layout": {"tkl": r"\b(tkl|tenkeyless)\b|\b80\s*%", "full": r"\b(full(?:[ -]?size)?|completo)\b|\b100\s*%|\b(104|108) keys\b", "60": r"\b60\s*%"},
        "color": {"negro": r"\b(negro|negra|black)\b", "blanco": r"\b(blanco|blanca|white)\b", "gris": r"\b(gris|gray|grey)\b", "plata": r"\b(plata|plateado|silver)\b", "rosa": r"\b(rosa|pink)\b", "verde": r"\b(verde|green)\b", "azul": r"\b(azul|blue)\b", "rojo": r"\b(rojo|red)\b"},
    }
    # Los colores de switches sólo se interpretan como tales en un teclado.
    keyboard = re.search(r"\b(keyboard|teclado|switch(?:es)?|cherry|gateron|kailh|mx|clicky|tactile|tactil|linear|lineal)\b", text)
    if not keyboard:
        groups.pop("switch")
    else:
        text_colors = re.sub(r"\b(?:red|blue|brown|rojo|azul|marron)\s+switch(?:es)?\b|\bswitch(?:es)?\s+(?:red|blue|brown|rojo|azul|marron)\b", "", text)
    for key, choices in groups.items():
        source = text_colors if key == "color" and keyboard else text
        values = {value for value, pattern in choices.items() if re.search(pattern, source)}
        if values:
            out[key] = values
    return out


def variant_conflicts(title_a: str, title_b: str) -> list[str]:
    """Lista atributos explícitos incompatibles; un atributo ausente no es contradicción."""
    a, b = _attributes(title_a), _attributes(title_b)
    return sorted(key for key in a.keys() & b.keys() if a[key].isdisjoint(b[key]) or (key in {"capacidad", "pulgadas", "mm"} and a[key] != b[key]))
