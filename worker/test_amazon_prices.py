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
    # Disponibilidad sin leer y sin vendedor en la caja de compra: no se puede asegurar que se pueda comprar.
    {"asin": "B01", "price": {"amount": 100, "currency": "USD"}, "availability": None, "buybox": None},
    {"asin": "B01", "price": {"amount": 100, "currency": "USD"}, "availability": None, "buybox": {"seller": None}},
])
def test_rejects_invalid_or_out_of_stock_items(bad_item):
    assert amazon_prices.valid_price(bad_item, "US") is None


def test_accepts_price_with_seller_when_availability_was_not_read():
    # Caso real 03/11 (MX Master 4): el scraper trajo precio y vendedor pero availability=null.
    item = {"asin": "B0FC5SJNQX", "price": {"amount": 118.0, "currency": "USD"}, "availability": None,
            "buybox": {"seller": {"name": "Deal B"}}}
    assert amazon_prices.valid_price(item, "US") == (118.0, "USD")


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


def test_skips_before_six_or_already_updated_or_without_url(tmp_path, monkeypatch):
    get = Mock(side_effect=AssertionError("no debe llamar al scraper"))
    monkeypatch.setattr(amazon_prices.requests, "get", get)
    out = tmp_path / "amazon-prices.json"
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]

    before = datetime(2026, 10, 30, 6, 59, tzinfo=timezone.utc)  # 03:59 ART
    assert amazon_prices.maybe_refresh(catalog, out, before) is False

    monkeypatch.setenv("AMAZON_SCRAPER_URL", "   ")
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is False

    monkeypatch.setenv("AMAZON_SCRAPER_URL", "http://scraper:8000")
    out.write_text(json.dumps({"date": "2026-10-30", "items": {}, "retried": True}), encoding="utf-8")
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
    monkeypatch.setattr(amazon_prices, "AR_SHIPPING_WEEKDAY", AFTER_SEVEN.weekday())  # día de relevamiento
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
    monkeypatch.setattr(amazon_prices, "AR_SHIPPING_WEEKDAY", AFTER_SEVEN.weekday())  # día de relevamiento
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


def test_ar_calls_agrupadas_por_store_y_con_param_store(tmp_path, monkeypatch):
    monkeypatch.setattr(amazon_prices, "AR_SHIPPING_WEEKDAY", AFTER_SEVEN.weekday())  # día de relevamiento
    monkeypatch.setenv("AMAZON_AR_URL", "http://ar:8001")
    catalog = [
        {"slug": "us-1", "asin": "B0US1", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "es-1", "asin": "B0ES1", "store": "ES", "verified": True, "ml": {"price": 1000}},
        {"slug": "us-2", "asin": "B0US2", "store": "US", "verified": True, "ml": {"price": 1000}},
    ]
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        if url.endswith("/ar-shipping"):
            return ar_response([ar_item(a, True, True) for a in params["asins"].split(",")])
        cur = "EUR" if params["country"] == "ES" else "USD"
        return bulk_response([ok_item(a, 150.5, cur) for a in params["products"].split(",")])

    monkeypatch.setattr(amazon_prices.requests, "get", fake_get)
    out = tmp_path / "amazon-prices.json"
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True

    ar_calls = [params for url, params in calls if url.endswith("/ar-shipping")]
    # Cada lote /ar-shipping lleva el store de sus ASINs y los ASINs quedan agrupados por tienda.
    por_store = {}
    for params in ar_calls:
        assert params["store"] in ("US", "ES")
        por_store.setdefault(params["store"], []).extend(params["asins"].split(","))
    assert por_store == {"US": ["B0US1", "B0US2"], "ES": ["B0ES1"]}

    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert items["us-1"]["shipsToAr"] == {"ships": True, "free": True, "checked": "2026-10-30"}
    assert items["es-1"]["shipsToAr"] == {"ships": True, "free": True, "checked": "2026-10-30"}


