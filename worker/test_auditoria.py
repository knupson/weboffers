"""Regresiones de frescura, variantes, reintentos y retención, sin red."""
from datetime import datetime, timedelta, timezone
import io
import json
import os
from unittest.mock import Mock

import pytest
import requests

import amazon_prices as amazon
import ml_prices as ml
import publish
import rates
import worker
from variants import variant_conflicts


@pytest.mark.parametrize("a,b,key", [
    ("Keyboard blue switches", "Teclado switches brown", "switch"),
    ("Keyboard tactile", "Keyboard linear", "switch"),
    ("SSD 1TB", "SSD 512 GB", "capacidad"),
    ('Monitor 27"', "Monitor 24 pulgadas", "pulgadas"),
    ("Watch 40mm", "Watch 44 mm", "mm"),
    ("Mouse con cable", "Mouse inalámbrico", "conexion"),
    ("Mouse Black", "Mouse blanco", "color"),
    ("Keyboard TKL", "Teclado full size", "layout"),
    ("Keyboard TKL", "Teclado 60%", "layout"),
])
def test_variant_conflicts(a, b, key):
    assert key in variant_conflicts(a, b)
    assert variant_conflicts(a, b) == variant_conflicts(b, a)
    from tools.match_candidates import evaluate
    status, reason, _ = evaluate({"amazonTitle": a}, {"name": b}, {}, 1000)
    if key == "color":   # 05/11: el color no rechaza el par (no es otro producto)
        assert reason != "variante"
    else:
        assert (status, reason) == ("rejected", "variante")


@pytest.mark.parametrize("a,b", [
    ("SSD 1TB black", "SSD 1000 GB negro"),
    ("Mouse wireless black", "Mouse"),
    ("Keyboard red switches black", "Teclado linear negro"),
    ("Headset Blue Voice", "Headset"),
])
def test_equivalent_or_unspecified_variant(a, b):
    assert not variant_conflicts(a, b)


@pytest.mark.parametrize("currency,accepted", [("USD", False), (None, False), ("ARS", True)])
def test_ml_currency(currency, accepted):
    assert bool(ml.cheapest_new([{"price": 500, "currency_id": currency}])) is accepted
    assert ml.cheapest_new([{"price": 500}])


def test_ml_partial_hourly_retries_keep_successes(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "is_configured", lambda: True)
    monkeypatch.setattr(ml, "pause", lambda: None)
    fetch = Mock(side_effect=lambda cid: [{"price": 500}] if cid == "OK" else (_ for _ in ()).throw(requests.ConnectionError()))
    monkeypatch.setattr(ml, "fetch_items", fetch)
    catalog = [{"slug": s, "verified": True, "ml": {"catalogId": s}} for s in ("OK", "FAIL")]
    path = tmp_path / "ml-prices.json"
    now = datetime(2026, 11, 5, 6, tzinfo=ml.ART)
    assert ml.maybe_refresh(catalog, path, tmp_path / "amazon.json", 1000, now)
    assert not ml.maybe_refresh(catalog, path, tmp_path / "amazon.json", 1000, now)
    for hour in (7, 8):
        assert ml.maybe_refresh(catalog, path, tmp_path / "amazon.json", 1000, now.replace(hour=hour))
    assert not ml.maybe_refresh(catalog, path, tmp_path / "amazon.json", 1000, now.replace(hour=9))
    data = json.loads(path.read_text())
    assert data["items"]["OK"]["catalogId"] == "OK"
    assert data["failed"] == ["FAIL"] and data["attempts"] == 3
    assert [c.args[0] for c in fetch.call_args_list] == ["OK", "FAIL", "FAIL", "FAIL"]


def test_amazon_three_delayed_retries_only_pending(tmp_path, monkeypatch):
    path = tmp_path / "amazon-prices.json"
    previous = {"date": "2026-11-05", "items": {"ok": {"amount": 150, "currency": "USD"}}}
    catalog = [{"slug": s, "asin": s, "store": "US", "shipsToAr": {"freeShipping": True, "checked": previous["date"]}} for s in ("ok", "pending")]
    fetch = Mock(return_value=({}, 0, 1))
    monkeypatch.setattr(amazon, "fetch_prices", fetch)
    monkeypatch.setattr(amazon, "refresh_ar_shipping", lambda *a, **k: {})
    for hour, minute, expected in [(4, 59, False), (5, 0, True), (5, 59, False), (6, 0, True), (7, 29, False), (7, 30, True), (9, 0, False)]:
        now = datetime(2026, 11, 5, hour, minute, tzinfo=amazon.ART)
        assert amazon.retry_missing(previous, catalog, path, now, "scraper") is expected
        if expected:
            previous = json.loads(path.read_text())
    assert fetch.call_count == 3
    assert all([p["slug"] for p in c.args[1]] == ["pending"] for c in fetch.call_args_list)
    assert previous["items"]["ok"]["amount"] == 150


