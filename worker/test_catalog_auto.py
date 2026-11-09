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
               amazonTitle="Samsung T9 SSD", amazonPriceUsd=150,
               amazonIds={"model_number": "MU-PG1T0B/AM"}, mlIds={"MPN": "MU-PG1T0B/AM"})
    return {**row, **changes}


@pytest.mark.parametrize("fecha,week", [("2026-11-09", "2026-W45"), ("2027-01-04", "2026-W53")])
@pytest.mark.parametrize("hora", [3, 8])
def test_lunes_0330_conserva_semana_del_domingo(setup_job, fecha, week, hora):
    from tools.recordatorio_franquicia import control_catalogo
    repo, output, _ = setup_job
    now = datetime.fromisoformat(fecha + "T03:30:00-03:00").replace(hour=hora)
    assert auto.maybe_grow(repo, output, now, mep=1200)
    state = json.loads((output / "catalog-auto-state.json").read_text())
    assert state["slot"] == fecha
    assert state["week"] == week
    assert control_catalogo(now.replace(hour=7, minute=30), lambda url: json.dumps({"catalogo": state})) == ""


@pytest.fixture
def setup_job(tmp_path, monkeypatch):
    repo = tmp_path / "catalog.json"
    repo.write_text(json.dumps([{"asin": "EXISTENTE", "slug": "existente", "category": "Almacenamiento"}]))
    output = tmp_path / "output"
    import publicacion
    publicacion.guardar(output, {})
    monkeypatch.setattr(auto.ml_prices, "is_configured", lambda: True)
    def discover(*args, **kwargs):
        kwargs["get"].__self__.valid = 1
        row = {"asin": "B000000001", "amazonTitle": "Samsung T9 SSD", "ml": []}
        kwargs["on_product"](row)
        return [row]
    discovery = Mock(side_effect=discover)
    monkeypatch.setattr(auto.discovery, "discover_products", discovery)
    def match(*args, **kwargs):
        row = candidate()
        kwargs["on_result"]("accepted", row)
        kwargs["journal"].append("match", row["asin"], "accepted", row=row)
        return {"accepted": [row], "doubtful": [], "rejected": []}
    monkeypatch.setattr(auto.matching, "match_products", match)
    monkeypatch.setattr(auto.crecer_desde_ml, "agregar_identificadores", lambda *a, **k: 0)
    monkeypatch.setattr(auto, "fetch_photo", lambda entry, output: entry.update(image=f"/products/{entry['slug']}.webp") or True)
    monkeypatch.setattr(auto.crecer_desde_ml, "candidatos", lambda *a, **k: [])  # sin API real de ML en los tests
    return repo, output, discovery


@pytest.mark.parametrize("hora", [0, 3, 12, 19, 20, 23])
def test_sin_ventana_horaria(setup_job, hora):
    repo, output, discover = setup_job
    now = datetime.fromisoformat(f"2026-11-09T{hora:02d}:00:00-03:00")
    assert auto.maybe_grow(repo, output, now, mep=1000)
    assert discover.call_count == 1
    assert not auto.maybe_grow(repo, output, now, mep=1000)
    assert discover.call_count == 1
    assert not (output / "catalog-auto.json").exists()
    entries = json.loads((output / "altas-pendientes.json").read_text())
    assert len(entries) == 1 and entries[0]["pendienteDesde"] == "2026-11-09"
    log = json.loads((output / "amazon-run-2026-11-09.json").read_text())
    assert log["passes"][0]["kind"] == "catalogo" and log["passes"][0]["ok"] == 1


@pytest.mark.parametrize("status,pages", [("failed", 0), ("failed", 1), ("running", 0), ("ok", 1)])
def test_sin_reintento_por_hora(setup_job, status, pages):
    repo, output, discover = setup_job
    output.mkdir(parents=True, exist_ok=True)
    (output / "catalog-auto-state.json").write_text(json.dumps({
        "slot": "2026-11-09", "status": status, "pages": pages, "at": "2026-11-09T00:00:00-03:00"}))
    attempted = auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-09T20:00:00-03:00"), mep=1000)
    assert attempted == (status != "ok")
    assert discover.call_count == int(status != "ok")
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-10T03:30:00-03:00"), mep=1000)
    assert discover.call_count == 1 + int(status != "ok")


def test_force_permite_corrida_explicita(setup_job):
    repo, output, discover = setup_job
    now = datetime.fromisoformat("2026-11-09T03:30:00-03:00")
    assert auto.maybe_grow(repo, output, now, mep=1000)
    assert auto.maybe_grow(repo, output, now, mep=1000, force=True)
    assert discover.call_count == 2


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
    assert sleep.call_count == 149
    assert all(call.args == (auto.amazon_prices.PAUSE_SECONDS,) for call in sleep.call_args_list)


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


def test_al_terminar_no_dispara_otra_cadena(setup_job):
    repo, output, discover = setup_job
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-09T03:30:00-03:00"), mep=1000)
    assert not (output / "alta-terminada.json").exists()


