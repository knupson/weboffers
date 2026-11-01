from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
import requests

import ml_prices


CATALOG = [
    {"slug": "monitor", "name": "Monitor", "store": "US", "verified": True, "verdict": "ml",
     "ml": {"price": 500000, "catalogId": "MLA111"}, "shipsToAr": {"freeShipping": True}},
    {"slug": "ssd", "name": "SSD", "store": "US", "verified": True, "verdict": "amazon",
     "ml": {"price": 600000, "catalogId": "MLA222"}, "shipsToAr": {"freeShipping": True}},
    {"slug": "sin-id", "name": "Sin id", "store": "US", "verified": True, "verdict": "ml",
     "ml": {"price": 100000}},
    {"slug": "no-verificado", "name": "X", "store": "US", "verified": False, "verdict": "ml",
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


def test_amazon_formula_matches_site_inputs_including_100_50_boundary():
    # Mismos valores que en src/lib/calc/calc.test.ts (<100 con envío 45, caso borde 100.50 de IVA, 100..400, >400).
    assert [ml_prices.amazon_total_usd(u) for u in (80, 100.5, 250, 550)] == [154.45, 125.63, 312.5, 756.47]
    assert [ml_prices.estimate_from_amazon(u, 1200) for u in (80, 100.5, 250, 550)] == [185340, 150756, 375000, 907764]


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
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN) is True
    assert get.call_count == 2
    data = json.loads(prices.read_text(encoding="utf-8"))
    assert set(data["items"]) == {"monitor", "ssd"}
    assert data["date"] == "2026-10-30"


def test_omits_product_when_items_call_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", route_get({
        "MLA111/items": requests.ConnectionError("caído"),
        "MLA222/items": items_response([{"price": 700000, "condition": "new"}]),
    }))
    prices = tmp_path / "ml-prices.json"
    previous = {"generatedAt": "2026-10-29T10:00:00+00:00", "date": "2026-10-29", "items": {
        "monitor": {"price": 480000, "checked": "2026-10-29", "verdict": "ml", "verdictReason": "precio"}}}
    prices.write_text(json.dumps(previous), encoding="utf-8")
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN) is True
    items = json.loads(prices.read_text(encoding="utf-8"))["items"]
    assert "monitor" not in items
    assert items["ssd"]["price"] == 700000


def test_verdict_from_scraped_amazon_price_ignores_list_price_and_handles_es(tmp_path, monkeypatch):
    catalog = [
        {"slug": "scraped", "name": "Scraped", "store": "US", "verified": True, "verdict": "ml",
         "ml": {"price": 500000, "catalogId": "MLA111"}, "shipsToAr": {"freeShipping": True},
         "listPrice": {"amount": 400, "currency": "USD"}},
        {"slug": "solo-listprice", "name": "Solo ListPrice", "store": "US", "verified": True, "verdict": "ml",
         "ml": {"price": 500000, "catalogId": "MLA222"}, "shipsToAr": {"freeShipping": True},
         "listPrice": {"amount": 400, "sale": 250, "currency": "USD"}},
        {"slug": "espana", "name": "España", "store": "ES", "verified": True, "verdict": "amazon",
         "ml": {"price": 500000, "catalogId": "MLA444"}, "shipsToAr": {"freeShipping": True},
         "listPrice": {"amount": 200, "currency": "EUR"}},
        {"slug": "sin-fuente", "name": "Sin fuente", "store": "US", "verified": True,
         "ml": {"price": 500000, "catalogId": "MLA555"}, "shipsToAr": {"freeShipping": True}},
    ]
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", route_get({
        "MLA111/items": items_response([{"price": 500000}]),
        "MLA222/items": items_response([{"price": 500000}]),
        "MLA444/items": items_response([{"price": 500000}]),
        "MLA555/items": items_response([{"price": 500000}]),
    }))
    amazon_prices = tmp_path / "amazon-prices.json"
    amazon_prices.write_text(json.dumps({"date": "2026-10-30", "items": {
        "scraped": {"amount": 250, "currency": "USD", "checked": "2026-10-30"},
        "espana": {"amount": 180, "currency": "EUR", "checked": "2026-10-30"},
    }}), encoding="utf-8")
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(catalog, prices, amazon_prices, MEP, AFTER_SEVEN)
    items = json.loads(prices.read_text(encoding="utf-8"))["items"]
    # 250 USD -> total 312.50 USD -> 312.500 ARS (~310.000 ARS) vs 500.000 ARS -> gana amazon
    assert items["scraped"]["verdict"] == "amazon"
    assert items["scraped"]["verdictReason"] == "precio"
    assert items["scraped"]["amazonSource"] == "amazon"
    # Sin precio scrapeado del día, nunca usa listPrice
    assert items["solo-listprice"]["verdict"] == "ml"
    assert items["solo-listprice"]["verdictReason"] == "existing"
    assert "amazonSource" not in items["solo-listprice"]
    # Tienda ES sin tasa EUR->USD: conserva el veredicto del catálogo
    assert items["espana"]["verdict"] == "amazon"
    assert items["espana"]["verdictReason"] == "existing"
    assert "amazonSource" not in items["espana"]
    # Sin scrapeado ni veredicto en catálogo: cae a "ml"
    assert items["sin-fuente"]["verdict"] == "ml"
    assert items["sin-fuente"]["verdictReason"] == "existing"

    # Con tasa EUR/USD, los productos de España calculan su veredicto desde el precio scrapeado del día.
    prices_es = tmp_path / "ml-prices-es.json"
    ml_prices.maybe_refresh(catalog, prices_es, amazon_prices, MEP, AFTER_SEVEN, eur_usd=1.25)
    items_es = json.loads(prices_es.read_text(encoding="utf-8"))["items"]
    # 180 EUR * 1.25 = 225 USD -> 281.250 ARS (~280.000 ARS) vs 500.000 ARS -> gana amazon
    assert items_es["espana"]["verdict"] == "amazon"
    assert items_es["espana"]["verdictReason"] == "precio"
    assert items_es["espana"]["amazonSource"] == "amazon"


