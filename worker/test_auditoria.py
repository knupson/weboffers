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
