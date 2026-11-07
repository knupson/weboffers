"""Altas semanales y persistencia sin consultas reales."""
from datetime import datetime
import io
import json
from unittest.mock import Mock

from PIL import Image
import pytest
import requests

import catalog_auto as auto
from catalog import load_catalog, merge_catalogs
from tools import apply_candidates, sync_catalogo_auto


def candidate(**changes):
    if "asin" in changes and "catalogId" not in changes:
        changes["catalogId"] = "MLA" + changes["asin"]  # cada producto de prueba con su propia ficha de ML
    row = dict(asin="B000000001", store="US", slug="samsung-t9", name="Samsung T9 SSD",
               brand="Samsung", category="Almacenamiento", summary="SSD Samsung T9.",
               catalogId="MLA123", itemId="MLA456", mlPrice=200000,
               amazonTitle="Samsung T9 SSD", amazonPriceUsd=150)
    return {**row, **changes}


@pytest.fixture
def setup_job(tmp_path, monkeypatch):
    repo = tmp_path / "catalog.json"
    repo.write_text(json.dumps([{"asin": "EXISTENTE", "slug": "existente", "category": "Almacenamiento"}]))
    output = tmp_path / "output"
    monkeypatch.setattr(auto.ml_prices, "is_configured", lambda: True)
    def discover(*args, **kwargs):
        kwargs["get"].__self__.valid = 1
        return []
    discovery = Mock(side_effect=discover)
    monkeypatch.setattr(auto.discovery, "discover_products", discovery)
    monkeypatch.setattr(auto.matching, "match_products", lambda *args: {"accepted": [candidate()], "doubtful": [], "rejected": []})
    monkeypatch.setattr(auto, "fetch_photo", lambda entry, output: entry.update(image=f"/products/{entry['slug']}.webp") or True)
    monkeypatch.setattr(auto.crecer_desde_ml, "candidatos", lambda *a, **k: [])  # sin API real de ML en los tests
    return repo, output, discovery


@pytest.mark.parametrize("instant", ["2026-11-07T20:00:00+00:00", "2026-11-08T16:59:00+00:00", "2026-11-09T00:00:00+00:00"])
def test_gate_art_before_sunday_afternoon(setup_job, instant):
    repo, output, discover = setup_job
    # Lunes UTC todavía es domingo ART: sí está dentro de la ventana.
    expected = instant == "2026-11-09T00:00:00+00:00"
    assert auto.maybe_grow(repo, output, datetime.fromisoformat(instant), mep=1000) is expected
    assert discover.call_count == int(expected)


def test_once_per_night_keeps_previous_and_logs(setup_job):
    """05/11: corre todas las noches (20:00-03:00 ART), una vez por noche."""
    repo, output, discover = setup_job
    now = datetime.fromisoformat("2026-11-08T23:30:00+00:00")  # 20:30 ART
    assert auto.maybe_grow(repo, output, now, mep=1000)
    assert not auto.maybe_grow(repo, output, now, mep=1000)
    assert not auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-09T05:59:00+00:00"), mep=1000)  # 02:59, misma noche
    assert discover.call_count == 1
    assert not (output / "catalog-auto.json").exists()
    entries = json.loads((output / "altas-pendientes.json").read_text())
    assert len(entries) == 1
    assert entries[0]["pendienteDesde"] == "2026-11-08"
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-09T23:30:00+00:00"), mep=1000)  # noche siguiente
    assert json.loads((output / "altas-pendientes.json").read_text()) == entries
    log = json.loads((output / "amazon-run-2026-11-08.json").read_text())
    assert log["passes"][0]["kind"] == "catalogo"
    assert log["passes"][0]["ok"] == 1


def test_force_runs_outside_the_window(setup_job):
    repo, output, discover = setup_job
    tarde = datetime.fromisoformat("2026-11-05T19:00:00+00:00")  # 16:00 ART
    assert not auto.maybe_grow(repo, output, tarde, mep=1000)
    assert auto.maybe_grow(repo, output, tarde, mep=1000, force=True)
    assert discover.call_count == 1