def test_amazon_budget_persists_and_blocks_before_http(tmp_path, monkeypatch):
    monkeypatch.setattr(amazon, "_budget_path", None)
    monkeypatch.setattr(amazon, "_budget_day", None)
    monkeypatch.setenv("AMAZON_DAILY_MAX_PAGES", "2")
    amazon.configure_budget(tmp_path / "amazon-prices.json", "2026-11-05")
    amazon.charge_pages(2)
    http = Mock()
    monkeypatch.setattr(amazon.requests, "get", http)
    amazon.configure_budget(tmp_path / "amazon-prices.json", "2026-11-05")
    with pytest.raises(ValueError, match="Presupuesto"):
        amazon.fetch_bulk("scraper", ["A"], "US")
    http.assert_not_called()
    amazon.configure_budget(tmp_path / "amazon-prices.json", "2026-11-06")
    amazon.charge_pages(1)


@pytest.mark.parametrize("days,valid", [(0, True), (2, True), (4, False)])
def test_rates_preserve_provider_date(monkeypatch, days, valid):
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    monkeypatch.setattr(rates.requests, "get", Mock(return_value=Mock(json=lambda: {"venta": 1000, "fechaActualizacion": stamp})))
    result = rates.get_rates()
    assert bool(result) is valid
    if valid:
        assert result["fetchedAt"] == stamp
    assert bool(rates.get_eur_usd(1000)) is valid


@pytest.mark.parametrize("name", ["ml-prices.json", "amazon-prices.json"])
def test_price_history_retains_sixty_days(tmp_path, name):
    publish.write_atomic(tmp_path / name, {"date": "2026-09-06", "items": {}})
    publish.write_atomic(tmp_path / name, {"date": "2026-09-07", "items": {}})
    publish.write_atomic(tmp_path / name, {"date": "2026-11-05", "items": {"new": 1}})
    history = tmp_path / "historial"
    assert not (history / f"2026-09-06-{name}").exists()
    assert (history / f"2026-09-07-{name}").exists()
    assert json.loads((history / f"2026-11-05-{name}").read_text())["items"] == {"new": 1}


def test_daily_log_purges_on_day_change(tmp_path, monkeypatch):
    log = worker.DailyLog(tmp_path, io.StringIO())
    purge = Mock(wraps=log._purge)
    monkeypatch.setattr(log, "_purge", purge)
    next_day = log._now_art() + timedelta(days=1)
    monkeypatch.setattr(log, "_now_art", lambda: next_day)
    old = tmp_path / "worker-2020-01-01.log"
    old.write_text("viejo")
    os.utime(old, (0, 0))
    log.write("nuevo\n")
    log.write("otro\n")
    purge.assert_called_once()
    assert not old.exists()


def test_capacidad_compara_la_mayor_no_la_ram():
    from variants import variant_conflicts
    assert variant_conflicts("Lenovo Idea Tab 11 | 128GB, WiFi", "Lenovo Idea Tab 11 8 GB RAM 128 GB") == []
    assert variant_conflicts("Seagate 8TB BarraCuda", "Seagate 8tb Barracuda 256mb") == []
    assert variant_conflicts("Redmi Pad 2 (256GB + 8GB)", "Redmi Pad 2 256gb 8 Ram") == []
    assert variant_conflicts("Galaxy Tab 128GB", "Galaxy Tab 256GB") == ["capacidad"]


def test_ml_no_publica_pares_con_variante_funcional_distinta():
    import ml_prices
    g915 = {"slug": "g915", "amazonTitle": "Logitech G915 X Lightspeed Wireless Keyboard, Clicky",
            "ml": {"name": "Teclado Logitech G915 X Inalámbrico GL Tactile"}}
    assert ml_prices.functional_conflicts(g915, {}) == ["switch"]
    color = {"slug": "xm6", "amazonTitle": "Sony WH-1000XM6, Black", "ml": {"name": "Sony WH-1000XM6 Rosa"}}
    assert ml_prices.functional_conflicts(color, {}) == []
    hoy = {"g915": {"title": "Logitech G915 X Lightspeed Wireless Keyboard, Tactile"}}
    assert ml_prices.functional_conflicts(g915, hoy) == []  # manda el título de hoy