@pytest.mark.parametrize("amazon_ids,ml_ids,strong", [
    ({"upc": "012345678905"}, {"GTIN": "0012345678905"}, True),
    ({"ean": "0 123-456-78905"}, {"UPC": "012345678905"}, True),
    ({"model_number": "ab 123/ZA"}, {"MPN": "AB-123ZA"}, True),
    ({"model_number": "AB123/ZA"}, {"MPN": "AB123/ZB"}, False),
    ({"model_number": "SM-A165F"}, {"ALPHANUMERIC_MODEL": "SM-A165M"}, False),
    ({"model_number": "SM-A165F"}, {"MODEL": "SM A165F"}, True),
    ({"model_number": "123456"}, {"MPN": "123456"}, False),
    ({"model_number": "ABCDE"}, {"MPN": "ABCDE"}, False),
    ({"model_number": "AB12"}, {"MODEL": "AB12"}, False),
    ({"model_number": "AB123/ZA"}, {"MPN": "AB123"}, False),
    ({"model_number": "AB123/ZA"}, {"MPN": "OTRO9, AB123/ZA"}, True),
    ({"model_name": "AB123"}, {"MODEL": "AB123"}, False),
    ({"upc": "000000"}, {"GTIN": "0000000"}, False),
    ({}, {}, False),
])
def test_identifier_gate_routes_to_pending_or_review(setup_job, monkeypatch, capsys, amazon_ids, ml_ids, strong):
    repo, output, _ = setup_job
    photo = Mock(return_value=True)
    monkeypatch.setattr(auto, "fetch_photo", photo)
    row = candidate(amazonIds=amazon_ids, mlIds=ml_ids)
    added, failures = auto.add_accepted(load_catalog(repo, output / "catalog-auto.json"),
                                      {"accepted": [row]}, output, "2026-11-07")
    pending = json.loads((output / "altas-pendientes.json").read_text())
    review = json.loads((output / "altas-revision.json").read_text())
    assert len(added) == len(pending) == int(strong)
    assert len(review) == int(not strong)
    assert not failures
    assert photo.call_count == int(strong)
    if not strong:
        assert review[0] == {**row, "motivoRevision": "sin_identificador_fuerte", "revisionDesde": "2026-11-07"}
        log = capsys.readouterr().out
        assert "decision=revision" in log and "motivo=sin_identificador_fuerte" in log


def test_review_persists_dedupes_and_expires(setup_job):
    repo, output, _ = setup_job
    row = candidate(amazonIds={})
    auto.add_accepted([], {"accepted": [row, row]}, output, "2026-11-07")
    other = candidate(amazonIds={}, catalogId="MLA999")
    auto.add_accepted([], {"accepted": [row, other]}, output, "2026-11-08")
    review = json.loads((output / "altas-revision.json").read_text())
    assert len(review) == 2
    assert review[0]["revisionDesde"] == "2026-11-07"
    from tools.confirmar_altas import confirm
    assert confirm(repo, output, "2026-11-08")["promovidas"] == 0
    assert not (output / "catalog-auto.json").exists()
    # Ni siquiera nuevos identificadores promueven una entrada que está en revisión.
    added, _ = auto.add_accepted([], {"accepted": [candidate()]}, output, "2026-11-21")
    assert not added
    assert len(json.loads((output / "altas-revision.json").read_text())) == 2
    auto.add_accepted([], {"accepted": []}, output, "2026-11-22")
    review = json.loads((output / "altas-revision.json").read_text())
    assert len(review) == 1 and review[0]["catalogId"] == "MLA999"
    assert json.loads((output / "altas-pendientes.json").read_text()) == []


def test_catalogo_ok_reports_review(setup_job, monkeypatch, capsys):
    repo, output, _ = setup_job
    def match(*a, **kwargs):
        row = candidate(amazonIds={})
        kwargs["on_result"]("accepted", row)
        return {"accepted": [row]}
    monkeypatch.setattr(auto.matching, "match_products", match)
    auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-08T23:30:00+00:00"), mep=1000)
    assert "CATALOGO_OK catálogo: pendientes=0, revision=1," in capsys.readouterr().out
    # El estado lleva la cantidad: estado.json la publica y el control de las 07:30 pide «revisá las altas».
    assert json.loads((output / "catalog-auto-state.json").read_text())["revision"] == 1


def test_strong_ids_do_not_bypass_validator(setup_job):
    _, output, _ = setup_job
    auto.add_accepted([], {"accepted": [], "rejected": [candidate()], "doubtful": [candidate()]}, output, "2026-11-07")
    assert json.loads((output / "altas-pendientes.json").read_text()) == []
    assert json.loads((output / "altas-revision.json").read_text()) == []



def test_descubrimiento_respeta_no_revisar(setup_job, monkeypatch):
    import publicacion
    repo, output, discover = setup_job
    publicacion.guardar(output, {
        s: publicacion._entrada("no_revisar", fecha, "sin_envio", s.upper())
        for s, fecha in (("vigente", "2026-11-02"), ("vencido", "2026-11-01"))})
    desde_ml = Mock(return_value=[])
    monkeypatch.setattr(auto.crecer_desde_ml, "candidatos", desde_ml)
    assert auto.maybe_grow(repo, output, datetime.fromisoformat("2026-11-08T23:30:00+00:00"), mep=1000)
    for asins in (discover.call_args.kwargs["existing_asins"], desde_ml.call_args.args[0]):
        assert "VIGENTE" in asins
        assert "VENCIDO" not in asins
        assert "EXISTENTE" in asins