def test_runs_once_per_day_and_not_before_six(tmp_path, monkeypatch):
    get = Mock(side_effect=AssertionError("no debe consultar"))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    prices = tmp_path / "ml-prices.json"
    early = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)  # 07:00 ART -> ya corre
    before = datetime(2026, 10, 30, 8, 30, tzinfo=timezone.utc)  # 05:30 ART
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "amazon-prices.json", MEP, before) is False
    prices.write_text(json.dumps({"date": "2026-10-30", "items": {}}), encoding="utf-8")
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "amazon-prices.json", MEP, early) is False
    get.assert_not_called()


def test_without_credentials_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.delenv("ML_CLIENT_ID")
    prices = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN) is False
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
    ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)
    items = json.loads(prices.read_text(encoding="utf-8"))["items"]
    assert items["monitor"]["price"] == 400000
    assert items["monitor"]["url"] == ("https://www.mercadolibre.com.ar/p/MLA111?pdp_filters=item_id%3AMLA7"
                                       "&matt_word=ale_benzoni&matt_tool=58527537")
    # Sin item_id válido, la ficha del producto (lista todos los vendedores).
    assert items["ssd"]["url"] == "https://www.mercadolibre.com.ar/p/MLA222?matt_word=ale_benzoni&matt_tool=58527537"


def test_merge_applies_daily_price_and_verdict(tmp_path):
    prices = tmp_path / "ml-prices.json"
    prices.write_text(json.dumps({"date": "2026-10-31", "items": {
        "monitor": {"price": 400000, "verdict": "amazon", "amazonSource": "amazon"},
        "sin-id": {"price": "x", "verdict": "amazon"}}}), encoding="utf-8")
    merged = {p["slug"]: p for p in ml_prices.merge(CATALOG, prices)}
    assert merged["monitor"]["ml"]["price"] == 400000
    assert merged["monitor"]["verdict"] == "amazon"
    assert merged["monitor"]["amazonSource"] == "amazon"
    assert merged["sin-id"] == CATALOG[2]
    assert CATALOG[0]["ml"]["price"] == 500000  # no muta
    assert ml_prices.merge(CATALOG, tmp_path / "no-existe.json") is CATALOG


def test_load_amazon_prices_accepts_only_today_checked(tmp_path, monkeypatch):
    amazon_prices = tmp_path / "amazon-prices.json"
    amazon_prices.write_text(json.dumps({"date": "2026-10-30", "items": {
        "hoy": {"amount": 250, "currency": "USD", "checked": "2026-10-30"},
        "ayer": {"amount": 250, "currency": "USD", "checked": "2026-10-29"},
        "sin-fecha": {"amount": 250, "currency": "USD"},
    }}), encoding="utf-8")
    loaded = ml_prices.load_amazon_prices(amazon_prices, AFTER_SEVEN)
    assert set(loaded) == {"hoy"}

    # En maybe_refresh un precio del día anterior no alimenta el veredicto.
    catalog = [
        {"slug": "ayer", "name": "Ayer", "store": "US", "verified": True, "verdict": "ml",
         "ml": {"price": 500000, "catalogId": "MLA111"}, "shipsToAr": {"freeShipping": True}},
    ]
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", route_get({
        "MLA111/items": items_response([{"price": 500000}]),
    }))
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(catalog, prices, amazon_prices, MEP, AFTER_SEVEN)
    items = json.loads(prices.read_text(encoding="utf-8"))["items"]
    assert items["ayer"]["verdict"] == "ml"
    assert items["ayer"]["verdictReason"] == "existing"
    assert "amazonSource" not in items["ayer"]


def test_cheapest_new_skips_international_listings():
    results = [
        {"price": 47243, "condition": "new", "item_id": "MLA1", "tags": ["cbt_item"],
         "shipping": {"tags": ["cbt_fulfillment"]}, "international_delivery_mode": "none"},
        {"price": 50000, "condition": "new", "item_id": "MLA2", "shipping": {"tags": ["cbt_fulfillment"]}},
        {"price": 60000, "condition": "new", "item_id": "MLA3", "international_delivery_mode": "intl"},
        {"price": 70000, "condition": "new", "item_id": "MLA4", "tags": ["good_quality_picture"],
         "shipping": {"tags": ["mandatory_free_shipping"]}, "international_delivery_mode": "none"},
    ]
    assert ml_prices.cheapest_new(results) == (70000, "MLA4")
    assert ml_prices.cheapest_new(results[:3]) is None


def test_verdict_without_confirmed_shipping_has_no_winner():
    assert ml_prices.verdict_from_ars(2600000, 1680000, None) == "sin_envio"
    assert ml_prices.verdict_from_ars(2600000, 1680000, True) == "amazon"
    assert ml_prices.verdict_from_ars(300000, 310000, None) == "ml"