def test_failed_before_scraping_retries_same_night(setup_job, monkeypatch, capsys):
    repo, output, discover = setup_job
    discover.side_effect = requests.ConnectionError("sin conexión")
    now = datetime.fromisoformat("2026-11-08T23:30:00+00:00")
    assert auto.maybe_grow(repo, output, now, mep=1000)
    assert auto.maybe_grow(repo, output, now, mep=1000)
    assert "DEPLOY_FAIL" in capsys.readouterr().out
    assert json.loads((output / "catalog-auto-state.json").read_text())["status"] == "failed"


def test_retry_missing_mep_before_three(setup_job):
    repo, output, discover = setup_job
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-08T23:30:00+00:00"), mep=None)
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-09T05:59:00+00:00"), mep=1000)
    assert discover.call_count == 1
    assert json.loads((output / "catalog-auto-state.json").read_text())["week"] == "2026-W45"
    assert not auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-09T06:00:00+00:00"), mep=1000)


def test_no_retry_after_scraping_started(setup_job):
    repo, output, discover = setup_job
    def fail(*args, **kwargs):
        kwargs["get"].__self__.pages = 1
        raise requests.ConnectionError()
    discover.side_effect = fail
    now = datetime.fromisoformat("2026-11-08T23:30:00+00:00")
    assert auto.maybe_grow(repo, output, now, mep=1000)
    assert not auto.maybe_grow(repo, output, now, mep=1000)
    assert discover.call_count == 1


@pytest.mark.parametrize("hours,retry", [(6, False), (7, True)])
def test_expired_running_retries(setup_job, hours, retry):
    from datetime import timedelta
    repo, output, discover = setup_job
    now = datetime.fromisoformat("2026-11-09T05:00:00+00:00")  # 02:00 ART, noche del 08/11
    output.mkdir(parents=True)
    (output / "catalog-auto-state.json").write_text(json.dumps({
        "slot": "2026-11-08", "week": "2026-W45", "status": "running", "at": (now - timedelta(hours=hours)).isoformat(),
    }))
    assert auto.maybe_grow(repo, output, now, mep=1000) is retry
    assert discover.call_count == int(retry)


def test_budget_comes_from_env_without_fixed_cap(setup_job, monkeypatch):
    repo, output, discover = setup_job
    monkeypatch.setenv("CATALOG_AUTO_MAX_PAGES", "900")
    auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-08T23:30:00+00:00"), mep=1000)
    assert discover.call_args.kwargs["get"].__self__.limit == 900


def test_iso_year_survives_calendar_year_boundary(setup_job):
    repo, output, discover = setup_job
    auto.maybe_grow(repo, output, datetime.fromisoformat("2027-01-03T23:30:00+00:00"), mep=1000)
    assert json.loads((output / "catalog-auto-state.json").read_text())["week"] == "2026-W53"


def test_category_exclusions_and_budget_return_partial_results(monkeypatch):
    monkeypatch.setattr(auto.discovery, "scraper_pause", lambda: None)
    fetch = Mock(side_effect=[[dict(asin="NUEVO", title="Samsung T9 SSD", price=150)], auto.discovery.PageBudgetExhausted()])
    monkeypatch.setattr(auto.discovery, "fetch_bestsellers_for_category", fetch)
    result = auto.discovery.collect_amazon_candidates(set(), categories=[
        {"id": "excluded", "name": "Renewed electronics"},
        {"id": "one", "name": "Storage"}, {"id": "two", "name": "Monitors"},
    ])
    assert fetch.call_count == 2
    assert [p["asin"] for p in result] == ["NUEVO"]


