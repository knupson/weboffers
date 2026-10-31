from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
import requests

import amazon_prices
import ml_prices
import rates
import worker


AFTER_SEVEN = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 09:00 ART


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AMAZON_SCRAPER_URL", "http://scraper:8000")
    monkeypatch.setattr(amazon_prices, "PAUSE_SECONDS", 0)


def bulk_response(products):
    resp = Mock()
    resp.json.return_value = {"products": products}
    resp.raise_for_status = Mock()
    return resp


def ok_item(asin, amount, currency="USD", in_stock=True):
    return {
        "asin": asin,
        "price": {"amount": amount, "currency": currency},
        "availability": {"is_in_stock": in_stock},
    }


def test_groups_by_store_and_chunks_by_bulk_max(tmp_path, monkeypatch):
    catalog = [
        {"slug": f"us-{i}", "asin": f"B0000000{i:02d}", "store": "US", "verified": True, "ml": {"price": 1000}}
        for i in range(12)
    ] + [
        {"slug": "es-1", "asin": "B000000099", "store": "ES", "verified": True, "ml": {"price": 1000}},
        {"slug": "sin-ml", "asin": "B000000088", "store": "US", "verified": True},
        {"slug": "sin-asin", "asin": "", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "no-verif", "asin": "B000000077", "store": "US", "verified": False, "ml": {"price": 1000}},
    ]

    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        asins = params["products"].split(",")
        cur = "EUR" if params["country"] == "ES" else "USD"
        return bulk_response([ok_item(a, 150.5, cur) for a in asins])

    monkeypatch.setattr(amazon_prices.requests, "get", fake_get)
    out = tmp_path / "amazon-prices.json"
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    assert len(calls) == 3
    assert calls[0][1]["country"] == "US" and len(calls[0][1]["products"].split(",")) == 10
    assert calls[1][1]["country"] == "US" and len(calls[1][1]["products"].split(",")) == 2
    assert calls[2][1]["country"] == "ES" and calls[2][1]["products"] == "B000000099"

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["date"] == "2026-10-30"
    assert len(data["items"]) == 13
    assert data["items"]["us-0"] == {"amount": 150.5, "currency": "USD", "checked": "2026-10-30"}
    assert data["items"]["es-1"] == {"amount": 150.5, "currency": "EUR", "checked": "2026-10-30"}


@pytest.mark.parametrize("bad_item", [
    {"asin": "B01", "error": "not found"},
    {"asin": "B01", "price": {"amount": 100, "currency": "USD"}, "availability": {"is_in_stock": False}},
    {"asin": "B01", "price": {"amount": 100, "currency": "USD"}, "availability": {"is_in_stock": None}},
    {"asin": "B01", "price": {"amount": 100, "currency": "EUR"}, "availability": {"is_in_stock": True}},
    {"asin": "B01", "price": {"amount": 0, "currency": "USD"}, "availability": {"is_in_stock": True}},
    {"asin": "B01", "price": {"amount": -5, "currency": "USD"}, "availability": {"is_in_stock": True}},
    {"asin": "B01", "price": {"amount": True, "currency": "USD"}, "availability": {"is_in_stock": True}},
    {"asin": "B01", "price": {"amount": float("nan"), "currency": "USD"}, "availability": {"is_in_stock": True}},
    {"asin": "B01", "price": None, "availability": {"is_in_stock": True}},
])
def test_rejects_invalid_or_out_of_stock_items(bad_item):
    assert amazon_prices.valid_price(bad_item, "US") is None


def test_keeps_previous_up_to_three_days_and_drops_older(tmp_path, monkeypatch, capsys):
    catalog = [
        {"slug": "fresco", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "tres-dias", "asin": "B02", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "cuatro-dias", "asin": "B03", "store": "US", "verified": True, "ml": {"price": 1000}},
    ]
    out = tmp_path / "amazon-prices.json"
    out.write_text(json.dumps({
        "generatedAt": "2026-10-29T10:00:00Z",
        "date": "2026-10-29",
        "items": {
            "tres-dias": {"amount": 200, "currency": "USD", "checked": "2026-10-27"},
            "cuatro-dias": {"amount": 300, "currency": "USD", "checked": "2026-10-26"},
        },
    }), encoding="utf-8")

    monkeypatch.setattr(amazon_prices.requests, "get", Mock(side_effect=requests.ConnectionError("caído")))
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert set(items) == {"tres-dias"}
    assert items["tres-dias"]["amount"] == 200
    stdout = capsys.readouterr().out
    assert "AMAZON_SCRAPER_FAIL" in stdout


def test_skips_before_seven_or_already_updated_or_without_url(tmp_path, monkeypatch):
    get = Mock(side_effect=AssertionError("no debe llamar al scraper"))
    monkeypatch.setattr(amazon_prices.requests, "get", get)
    out = tmp_path / "amazon-prices.json"
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]

    before = datetime(2026, 10, 30, 9, 59, tzinfo=timezone.utc)  # 06:59 ART
    assert amazon_prices.maybe_refresh(catalog, out, before) is False

    monkeypatch.setenv("AMAZON_SCRAPER_URL", "   ")
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is False

    monkeypatch.setenv("AMAZON_SCRAPER_URL", "http://scraper:8000")
    out.write_text(json.dumps({"date": "2026-10-30", "items": {}}), encoding="utf-8")
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is False
    get.assert_not_called()


def test_worker_runs_amazon_before_ml(tmp_path, monkeypatch):
    order = []
    cat_path = tmp_path / "catalog.json"
    cat_path.write_text(json.dumps([{"asin": "B01", "store": "US", "slug": "p", "verified": True}]), encoding="utf-8")
    monkeypatch.setenv("CATALOG_PATH", str(cat_path))
    monkeypatch.setattr(rates, "get_rates", lambda: None)
    monkeypatch.setattr(amazon_prices, "maybe_refresh", lambda *a, **kw: order.append("amazon"))
    monkeypatch.setattr(ml_prices, "maybe_refresh", lambda *a, **kw: order.append("ml"))
    worker.run_once()
    assert order == ["amazon", "ml"]
