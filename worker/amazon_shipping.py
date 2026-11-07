"""Ubicación AR y clasificación compartidas; sin consultas al importar."""
import re
HTTP_TIMEOUT = 45

# Frases (ya en minúsculas) con las que Amazon niega el envío de forma explícita y confiable.
NO_SHIP_PATTERNS = (
    "cannot be shipped",
    "can't be shipped",
    "does not ship",
    "not available for shipping",
    "no se puede enviar",
)


PAID_DELIVERY_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s+delivery", re.IGNORECASE)
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
    elif located and amount_ok and text.upper().startswith("FREE DELIVERY"):
        ships = True
    elif located and "argentina" in location.lower() and amount_ok and PAID_DELIVERY_RE.search(text):
        # 03/11: «$71.77 delivery Monday…» con la sesión en Argentina = envía, pero cobra el envío.
        # Antes quedaba desconocido para siempre y el producto se volvía a relevar todos los días.
        ships = True
    # Sin oferta ni texto explícito (31/10: joystick Xbox, HyperX Cloud III) es ambiguo: queda desconocido.

    free = None
    if ships is True:
        free = text.upper().startswith("FREE DELIVERY")
        for option in options:
            if not isinstance(option, dict):
                continue
            price_text = option.get("price_text")
            if isinstance(price_text, str) and price_text.strip().upper() == "FREE":
                free = True
        # 03/11: «FREE delivery … on eligible orders over $99» no es gratis si el producto vale menos que el mínimo.
        minimo = ELIGIBLE_OVER_RE.search(text)
        if free and minimo and amount_ok and amount < float(minimo.group(1).replace(",", "")):
            free = False
    condition = details.get("condition")
    return {
        "ships": ships,
        "free": free,
        "text": text or None,
        "price": amount if amount_ok else None,
        "condition": condition if isinstance(condition, str) else None,
    }


def apply_ar_location():
    """Reemplaza set_location del paquete amazon para consultar como comprador en Argentina."""
    from amazon import fetch

    fetch.TIMEOUT = HTTP_TIMEOUT  # Las sesiones del transporte heredan este timeout.

    def set_ar(sess, postal_code=None):
        if getattr(sess, "located", None) == "AR" or not sess.glow_token:
            return False
        base = sess.site["base"]
        headers = {**sess.headers(fetch.AJAX_HEADERS), "anti-csrftoken-a2z": sess.glow_token, "referer": base + "/"}
        resp = sess.curl.get(base + "/portal-migration/hz/glow/get-rendered-address-selections",
                             params={"deviceType": "desktop", "pageType": "Detail", "storeContext": "generic",
                                     "actionSource": "desktop-modal"}, headers=headers, timeout=HTTP_TIMEOUT)
        m = fetch._MODAL_TOKEN_RE.search(resp.text or "")
        token = m.group(1) if m else sess.glow_token
        resp = sess.curl.post(base + "/portal-migration/hz/glow/address-change", params={"actionSource": "glow"},
                              json={"locationType": "COUNTRY", "district": "AR", "countryCode": "AR", "deviceType": "web",
                                    "storeContext": "generic", "pageType": "Detail", "actionSource": "glow"},
                              headers={**headers, "anti-csrftoken-a2z": token, "content-type": "application/json"}, timeout=HTTP_TIMEOUT)
        # La ubicación en AR sólo queda confirmada si Amazon respondió 200 con éxito
        # (isAddressUpdated o successful) y, si informa la dirección, su país es AR;
        # cualquier otra respuesta deja la sesión como estaba (ubicación desconocida).
        confirmado = False
        if resp.status_code == 200:
            try:
                body = resp.json()
            except ValueError:
                body = None
            if isinstance(body, dict) and (body.get("isAddressUpdated") or body.get("successful")):
                address = body.get("address")
                if not isinstance(address, dict) or address.get("countryCode") == "AR":
                    confirmado = True
        if confirmado:
            sess.located = "AR"
        return confirmado

    fetch.set_location = set_ar

