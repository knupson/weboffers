import json
import pytest
from .config import Config
from .events import now_art
from .models import normalize_product
from .runner import run_all, run_store, retry_page, enrich_variations
from .amazon_source import SourceError
from .state import State


def rate(store, date):
    return {"value": 1, "source": "fixture", "observed_at": date + "T12:00:00-03:00"}


def row(identity="FIXTURE1", category="A", variations=None):
    stamp = now_art().isoformat()
    return normalize_product({"title": "Prueba", "price": {"amount": 200, "currency": "USD"}, "has_variations": variations},
        store="US", identity=identity, stamp=stamp, currency="USD", rate=rate("US", stamp[:10]),
        provenance=dict(category_id=category, category_name="Prueba", page=1, url="fixture"),
        shipping={"shipping_class": "gratis", "text": "FREE delivery to Argentina"}, located=True, condition="new")


class FakeSource:
    def __init__(self, blocked=False, pages=2, repeated=False):
        self.calls, self.blocked, self.total, self.repeated = [], blocked, pages, repeated

    def fetch_search_page(self, category, page, stamp):
        self.calls.append((category["id"], page))
        if self.blocked:
            raise SourceError("503 dogs page (after 4 sessions)\nerror literal", http=503, blocked=True)
        return dict(products=[row("FIXTURE" + str(1 if self.repeated else page), category["id"])], http=200,
                    count=self.total, total_pages=self.total, current_page=page, has_next=page < self.total)


def test_bloqueo_continua_otras_tiendas(tmp_path, capsys):
    sources = {"US": FakeSource(blocked=True), "ES": FakeSource()}
    categories = {"stores": {store: {"nodes": [{"id": "A", "name": "Prueba", "kind": "leaf"}]} for store in sources}}
    result = run_all(categories, Config(backoff=0), tmp_path, source_factory=lambda store, *a: sources[store], rate_loader=rate, sleep=lambda _: None)
    assert result["US"]["status"] == "partial" and result["ES"]["status"] == "complete"
    assert State(tmp_path, now_art().date().isoformat(), "US").load_checkpoint("A") == 1
    lines = capsys.readouterr().out.splitlines()
    assert all("-03:00 " in line for line in lines)
    assert any("BARRIDO_BLOQUEADO" in line and "error literal" in line and '"http": 503' in line for line in lines)


def test_backoff_con_tope():
    delays = []
    def blocked():
        raise SourceError("captcha fixture", blocked=True)
    with pytest.raises(SourceError):
        retry_page(blocked, Config(consecutive_blocks=4, backoff=30, backoff_cap=45), store="US", category="A", page=1, sleep=delays.append)
    assert delays == [30, 45, 45]


def test_aceptacion_paginas_reanudacion_dry_run(tmp_path):
    source = FakeSource()
    definition = {"nodes": [{"id": "A", "name": "Prueba", "kind": "leaf"}]}
    options = dict(source_factory=lambda *a: source, rate_loader=rate, sleep=lambda _: None)
    date = now_art().date().isoformat()
    result = run_store("US", definition, Config(), tmp_path, date, max_pages=1, **options)
    assert result["status"] == "partial" and source.calls == [("A", 1)]
    result = run_store("US", definition, Config(), tmp_path, date, **options)
    assert result["status"] == "complete" and source.calls[-1] == ("A", 2)
    assert result["products"] == 2
    run_store("US", definition, Config(), tmp_path, date, **options)
    assert len(source.calls) == 2
    dry = tmp_path / "dry"
    result = run_store("US", definition, Config(), dry, date, dry_run=True, **options)
    assert result["categories"]["A"]["total_pages"] == 2
    assert source.calls[-1] == ("A", 1) and not (dry / "state").exists()


def test_detecta_pagina_repetida(tmp_path):
    source = FakeSource(repeated=True)
    result = run_store("US", {"nodes": [{"id": "A", "name": "Prueba"}]}, Config(), tmp_path,
        now_art().date().isoformat(), source_factory=lambda *a: source, rate_loader=rate, sleep=lambda _: None)
    assert result["status"] == "partial" and "repetida" in result["error"]
    assert result["products"] == 1


def test_tope_variantes_persistido(tmp_path, fixture_dir):
    state = State(tmp_path, now_art().date().isoformat(), "US")
    calls = []
    class Source:
        def variations(self, identity):
            calls.append(identity)
            return json.loads((fixture_dir / "variations.json").read_text(encoding="utf-8"))
    rows = [row("FIXTURE1", variations=True), row("FIXTURE2", variations=True)]
    enrich_variations(rows, Source(), state, Config(variation_limit=1))
    enrich_variations(rows, Source(), State(tmp_path, state.date, "US"), Config(variation_limit=1))
    assert calls == ["FIXTURE1"] and rows[0]["variations"] and rows[1]["variations"] is None


def test_no_red_si_tasa_ausente(tmp_path):
    def failure(*args):
        raise ValueError("Cotización de hoy ausente fixture")
    result = run_store("ML", {"nodes": []}, Config(), tmp_path, now_art().date().isoformat(), rate_loader=failure)
    assert result["status"] == "failed" and result["error"] == "Cotización de hoy ausente fixture"


def test_cambio_de_dia_no_confirma_pagina(tmp_path, monkeypatch):
    from datetime import timedelta
    from . import runner
    current = now_art()
    calls = iter([current, current, current + timedelta(days=1)])
    monkeypatch.setattr(runner, "now_art", lambda: next(calls))
    source = FakeSource()
    date = current.date().isoformat()
    result = run_store("US", {"nodes": [{"id": "A", "name": "Prueba"}]}, Config(), tmp_path,
        date, source_factory=lambda *a: source, rate_loader=rate, sleep=lambda _: None)
    assert result["status"] == "failed" and "Cambió el día" in result["error"]
    assert State(tmp_path, date, "US").load_checkpoint("A") == 1
