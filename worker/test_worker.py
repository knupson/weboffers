from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import creators_api
import publish
import rates
import worker


@pytest.mark.parametrize("cursor,next_cursor,order", [
    ("MLA2", "MLA3", ["MLA3", "MLA1", "MLA2"]),
    ("MLA3", "MLA1", ["MLA1", "MLA2", "MLA3"]),
])
def test_catalogo_ignora_corte_y_completa_con_cursor(tmp_path, monkeypatch, capsys, cursor, next_cursor, order):
    auto = worker.catalog_auto
    ml = auto.crecer_desde_ml
    reloj = [0.0]
    monkeypatch.setattr(auto.time, "monotonic", lambda: reloj[0])
    monkeypatch.setattr(auto.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("CATALOG_AUTO_MAX_SECONDS", "10")
    # 7732806 (09/11): el recorrido ML→Amazon es modo manual; sin esto no se visita ningún MLA y added=0.
    monkeypatch.setenv("CATALOG_AUTO_DESDE_ML", "1")
    monkeypatch.setattr(auto.ml_prices, "is_configured", lambda: True)
    repo = tmp_path / "catalog.json"
    repo.write_text(json.dumps([{"asin": "EXISTENTE", "slug": "existente", "category": "Almacenamiento"}]))
    auto.publicacion.guardar(tmp_path, {})
    state_path = tmp_path / "catalog-auto-state.json"
    state_path.write_text(json.dumps({"cursorMl": cursor, "extra": "conservar"}))
    monkeypatch.setattr(auto.discovery, "discover_categories", lambda **kw: [])
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **kw: dict.fromkeys(["MLA1", "MLA2", "MLA3"]))
    visited = []
    def items(pid):
        visited.append(pid)
        return [{"price": 200000, "condition": "new", "id": "MLA456"}]
    monkeypatch.setattr(auto.ml_prices, "fetch_items", items)
    monkeypatch.setattr(auto.ml_prices, "cheapest_new", lambda items: (200000, "MLA456"))
    ficha = {"name": "Samsung 990 PRO 1TB", "domain_id": "MLA-SOLID_STATE_DRIVES", "attributes": [
        {"id": "BRAND", "value_name": "Samsung"}, {"id": "MODEL", "value_name": "990 PRO"},
        {"id": "ALPHANUMERIC_MODEL", "value_name": "MZ-V9P1T0B"}]}
    monkeypatch.setattr(ml, "_get", lambda *a, **kw: Mock(ok=True, json=lambda: ficha))
    monkeypatch.setattr(auto.ml_prices, "get_json", lambda *a, **kw: ficha)
    monkeypatch.setattr(auto.ml_prices, "pause", lambda: None)
    def get(*a, **kw):
        reloj[0] = 11.0
        return Mock(json=lambda: {"items": [{"asin": "B000000001", "title": "Samsung 990 PRO 1TB MZ-V9P1T0B", "price": 150}]})
    monkeypatch.setattr(auto.requests, "get", get)
    monkeypatch.setattr(auto.amazon_prices, "fetch_ar_shipping", lambda *a: {
        "B000000001": {"identifiers": {"model_number": "MZ-V9P1T0B"}}})
    monkeypatch.setattr(auto, "fetch_photo", lambda entry, output: entry.update(image="/products/test.webp") or True)
    assert auto.maybe_grow(repo, tmp_path, datetime(2026, 11, 9, tzinfo=timezone.utc), mep=1000, force=True)
    state = json.loads(state_path.read_text())
    assert state["status"] == "ok" and state["added"] == 1
    assert state["cursorMl"] == cursor and state["extra"] == "conservar"
    assert state["week"] == "2026-W45"
    assert {"slot", "pages", "revision", "motivos"} <= state.keys()
    assert len(json.loads((tmp_path / "altas-pendientes.json").read_text())) == 1
    assert len(json.loads((tmp_path / "match-results.json").read_text())["accepted"]) == 1
    start = ["MLA1", "MLA2", "MLA3"].index(cursor)
    expected = ["MLA1", "MLA2", "MLA3"][start:] + ["MLA1", "MLA2", "MLA3"][:start]
    assert visited == expected
    assert "CATALOGO_CORTE_TIEMPO" not in capsys.readouterr().out
    # La corrida siguiente retoma desde el cursor y cruza el final de la lista.
    reloj[0] = 0
    monkeypatch.delenv("CATALOG_AUTO_MAX_SECONDS")
    auto.maybe_grow(repo, tmp_path, datetime(2026, 11, 10, tzinfo=timezone.utc), mep=1000, force=True)
    assert visited == expected  # Definitivos vigentes durante siete días.
    assert json.loads(state_path.read_text())["cursorMl"] == cursor


