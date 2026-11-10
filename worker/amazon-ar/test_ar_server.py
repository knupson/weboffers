"""Tests del servidor AR: parse_delivery (lógica pura), set_ar (confirmación de ubicación) y el handler HTTP."""

import re
import sys
import types
from unittest.mock import Mock

import pytest

import ar_server
from ar_server import parse_delivery


@pytest.mark.parametrize('text,expected', [
    ('ENVÍO GRATIS en pedidos superiores a 99 €', (None, None)),
    ('ENVÍO GRATIS el martes', (None, None)),
    ('Entrega GRATIS el lunes', (None, None)),
    ('Envío de 6,99 € el lunes', (None, None)),
    ('Este artículo no se envía a Argentina', (True, False)),
])
def test_regresion_delivery_legacy_es(text, expected):
    result = parse_delivery({'price': {'amount': 150}, 'delivery': {'text': text, 'location': 'Argentina'}}, located=True)
    assert result == dict(ships=expected[0], free=expected[1], text=text, price=150, condition=None)


# ---------- parse_delivery: ships True ----------


def test_envia_con_envio_gratis():
    details = {
        "price": {"amount": 25.99, "currency": "USD"},
        "delivery": {
            "text": "FREE delivery Wednesday, November 11 to Argentina Or fastest ...",
            "options": [{"type": "delivery", "price_text": "FREE"}],
            "location": "Argentina",
        },
        "condition": "New",
    }
    assert parse_delivery(details) == {
        "ships": True,
        "free": True,
        "text": "FREE delivery Wednesday, November 11 to Argentina Or fastest ...",
        "price": 25.99,
        "condition": "New",
    }


def test_envia_sin_envio_gratis():
    details = {
        "price": {"amount": 10.0},
        "delivery": {
            "text": "Delivery Wednesday, November 11 to Argentina",
            "options": [{"type": "delivery", "price_text": "$5.99"}],
            "location": "Argentina",
        },
    }
    out = parse_delivery(details)
    assert out["ships"] is True
    assert out["free"] is False
    assert out["condition"] is None


def test_free_por_opcion_en_minusculas_y_text_free_empieza():
    base = {"price": {"amount": 1}, "delivery": {"text": "Llega a Argentina", "options": [], "location": "Argentina"}}
    con_opcion = {**base, "delivery": {**base["delivery"], "options": [{"price_text": "free"}]}}
    assert parse_delivery(con_opcion)["free"] is True
    con_texto = {**base, "delivery": {**base["delivery"], "text": "free delivery Friday to Argentina"}}
    assert parse_delivery(con_texto)["free"] is True


# ---------- parse_delivery: ships False (negativos confiables) ----------


@pytest.mark.parametrize("frase", [
    "Cannot be shipped to your location",
    "CAN'T BE SHIPPED to Argentina",
    "This item does not ship to Argentina",
    "Not available for shipping",
    "No se puede enviar a tu dirección",
])
def test_texto_de_no_envio_explicito_da_ships_false(frase):
    details = {
        "price": {"amount": 25.99},
        "delivery": {"text": frase, "options": [], "location": "Argentina"},
    }
    out = parse_delivery(details, located=True)
    assert out["ships"] is False
    assert out["free"] is None


@pytest.mark.parametrize("availability", [
    "Cannot be shipped",
    {"text": "does not ship to Argentina"},
    {"message": "no se puede enviar"},  # sin clave text: no es texto usable, queda desconocido
])
def test_texto_de_availability_tambien_cuenta(availability):
    details = {"price": None, "availability": availability, "delivery": {"text": None, "options": [], "location": "Argentina"}}
    out = parse_delivery(details, located=True)
    if isinstance(availability, dict) and "text" not in availability:
        assert out["ships"] is None  # sin texto usable: desconocido
    else:
        assert out["ships"] is False
    # El negativo explícito sólo vale con la ubicación confirmada en Argentina.
    assert parse_delivery(details, located=False)["ships"] is None


def test_negativo_vacio_solo_si_sesion_confirmada_en_ar():
    # Página sin oferta ni texto explícito: ambiguo, desconocido aunque la ubicación sea AR (31/10).
    details = {"price": None, "delivery": {"text": None, "options": [], "location": "Argentina"}}
    out = parse_delivery(details, located=True)
    assert out["ships"] is None
    assert out["free"] is None
    assert out["text"] is None
    assert out["price"] is None
    out = parse_delivery(details, located=False)
    assert out["ships"] is None
    assert out["free"] is None


