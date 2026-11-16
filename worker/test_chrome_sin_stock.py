"""Regresión del LEGO 71869 (B0G2T22QC3): precio y entrega visibles sin stock."""
import json
import shutil
import subprocess

import pytest

import amazon_prices
import diario
from test_panel_ofertas import _modulo
from tools import altas_chrome
from article_log import chrome_line


TODAY = "2026-11-16"
ASIN = "B0G2T22QC3"


def pagina(stock):
    return {"deliver": "Deliver to Argentina", "buybox": True, "lang": "en-us",
            "stock": stock, "envio": "FREE delivery November 23 to Argentina",
            "precio": "$149.99", "titulo": "LEGO 71869"}


@pytest.mark.parametrize("stock", ["Temporarily out of stock.", "Currently unavailable.",
                                   "Out of Stock", "TEMPORARILY OUT OF STOCK", "out of stock " + "x" * 180])
def test_sin_stock_descarta_precio_y_envio(monkeypatch, stock):
    mod = _modulo(monkeypatch)
    item = mod.interpretar(pagina(stock))
    assert item == {"ships": None, "free": None, "motivo": "sin_stock", "text": stock[:160]}
    assert not mod.abre_panel(item)
    assert "motivo=sin_stock" in chrome_line(["lego-71869"], ASIN, item)


@pytest.mark.parametrize("stock", ["Only 2 left in stock", "In Stock", "in stock"])
def test_con_stock_conserva_precio_y_envio(monkeypatch, stock):
    item = _modulo(monkeypatch).interpretar(pagina(stock))
    assert item["ships"] is True and item["free"] is True
    assert item["precio"] == "$149.99" and item["motivo"] is None


def test_js_lee_disponibilidad_de_la_pagina(monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Requiere Node para ejecutar el lector JavaScript")
    mod = _modulo(monkeypatch)
    # DOM mínimo: disponibilidad fuera del recuadro, entrega y precio todavía visibles.
    script = """
const stock = {innerText: 'Temporarily out of stock.'};
const bb = {innerText: 'FREE delivery to Argentina', querySelector: () => ({innerText: 'FREE delivery to Argentina'})};
global.document = {body: {innerText: ''}, documentElement: {lang: 'en-US'},
 getElementById: id => ({availability: stock, desktop_buybox: bb,
  'glow-ingress-block': {innerText: 'Deliver to Argentina'}, productTitle: {innerText: 'LEGO 71869'}}[id]),
 querySelector: () => ({innerText: '$149.99'})};
"""
    run = subprocess.run([node, "-e", script + "process.stdout.write(" + mod.LEER + ");"],
                         capture_output=True, text=True, check=True, timeout=10)
    data = json.loads(run.stdout)
    assert data["stock"] == "Temporarily out of stock."
    assert mod.interpretar(data)["motivo"] == "sin_stock"


@pytest.mark.parametrize("journal_day", [None, "2026-11-15", TODAY])
def test_sin_stock_no_recupera_precio_del_scraper_ni_del_diario(tmp_path, monkeypatch, journal_day):
    item = {"ships": None, "free": None, "motivo": "sin_stock", "text": "Temporarily out of stock."}
    altas_chrome.merge_chrome(tmp_path, TODAY, {"generado": TODAY + "T10:00:00-03:00", "items": {ASIN: item}})
    prices = tmp_path / "amazon-prices.json"
    if journal_day:
        diario.anotar(diario.ruta(prices, journal_day), {"t": "precio", "slug": "lego", "item": {
            "asin": ASIN, "amount": 149.99, "currency": "USD", "checked": journal_day}})
    pedidos = []
    def fetch(base, products, today):
        pedidos.extend(products)
        return {p["slug"]: {"amount": 149.99, "currency": "USD", "checked": today} for p in products}, len(products), 0
    monkeypatch.setattr(amazon_prices, "fetch_prices", fetch)
    products = [{"slug": "lego", "asin": ASIN, "store": "US", "name": "LEGO 71869"}]
    assert amazon_prices.prices_with_chrome("http://scraper", products, TODAY, prices) == ({}, 0, 1)
    assert pedidos == []
    assert amazon_prices.chrome_sin_envio_gratis(prices, TODAY) == {ASIN: "sin_stock"}
    assert amazon_prices.load_chrome_prices(prices, TODAY) == {}
    assert amazon_prices.load_ar_chrome(prices, TODAY) == {}
    assert amazon_prices.chrome_shipping(products, prices, TODAY) == {
        "lego": {"ships": None, "free": None, "checked": TODAY}}
    assert altas_chrome.relevados_hoy(tmp_path, TODAY) == set()