@pytest.mark.parametrize("ships", [None, "si", 1, 0, [True]])
def test_ar_ships_que_no_es_booleano_no_se_guarda(tmp_path, monkeypatch, ships):
    monkeypatch.setattr(amazon_prices, "AR_SHIPPING_WEEKDAY", AFTER_SEVEN.weekday())
    monkeypatch.setenv("AMAZON_AR_URL", "http://ar:8001")
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]
    item = ar_item("B01", True, True)
    item["ships"] = ships
    monkeypatch.setattr(amazon_prices.requests, "get", fake_get_router(None, [item]))
    out = tmp_path / "amazon-prices.json"
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    items = json.loads(out.read_text(encoding="utf-8"))["items"]
    assert items["p"]["amount"] == 150.5
    assert "shipsToAr" not in items["p"]  # desconocido: no se guarda nada


def test_ar_chunk_failure_does_not_break_prices(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(amazon_prices, "AR_SHIPPING_WEEKDAY", AFTER_SEVEN.weekday())  # día de relevamiento
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


def test_plausible_descarta_precio_muy_bajo_contra_lista():
    product = {"listPrice": {"amount": 459.99, "currency": "USD"}}
    assert not amazon_prices.plausible((21.0, "USD"), product)
    assert amazon_prices.plausible((378.0, "USD"), product)


def test_plausible_sin_lista_o_otra_moneda_acepta():
    assert amazon_prices.plausible((21.0, "USD"), {})
    assert amazon_prices.plausible((21.0, "USD"), {"listPrice": {"amount": 459.99, "currency": "EUR"}})


def test_ar_shipping_off_day_only_surveys_unconfirmed(tmp_path, monkeypatch):
    # 30/10/2026 es viernes: fuera del lunes sólo se releva lo que no tiene envío confirmado (catálogo o caché).
    catalog = [
        {"slug": "catalogo", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}, "shipsToAr": {"freeShipping": True, "checked": "2026-10-01"}},
        {"slug": "cache", "asin": "B02", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "sin-dato", "asin": "B03", "store": "US", "verified": True, "ml": {"price": 1000}},
    ]
    out = tmp_path / "amazon-prices.json"
    out.write_text(json.dumps({"date": "2026-10-29", "items": {}, "arShipping": {"cache": {"ships": True, "free": True, "checked": "2026-10-27"}}}), encoding="utf-8")
    monkeypatch.setattr(amazon_prices, "scraper_url", lambda: "http://scraper")
    monkeypatch.setattr(amazon_prices, "ar_url", lambda: "http://ar")
    monkeypatch.setattr(amazon_prices, "pause", lambda: None)
    monkeypatch.setattr(amazon_prices, "fetch_bulk", lambda base, asins, store: {a: {"asin": a, "price": {"amount": 150.5, "currency": "USD"}, "availability": {"is_in_stock": True}} for a in asins})
    pedidos = []
    def ar(base, asins, store):
        pedidos.append(list(asins))
        return {a: {"asin": a, "ships": True, "free": True} for a in asins}
    monkeypatch.setattr(amazon_prices, "fetch_ar_shipping", ar)
    assert AFTER_SEVEN.weekday() != amazon_prices.AR_SHIPPING_WEEKDAY
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    assert pedidos == [["B03"]]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert set(data["arShipping"]) == {"cache", "sin-dato"}