def test_negativo_vacio_exige_todos_los_campos():
    base = {"price": None, "delivery": {"text": None, "options": [], "location": "Argentina"}}
    # Con texto de delivery -> desconocido.
    assert parse_delivery({**base, "delivery": {**base["delivery"], "text": "Llega pronto"}}, located=True)["ships"] is None
    # Con opciones -> desconocido.
    assert parse_delivery({**base, "delivery": {**base["delivery"], "options": [{"price_text": "$9"}]}}, located=True)["ships"] is None
    # Con amount numérico -> desconocido (no es "None").
    assert parse_delivery({**base, "price": {"amount": 5}}, located=True)["ships"] is None
    # Location que no es Argentina -> desconocido.
    assert parse_delivery({**base, "delivery": {**base["delivery"], "location": "United States"}}, located=True)["ships"] is None


# ---------- parse_delivery: ships None (desconocido, nunca False) ----------


def test_sin_bloque_delivery_es_desconocido():
    assert parse_delivery({"price": {"amount": 5}}, located=True) == {
        "ships": None,
        "free": None,
        "text": None,
        "price": 5,
        "condition": None,
    }
    assert parse_delivery({})["ships"] is None
    assert parse_delivery(None)["ships"] is None
    assert parse_delivery(None)["free"] is None


def test_precio_no_numerico_es_desconocido_no_false():
    details = {
        "price": {"amount": None},
        "delivery": {"text": "FREE delivery to Argentina", "options": [{"price_text": "FREE"}], "location": "Argentina"},
    }
    out = parse_delivery(details, located=True)
    assert out["ships"] is None
    assert out["free"] is None
    assert out["price"] is None
    # amount bool no es un número válido.
    assert parse_delivery({"price": {"amount": True}, "delivery": {"text": "to Argentina"}})["ships"] is None


# ---------- set_ar: la ubicación sólo se marca confirmada con respuesta exitosa ----------


@pytest.fixture
def fake_amazon(monkeypatch):
    """Inyecta un paquete `amazon` falso con el módulo fetch que usa apply_ar_location."""
    amazon_pkg = types.ModuleType("amazon")
    fetch_mod = types.ModuleType("amazon.fetch")
    fetch_mod.AJAX_HEADERS = {"x-ajax": "1"}
    fetch_mod._MODAL_TOKEN_RE = re.compile(r'modal-token="([^"]+)"')
    amazon_pkg.fetch = fetch_mod
    monkeypatch.setitem(sys.modules, "amazon", amazon_pkg)
    monkeypatch.setitem(sys.modules, "amazon.fetch", fetch_mod)
    return fetch_mod, amazon_pkg


def _resp(status, body=None, no_json=False):
    r = Mock()
    r.status_code = status
    r.json = Mock(side_effect=ValueError("no es json")) if no_json else Mock(return_value=body)
    return r


def _sess(post_resp, glow_token="glow", located=None):
    sess = Mock()
    sess.glow_token = glow_token
    sess.located = located
    sess.site = {"base": "https://www.amazon.com"}
    sess.headers = lambda h: dict(h)
    get_resp = Mock()
    get_resp.text = '<input modal-token="modal123">'
    sess.curl = Mock()
    sess.curl.get = Mock(return_value=get_resp)
    sess.curl.post = Mock(return_value=post_resp)
    return sess


