from types import SimpleNamespace
import pytest
from .shipping import delivery_from_card, classify_shipping, session_is_ar


@pytest.mark.parametrize("text,expected", [
    ("FREE delivery to Argentina", "gratis"), ("$6.99 delivery", "pago"),
    ("ENVÍO GRATIS a Argentina", "gratis"), ("Entrega GRATIS a Argentina", "gratis"),
    ("Envío de 6,99 € a Argentina", "pago"), ("6,99 € de envío a Argentina", "pago"),
    ("No se puede enviar a Argentina", "no_envia"), ("No se envía a Argentina", "no_envia"),
    ("Delivery to Argentina", "envia_costo_desconocido"), ("", "desconocido"),
])
def test_ar_us_es(text, expected):
    row = {"price": {"amount": 150, "currency": "EUR"}, "delivery": text}
    assert delivery_from_card(row, located=True)["shipping_class"] == expected
    assert delivery_from_card(row, located=False)["shipping_class"] == "desconocido"


def test_sesion_idioma_correcta():
    assert session_is_ar(SimpleNamespace(located="AR"))
    assert not session_is_ar(SimpleNamespace(located="28001"))
    assert classify_shipping({"ships": True, "free": None}) == "envia_costo_desconocido"


def test_minimo_es():
    out = delivery_from_card({"price": {"amount": 90}, "delivery": "ENVÍO GRATIS a Argentina en pedidos superiores a 99 €"}, located=True)
    assert out["free"] is None  # No se inventa un costo pago cuando sólo se perdió el beneficio.