def test_retry_only_missing_once_after_retry_time(tmp_path, monkeypatch):
    catalog = [
        {"slug": "ya", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}},
        {"slug": "falta", "asin": "B02", "store": "US", "verified": True, "ml": {"price": 1000}},
    ]
    out = tmp_path / "amazon-prices.json"
    out.write_text(json.dumps({"date": "2026-10-30", "items": {"ya": {"amount": 10, "currency": "USD", "checked": "2026-10-30"}}}), encoding="utf-8")
    monkeypatch.setattr(amazon_prices, "scraper_url", lambda: "http://scraper")
    monkeypatch.setattr(amazon_prices, "pause", lambda: None)
    pedidos = []
    def fetch(base, asins, store):
        pedidos.append(list(asins))
        return {"B02": {"asin": "B02", "price": {"amount": 20.0, "currency": "USD"}, "availability": {"is_in_stock": True}}}
    monkeypatch.setattr(amazon_prices, "fetch_bulk", fetch)
    antes = datetime(2026, 10, 30, 7, 30, tzinfo=timezone.utc)  # 04:30 ART: todavía no
    assert amazon_prices.maybe_refresh(catalog, out, antes) is False
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    assert pedidos == [["B02"]]  # sólo el faltante
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["retried"] is True
    assert data["items"]["ya"]["amount"] == 10 and data["items"]["falta"] == {"amount": 20.0, "currency": "USD", "checked": "2026-10-30"}
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is False  # una sola vez por día
    assert pedidos == [["B02"]]


@pytest.mark.parametrize("checked,kept", [
    ("2026-10-29", True),
    ("2026-10-16", True),  # exactamente 14 días ART
    ("2026-10-15", False),
    ("2026-10-31", False),
    ("2026-02-30", False),
    (None, False),
])
def test_ar_shipping_carry_over_and_expiry(tmp_path, monkeypatch, checked, kept):
    out = tmp_path / "amazon-prices.json"
    ar = {"ships": False, "free": None, "checked": checked}
    out.write_text(json.dumps({
        "date": "2026-10-29",
        "arShipping": {"p": ar},
        "items": {"p": {"amount": 100, "currency": "USD", "checked": "2026-10-29"}},
    }), encoding="utf-8")
    monkeypatch.setattr(amazon_prices.requests, "get", Mock(side_effect=requests.ConnectionError("caído")))
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]
    # Ya es 31/10 UTC, pero sigue siendo 30/10 ART.
    now = datetime(2026, 10, 31, 2, 0, tzinfo=timezone.utc)
    assert amazon_prices.maybe_refresh(catalog, out, now) is True
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["date"] == "2026-10-30"
    assert data["arShipping"] == ({"p": ar} if kept else {})
    assert data["items"] == {}  # nunca se conservan precios de ayer


@pytest.mark.parametrize("ships", [True, False, None, "si", 1])
def test_ar_shipping_updates_only_with_real_survey(tmp_path, monkeypatch, ships):
    monkeypatch.setattr(amazon_prices, "AR_SHIPPING_WEEKDAY", AFTER_SEVEN.weekday())
    monkeypatch.setenv("AMAZON_AR_URL", "http://ar:8001")
    old = {"ships": True, "free": True, "checked": "2026-10-29"}
    out = tmp_path / "amazon-prices.json"
    out.write_text(json.dumps({"date": "2026-10-29", "items": {}, "arShipping": {"p": old}}), encoding="utf-8")
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]
    monkeypatch.setattr(amazon_prices.requests, "get", fake_get_router(None, [ar_item("B01", ships, None)]))
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    data = json.loads(out.read_text(encoding="utf-8"))
    if isinstance(ships, bool):
        expected = {"ships": ships, "free": None, "checked": "2026-10-30"}
        assert data["arShipping"] == {"p": expected}
        assert data["items"]["p"]["shipsToAr"] == expected
    else:
        assert data["arShipping"] == {"p": old}
        assert "shipsToAr" not in data["items"]["p"]


def test_retry_keeps_ar_shipping_and_merges_todays_survey(tmp_path, monkeypatch):
    old = {"ships": False, "free": None, "checked": "2026-10-16"}
    today = {"ships": True, "free": True, "checked": "2026-10-30"}
    out = tmp_path / "amazon-prices.json"
    out.write_text(json.dumps({
        "date": "2026-10-30",
        "items": {"hoy": {"shipsToAr": today}},
        "arShipping": {"p": old, "hoy": old, "vencido": {**old, "checked": "2026-10-15"}},
    }), encoding="utf-8")
    catalog = [{"slug": "p", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}}]
    monkeypatch.setattr(amazon_prices.requests, "get", fake_get_router(None, []))
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["retried"] is True
    assert data["arShipping"] == {"p": old, "hoy": today}
    assert data["items"]["p"] == {"amount": 150.5, "currency": "USD", "checked": "2026-10-30"}


