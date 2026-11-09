from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
import requests

import ml_prices


CATALOG = [
    {"slug": "monitor", "name": "Monitor", "store": "US", "verified": True, "verdict": "ml",
     "ml": {"price": 500000, "catalogId": "MLA111"}, "shipsToAr": {"freeShipping": True}, "image": "/p.webp", "asin": "B0MON"},
    {"slug": "ssd", "name": "SSD", "store": "US", "verified": True, "verdict": "amazon",
     "ml": {"price": 600000, "catalogId": "MLA222"}, "shipsToAr": {"freeShipping": True}, "image": "/p.webp", "asin": "B0SSD"},
    {"slug": "sin-id", "name": "Sin id", "store": "US", "verified": True, "verdict": "ml",
     "ml": {"price": 100000}},
    {"slug": "no-verificado", "name": "X", "store": "US", "verified": False, "verdict": "ml",
     "ml": {"price": 1, "catalogId": "MLA333"}},
]
# Ahorro exacto de 10%: 900 USD * 1000 ARS / 1.000.000 ARS.
MEP = 1000.0
AFTER_SEVEN = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 09:00 ART


@pytest.fixture(autouse=True)
def amazon_hoy(tmp_path):
    """08/11: ML sólo consulta lo que tiene precio de Amazon de hoy en rango. Por defecto, todos lo tienen."""
    (tmp_path / "amazon-prices.json").write_text(json.dumps({"date": "2026-10-30", "items": {
        slug: {"amount": 200.0, "currency": "USD", "checked": "2026-10-30"}
        for slug in ("monitor", "ssd", "sin-id", "no-verificado", "sin-oferta", *(f"p{i}" for i in range(10)))}}),
        encoding="utf-8")


@pytest.fixture(autouse=True)
def env(monkeypatch):
    # Los casos previos consultan productos sin estado, como el proceso de alta.
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
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
    partial = json.loads(prices.read_text(encoding="utf-8"))
    assert set(partial["items"]) == {"ssd"}
    assert partial["failed"] == ["monitor"]
    monkeypatch.setattr(ml_prices, "fetch_items", lambda _: [{"price": 700000}])
    assert ml_prices.maybe_refresh(CATALOG, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN.replace(hour=13)) is True
    assert set(json.loads(prices.read_text(encoding="utf-8"))["items"]) == {"monitor", "ssd"}


@pytest.mark.parametrize("error", [requests.HTTPError("503"), requests.ConnectionError("sin red")])
def test_failure_does_not_create_completed_slot(tmp_path, monkeypatch, error):
    monkeypatch.setattr(ml_prices, "fetch_items", Mock(side_effect=error))
    path = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(CATALOG, path, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)
    assert json.loads(path.read_text())["failed"] == ["monitor", "ssd"]
    assert not ml_prices.maybe_refresh(CATALOG, path, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)


def test_confirmed_absence_completes_slot(tmp_path, monkeypatch):
    monkeypatch.setattr(ml_prices, "fetch_items", lambda _: [])
    path = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(CATALOG, path, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)
    data = json.loads(path.read_text())
    assert data["absent"] == ["monitor", "ssd"]
    assert data["items"] == {}
    assert not ml_prices.maybe_refresh(CATALOG, path, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)


def _http_error(status, body):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    return requests.HTTPError(str(status), response=response)


def test_no_winners_404_is_absence_not_failure(monkeypatch):
    """ML responde 404 "No winners found" cuando el producto no tiene vendedores activos (05/11, 7 productos)."""
    def raise_no_winners(_path, params=None):
        raise _http_error(404, {"message": "No winners found", "error": "not_found", "status": 404, "cause": []})
    monkeypatch.setattr(ml_prices, "get_json", raise_no_winners)
    assert ml_prices.fetch_items("MLA123") == []


@pytest.mark.parametrize("status,body", [(404, {"message": "Product not found", "error": "not_found"}),
                                         (500, {"message": "No winners found", "error": "not_found"})])
def test_other_http_errors_still_fail(monkeypatch, status, body):
    def raise_error(_path, params=None):
        raise _http_error(status, body)
    monkeypatch.setattr(ml_prices, "get_json", raise_error)
    with pytest.raises(requests.HTTPError):
        ml_prices.fetch_items("MLA123")


@pytest.mark.parametrize("payload", [{}, {"results": None}, {"results": {}}, []])
def test_malformed_response_is_not_absence(monkeypatch, payload):
    monkeypatch.setattr(ml_prices, "get_json", lambda _: payload)
    with pytest.raises(ValueError):
        ml_prices.fetch_items("MLA123")


