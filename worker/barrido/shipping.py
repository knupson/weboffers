"""Adaptador conservador entre tarjetas y clasificación compartida."""
import re
# Frases (ya en minúsculas) con las que Amazon niega el envío de forma explícita y confiable.
NO_SHIP_PATTERNS = (
    "cannot be shipped",
    "can't be shipped",
    "does not ship",
    "not available for shipping",
    "no se puede enviar",
    "no se envía",
    "no se envia",
)


PAID_DELIVERY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s+delivery", re.IGNORECASE)
ES_PAID_RE = re.compile(r"(?:env[ií]o(?: de| por)?\s*[€$]?\s*\d+[,.]\d{2}\s*€?|\d+[,.]\d{2}\s*€\s*(?:de env[ií]o|de entrega))", re.I)
FREE_RE = re.compile(r"^(?:FREE DELIVERY|ENV[IÍ]O GRATIS|ENTREGA GRATIS)", re.I)
ELIGIBLE_OVER_RE = re.compile(r"orders? over \$\s?(\d[\d,]*(?:\.\d+)?)", re.IGNORECASE)


def _texto_de(valor):
    """Texto de un campo que puede venir como str o como dict con clave "text"."""
    if isinstance(valor, str):
        return valor
    if isinstance(valor, dict):
        texto = valor.get("text")
        if isinstance(texto, str):
            return texto
    return ""


def parse_delivery(details, located=False):
    """Lógica pura (sin red): interpreta el `details` de `amazon.products.details(asin, store)`.

    Devuelve {"ships", "free", "text", "price", "condition"}:
    - ships: True sólo si el texto de delivery menciona "Argentina" y el precio tiene un amount
      numérico. False sólo si (a) la sesión quedó confirmada en Argentina (`located`), delivery.location
      contiene "Argentina", no hay texto ni opciones de delivery y el amount es None, o (b) algún texto
      de availability/delivery dice explícitamente que no se envía (eso prima sobre la mención de
      "Argentina" en el texto). Cualquier otro caso (falta el bloque
      delivery, location que no es Argentina, datos incompletos, sesión sin confirmar) es DESCONOCIDO:
      ships = None y free = None; False nunca es un "no sé" porque ocultaría un producto;
    - free: True si alguna opción tiene price_text "FREE" (sin distinguir mayúsculas) o el texto
      empieza con "FREE delivery"; False si envía pero no es gratis; None si no envía o es desconocido;
    - condition: el campo condition de details, si está.
    """
    details = details if isinstance(details, dict) else {}
    delivery = details.get("delivery")
    delivery = delivery if isinstance(delivery, dict) else None
    text = ""
    options = []
    location = ""
    if delivery is not None:
        raw_text = delivery.get("text")
        text = raw_text if isinstance(raw_text, str) else ""
        raw_options = delivery.get("options")
        options = raw_options if isinstance(raw_options, list) else []
        raw_location = delivery.get("location")
        location = raw_location if isinstance(raw_location, str) else ""
    price = details.get("price")
    amount = price.get("amount") if isinstance(price, dict) else None
    amount_ok = isinstance(amount, (int, float)) and not isinstance(amount, bool)

    ships = None
    textos = " ".join([text, _texto_de(details.get("availability"))]).lower()
    if located and any(patron in textos for patron in NO_SHIP_PATTERNS):
        # Negativo explícito de Amazon ("does not ship to Argentina" etc.): no se envía,
        # aunque el texto mencione Argentina.
        ships = False
    elif "Argentina" in text and amount_ok:
        ships = True
    elif located and amount_ok and bool(FREE_RE.search(text)):
        ships = True
    elif located and "argentina" in location.lower() and amount_ok and (PAID_DELIVERY_RE.search(text) or ES_PAID_RE.search(text)):
        # 03/11: «$71.77 delivery Monday…» con la sesión en Argentina = envía, pero cobra el envío.
        # Antes quedaba desconocido para siempre y el producto se volvía a relevar todos los días.
        ships = True
    # Sin oferta ni texto explícito (31/10: joystick Xbox, HyperX Cloud III) es ambiguo: queda desconocido.

    free = None
    if ships is True:
        free = bool(FREE_RE.search(text))
        for option in options:
            if not isinstance(option, dict):
                continue
            price_text = option.get("price_text")
            if isinstance(price_text, str) and price_text.strip().upper() in ("FREE", "GRATIS", "ENVÍO GRATIS"):
                free = True
        # 03/11: «FREE delivery … on eligible orders over $99» no es gratis si el producto vale menos que el mínimo.
        minimo = ELIGIBLE_OVER_RE.search(text) or re.search(r"pedidos? (?:superiores a|de más de)\s*(\d+(?:[,.]\d+)?)\s*€", text, re.I)
        if free and minimo and amount_ok and amount < float(minimo.group(1).replace(",", ".") if "€" in text else minimo.group(1).replace(",", "")):
            free = False
    condition = details.get("condition")
    return {
        "ships": ships,
        "free": free,
        "text": text or None,
        "price": amount if amount_ok else None,
        "condition": condition if isinstance(condition, str) else None,
    }





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
    elif isinstance(delivery, dict) and located and not delivery.get('location'):
        delivery = {**delivery, 'location': 'Argentina'}
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
