"""Tests de parse_delivery: lógica pura, sin red ni paquete amazon."""

from ar_server import parse_delivery


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


def test_no_envia_a_argentina():
    details = {
        "price": None,
        "delivery": {"text": None, "options": [], "location": "Argentina"},
    }
    out = parse_delivery(details)
    assert out["ships"] is False
    assert out["free"] is None
    assert out["text"] is None
    assert out["price"] is None


def test_sin_bloque_delivery():
    assert parse_delivery({"price": {"amount": 5}}) == {
        "ships": False,
        "free": None,
        "text": None,
        "price": 5,
        "condition": None,
    }
    assert parse_delivery({})["ships"] is False
    assert parse_delivery(None)["ships"] is False


def test_free_por_opcion_en_minusculas_y_text_free_empieza():
    base = {"price": {"amount": 1}, "delivery": {"text": "Llega a Argentina", "options": [], "location": "Argentina"}}
    con_opcion = {**base, "delivery": {**base["delivery"], "options": [{"price_text": "free"}]}}
    assert parse_delivery(con_opcion)["free"] is True
    con_texto = {**base, "delivery": {**base["delivery"], "text": "free delivery Friday to Argentina"}}
    assert parse_delivery(con_texto)["free"] is True


def test_precio_no_numerico_no_envia():
    details = {
        "price": {"amount": None},
        "delivery": {"text": "FREE delivery to Argentina", "options": [{"price_text": "FREE"}], "location": "Argentina"},
    }
    out = parse_delivery(details)
    assert out["ships"] is False
    assert out["free"] is None
    assert out["price"] is None
