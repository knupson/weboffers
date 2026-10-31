"""Servidor HTTP mínimo (sólo stdlib) que informa si Amazon envía cada ASIN a Argentina y si el envío es gratis.

Al arrancar reemplaza `amazon.fetch.set_location` para que el scraper consulte "desde Argentina"
(referencia probada en la Pi4, ver ar_probe_REFERENCIA.py en la raíz del repo). Escucha en el puerto 8001.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8001
MAX_ASINS = 5


def parse_delivery(details):
    """Lógica pura (sin red): interpreta el `details` de `amazon.products.details(asin, "US")` con location AR.

    Devuelve {"ships", "free", "text", "price", "condition"}:
    - ships: el texto de delivery menciona "Argentina" Y el precio tiene un amount numérico;
    - free: alguna opción con price_text "FREE" (sin distinguir mayúsculas) o el texto empieza con "FREE delivery";
      es None cuando el producto no se envía;
    - condition: el campo condition de details, si está.
    """
    details = details if isinstance(details, dict) else {}
    delivery = details.get("delivery")
    delivery = delivery if isinstance(delivery, dict) else {}
    text = delivery.get("text")
    text = text if isinstance(text, str) else ""
    options = delivery.get("options")
    options = options if isinstance(options, list) else []
    price = details.get("price")
    amount = price.get("amount") if isinstance(price, dict) else None
    amount_ok = isinstance(amount, (int, float)) and not isinstance(amount, bool)
    ships = "Argentina" in text and amount_ok
    free = None
    if ships:
        free = text.upper().startswith("FREE DELIVERY")
        for option in options:
            if not isinstance(option, dict):
                continue
            price_text = option.get("price_text")
            if isinstance(price_text, str) and price_text.strip().upper() == "FREE":
                free = True
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

    def set_ar(sess, postal_code=None):
        if getattr(sess, "located", None) == "AR" or not sess.glow_token:
            return False
        base = sess.site["base"]
        headers = {**sess.headers(fetch.AJAX_HEADERS), "anti-csrftoken-a2z": sess.glow_token, "referer": base + "/"}
        resp = sess.curl.get(base + "/portal-migration/hz/glow/get-rendered-address-selections",
                             params={"deviceType": "desktop", "pageType": "Detail", "storeContext": "generic",
                                     "actionSource": "desktop-modal"}, headers=headers)
        m = fetch._MODAL_TOKEN_RE.search(resp.text or "")
        token = m.group(1) if m else sess.glow_token
        sess.curl.post(base + "/portal-migration/hz/glow/address-change", params={"actionSource": "glow"},
                       json={"locationType": "COUNTRY", "district": "AR", "countryCode": "AR", "deviceType": "web",
                             "storeContext": "generic", "pageType": "Detail", "actionSource": "glow"},
                       headers={**headers, "anti-csrftoken-a2z": token, "content-type": "application/json"})
        sess.located = "AR"
        return True

    fetch.set_location = set_ar


def fetch_details(asin):
    """ pide el detalle del ASIN en la tienda US con la location ya fijada en Argentina."""
    from amazon import products

    return products.details(asin, "US")


class ArShippingHandler(BaseHTTPRequestHandler):
    server_version = "ar-server/1.0"

    def log_message(self, format, *args):
        print(f"ar-server: {self.address_string()} {format % args}", flush=True)

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/ar-shipping":
            self._send_json(404, {"error": "not found"})
            return
        raw = parse_qs(parsed.query).get("asins", [""])[0]
        asins = [a.strip() for a in raw.split(",") if a.strip()]
        if not asins or len(asins) > MAX_ASINS:
            self._send_json(400, {"error": f"asins debe tener entre 1 y {MAX_ASINS} ASINs"})
            return
        products = []
        for asin in asins:
            try:
                products.append({"asin": asin, **parse_delivery(fetch_details(asin))})
            except Exception as exc:  # por ASIN: un error no tumba al resto del lote
                products.append({"asin": asin, "error": type(exc).__name__})
        self._send_json(200, {"products": products})


def main():
    apply_ar_location()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), ArShippingHandler)
    print(f"ar-server escuchando en el puerto {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
