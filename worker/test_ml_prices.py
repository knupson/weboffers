from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
import requests

import ml_prices


CATALOG = [
    {"slug": "monitor", "name": "Monitor", "verified": True, "verdict": "ml",
     "ml": {"price": 500000, "catalogId": "MLA111"}, "shipsToAr": {"freeShipping": True}},
    {"slug": "ssd", "name": "SSD", "verified": True, "verdict": "amazon",
     "ml": {"price": 600000, "catalogId": "MLA222"}, "shipsToAr": {"freeShipping": True}},
    {"slug": "sin-id", "name": "Sin id", "verified": True, "verdict": "ml",
     "ml": {"price": 100000}},
    {"slug": "no-verificado", "name": "X", "verified": False, "verdict": "ml",
     "ml": {"price": 1, "catalogId": "MLA333"}},
]
# Ahorro exacto de 10%: 900 USD * 1000 ARS / 1.000.000 ARS.
MEP = 1000.0
AFTER_SEVEN = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 09:00 ART


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("ML_CLIENT_ID", "id")
    monkeypatch.setenv("ML_CLIENT_SECRET", "secret")
    monkeypatch.setattr(ml_prices, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(ml_prices, "_token_cache", {"value": None, "expires_at": 0.0})


def token_response():
    response = Mock()
    response.json.return_value = {"access_token": "tok", "expires_in": 21600}
    response.raise_for_status = Mock()
    return response


def items_response(results):
    response = Mock()
    response.json.return_value = {"results": results}
    response.raise_for_status = Mock()
    return response


def route_get(routes):
    def get(url, params=None, headers=None, timeout=None):
        value = routes[url.rsplit("/products/", 1)[1]]
        if isinstance(value, Exception):
            raise value
        return value
    return get


def test_verdict_amazon_needs_ten_percent_and_free_shipping():
    assert ml_prices.verdict_for(900, MEP, 1000000, True) == "amazon"  # exactamente 10%
    assert ml_prices.verdict_for(901, MEP, 1000000, True) == "ml"      # 9.9%
    assert ml_prices.verdict_for(100, MEP, 1000000, False) == "ml"     # sin envío gratis


def test_min_new_price_ignores_used_and_accepts_missing_condition():
    results = [
        {"price": 300, "condition": "used"},
        {"price": 500, "condition": "new"},
        {"price": 400},
        {"price": None, "condition": "new"},
        {"price": 250, "condition": "refurbished"},
    ]
    assert ml_prices.min_new_price(results) == 400
    assert ml_prices.min_new_price([{"price": 10, "condition": "used"}]) is None


def test_skips_without_catalog_id_and_unverified(tmp_path, monkeypatch):
    get = Mock(side_effect=route_get({"MLA111/items": items_response([{"price": 450000}]),
                                      "MLA222/items": items_response([{"price": 700000}])}))
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    prices = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "t.json", MEP, AFTER_SEVEN) is True
    assert get.call_count == 2
    data = json.loads(prices.read_text(encoding="utf-8"))
    assert set(data["items"]) == {"monitor", "ssd"}
    assert data["date"] == "2026-10-30"


def test_keeps_previous_value_when_items_call_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", route_get({
        "MLA111/items": requests.ConnectionError("caído"),
        "MLA222/items": items_response([{"price": 700000, "condition": "new"}]),
    }))
    prices = tmp_path / "ml-prices.json"
    previous = {"generatedAt": "2026-10-29T10:00:00+00:00", "date": "2026-10-29", "items": {
        "monitor": {"price": 480000, "checked": "2026-10-29", "verdict": "ml", "verdictReason": "precio"}}}
    prices.write_text(json.dumps(previous), encoding="utf-8")
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "t.json", MEP, AFTER_SEVEN) is True
    items = json.loads(prices.read_text(encoding="utf-8"))["items"]
    assert items["monitor"]["price"] == 480000
    assert items["ssd"]["price"] == 700000


def test_keeps_catalog_verdict_without_amazon_total(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", route_get({
        "MLA111/items": items_response([{"price": 450000}]),
        "MLA222/items": items_response([{"price": 700000}]),
    }))
    totals = tmp_path / "t.json"
    totals.write_text(json.dumps({"ssd": 100}), encoding="utf-8")  # sólo ssd tiene total
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(CATALOG, prices, totals, MEP, AFTER_SEVEN)
    items = json.loads(prices.read_text(encoding="utf-8"))["items"]
    assert items["monitor"]["verdict"] == "ml" and items["monitor"]["verdictReason"] == "existing"
    assert items["ssd"]["verdictReason"] == "precio"
    assert items["ssd"]["verdict"] == "amazon"  # 100*1000 = 100k frente a 700k: ahorro ~86%


def test_runs_once_per_day_and_not_before_seven(tmp_path, monkeypatch):
    get = Mock(side_effect=AssertionError("no debe consultar"))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    prices = tmp_path / "ml-prices.json"
    early = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)  # 07:00 ART -> ya corre
    before = datetime(2026, 10, 30, 9, 30, tzinfo=timezone.utc)  # 06:30 ART
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "t.json", MEP, before) is False
    prices.write_text(json.dumps({"date": "2026-10-30", "items": {}}), encoding="utf-8")
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "t.json", MEP, early) is False
    get.assert_not_called()


def test_without_credentials_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.delenv("ML_CLIENT_ID")
    prices = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "t.json", MEP, AFTER_SEVEN) is False
    assert not prices.exists()


def test_token_is_cached_until_expiry(monkeypatch):
    post = Mock(return_value=token_response())
    monkeypatch.setattr(ml_prices.requests, "post", post)
    assert ml_prices.get_token() == "tok"
    assert ml_prices.get_token() == "tok"
    assert post.call_count == 1


def test_link_points_to_the_cheapest_listing_with_affiliate(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", route_get({
        "MLA111/items": items_response([
            {"price": 449999, "condition": "new", "item_id": "MLA9"},
            {"price": 400000, "condition": "new", "item_id": "MLA7"},
            {"price": 300000, "condition": "used", "item_id": "MLA5"}]),
        "MLA222/items": items_response([{"price": 700000, "item_id": "no-valido"}]),
    }))
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "t.json", MEP, AFTER_SEVEN)
    items = json.loads(prices.read_text(encoding="utf-8"))["items"]
    assert items["monitor"]["price"] == 400000
    assert items["monitor"]["url"] == ("https://www.mercadolibre.com.ar/p/MLA111?pdp_filters=item_id%3AMLA7"
                                       "&matt_word=ale_benzoni&matt_tool=58527537")
    # Sin item_id válido, la ficha del producto (lista todos los vendedores).
    assert items["ssd"]["url"] == "https://www.mercadolibre.com.ar/p/MLA222?matt_word=ale_benzoni&matt_tool=58527537"


def test_merge_applies_daily_price_and_verdict(tmp_path):
    prices = tmp_path / "ml-prices.json"
    prices.write_text(json.dumps({"date": "2026-10-31", "items": {
        "monitor": {"price": 400000, "verdict": "amazon"},
        "sin-id": {"price": "x", "verdict": "amazon"}}}), encoding="utf-8")
    merged = {p["slug"]: p for p in ml_prices.merge(CATALOG, prices)}
    assert merged["monitor"]["ml"]["price"] == 400000
    assert merged["monitor"]["verdict"] == "amazon"
    assert merged["sin-id"] == CATALOG[2]
    assert CATALOG[0]["ml"]["price"] == 500000  # no muta
    assert ml_prices.merge(CATALOG, tmp_path / "no-existe.json") is CATALOG
