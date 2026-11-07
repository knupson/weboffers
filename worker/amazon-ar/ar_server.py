"""Servidor HTTP mínimo (sólo stdlib) que informa si Amazon envía cada ASIN a Argentina y si el envío es gratis.

Al arrancar reemplaza `amazon.fetch.set_location` para que el scraper consulte "desde Argentina"
(referencia probada en la Pi4, ver ar_probe_REFERENCIA.py en la raíz del repo). Escucha en el puerto 8001.
"""

import json
import re
from threading import BoundedSemaphore
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HTTP_TIMEOUT = 45
QUEUE_TIMEOUT = 240
REQUEST_SLOT = BoundedSemaphore(1)

PORT = 8001
MAX_ASINS = 5
STORES = ("US", "ES")

try:
    from amazon_shipping import apply_ar_location, parse_delivery
except ModuleNotFoundError as exc:
    # Ejecución desde el checkout: el módulo compartido vive un nivel arriba.
    if exc.name != "amazon_shipping":
        raise
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from amazon_shipping import apply_ar_location, parse_delivery


def identificadores(details):
    """Número de modelo, UPC y GTIN de la página de Amazon (05/11): permiten emparejar con el MPN/GTIN de la ficha
    de ML aunque el título no diga el modelo («Logitech 4k Webcam» = 960-001105 = Brio C1000E)."""
    ids = details.get("identifiers") if isinstance(details, dict) else None
    ids = ids if isinstance(ids, dict) else {}
    extra = details.get("details") if isinstance(details, dict) and isinstance(details.get("details"), dict) else {}
    return {k: str(v)[:300] for k, v in {"model_number": ids.get("model_number") or extra.get("model_number"),
                                         "upc": ids.get("upc") or extra.get("upc"),
                                         "gtin": ids.get("gtin") or extra.get("global_trade_identification_number"),
                                         "model_name": extra.get("model_name")}.items() if v}


def sesion_confirmada_ar(store="US"):
    """True si la sesión de la tienda `store` en este hilo quedó confirmada con ubicación en Argentina."""
    from amazon import fetch, sites

    sess = fetch.session(sites.site(store)["country"], "page")
    return getattr(sess, "located", None) == "AR"


def fetch_details(asin, store="US"):
    """Pide el detalle del ASIN en la tienda indicada (misma tienda que da el precio)."""
    from amazon import products

    return products.details(asin, store)


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
        query = parse_qs(parsed.query)
        raw = query.get("asins", [""])[0]
        asins = [a.strip() for a in raw.split(",") if a.strip()]
        if not asins or len(asins) > MAX_ASINS:
            self._send_json(400, {"error": f"asins debe tener entre 1 y {MAX_ASINS} ASINs"})
            return
        store = (query.get("store", ["US"])[0] or "US").upper()
        if store not in STORES:
            self._send_json(400, {"error": f"store debe ser uno de: {', '.join(STORES)}"})
            return
        if not REQUEST_SLOT.acquire(timeout=QUEUE_TIMEOUT):
            self._send_json(503, {"error": "Tiempo de espera agotado"})
            return
        try:
            products = []
            for asin in asins:
                try:
                    details = fetch_details(asin, store)
                    located = sesion_confirmada_ar(store)
                    products.append({"asin": asin, **parse_delivery(details, located=located),
                                     "identifiers": identificadores(details)})
                except Exception as exc:  # por ASIN: un error no tumba al resto del lote; queda desconocido
                    products.append({"asin": asin, "ships": None, "free": None, "error": type(exc).__name__})
            self._send_json(200, {"products": products})
        finally:
            REQUEST_SLOT.release()



def main():
    apply_ar_location()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), ArShippingHandler)
    print(f"ar-server escuchando en el puerto {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