def test_scraper_pausa_corta_tambien_despues_de_cien_paginas(monkeypatch):
    auto = worker.catalog_auto
    pauses = []
    monkeypatch.setattr(auto.time, "sleep", pauses.append)
    monkeypatch.setattr(auto.requests, "get", lambda *a, **k: Mock(json=lambda: {"results": []}))
    scraper = auto.PacedScraper(1000)
    scraper.pages = 100
    scraper.get("http://scraper")
    assert pauses == [auto.amazon_prices.PAUSE_SECONDS]
    assert scraper.pages == 101 and scraper.failures == 1


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


def test_bucle_no_llama_precios_ni_alta(tmp_path, monkeypatch):
    repo = [{"asin": "A", "slug": "a", "store": "US"}]
    automatic = [{"asin": "A", "slug": "repetido", "store": "US"}, {"asin": "B", "slug": "b", "store": "US"}]
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(repo))
    (tmp_path / "catalog-auto.json").write_text(json.dumps(automatic))
    (tmp_path / "offers.json").write_text('{"previo": true}')
    monkeypatch.setenv("CATALOG_PATH", str(path))
    monkeypatch.setattr(rates, "get_rates", lambda: None)
    consumidores = [(worker.amazon_prices, "maybe_refresh"), (worker.ml_prices, "maybe_refresh"),
                    (worker.ml_fichas, "refresh_optional"), (worker.catalog_auto, "maybe_grow"),
                    (worker.creators_api, "fetch_items"), (worker.publish, "publish")]
    mocks = []
    for module, name in consumidores:
        mock = Mock(side_effect=AssertionError("Sólo Telegram en el bucle"))
        monkeypatch.setattr(module, name, mock)
        mocks.append(mock)
    merge = Mock(return_value=[])
    post = Mock()
    monkeypatch.setattr(worker.ml_prices, "merge", merge)
    monkeypatch.setattr(worker.telegram, "maybe_post", post)
    worker.run_once()
    for mock in mocks:
        mock.assert_not_called()
    assert merge.call_args.args[0] == repo + automatic[1:]
    post.assert_called_once()
    assert json.loads((tmp_path / "offers.json").read_text()) == {"previo": True}


