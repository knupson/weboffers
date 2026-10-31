from datetime import datetime
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import creators_api
import publish
import rates
import worker


@pytest.fixture(autouse=True)
def local_temp_files(tmp_path, monkeypatch):
    # pytest se ejecuta con --basetemp dentro de worker/.
    for name in ("CREATORS_CLIENT_ID", "CREATORS_CLIENT_SECRET",
                 "CREATORS_PARTNER_TAG_US", "CREATORS_PARTNER_TAG_ES",
                 "CF_DEPLOY_HOOK_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    monkeypatch.setenv("AMAZON_PRICES_PATH", str(tmp_path / "amazon-prices.json"))
    monkeypatch.setenv("ML_PRICES_PATH", str(tmp_path / "ml-prices.json"))
    monkeypatch.delenv("AMAZON_SCRAPER_URL", raising=False)
    monkeypatch.delenv("ML_CLIENT_ID", raising=False)
    monkeypatch.delenv("ML_CLIENT_SECRET", raising=False)


def test_offline_output_matches_spec(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CATALOG_PATH", "../data/catalog.json")
    monkeypatch.setattr(rates, "get_rates", lambda: None)
    http = Mock(side_effect=AssertionError("No debe consultar Amazon sin credenciales"))
    monkeypatch.setattr(requests, "post", http)
    payload = worker.run_once()
    assert set(payload) == {"generatedAt", "mode", "rates", "items"}
    assert payload["mode"] == "offline"
    assert payload["rates"] is None
    assert datetime.fromisoformat(payload["generatedAt"]).tzinfo is not None
    catalog = json.loads((Path(__file__).parent / "../data/catalog.json").read_text(encoding="utf-8"))
    assert len(payload["items"]) == len(catalog)
    for item in payload["items"]:
        assert set(item) == {"asin", "store", "title", "priceUsd", "priceFetchedAt",
                             "imageUrl", "availability"}
        assert item["store"] in ("US", "ES")
        assert all(item[key] is None for key in (
            "title", "priceUsd", "priceFetchedAt", "imageUrl", "availability"))
    assert "Modo offline" in capsys.readouterr().out
    assert json.loads((tmp_path / "offers.json").read_text(encoding="utf-8")) == payload
    http.assert_not_called()


def test_atomic_write_replaces_content_without_temp_files(tmp_path):
    path = tmp_path / "offers.json"
    publish.write_atomic(path, {"old": True})
    publish.write_atomic(path, {"new": "actualizado"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": "actualizado"}
    assert list(tmp_path.iterdir()) == [path]


def test_cycle_groups_stores_with_partial_credentials(tmp_path, monkeypatch):
    catalog = [{"asin": "EXAMPLE0001", "store": "US"},
               {"asin": "EXAMPLE0002", "store": "ES"},
               {"asin": "EXAMPLE0003", "store": "US"}]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")
    monkeypatch.setenv("CATALOG_PATH", str(path))
    monkeypatch.setattr(rates, "get_rates", lambda: None)
    for name in ("CREATORS_CLIENT_ID", "CREATORS_CLIENT_SECRET", "CREATORS_PARTNER_TAG_US"):
        monkeypatch.setenv(name, "test")
    fetch = Mock(side_effect=lambda asins, store: [creators_api.empty_item(a, store) for a in asins])
    monkeypatch.setattr(creators_api, "fetch_items", fetch)
    payload = worker.run_once()
    assert payload["mode"] == "api"
    assert fetch.call_count == 2
    assert fetch.call_args_list[0].args == (["EXAMPLE0001", "EXAMPLE0003"], "US")
    assert fetch.call_args_list[1].args == (["EXAMPLE0002"], "ES")


def test_atomic_write_failure_preserves_previous_content(tmp_path, monkeypatch):
    path = tmp_path / "offers.json"
    publish.write_atomic(path, {"old": True})
    monkeypatch.setattr(publish.os, "replace", Mock(side_effect=OSError("falló")))
    with pytest.raises(OSError):
        publish.write_atomic(path, {"new": True})
    assert json.loads(path.read_text()) == {"old": True}
    assert list(tmp_path.iterdir()) == [path]


def test_hook_only_when_content_changed(tmp_path, monkeypatch):
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    path = tmp_path / "offers.json"
    hook = "https://example.test/hook"
    payload = publish.build_offers("2026-10-30T00:00:00Z", "offline", None, [])
    assert publish.publish(path, payload, hook) is True
    post.assert_called_once_with(hook, timeout=30)
    payload["generatedAt"] = "2026-10-30T01:00:00Z"
    assert publish.publish(path, dict(reversed(list(payload.items()))), hook) is False
    assert post.call_count == 1
    assert json.loads(path.read_text())["generatedAt"] == payload["generatedAt"]
    payload["items"] = [creators_api.empty_item("EXAMPLE0001", "US")]
    assert publish.publish(path, payload, hook) is True
    assert post.call_count == 2


def test_no_hook_url_still_writes(tmp_path, monkeypatch):
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    publish.publish(tmp_path / "offers.json", {"generatedAt": "now"}, "")
    post.assert_not_called()


def test_rates_failure_returns_none(monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(side_effect=requests.RequestException("sin red")))
    assert rates.get_rates() is None


def test_rates_mapping(monkeypatch):
    responses = [Mock(json=Mock(return_value={"venta": value})) for value in (1200, 1500, 1000)]
    get = Mock(side_effect=responses)
    monkeypatch.setattr(requests, "get", get)
    result = rates.get_rates()
    assert {key: result[key] for key in ("mep", "tarjeta", "oficial")} == {
        "mep": 1200, "tarjeta": 1500, "oficial": 1000}
    assert result["source"] == "dolarapi.com"
    assert datetime.fromisoformat(result["fetchedAt"]).tzinfo is not None
    assert [call.args[0].rsplit("/", 1)[-1] for call in get.call_args_list] == [
        "bolsa", "tarjeta", "oficial"]


def test_eur_usd_mapping(monkeypatch):
    get = Mock(return_value=Mock(json=Mock(return_value={"venta": 1250}), raise_for_status=Mock()))
    monkeypatch.setattr(requests, "get", get)
    assert rates.get_eur_usd(1000) == 1.25
    assert get.call_args.args[0].endswith("/cotizaciones/eur")


@pytest.mark.parametrize("value", [None, "inválido", -1, float("nan"), True])
def test_invalid_rates_return_none(value, monkeypatch):
    monkeypatch.setattr(requests, "get", Mock(return_value=Mock(json=lambda: {"venta": value})))
    assert rates.get_rates() is None


def test_api_fetch_assigns_fresh_timestamp_and_rejects_eur(monkeypatch):
    for name in ("CREATORS_CLIENT_ID", "CREATORS_CLIENT_SECRET", "CREATORS_PARTNER_TAG_ES"):
        monkeypatch.setenv(name, "test")
    remote = [
        {"asin": "EXAMPLE0001", "price": {"currency": "USD", "amount": 5},
         "priceFetchedAt": "2000-01-01T00:00:00Z", "title": "Respuesta de prueba"},
        {"asin": "EXAMPLE0002", "price": {"currency": "EUR", "amount": 6}},
    ]
    post = Mock(side_effect=[Mock(json=lambda: {"access_token": "test"}),
                             Mock(json=lambda: {"items": remote})])
    monkeypatch.setattr(requests, "post", post)
    before = datetime.now().astimezone()
    items = creators_api.fetch_items(["EXAMPLE0001", "EXAMPLE0002"], "ES")
    assert items[0]["priceUsd"] == 5
    assert datetime.fromisoformat(items[0]["priceFetchedAt"]) >= before
    assert items[1]["priceUsd"] is None
    assert items[1]["priceFetchedAt"] is None
    assert post.call_args_list[0].kwargs["data"]["grant_type"] == "client_credentials"


def test_loop_honors_stop_flag(monkeypatch):
    monkeypatch.setattr(worker, "stop_requested", False)
    monkeypatch.setattr(worker.signal, "signal", Mock())
    run = Mock(side_effect=lambda: worker.request_stop(None, None))
    monkeypatch.setattr(worker, "run_once", run)
    worker.main()
    run.assert_called_once()


def test_catalog_entries_are_complete_and_unique():
    catalog = json.loads((Path(__file__).parent / "../data/catalog.json").read_text(encoding="utf-8"))
    required = {"asin", "store", "slug", "name", "brand", "category", "summary", "verified"}
    for item in catalog:
        assert required <= set(item)
        assert item["store"] in ("US", "ES")
        assert isinstance(item["verified"], bool)
        if item["verified"] and "ml" in item:
            # Visible = comparado con Mercado Libre; si gana Amazon, tiene que estar verificado el envío gratis.
            assert item["ml"]["price"] > 0 and item["ml"]["url"].startswith(
                ("https://meli.la/", "https://www.mercadolibre.com.ar/"))
            if "verdict" in item:
                assert item["verdict"] in ("amazon", "ml")
            if item.get("verdict") == "amazon":
                assert item["asin"] and item["shipsToAr"]["freeShipping"] is True
        if "image" in item:
            assert item["image"].startswith("/products/") and item["imageSource"].startswith("https://")
    assert len({item["slug"] for item in catalog}) == len(catalog)
    # Sin ASIN = no está en Amazon con envío a Argentina; los visibles con ASIN no se repiten.
    with_asin = [item for item in catalog if item["verified"] and item["asin"]]
    assert len({(item["store"], item["asin"]) for item in with_asin}) == len(with_asin)