def test_each_missing_product_logs_its_reason_and_daily_file(tmp_path, monkeypatch, capsys):
    # 03/11: el log sólo decía «faltantes=41» y se perdía al recrear el contenedor.
    catalog = [
        {"slug": "ok", "asin": "B01", "store": "US", "verified": True, "ml": {"price": 1000}, "shipsToAr": {"freeShipping": True, "checked": "2026-10-01"}},
        {"slug": "vacio", "asin": "B02", "store": "US", "verified": True, "ml": {"price": 1000}, "shipsToAr": {"freeShipping": True, "checked": "2026-10-01"}},
        {"slug": "agotado", "asin": "B03", "store": "US", "verified": True, "ml": {"price": 1000}, "shipsToAr": {"freeShipping": True, "checked": "2026-10-01"}},
    ]
    monkeypatch.setattr(amazon_prices, "scraper_url", lambda: "http://scraper")
    monkeypatch.setattr(amazon_prices, "ar_url", lambda: "")
    monkeypatch.setattr(amazon_prices, "fetch_bulk", lambda base, asins, store: {
        "B01": {"asin": "B01", "price": {"amount": 10.0, "currency": "USD"}, "availability": {"is_in_stock": True}},
        "B02": {"asin": "B02", "title": "x", "price": None, "buybox": None, "availability": None},
        "B03": {"asin": "B03", "price": {"amount": 10.0, "currency": "USD"}, "availability": {"is_in_stock": False}},
    })
    out = tmp_path / "amazon-prices.json"
    assert amazon_prices.maybe_refresh(catalog, out, AFTER_SEVEN) is True
    printed = capsys.readouterr().out
    assert "sin precio vacio (pos 2, sin_precio_ni_vendedor)" in printed
    assert "sin precio agotado (pos 3, sin_stock)" in printed
    log = json.loads((tmp_path / "amazon-run-2026-10-30.json").read_text(encoding="utf-8"))
    assert log["passes"][0]["kind"] == "corrida" and log["passes"][0]["ok"] == 1
    assert [f["motivo"] for f in log["passes"][0]["fallas"]] == ["sin_precio_ni_vendedor", "sin_stock"]


def test_pace_adjusts_itself():
    base = {"pause_s": 60.0, "limpios": 0}
    rafaga = {"rafaga": True, "fallas": 30}
    limpio = {"rafaga": False, "fallas": 0}
    assert amazon_prices.adjust_pace(base, rafaga)["pause_s"] == 120.0
    assert amazon_prices.adjust_pace({"pause_s": 150.0, "limpios": 2}, rafaga)["pause_s"] == amazon_prices.PAUSE_MAX
    p = base
    for _ in range(3):
        p = amazon_prices.adjust_pace(p, limpio)
    assert p == {"pause_s": 45.0, "limpios": 0}
    assert amazon_prices.adjust_pace({"pause_s": 30.0, "limpios": 2}, limpio)["pause_s"] == amazon_prices.PAUSE_MIN
    assert amazon_prices.adjust_pace({"pause_s": 60.0, "limpios": 2}, {"rafaga": False, "fallas": 3}) == {"pause_s": 60.0, "limpios": 0}


def test_run_summary_detects_burst(monkeypatch):
    monkeypatch.setattr(amazon_prices, "failures", [{"pos": p, "motivo": "sin_precio_ni_vendedor"} for p in (60, 70, 80, 90, 100)])
    s = amazon_prices.run_summary(95, 100)
    assert s["rafaga"] is True and s["motivos"] == {"sin_precio_ni_vendedor": 5} and s["primeraFallaPos"] == 60
    monkeypatch.setattr(amazon_prices, "failures", [{"pos": p, "motivo": "sin_precio_ni_vendedor"} for p in (2, 5, 9, 12, 70)])
    assert amazon_prices.run_summary(95, 100)["rafaga"] is False