def test_atomic_write_replaces_content_without_temp_files(tmp_path):
    path = tmp_path / "offers.json"
    publish.write_atomic(path, {"old": True})
    publish.write_atomic(path, {"new": "actualizado"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": "actualizado"}
    assert list(tmp_path.iterdir()) == [path]


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
    responses = [Mock(json=Mock(return_value={"venta": value, "fechaActualizacion": datetime.now(timezone.utc).isoformat()})) for value in (1200, 1500, 1000)]
    get = Mock(side_effect=responses)
    monkeypatch.setattr(requests, "get", get)
    result = rates.get_rates()
    assert {key: result[key] for key in ("mep", "tarjeta", "oficial")} == {
        "mep": 1200, "tarjeta": 1500, "oficial": 1000}
    assert result["source"] == "dolarapi.com"
    assert datetime.fromisoformat(result["fetchedAt"]).tzinfo is not None
    assert [call.args[0].rsplit("/", 1)[-1] for call in get.call_args_list] == [
        "bolsa", "tarjeta", "oficial"]


def test_stale_rate_does_not_drop_fresh_mep(monkeypatch):
    """09/11: DolarAPI dejó tarjeta y oficial con fecha 05/11 y el MEP vigente se perdía con ellos:
    el alta nocturna falló toda la noche con «Faltan credenciales de ML o cotización MEP»."""
    now = datetime.now(timezone.utc)
    old = (now - timedelta(days=4)).isoformat()
    bodies = [{"venta": 1587.9, "fechaActualizacion": now.isoformat()},
              {"venta": 2041, "fechaActualizacion": old},
              {"venta": 1570, "fechaActualizacion": old}]
    monkeypatch.setattr(requests, "get", Mock(side_effect=[Mock(json=Mock(return_value=b)) for b in bodies]))
    result = rates.get_rates()
    assert result["mep"] == 1587.9
    # Lo vencido no se rellena: no aparece.
    assert "tarjeta" not in result and "oficial" not in result


def test_eur_usd_mapping(monkeypatch):
    get = Mock(return_value=Mock(json=Mock(return_value={"venta": 1250, "fechaActualizacion": datetime.now(timezone.utc).isoformat()}), raise_for_status=Mock()))
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


def test_loop_honors_stop_flag(monkeypatch, capsys):
    monkeypatch.setattr(worker, "stop_requested", False)
    monkeypatch.setattr(worker.signal, "signal", Mock())
    run = Mock(side_effect=lambda: worker.request_stop(None, None))
    monkeypatch.setattr(worker, "run_once", run)
    worker.main()
    run.assert_called_once()
    assert capsys.readouterr().out.count("LATIDO worker") == 1


def test_publicar_offers_escribe_respaldo_del_dia(tmp_path, monkeypatch):
    catalog = [{"asin": "A", "store": "US"}, {"asin": "B", "store": "ES"}]
    monkeypatch.setattr(worker, "load_catalog", lambda *args: catalog)
    current = {"mep": 1500, "oficial": 1200, "fetchedAt": "2026-11-09T06:30:00Z"}
    monkeypatch.setattr(rates, "get_rates", lambda: current)
    fetch = Mock(side_effect=lambda asins, store: [creators_api.empty_item(a, store) for a in asins])
    monkeypatch.setattr(creators_api, "fetch_items", fetch)
    worker.publicar_offers()
    data = json.loads((tmp_path / "offers.json").read_text())
    assert data["rates"] == current and data["mode"] == "offline"
    assert [(p["asin"], p["store"]) for p in data["items"]] == [("A", "US"), ("B", "ES")]
    assert datetime.fromisoformat(data["generatedAt"]).tzinfo is not None
    assert fetch.call_count == 2


def test_publicar_offers_propaga_falla(monkeypatch):
    monkeypatch.setattr(worker, "load_catalog", lambda *a: [])
    monkeypatch.setattr(rates, "get_rates", lambda: None)
    monkeypatch.setattr(publish, "publish", Mock(side_effect=OSError("sin disco")))
    with pytest.raises(OSError, match="sin disco"):
        worker.publicar_offers()


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


def test_daily_log_survives_in_output_dir(tmp_path):
    """El log del worker queda en output/logs (volumen): sobrevive a recrear el contenedor (05/11)."""
    import io
    stream = io.StringIO()
    log = worker.DailyLog(tmp_path / "logs", stream)
    print("Mercado Libre: no se pudo consultar x (HTTPError); se omite.", file=log, flush=True)
    assert "no se pudo consultar x" in stream.getvalue()
    files = list((tmp_path / "logs").glob("worker-*.log"))
    assert len(files) == 1
    assert "no se pudo consultar x" in files[0].read_text(encoding="utf-8")