def test_merge_converts_eur_for_telegram(tmp_path):
    ml = tmp_path / "ml.json"
    amz = tmp_path / "amz.json"
    ml.write_text(json.dumps({"date": "2026-10-30", "items": {"monitor": {"price": 500000, "checked": "2026-10-30"}}}))
    amz.write_text(json.dumps({"date": "2026-10-30", "items": {
        "monitor": {"amount": 90, "currency": "EUR", "checked": "2026-10-30"}}}))
    assert ml_prices.merge(CATALOG[:1], ml, amz, MEP, 1.2, AFTER_SEVEN)[0]["amazonUsd"] == 108


def test_verdict_from_scraped_amazon_price_ignores_list_price_and_handles_es(tmp_path, monkeypatch):
    catalog = [
        {"slug": "scraped", "name": "Scraped", "store": "US", "verified": True, "asin": "B0S1", "image": "/p.webp", "verdict": "ml",
         "ml": {"price": 500000, "catalogId": "MLA111"}, "shipsToAr": {"freeShipping": True},
         "listPrice": {"amount": 400, "currency": "USD"}},
        {"slug": "solo-listprice", "name": "Solo ListPrice", "store": "US", "verified": True, "asin": "B0S2", "image": "/p.webp", "verdict": "ml",
         "ml": {"price": 500000, "catalogId": "MLA222"}, "shipsToAr": {"freeShipping": True},
         "listPrice": {"amount": 400, "sale": 250, "currency": "USD"}},
        {"slug": "espana", "name": "España", "store": "ES", "verified": True, "asin": "B0S3", "image": "/p.webp", "verdict": "amazon",
         "ml": {"price": 500000, "catalogId": "MLA444"}, "shipsToAr": {"freeShipping": True},
         "listPrice": {"amount": 200, "currency": "EUR"}},
        {"slug": "sin-fuente", "name": "Sin fuente", "store": "US", "verified": True, "asin": "B0S4", "image": "/p.webp",
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
    # 08/11: sin precio de Amazon del día no se publica, así que ML ni lo consulta (nunca usa listPrice).
    skipped = json.loads(prices.read_text(encoding="utf-8"))["skipped"]
    assert "solo-listprice" not in items and skipped["solo-listprice"] == "sin_precio_amazon_hoy"
    assert "sin-fuente" not in items and skipped["sin-fuente"] == "sin_precio_amazon_hoy"
    # Tienda ES sin tasa EUR->USD: no se puede medir el rango, no se saltea; conserva el veredicto del catálogo
    assert items["espana"]["verdict"] == "amazon"
    assert items["espana"]["verdictReason"] == "existing"
    assert "amazonSource" not in items["espana"]

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
        {"slug": "ayer", "name": "Ayer", "store": "US", "verified": True, "verdict": "ml", "asin": "B0AY", "image": "/p.webp",
         "ml": {"price": 500000, "catalogId": "MLA111"}, "shipsToAr": {"freeShipping": True}},
    ]
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", route_get({
        "MLA111/items": items_response([{"price": 500000}]),
    }))
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(catalog, prices, amazon_prices, MEP, AFTER_SEVEN)
    data = json.loads(prices.read_text(encoding="utf-8"))
    # 08/11: un precio de Amazon de ayer no alimenta nada: ML saltea el producto (no se publica sin precio de hoy).
    assert "ayer" not in data["items"] and data["skipped"]["ayer"] == "sin_precio_amazon_hoy"


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


# 2026-11-02 es día extra (EXTRA_REFRESH_DATES); 2026-10-30 es día normal.
EXTRA_MORNING = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)    # 06:00 ART
EXTRA_NOON = datetime(2026, 11, 2, 15, 30, tzinfo=timezone.utc)     # 12:30 ART
EXTRA_13 = datetime(2026, 11, 2, 16, 0, tzinfo=timezone.utc)        # 13:00 ART
EXTRA_14 = datetime(2026, 11, 2, 17, 0, tzinfo=timezone.utc)        # 14:00 ART
NORMAL_13 = datetime(2026, 10, 30, 16, 0, tzinfo=timezone.utc)      # 13:00 ART día normal


def mock_ml_get(monkeypatch):
    get = Mock(side_effect=route_get({
        "MLA111/items": items_response([{"price": 450000}]),
        "MLA222/items": items_response([{"price": 700000}]),
    }))
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    return get


