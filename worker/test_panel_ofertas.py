"""10/11: con «See All Buying Options» se lee el panel de ofertas y se elige la más barata que cumpla."""
import importlib.util
import json
import pathlib
import sys
import types

import amazon_prices


def _modulo(monkeypatch):
    # websockets sólo existe en el contenedor de Chrome; el stub se deshace al terminar cada test (no afecta a otros).
    monkeypatch.setitem(sys.modules, "websockets", sys.modules.get("websockets") or types.ModuleType("websockets"))
    spec = importlib.util.spec_from_file_location(
        "envio_ar_chrome_panel", pathlib.Path(__file__).resolve().parent.parent / "tools" / "envio_ar_chrome.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


AR = "Deliver to Argentina"
PREVIO = {"ships": False, "free": None, "text": "See All Buying Options", "motivo": "sin_oferta_ar"}


def oferta(precio, envio, condicion="New", vendedor="v", no_envia=False):
    return {"precio": precio, "envio": envio, "condicion": condicion, "vendedor": vendedor, "noEnvia": no_envia}


def test_elige_la_mas_barata_que_cumple_no_la_primera(monkeypatch):
    # Caso real B004HS7T7S (10/11): las más baratas sin «FREE», sin texto o que no envían; gana la gratis más barata.
    mod = _modulo(monkeypatch)
    d = {"deliver": AR, "lang": "en-us", "lista": True, "ofertas": [
        oferta("$119.55", "Delivery Monday, November 23"),
        oferta("$210.57", None, vendedor="Amazon Germany", no_envia=True),
        oferta("$259.82", "FREE delivery Monday, November 23", vendedor="Zentra"),
        oferta("$225.00", "FREE delivery Monday, November 23", vendedor="Fabulous Yarn"),
        oferta("$150.00", "FREE delivery Monday, November 23", condicion="Used - Good"),
        oferta("$90.00", "FREE delivery Monday, November 23", vendedor="fuera de rango")]}
    r = mod.interpretar_panel(d, PREVIO)
    assert r == {"ships": True, "free": True, "text": "FREE delivery Monday, November 23", "motivo": "panel_ofertas",
                 "precio": "$225.00", "vendedor": "Fabulous Yarn"}


def test_sin_elegible_o_panel_dudoso_conserva_el_recuadro(monkeypatch):
    mod = _modulo(monkeypatch)
    sin = {"deliver": AR, "lang": "en-us", "lista": True, "ofertas": [oferta("$120.00", "$31.20 delivery")]}
    assert mod.interpretar_panel(sin, PREVIO) == {**PREVIO, "panel": "sin_oferta_elegible:1"}
    for d, motivo in (({"lista": False}, "no_leido"), ({"lista": True, "captcha": True}, "no_leido"),
                      ({"lista": True, "lang": "es-us", "deliver": AR}, "no_leido"),
                      ({"lista": True, "deliver": "Deliver to 10001", "ofertas": []}, "ubicacion_no_ar")):
        assert mod.interpretar_panel(d, PREVIO) == {**PREVIO, "panel": motivo}


def test_solo_abre_el_panel_con_see_all_buying_options(monkeypatch):
    mod = _modulo(monkeypatch)
    assert mod.abre_panel(PREVIO)
    assert not mod.abre_panel({**PREVIO, "text": "This item cannot be shipped to your selected delivery location."})
    assert not mod.abre_panel({"ships": True, "motivo": None, "text": "FREE delivery"})


def test_precio_del_panel_llega_al_control_de_misma_oferta(tmp_path):
    # La oferta del panel puede ser de otro vendedor: su precio entra a offer_mismatch (tolerancia 15 %).
    prices = tmp_path / "amazon-prices.json"
    (tmp_path / "ar-chrome-2026-11-10.json").write_text(json.dumps({"items": {
        "B0PANEL": {"ships": True, "free": True, "text": "FREE delivery", "motivo": "panel_ofertas", "precio": "$329.95"},
        "B0RECUADRO": {"ships": True, "free": True, "text": "FREE delivery", "precio": "$99.99"}}}))
    cargado = amazon_prices.load_ar_chrome(prices, "2026-11-10")
    assert cargado["B0PANEL"]["price"] == 329.95
    assert cargado["B0RECUADRO"]["price"] is None  # el recuadro de compra sigue como antes
    assert amazon_prices.offer_mismatch(cargado["B0PANEL"], {"amount": 99.99}) == "oferta_distinta"
    assert amazon_prices.offer_mismatch(cargado["B0PANEL"], {"amount": 319.99}) is None