def test_set_ar_confirma_solo_con_200_y_exito(fake_amazon):
    fetch_mod, _ = fake_amazon
    ar_server.apply_ar_location()
    set_ar = fetch_mod.set_location

    # 200 + isAddressUpdated -> confirmada.
    sess = _sess(_resp(200, {"isAddressUpdated": True}))
    assert set_ar(sess) is True
    assert sess.located == "AR"
    assert fetch_mod.TIMEOUT == ar_server.HTTP_TIMEOUT
    assert sess.curl.get.call_args.kwargs["timeout"] == ar_server.HTTP_TIMEOUT
    assert sess.curl.post.call_args.kwargs["timeout"] == ar_server.HTTP_TIMEOUT

    # 200 + successful + address.countryCode AR -> confirmada.
    sess = _sess(_resp(200, {"successful": True, "address": {"countryCode": "AR"}}))
    assert set_ar(sess) is True
    assert sess.located == "AR"

    # 200 + éxito pero otro país -> NO confirmada.
    sess = _sess(_resp(200, {"isAddressUpdated": True, "address": {"countryCode": "US"}}))
    assert set_ar(sess) is False
    assert sess.located is None

    # 200 sin flag de éxito, HTTP 500 y cuerpo no-JSON -> NO confirmada.
    for resp in [_resp(200, {"isAddressUpdated": False}), _resp(500, {"isAddressUpdated": True}), _resp(200, no_json=True)]:
        sess = _sess(resp)
        assert set_ar(sess) is False
        assert sess.located is None

    # Ya localizada en AR o sin glow token: no vuelve a llamar al address-change.
    sess = _sess(_resp(200, {"isAddressUpdated": True}), located="AR")
    assert set_ar(sess) is False
    sess = _sess(_resp(200, {"isAddressUpdated": True}), glow_token=None)
    assert set_ar(sess) is False
    assert sess.curl.post.call_count == 0


def test_sesion_confirmada_ar(fake_amazon, monkeypatch):
    fetch_mod, amazon_pkg = fake_amazon
    sites_mod = types.ModuleType("amazon.sites")
    sites_mod.site = lambda country=None: {"country": (country or "US").upper()}
    amazon_pkg.sites = sites_mod
    monkeypatch.setitem(sys.modules, "amazon.sites", sites_mod)

    sess = Mock()
    sess.located = "AR"
    fetch_mod.session = lambda country, purpose="page", language=None: sess
    assert ar_server.sesion_confirmada_ar("US") is True
    assert ar_server.sesion_confirmada_ar("ES") is True  # misma sesión marcada
    sess.located = None
    assert ar_server.sesion_confirmada_ar("US") is False


# ---------- handler HTTP: store param, located y errores ----------


def _handler(path, monkeypatch, fetch_impl, located=True):
    monkeypatch.setattr(ar_server, "fetch_details", fetch_impl)
    monkeypatch.setattr(ar_server, "sesion_confirmada_ar", lambda store="US": located)
    captured = {}
    handler = ar_server.ArShippingHandler.__new__(ar_server.ArShippingHandler)
    handler.path = path
    handler._send_json = lambda status, payload: captured.update(status=status, payload=payload)
    handler.do_GET()
    return captured


def test_handler_pasa_store_a_fetch_details(monkeypatch):
    seen = []

    def fake_fetch(asin, store="US"):
        seen.append(store)
        return {"price": {"amount": 10}, "delivery": {"text": "to Argentina", "options": [], "location": "Argentina"}}

    cap = _handler("/ar-shipping?asins=B01", monkeypatch, fake_fetch)
    assert cap["status"] == 200
    assert seen == ["US"]  # default US
    assert cap["payload"]["products"][0]["ships"] is True

    cap = _handler("/ar-shipping?asins=B01&store=es", monkeypatch, fake_fetch)
    assert seen[-1] == "ES"

    cap = _handler("/ar-shipping?asins=B01&store=FR", monkeypatch, fake_fetch)
    assert cap["status"] == 400
    assert "store" in cap["payload"]["error"]


def test_handler_pasa_sesion_confirmada_a_parse_delivery(monkeypatch):
    detalles = {"price": None, "availability": {"text": "This item cannot be shipped to your selected delivery location."},
                "delivery": {"text": None, "options": [], "location": "Argentina"}}
    fake = lambda asin, store="US": detalles  # noqa: E731

    cap = _handler("/ar-shipping?asins=B01", monkeypatch, fake, located=True)
    assert cap["payload"]["products"][0]["ships"] is False

    cap = _handler("/ar-shipping?asins=B01", monkeypatch, fake, located=False)
    assert cap["payload"]["products"][0]["ships"] is None
    assert cap["payload"]["products"][0]["free"] is None


