"""Precios de ML leídos con Chrome (24/11): lectura de la página y uso desde ml_prices."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import ml_chrome  # noqa: E402
import ml_prices  # noqa: E402

# Forma real leída de /p/MLA17332828/s el 24/11 10:20 (recortada): la primera oferta es internacional.
PAGINA = {
    "items": [
        {"item_id": "MLA4201472256", "price": 415182.71, "currency_id": "ARS", "condition": "new"},
        {"item_id": "MLA1104507026", "price": 1026899, "currency_id": "ARS", "condition": "new"},
        {"item_id": "MLA1848139213", "price": 700000, "currency_id": "ARS", "condition": "new"},
    ],
    "ofertas": [
        {"ids": ["MLA4201472256"], "cbt": True},
        {"ids": ["MLA1104507026"], "cbt": False},
        {"ids": ["MLA1848139213"], "cbt": False},
    ],
    "hayResultados": True,
}


def test_la_internacional_no_cuenta_y_gana_la_local_mas_barata():
    results, motivo = ml_chrome.interpretar([PAGINA])
    assert motivo == "ok"
    assert ml_prices.cheapest_new(results) == (700000, "MLA1848139213")


def test_oferta_sin_fila_visible_o_sin_condicion_es_falla():
    # Revisión de Codex 24/11: no se adivina si es internacional ni si es nueva.
    pagina = {**PAGINA, "ofertas": PAGINA["ofertas"][1:]}
    assert ml_chrome.interpretar([pagina]) == (None, "oferta_sin_fila_visible")
    items = [{**PAGINA["items"][0], "condition": None}] + PAGINA["items"][1:]
    assert ml_chrome.interpretar([{**PAGINA, "items": items}])[0] is None


def test_pagina_de_otro_catalogo_o_vacia_es_falla():
    assert ml_chrome.interpretar([{**PAGINA, "catalogo": "MLA999"}], "MLA17332828")[1].startswith("pagina_de_otro_catalogo")
    assert ml_chrome.interpretar([{**PAGINA, "catalogo": "MLA17332828"}], "MLA17332828")[1] == "ok"
    assert ml_chrome.interpretar([{"items": [], "ofertas": [], "hayResultados": True}]) == (None, "sin_items")
    assert ml_chrome.interpretar([PAGINA, {"items": [], "ofertas": []}]) == (None, "pagina_siguiente_vacia")
    assert ml_chrome.interpretar([PAGINA, PAGINA]) == (None, "pagina_repetida")


def test_verificacion_o_pagina_rota_es_falla_no_ausencia():
    assert ml_chrome.interpretar([{"verificacion": True}]) == (None, "verificacion_ml")
    assert ml_chrome.interpretar([{"error": "TypeError: x"}])[0] is None
    assert ml_chrome.interpretar([PAGINA, {"verificacion": True}]) == (None, "pagina_siguiente_sin_leer")
    assert ml_chrome.interpretar([]) == (None, "sin_lectura")


def test_varias_paginas_se_unen():
    otra = {"items": [{"item_id": "MLA999", "price": 650000, "currency_id": "ARS", "condition": "new"}],
            "ofertas": [{"ids": ["MLA999"], "cbt": False}], "hayResultados": True}
    results, motivo = ml_chrome.interpretar([PAGINA, otra])
    assert motivo == "ok"
    assert ml_prices.cheapest_new(results) == (650000, "MLA999")


def escribir(tmp_path, today, items):
    (tmp_path / f"ml-chrome-{today}.json").write_text(json.dumps({"date": today, "items": items}), encoding="utf-8")


def test_chrome_results_solo_de_hoy(tmp_path):
    escribir(tmp_path, "2026-11-23", {"MLA1": {"results": []}})
    assert ml_prices.chrome_results("MLA1", tmp_path, "2026-11-24") is None
    escribir(tmp_path, "2026-11-24", {"MLA1": {"results": [{"price": 1}]}, "MLA2": {"results": None, "motivo": "verificacion_ml"}})
    assert ml_prices.chrome_results("MLA1", tmp_path, "2026-11-24") == [{"price": 1}]
    assert ml_prices.chrome_results("MLA3", tmp_path, "2026-11-24") is None
    with pytest.raises(ValueError, match="verificacion_ml"):
        ml_prices.chrome_results("MLA2", tmp_path, "2026-11-24")


def test_fetch_items_usa_chrome_antes_que_la_api(tmp_path, monkeypatch):
    today = ml_prices.datetime.now(ml_prices.ART).date().isoformat()
    escribir(tmp_path, today, {"MLA17332828": {"results": ml_chrome.interpretar([PAGINA])[0]}})
    monkeypatch.setenv("ML_PRICES_PATH", str(tmp_path / "ml-prices.json"))
    monkeypatch.setattr(ml_prices, "get_json", lambda *a, **k: pytest.fail("no debe llamar a la API"))
    assert ml_prices.cheapest_new(ml_prices.fetch_items("MLA17332828")) == (700000, "MLA1848139213")