def test_accepted_only_skip_existing_range_and_photo(setup_job, monkeypatch):
    repo, output, _ = setup_job
    rows = [candidate(), candidate(asin="EXISTENTE", slug="otro"), candidate(asin="otro", slug="existente"),
            candidate(asin="barato", slug="barato", amazonPriceUsd=99),
            candidate(asin="caro", slug="caro", amazonPriceUsd=401),
            candidate(asin="sin-foto", slug="sin-foto", name="Samsung T7 SSD", amazonTitle="Samsung T7 SSD"),
            candidate(asin="funda", slug="funda", amazonTitle="Samsung T9 protective case")]
    photo = Mock(side_effect=lambda p, _: p["slug"] != "sin-foto")
    monkeypatch.setattr(auto, "fetch_photo", photo)
    added, failures = auto.add_accepted(load_catalog(repo, output / "catalog-auto.json"),
        {"accepted": rows, "doubtful": [candidate(asin="duda", slug="duda")], "rejected": []}, output, "2026-11-08")
    assert [p["slug"] for p in added] == ["samsung-t9"]
    assert failures == [{"slug": "sin-foto", "motivo": "sin_foto"}]
    assert photo.call_count == 2


def test_merge_repo_wins_on_asin_and_slug(tmp_path):
    repo = [{"asin": "A", "slug": "a"}]
    automatic = [{"asin": "A", "slug": "otro"}, {"asin": "B", "slug": "a"}, {"asin": "C", "slug": "c"}]
    assert merge_catalogs(repo, automatic) == repo + automatic[2:]
    assert merge_catalogs(repo, automatic + automatic) == repo + automatic[2:]


def test_photo_official_webp_max_900(tmp_path, monkeypatch):
    monkeypatch.setattr(auto.ml_prices, "get_json", lambda _: {"pictures": [{"url": "https://http2.mlstatic.com/test.jpg"}]})
    monkeypatch.setattr(auto.ml_prices, "pause", lambda: None)
    buf = io.BytesIO()
    Image.new("RGB", (1800, 1200)).save(buf, "JPEG")
    monkeypatch.setattr(auto.requests, "get", Mock(return_value=Mock(content=buf.getvalue())))
    entry = {"slug": "foto", "ml": {"catalogId": "MLA123"}}
    assert auto.fetch_photo(entry, tmp_path)
    with Image.open(tmp_path / "products" / "foto.webp") as img:
        assert img.size == (900, 600)
        assert img.format == "WEBP"
    with Image.open(tmp_path / "products" / "foto.jpg") as img:
        assert img.size == (900, 600)
        assert img.format == "JPEG"
    assert entry["imageSource"] == "https://http2.mlstatic.com/test.jpg"


@pytest.mark.parametrize("pictures", [[], [{"url": "https://otro.com/foto.jpg"}]])
def test_photo_missing_or_unofficial(tmp_path, monkeypatch, pictures):
    monkeypatch.setattr(auto.ml_prices, "get_json", lambda _: {"pictures": pictures})
    monkeypatch.setattr(auto.ml_prices, "pause", lambda: None)
    assert not auto.fetch_photo({"slug": "foto", "ml": {"catalogId": "MLA1"}}, tmp_path)
    assert not (tmp_path / "products").exists()