def test_dockerfile_copia_todos_los_modulos_del_worker():
    """05/11: variants.py nuevo no entró en la imagen y el worker quedó reiniciándose en bucle."""
    import ast
    import pathlib
    here = pathlib.Path(__file__).resolve().parent
    copiados = set(next(l for l in (here / "Dockerfile").read_text().splitlines() if l.startswith("COPY")).split()[1:-1])
    pendientes, vistos = ["worker.py"], set()
    while pendientes:
        f = pendientes.pop()
        if f in vistos:
            continue
        vistos.add(f)
        for node in ast.walk(ast.parse((here / f).read_text(encoding="utf-8"))):
            nombres = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for n in nombres:
                if (here / f"{n}.py").exists():
                    pendientes.append(f"{n}.py")
    faltan = vistos - copiados
    assert not faltan, f"faltan en el COPY del Dockerfile: {sorted(faltan)}"


def test_envio_de_otra_oferta_no_confirma():
    import amazon_prices as a
    precio = {"amount": 100.0}
    assert a.offer_mismatch({"ships": True, "free": True, "price": 104.0, "condition": "New"}, precio) is None
    assert a.offer_mismatch({"ships": True, "free": True, "price": 70.0, "condition": "New"}, precio) == "oferta_distinta"
    assert a.offer_mismatch({"ships": True, "free": True, "price": 100.0, "condition": "Used - Good"}, precio).startswith("condicion")
    assert a.offer_mismatch({"ships": True, "free": True}, precio) is None  # sin datos de oferta: como antes


def test_envio_ar_usa_el_relevamiento_del_chrome(tmp_path, monkeypatch):
    """05/11: amazon-ar bloqueado por Amazon; el Chrome anónimo de la VM releva y el worker lo usa primero."""
    import json
    import amazon_prices as a
    prices = tmp_path / "amazon-prices.json"
    (tmp_path / "ar-chrome-2026-11-05.json").write_text(json.dumps({"items": {
        "B1": {"ships": True, "free": True, "text": "FREE delivery Mon, Nov 16 to Argentina"},
        "B2": {"ships": None, "free": None, "motivo": "error:TimeoutError"}}}), encoding="utf-8")
    llamados = []
    monkeypatch.setattr(a, "ar_url", lambda: "http://ar")
    monkeypatch.setattr(a, "pause", lambda: None)
    monkeypatch.setattr(a.time, "sleep", lambda s: None)

    def fake(base, asins, store):
        llamados.append(list(asins))
        return {x: {"asin": x, "ships": False, "free": None} for x in asins}
    monkeypatch.setattr(a, "fetch_ar_shipping", fake)
    items = {}
    productos = [{"slug": "s1", "asin": "B1", "store": "US"}, {"slug": "s2", "asin": "B2", "store": "US"}]
    a.refresh_ar_shipping(productos, items, "2026-11-05", prices)
    assert items["s1"]["shipsToAr"] == {"ships": True, "free": True, "checked": "2026-11-05"}
    assert llamados == [["B2"]]  # sólo lo que el Chrome no pudo leer va al servicio


def test_interpretar_texto_del_chrome():
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location("envio_ar_chrome", pathlib.Path(__file__).resolve().parent.parent / "tools" / "envio_ar_chrome.py")
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except ModuleNotFoundError:  # websockets sólo existe en el contenedor de Chrome
        import pytest
        pytest.skip("sin websockets")
    ar = "Deliver to Argentina"
    assert mod.interpretar({"deliver": ar, "buybox": True, "envio": "FREE delivery Mon, Nov 16 to Argentina", "precio": "$10", "titulo": "x"})["free"] is True
    assert mod.interpretar({"deliver": ar, "buybox": True, "envio": "Delivery Monday, November 16 to Argentina", "precio": "$10", "titulo": "x"}) == {
        "ships": True, "free": False, "text": "Delivery Monday, November 16 to Argentina", "motivo": None, "precio": "$10"}
    # 05/11: texto de envío sin precio en el recuadro = no confirma; sin recuadro = desconocido.
    assert mod.interpretar({"deliver": ar, "buybox": True, "envio": "FREE delivery to Argentina", "titulo": "x"})["ships"] is None
    assert mod.interpretar({"deliver": ar, "buybox": False, "envio": "FREE delivery to Argentina", "precio": "$1"})["ships"] is None
    assert mod.interpretar({"deliver": ar, "buybox": True, "sinOferta": "See All Buying Options", "titulo": "x"})["ships"] is False
    assert mod.interpretar({"deliver": ar, "sinOferta": "See All Buying Options", "titulo": "x"})["ships"] is False
    assert mod.interpretar({"deliver": "Deliver to 10001", "envio": "FREE delivery"})["ships"] is None
    assert mod.interpretar({"deliver": ar, "captcha": True})["motivo"] == "captcha"
    # 07/11: la página «Click the button below to continue shopping» no es «ubicación no AR».
    assert mod.interpretar({"deliver": "", "intersticial": True, "titulo": ""})["motivo"] == "intersticial"