def test_extra_slot_runs_once_on_extra_date_after_13_art(tmp_path, monkeypatch):
    get = mock_ml_get(monkeypatch)
    prices = tmp_path / "ml-prices.json"
    amazon = tmp_path / "amazon-prices.json"
    amazon.write_text(json.dumps({"date": "2026-11-02", "items": {
        s: {"amount": 200.0, "currency": "USD", "checked": "2026-11-02"} for s in ("monitor", "ssd")}}), encoding="utf-8")
    amazon_before = amazon.read_text(encoding="utf-8")
    # Mañana: corre y firma slot T06
    assert ml_prices.maybe_refresh(CATALOG, prices, amazon, MEP, EXTRA_MORNING) is True
    data = json.loads(prices.read_text(encoding="utf-8"))
    assert data["date"] == "2026-11-02"
    assert data["slot"] == "2026-11-02T06"
    # Antes de las 13:00 ART no corre de nuevo
    assert ml_prices.maybe_refresh(CATALOG, prices, amazon, MEP, EXTRA_NOON) is False
    # A las 13:00 ART corre una vez más y firma slot T13
    assert ml_prices.maybe_refresh(CATALOG, prices, amazon, MEP, EXTRA_13) is True
    assert json.loads(prices.read_text(encoding="utf-8"))["slot"] == "2026-11-02T13"
    # Después de las 13:00 ART no corre más ese día
    assert ml_prices.maybe_refresh(CATALOG, prices, amazon, MEP, EXTRA_14) is False
    assert get.call_count == 4  # 2 productos en la mañana + 2 en el slot extra
    # Amazon se reutiliza tal cual: el archivo no se tocó
    assert amazon.read_text(encoding="utf-8") == amazon_before


def test_no_extra_slot_on_normal_date(tmp_path, monkeypatch):
    mock_ml_get(monkeypatch)
    prices = tmp_path / "ml-prices.json"
    amazon = tmp_path / "amazon-prices.json"
    # Mañana del día normal: corre y firma slot T06
    assert ml_prices.maybe_refresh(CATALOG, prices, amazon, MEP, AFTER_SEVEN) is True
    assert json.loads(prices.read_text(encoding="utf-8"))["slot"] == "2026-10-30T06"
    # A las 13:00 ART de un día normal no hay segundo refresh
    assert ml_prices.maybe_refresh(CATALOG, prices, amazon, MEP, NORMAL_13) is False


def test_missing_slot_key_counts_as_morning_slot_of_its_date(tmp_path, monkeypatch):
    mock_ml_get(monkeypatch)
    amazon = tmp_path / "amazon-prices.json"
    # Archivo viejo sin "slot" en día normal: ya se considera corrido el slot de la mañana
    prices = tmp_path / "ml-prices.json"
    prices.write_text(json.dumps({"date": "2026-10-30", "items": {}}), encoding="utf-8")
    assert ml_prices.maybe_refresh(CATALOG, prices, amazon, MEP, NORMAL_13) is False
    # El mismo caso en día extra a las 13:30 ART dispara el slot extra
    prices_extra = tmp_path / "ml-prices-extra.json"
    prices_extra.write_text(json.dumps({"date": "2026-11-02", "items": {}}), encoding="utf-8")
    at_1330 = datetime(2026, 11, 2, 16, 30, tzinfo=timezone.utc)  # 13:30 ART
    assert ml_prices.maybe_refresh(CATALOG, prices_extra, amazon, MEP, at_1330) is True
    assert json.loads(prices_extra.read_text(encoding="utf-8"))["slot"] == "2026-11-02T13"


def test_isolated_failure_still_completes_slot(tmp_path, monkeypatch):
    """Un catalogId roto entre muchos no deja al sitio sin precios de ML: se guarda lo obtenido."""
    catalog = [{"slug": f"p{i}", "verified": True, "asin": f"B0P{i}", "image": "/p.webp", "store": "US", "ml": {"catalogId": f"MLA{i}"}} for i in range(10)]

    def fetch(catalog_id):
        if catalog_id == "MLA3":
            raise requests.HTTPError("404")
        return [{"price": 100000, "condition": "new", "id": "MLA9" + catalog_id}]

    monkeypatch.setattr(ml_prices, "fetch_items", fetch)
    monkeypatch.setattr(ml_prices, "pause", lambda: None)
    path = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(catalog, path, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)
    data = json.loads(path.read_text())
    assert data["failed"] == ["p3"] and "p3" not in data["absent"] and len(data["items"]) == 9