def test_handler_error_por_asin_queda_desconocido(monkeypatch):
    def fake_fetch(asin, store="US"):
        if asin == "B02":
            raise RuntimeError("caído")
        return {"price": {"amount": 10}, "delivery": {"text": "to Argentina", "options": [], "location": "Argentina"}}

    cap = _handler("/ar-shipping?asins=B01,B02", monkeypatch, fake_fetch)
    assert cap["status"] == 200
    ok, falla = cap["payload"]["products"]
    assert ok["asin"] == "B01" and ok["ships"] is True
    # Un error es desconocido (ships/free null), nunca False.
    assert falla["asin"] == "B02"
    assert falla["ships"] is None
    assert falla["free"] is None
    assert falla["error"] == "RuntimeError"


def test_envio_pago_con_sesion_en_argentina_es_ships_sin_gratis():
    # 03/11 (ASUS VG27AQ3A): «$71.77 delivery Monday…» quedaba desconocido para siempre.
    d = {"price": {"amount": 199.0}, "delivery": {"text": "$71.77 delivery Monday, November 16 Or fastest delivery Saturday", "options": [], "location": "Argentina"}}
    out = parse_delivery(d, located=True)
    assert out["ships"] is True and out["free"] is False
    assert parse_delivery(d, located=False)["ships"] is None  # sin sesión confirmada en AR, sigue desconocido


def test_gratis_condicional_por_monto_minimo_no_es_gratis_si_el_producto_vale_menos():
    # 03/11 (Logitech C920x a USD 67.90): «FREE delivery … on eligible orders over $99».
    base = {"delivery": {"text": "FREE delivery November 11 - 17 to Argentina on eligible orders over $99", "options": [], "location": "Argentina"}}
    assert parse_delivery({**base, "price": {"amount": 67.9}}, located=True)["free"] is False
    assert parse_delivery({**base, "price": {"amount": 120.0}}, located=True)["free"] is True


def test_free_delivery_without_country_uses_confirmed_session():
    details = {"price": {"amount": 120}, "delivery": {"text": "FREE delivery November 11 - 17"}}
    assert parse_delivery(details, located=True)["ships"] is True
    assert parse_delivery(details, located=True)["free"] is True
    assert parse_delivery(details, located=False)["ships"] is None
    details["delivery"]["text"] += " on eligible orders over $150"
    assert parse_delivery(details, located=True)["free"] is False


def test_handler_checks_location_after_fetch(monkeypatch):
    confirmed = []
    monkeypatch.setattr(ar_server, "sesion_confirmada_ar", lambda store: bool(confirmed))
    def fetch(asin, store):
        confirmed.append(store)
        return {"price": {"amount": 120}, "delivery": {"text": "FREE delivery tomorrow"}}
    monkeypatch.setattr(ar_server, "fetch_details", fetch)
    handler = ar_server.ArShippingHandler.__new__(ar_server.ArShippingHandler)
    handler.path = "/ar-shipping?asins=B01"
    result = {}
    handler._send_json = lambda status, payload: result.update(payload)
    handler.do_GET()
    assert result["products"][0]["ships"] is True
    assert result["products"][0]["free"] is True


def test_handler_serializes_and_times_out_queue(monkeypatch):
    from threading import BoundedSemaphore, Event, Thread
    semaphore = BoundedSemaphore(1)
    entered, release = Event(), Event()
    monkeypatch.setattr(ar_server, "REQUEST_SLOT", semaphore)
    monkeypatch.setattr(ar_server, "QUEUE_TIMEOUT", 0.02)
    monkeypatch.setattr(ar_server, "sesion_confirmada_ar", lambda _: True)
    def fetch(*args):
        entered.set()
        assert release.wait(2)
        return {}
    monkeypatch.setattr(ar_server, "fetch_details", fetch)
    def handler():
        h = ar_server.ArShippingHandler.__new__(ar_server.ArShippingHandler)
        h.path = "/ar-shipping?asins=A"
        h._send_json = Mock()
        return h
    first, second = handler(), handler()
    thread = Thread(target=first.do_GET)
    thread.start()
    try:
        assert entered.wait(2)
        second.do_GET()
        assert second._send_json.call_args.args[0] == 503
    finally:
        release.set()
        thread.join(2)
    assert first._send_json.call_args.args[0] == 200
    second.do_GET()
    assert second._send_json.call_args.args[0] == 200