def test_chrome_aprieta_continue_shopping_y_recarga_en_ingles():
    # 07/11 (autorizado por Alejandro): Amazon muestra a veces la página intermedia; se aprieta el botón
    # y se vuelve a cargar el producto con language=en_US (después del clic la página salía en castellano).
    import asyncio
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location("envio_ar_chrome", pathlib.Path(__file__).resolve().parent.parent / "tools" / "envio_ar_chrome.py")
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except ModuleNotFoundError:
        import pytest
        pytest.skip("sin websockets")
    mod.ESPERA_CARGA = 0
    lecturas = iter([{"intersticial": True, "titulo": ""}, {"deliver": "Deliver to Argentina", "titulo": "SSD"}])
    llamadas = []

    class FakeCdp:
        async def call(self, method, params=None, session=None, timeout=30):
            llamadas.append((method, params))
            if method == "Runtime.evaluate" and params["expression"] == mod.LEER:
                import json
                return {"result": {"value": json.dumps(next(lecturas))}}
            return {"result": {"value": True}}

    d = asyncio.run(mod.leer_producto(FakeCdp(), "s", "B1"))
    assert d["titulo"] == "SSD"
    navegaciones = [p["url"] for m, p in llamadas if m == "Page.navigate"]
    assert navegaciones == ["https://www.amazon.com/dp/B1?language=en_US"] * 2
    assert any(m == "Runtime.evaluate" and p["expression"] == mod.CONTINUAR for m, p in llamadas)


def test_precios_de_chrome_primero_y_scraper_de_respaldo(tmp_path, monkeypatch):
    import json
    import amazon_prices as a
    prices = tmp_path / "amazon-prices.json"
    (tmp_path / "ar-chrome-2026-11-05.json").write_text(json.dumps({"items": {
        "B1": {"ships": True, "free": True, "precio": "$1,159.00"},
        "B2": {"ships": False, "free": None},
        "B3": {"ships": None, "motivo": "error:TimeoutError"}}}), encoding="utf-8")
    llamados = []

    def fake(base, products, today):
        llamados.append([p["asin"] for p in products])
        return {p["slug"]: {"asin": p["asin"], "amount": 50.0, "currency": "USD", "checked": today} for p in products}, len(products), 0
    monkeypatch.setattr(a, "fetch_prices", fake)
    productos = [{"slug": f"s{i}", "asin": f"B{i}", "store": "US"} for i in (1, 2, 3)] + [{"slug": "es", "asin": "E1", "store": "ES"}]
    items, ok, missing = a.prices_with_chrome("http://scraper", productos, "2026-11-05", prices)
    assert items["s1"]["amount"] == 1159.0 and items["s1"]["source"] == "chrome"
    assert "s2" not in items and missing == 1          # sin oferta AR según Chrome: ni se consulta
    assert llamados == [["B3", "E1"]]                  # lo que Chrome no leyó y la tienda ES van al scraper
    assert ok == 3


def test_envio_de_chrome_de_hoy_reemplaza_confirmacion_vieja(tmp_path):
    import json
    import amazon_prices as a
    prices = tmp_path / "amazon-prices.json"
    (tmp_path / "ar-chrome-2026-11-05.json").write_text(json.dumps({"items": {
        "B1": {"ships": True, "free": False}, "B2": {"ships": False}, "B3": {"ships": None}}}), encoding="utf-8")
    productos = [{"slug": f"s{i}", "asin": f"B{i}", "store": "US"} for i in (1, 2, 3)]
    out = a.chrome_shipping(productos, prices, "2026-11-05")
    assert out == {"s1": {"ships": True, "free": False, "checked": "2026-11-05"},
                   "s2": {"ships": False, "free": None, "checked": "2026-11-05"}}