def test_force_adelanta_sin_repetir_slot_y_conserva_reintento(tmp_path, monkeypatch):
    now = AFTER_SEVEN.replace(hour=7)  # 04:00 ART
    path = tmp_path / "ml-prices.json"
    amazon = tmp_path / "amazon-prices.json"
    assert not ml_prices.maybe_refresh([], path, amazon, MEP, now)
    assert ml_prices.maybe_refresh([], path, amazon, MEP, now, force=True)
    data = json.loads(path.read_text())
    assert data["slot"] == "2026-10-30T06"
    assert not ml_prices.maybe_refresh([], path, amazon, MEP, now, force=True)
    data["failed"] = ["pendiente"]
    path.write_text(json.dumps(data))
    assert not ml_prices.maybe_refresh([], path, amazon, MEP, now, force=True)
    assert ml_prices.maybe_refresh([], path, amazon, MEP, now.replace(hour=8), force=True)
    assert json.loads(path.read_text())["attempts"] == 2


def test_force_consulta_productos_nuevos_despues_del_slot(tmp_path, monkeypatch):
    # 07/11: la Zotac se promovió de día (confirmar_altas) y refresh_ahora ml no la consultó porque el slot
    # de hoy ya estaba hecho: quedaba sin precio de ML hasta el día siguiente. Con force se consultan los
    # productos que el slot nunca vio, sin reconsultar los que ya tienen dato.
    consultados = []

    def fetch(catalog_id):
        consultados.append(catalog_id)
        return [{"price": 100000, "condition": "new", "id": "MLA9" + catalog_id}]

    monkeypatch.setattr(ml_prices, "fetch_items", fetch)
    monkeypatch.setattr(ml_prices, "pause", lambda: None)
    path = tmp_path / "ml-prices.json"
    amazon = tmp_path / "amazon-prices.json"
    viejo = [{"slug": "p1", "verified": True, "asin": "B0P1", "image": "/p.webp", "store": "US", "ml": {"catalogId": "MLA1"}}]
    assert ml_prices.maybe_refresh(viejo, path, amazon, MEP, AFTER_SEVEN)
    consultados.clear()
    nuevo = viejo + [{"slug": "p2", "verified": True, "asin": "B0P2", "image": "/p.webp", "store": "US", "ml": {"catalogId": "MLA2"}}]
    assert not ml_prices.maybe_refresh(nuevo, path, amazon, MEP, AFTER_SEVEN)  # sin force: horario normal
    assert ml_prices.maybe_refresh(nuevo, path, amazon, MEP, AFTER_SEVEN, force=True)
    assert consultados == ["MLA2"]
    data = json.loads(path.read_text())
    assert set(data["items"]) == {"p1", "p2"}


def test_skips_products_chrome_saw_without_free_shipping_today(tmp_path, monkeypatch):
    # 08/11 Alejandro: lo que no cumple se filtra en el paso que lo ve; ML no consulta envío pago ni sin oferta AR.
    catalog = [{**CATALOG[0], "asin": "B0PAGO"}, {**CATALOG[1], "asin": "B0GRATIS"},
               {"slug": "sin-oferta", "name": "Z", "store": "US", "verified": True, "verdict": "ml", "asin": "B0NOAR",
                "image": "/p.webp", "ml": {"price": 1, "catalogId": "MLA444"}}]
    (tmp_path / "ar-chrome-2026-10-30.json").write_text(json.dumps({"items": {
        "B0PAGO": {"ships": True, "free": False}, "B0GRATIS": {"ships": True, "free": True},
        "B0NOAR": {"ships": False, "free": None}}}), encoding="utf-8")
    get = Mock(side_effect=route_get({"MLA222/items": items_response([{"price": 700000}])}))
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    prices = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(catalog, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN) is True
    assert get.call_count == 1
    assert set(json.loads(prices.read_text(encoding="utf-8"))["items"]) == {"ssd"}


def test_chrome_skipped_products_are_not_new_on_forced_rerun(tmp_path, monkeypatch):
    # Un salteado por envío no entra en items/absent/failed: no debe contar como «nuevo» ni sumar attempts.
    catalog = [{**CATALOG[0], "asin": "B0PAGO"}, {**CATALOG[1], "asin": "B0GRATIS"}]
    (tmp_path / "ar-chrome-2026-10-30.json").write_text(json.dumps({"items": {
        "B0PAGO": {"ships": True, "free": False}, "B0GRATIS": {"ships": True, "free": True}}}), encoding="utf-8")
    get = Mock(side_effect=route_get({"MLA222/items": items_response([{"price": 700000}])}))
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    prices = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(catalog, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN, force=True) is True
    antes = prices.read_text(encoding="utf-8")
    assert ml_prices.maybe_refresh(catalog, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN, force=True) is False
    assert prices.read_text(encoding="utf-8") == antes
    assert get.call_count == 1


