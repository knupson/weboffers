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
    monkeypatch.delenv("AMAZON_AR_URL", raising=False)
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
    n = amazon_prices.BULK_MAX
    us_calls = -(-12 // n)  # 12 productos US en lotes de BULK_MAX
    assert len(calls) == us_calls + 1
    sizes = [len(c[1]["products"].split(",")) for c in calls if c[1]["country"] == "US"]
    assert sizes == [n] * (12 // n) + ([12 % n] if 12 % n else [])
    assert calls[-1][1]["country"] == "ES" and calls[-1][1]["products"] == "B000000099"

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


def test_does_not_keep_previous_when_scraper_fails(tmp_path, monkeypatch, capsys):
    catalog = [
        {"slug": "ayer", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "tres-dias", "asin": "B02", "store": "US", "verified": True, "ml": {"price": 1000}},
    ]
    out = tmp_path / "amazon-prices.json"
    out.write_text(json.dumps({
        "generatedAt": "2026-10-29T10:00:00Z",
        "date": "2026-10-29",
        "items": {
            "ayer": {"amount": 180, "currency": "USD", "checked": "2026-10-29"},
            "tres-dias": {"amount": 200, "currency": "USD", "checked": "2026-10-27"},
        },
    }), encoding="utf-8")

    monkeypatch.setattr(amazon_prices.requests, "get", Mock(side_effect=requests.ConnectionError("caído")))
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert items == {}
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


def ar_response(products):
    resp = Mock()
    resp.json.return_value = {"products": products}
    resp.raise_for_status = Mock()
    return resp


def ar_item(asin, ships, free, text="FREE delivery Wednesday, November 11 to Argentina", price=25.99):
    return {"asin": asin, "ships": ships, "free": free, "text": text if ships else None, "price": price if ships else None, "condition": "New"}


def fake_get_router(bulk_items, ar_items):
    def fake_get(url, params=None, timeout=None):
        if url.endswith("/ar-shipping"):
            by_asin = {p["asin"]: p for p in ar_items}
            return ar_response([by_asin.get(a, {"asin": a, "error": "KeyError"}) for a in params["asins"].split(",")])
        asins = params["products"].split(",")
        cur = "EUR" if params["country"] == "ES" else "USD"
        return bulk_response(bulk_items or [ok_item(a, 150.5, cur) for a in asins])
    return fake_get


def test_stores_ships_to_ar_in_chunks_of_bulk_max(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAZON_AR_URL", "http://ar:8001")
    catalog = [
        {"slug": f"us-{i}", "asin": f"B0000000{i:02d}", "store": "US", "verified": True, "ml": {"price": 1000}}
        for i in range(7)
    ]
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        if url.endswith("/ar-shipping"):
            asins = params["asins"].split(",")
            return ar_response([ar_item(a, True, int(a[-2:]) % 2 == 0) for a in asins])
        return bulk_response([ok_item(a, 150.5, "USD") for a in params["products"].split(",")])

    monkeypatch.setattr(amazon_prices.requests, "get", fake_get)
    out = tmp_path / "amazon-prices.json"
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True

    ar_calls = [c for c in calls if c[0].endswith("/ar-shipping")]
    n = amazon_prices.BULK_MAX
    assert [len(c[1]["asins"].split(",")) for c in ar_calls] == [n, 7 % n]
    assert all(c[2] == amazon_prices.TIMEOUT for c in ar_calls)

    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert len(items) == 7
    for i in range(7):
        assert items[f"us-{i}"]["shipsToAr"] == {"ships": True, "free": i % 2 == 0, "checked": "2026-10-30"}
        assert items[f"us-{i}"]["amount"] == 150.5


def test_ar_error_or_missing_leaves_ships_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAZON_AR_URL", "http://ar:8001")
    catalog = [
        {"slug": "ok", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "falla", "asin": "B02", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "no-envia", "asin": "B03", "store": "US", "verified": True, "ml": {"price": 1000}},
    ]
    ar_items = [
        ar_item("B01", True, True),
        {"asin": "B02", "error": "Timeout"},
        ar_item("B03", False, None, text=None, price=None),
    ]
    monkeypatch.setattr(amazon_prices.requests, "get", fake_get_router(None, ar_items))
    out = tmp_path / "amazon-prices.json"
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert items["ok"]["shipsToAr"] == {"ships": True, "free": True, "checked": "2026-10-30"}
    assert "shipsToAr" not in items["falla"]  # error por producto: queda desconocido
    assert items["no-envia"]["shipsToAr"] == {"ships": False, "free": None, "checked": "2026-10-30"}


def test_ar_chunk_failure_does_not_break_prices(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("AMAZON_AR_URL", "http://ar:8001")
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/ar-shipping"):
            raise requests.ConnectionError("caído")
        return bulk_response([ok_item("B01", 150.5, "USD")])

    monkeypatch.setattr(amazon_prices.requests, "get", fake_get)
    out = tmp_path / "amazon-prices.json"
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert items["p"]["amount"] == 150.5
    assert "shipsToAr" not in items["p"]
    assert "Amazon AR" in capsys.readouterr().out


def test_empty_ar_url_skips_ar_step(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAZON_AR_URL", "   ")
    get = Mock(side_effect=AssertionError("no debe llamar a /ar-shipping"))

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/ar-shipping"):
            return get(url, params=params, timeout=timeout)
        return bulk_response([ok_item(a, 150.5, "USD") for a in params["products"].split(",")])

    monkeypatch.setattr(amazon_prices.requests, "get", fake_get)
    out = tmp_path / "amazon-prices.json"
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert "shipsToAr" not in items["p"]
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