def test_pacing_backoff_and_hard_cap(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(auto.time, "sleep", sleep)
    get = Mock(side_effect=[Mock(json=lambda: {}), Mock(json=lambda: {"items": [1]})])
    monkeypatch.setattr(auto.requests, "get", get)
    scraper = auto.PacedScraper(2)
    scraper.get("http://scraper")
    with pytest.raises(auto.discovery.PageBudgetExhausted):
        scraper.get("http://scraper")
    assert get.call_count == 2
    assert any(call.args == (auto.amazon_prices.BACKOFF_SECONDS,) for call in sleep.call_args_list)
    assert any(call.args == (auto.amazon_prices.PAUSE_SECONDS,) for call in sleep.call_args_list)


def test_pause_breaks_consecutive_pages(monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(auto.time, "sleep", sleep)
    monkeypatch.setattr(auto.requests, "get", Mock(return_value=Mock(json=lambda: {"items": [1]})))
    scraper = auto.PacedScraper(150)  # el tope sale del parámetro (05/11: sin tope fijo en el código)
    for _ in range(150):
        scraper.get("http://scraper")
    with pytest.raises(auto.discovery.PageBudgetExhausted):
        scraper.get("http://scraper")
    assert scraper.pages == 150
    sleep.assert_any_call(300)


def test_manual_apply_accepts_match_document(setup_job):
    repo, _, _ = setup_job
    assert len(apply_candidates.apply_candidates(repo, {"accepted": [candidate()], "doubtful": [candidate()]}, dry_run=True)) == 1


def test_sync_preserves_repo_and_photos(tmp_path):
    root, output = tmp_path / "repo", tmp_path / "output"
    (root / "data").mkdir(parents=True)
    (root / "public" / "products").mkdir(parents=True)
    (output / "products").mkdir(parents=True)
    existing = {"asin": "A", "slug": "a", "summary": "del repo"}
    (root / "data" / "catalog.json").write_text(json.dumps([existing]))
    (output / "catalog-auto.json").write_text(json.dumps([dict(existing, summary="auto"), {"asin": "B", "slug": "b"}]))
    (root / "public" / "products" / "a.webp").write_bytes(b"original")
    for slug in ("a", "b"):
        (output / "products" / f"{slug}.webp").write_bytes(b"auto")
    sync_catalogo_auto.sync_catalog(output, root)
    assert json.loads((root / "data" / "catalog.json").read_text())[0] == existing
    assert (root / "public" / "products" / "a.webp").read_bytes() == b"original"
    assert (root / "public" / "products" / "b.webp").read_bytes() == b"auto"


def test_no_da_de_alta_dos_veces_la_misma_ficha_de_ml(setup_job):
    repo, output, _ = setup_job
    rows = [candidate(asin="A1", slug="a1", catalogId="MLA999"), candidate(asin="A2", slug="a2", catalogId="MLA999")]
    added, _ = auto.add_accepted(load_catalog(repo, output / "catalog-auto.json"),
                                 {"accepted": rows, "doubtful": [], "rejected": []}, output, "2026-11-08")
    assert [p["slug"] for p in added] == ["a1"]


def test_no_duplica_el_mismo_modelo_en_otro_color():
    existente = {"slug": "jbl-flip-7", "brand": "JBL", "name": "JBL Flip 7 negro", "verified": True}
    nuevo = {"slug": "jbl-flip7", "brand": "JBL", "name": "Parlante Jbl Flip 7 Portátil Azul", "amazonTitle": "Flip 7 Portable Speaker - Teal"}
    assert auto.mismo_producto(nuevo, existente)
    otro = {"slug": "s", "brand": "Samsung", "name": "Galaxy Tab A11 128GB"}
    assert not auto.mismo_producto(otro, {"slug": "t", "brand": "Samsung", "name": "Galaxy Tab A11 64GB"})


def test_falla_suelta_no_marca_la_corrida_como_fallida(setup_job, monkeypatch, capsys):
    """05/11: una foto o una búsqueda que falla queda contada, pero la corrida es OK (el vigía no avisa en falso)."""
    repo, output, _ = setup_job
    monkeypatch.setattr(auto, "fetch_photo", lambda entry, out: False)
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-08T23:30:00+00:00"), mep=1000)
    estado = json.loads((output / "catalog-auto-state.json").read_text())
    assert estado["status"] == "ok" and "sin_foto" in estado["motivos"]
    assert "CATALOGO_OK" in capsys.readouterr().out


def test_al_terminar_avisa_al_host(setup_job):
    # 07/11: el alta nocturna terminó 05:11 y la cadena ya había buscado altas a las 03:46; las altas esperaban
    # un día. Al terminar se escribe alta-terminada.json (escritura directa: la unidad systemd .path ve el cierre).
    repo, output, discover = setup_job
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-08T23:30:00+00:00"), mep=1000)
    aviso = json.loads((output / "alta-terminada.json").read_text())
    assert aviso["slot"] == "2026-11-08" and aviso["status"] == "ok" and aviso["added"] == 1 and aviso["fin"]