def test_ml_saltea_sin_precio_amazon_y_lo_consulta_cuando_aparece(tmp_path, monkeypatch, capsys):
    # 08/11: sin precio de Amazon de hoy no se publica; ML no lo consulta. Si un reintento de Amazon lo
    # recupera, la pasada siguiente (aun sin force) lo consulta. Queda el resumen de la etapa en el log.
    catalog = [CATALOG[0], CATALOG[1]]
    (tmp_path / "amazon-prices.json").write_text(json.dumps({"date": "2026-10-30", "items": {
        "ssd": {"amount": 200.0, "currency": "USD", "checked": "2026-10-30"}}}), encoding="utf-8")
    get = Mock(side_effect=route_get({"MLA111/items": items_response([{"price": 450000}]),
                                      "MLA222/items": items_response([{"price": 700000}])}))
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    prices = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(catalog, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN) is True
    data = json.loads(prices.read_text(encoding="utf-8"))
    assert set(data["items"]) == {"ssd"} and data["skipped"] == {"monitor": "sin_precio_amazon_hoy"}
    out = capsys.readouterr().out
    assert "ML_PRODUCTO slug=monitor price=ausente checked=ausente estado=omitido motivo=sin_precio_amazon_hoy" in out
    assert "ETAPA_RESUMEN ml entran=2 salteados=1 motivos_salteo=sin_precio_amazon_hoy:1 consultados=1 con_precio=1" in out
    (tmp_path / "amazon-prices.json").write_text(json.dumps({"date": "2026-10-30", "items": {
        s: {"amount": 200.0, "currency": "USD", "checked": "2026-10-30"} for s in ("ssd", "monitor")}}), encoding="utf-8")
    later = datetime(2026, 10, 30, 15, 0, tzinfo=timezone.utc)
    assert ml_prices.maybe_refresh(catalog, prices, tmp_path / "amazon-prices.json", MEP, later) is True
    assert set(json.loads(prices.read_text(encoding="utf-8"))["items"]) == {"ssd", "monitor"}
    assert get.call_count == 2


def test_ml_saltea_fuera_de_rango_y_sin_imagen(tmp_path, monkeypatch):
    catalog = [CATALOG[0], {**CATALOG[1], "image": ""}]
    (tmp_path / "amazon-prices.json").write_text(json.dumps({"date": "2026-10-30", "items": {
        s: {"amount": 450.0, "currency": "USD", "checked": "2026-10-30"} for s in ("ssd", "monitor")}}), encoding="utf-8")
    get = Mock()
    monkeypatch.setattr(ml_prices.requests, "post", Mock(return_value=token_response()))
    monkeypatch.setattr(ml_prices.requests, "get", get)
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(catalog, prices, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)
    assert get.call_count == 0
    assert json.loads(prices.read_text(encoding="utf-8"))["skipped"] == {"monitor": "amazon_fuera_de_rango", "ssd": "sin_imagen"}



def test_ml_saltea_no_publicado_en_verificacion(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PUBLICACION_MODO", "verificacion")
    get = Mock()
    monkeypatch.setattr(ml_prices.requests, "get", get)
    out = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(CATALOG[:1], out, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)
    assert json.loads(out.read_text())["skipped"] == {"monitor": "no_publicado"}
    get.assert_not_called()
    assert "ETAPA_RESUMEN ml entran=1 salteados=1 motivos_salteo=no_publicado:1" in capsys.readouterr().out


@pytest.mark.parametrize("modo,esperados", [("verificacion", {"monitor"}), ("alta", {"ssd"})])
def test_ml_consulta_solo_el_proceso_actual(tmp_path, monkeypatch, modo, esperados):
    import publicacion
    monkeypatch.setenv("PUBLICACION_MODO", modo)
    publicacion.guardar(tmp_path, {"monitor": publicacion._entrada(
        "republicacion", "2026-10-30", "", "B0MON")})
    fetch = Mock(return_value=[{"price": 700000, "id": "MLA123"}])
    monkeypatch.setattr(ml_prices, "fetch_items", fetch)
    path = tmp_path / "ml-prices.json"
    assert ml_prices.maybe_refresh(CATALOG[:2], path, tmp_path / "amazon-prices.json", MEP, AFTER_SEVEN)
    data = json.loads(path.read_text())
    assert set(data["items"]) == esperados
    assert set(data["skipped"]) == {"monitor", "ssd"} - esperados
