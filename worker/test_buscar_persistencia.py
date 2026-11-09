"""Persistencia real ante interrupciones; sólo se simulan los límites de red."""
import json
from datetime import datetime
import io
import os
from pathlib import Path
import subprocess
import sys

import pytest
import catalog_auto
from tools import crecer_desde_ml as ml, vigia_franquicia as vigia
from buscar_log import BuscarLog
from tools import discover_products as discovery, match_candidates as matching, crecer_ahora
from test_catalog_auto import candidate


def test_ml_guarda_descartes_y_reanuda(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **k: {"MLA1": "cat", "MLA2": "cat"})
    visits = []
    def fetch(pid):
        visits.append(pid)
        if pid == "MLA2":
            raise KeyboardInterrupt()
        return []
    monkeypatch.setattr(ml.ml_prices, "fetch_items", fetch)
    state = {}
    with pytest.raises(KeyboardInterrupt):
        ml.candidatos(set(), set(), 1000, output=tmp_path, state=state)
    lines = list(tmp_path.glob("buscar-*.jsonl"))[0].read_text().splitlines()
    assert json.loads(lines[0])["id"] == "MLA1"
    assert "BUSCAR_ML id=MLA1" in capsys.readouterr().out
    monkeypatch.setattr(ml.ml_prices, "fetch_items", lambda pid: visits.append(pid) or [])
    ml.candidatos(set(), set(), 1000, output=tmp_path, state={})
    assert visits == ["MLA1", "MLA2", "MLA2"]


def test_amazon_vacia_es_valida(monkeypatch, capsys):
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"results": []}
    monkeypatch.setattr(catalog_auto.requests, "get", lambda *a, **k: Response())
    monkeypatch.setattr(catalog_auto.amazon_prices, "charge_pages", lambda n: None)
    monkeypatch.setattr(catalog_auto.time, "sleep", lambda s: pytest.fail("No debe esperar"))
    scraper = catalog_auto.PacedScraper(10)
    scraper.get("http://prueba/search")
    assert (scraper.valid, scraper.failures, scraper.pages) == (0, 1, 1)
    assert "AMAZON_PAGINA" in capsys.readouterr().out


def test_vigia_alerta_cadena_muerta(tmp_path):
    today = "2026-11-09"
    (tmp_path / f"cadena-{today}.json").write_text(json.dumps({
        "fecha": today, "inicio": "03:30", "fin": None,
        "pasos": [{"paso": "alta:buscar", "estado": "en_curso"}]}))
    problems = vigia.chequear_cadena(today, tmp_path)
    assert "alta:buscar" in problems["cadena-interrumpida"]


def test_kill_real_con_fsync_y_ultima_linea_truncada(tmp_path):
    script = '''
import os, sys
from buscar_log import BuscarLog
j = BuscarLog(sys.argv[1], "2026-11-09")
j.append("ml", "MLA1", "sin_precio")
with j.path.open("ab", buffering=0) as f:
    f.write(b'{"stage": "ml", "id": "MLA2"')
    os.fsync(f.fileno())
os._exit(137)
'''
    env = {**os.environ, "PYTHONPATH": str(Path(catalog_auto.__file__).parent)}
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=env)
    assert result.returncode == 137
    journal = BuscarLog(tmp_path, "2026-11-09")
    assert set(journal.resolved("ml")) == {"MLA1"}
    journal.append("ml", "MLA2", "sin_precio")
    assert set(BuscarLog(tmp_path, "2026-11-09").resolved("ml")) == {"MLA1", "MLA2"}
    assert all(json.loads(raw)["at"].endswith("-03:00") for raw in journal.path.read_text().splitlines())


def test_alta_persiste_antes_de_pedir_siguiente_foto(tmp_path, monkeypatch):
    rows = [candidate(), candidate(asin="B000000002", slug="samsung-otro", name="Samsung T8", amazonTitle="Samsung T8")]
    def photo(entry, output):
        if entry["asin"] == "B000000002":
            assert json.loads((tmp_path / "altas-pendientes.json").read_text())[0]["asin"] == rows[0]["asin"]
            raise KeyboardInterrupt()
        return True
    monkeypatch.setattr(catalog_auto, "fetch_photo", photo)
    with pytest.raises(KeyboardInterrupt):
        catalog_auto.add_accepted([{"slug": "base", "category": "Almacenamiento"}], {"accepted": rows}, tmp_path, "2026-11-09")
    photos = []
    monkeypatch.setattr(catalog_auto, "fetch_photo", lambda row, out: photos.append(row["asin"]) or True)
    catalog_auto.add_accepted([{"slug": "base", "category": "Almacenamiento"}], {"accepted": rows}, tmp_path, "2026-11-09")
    assert photos == [rows[1]["asin"]]
    assert len(json.loads((tmp_path / "altas-pendientes.json").read_text())) == 2


def test_error_inesperado_por_fila_no_pierde_el_resto(tmp_path, monkeypatch):
    rows = [candidate(), candidate(asin="B000000002", slug="samsung-otro", name="Samsung T8", amazonTitle="Samsung T8")]
    def photo(entry, output):
        if entry["asin"] == rows[0]["asin"]:
            raise IndexError("foto inválida")
        return True
    monkeypatch.setattr(catalog_auto, "fetch_photo", photo)
    added, failures = catalog_auto.add_accepted([{"slug": "base", "category": "Almacenamiento"}], {"accepted": rows}, tmp_path, "2026-11-09")
    assert [r["asin"] for r in added] == [rows[1]["asin"]]
    assert failures[0]["motivo"] == "IndexError"


def test_discovery_reanuda_sin_redescargar_resueltos(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "scraper_pause", lambda: None)
    monkeypatch.setattr(discovery.ml_prices, "pause", lambda: None)
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return {"items": [{"asin": asin, "title": "Samsung 990 PRO 1TB", "price": 150} for asin in ("A", "B")]}
    page_visits = []
    def get(*a, **k):
        page_visits.append(a)
        return Response()
    visits = []
    def search(query):
        visits.append(query)
        if len(visits) == 2:
            raise KeyboardInterrupt()
        return []
    monkeypatch.setattr(discovery.ml_prices, "search_products", search)
    dest = tmp_path / "discovery.json"
    kwargs = dict(categories=[{"id": "pc", "name": "Computers"}], get=get, existing_asins=set())
    with pytest.raises(KeyboardInterrupt):
        discovery.discover_products("unused", dest, **kwargs)
    journal = BuscarLog(tmp_path)
    assert set(journal.resolved("amazon")) == {"A"}
    result = discovery.discover_products("unused", dest, **kwargs)
    assert [r["asin"] for r in result] == ["A", "B"]
    assert len(visits) == 3 and len(page_visits) == 1
    assert capsys.readouterr().out.count("BUSCAR_AMAZON asin=A estado=sin_pares") == 1


def test_matching_guarda_decision_y_reutiliza_ficha(tmp_path, monkeypatch, capsys):
    journal = BuscarLog(tmp_path)
    calls = []
    monkeypatch.setattr(matching.ml_prices, "get_json", lambda path: calls.append(path) or {})
    monkeypatch.setattr(matching.ml_prices, "pause", lambda: None)
    products = [{"asin": asin, "amazonTitle": "Samsung 990 PRO", "ml": [{"catalogId": "MLA1"}]} for asin in ("A", "B")]
    def decided(status, row):
        if row["asin"] == "B":
            raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        matching.match_products(products, 1000, journal=journal, on_result=decided)
    journal = BuscarLog(tmp_path)
    assert set(journal.resolved("match")) == {"A"}
    matching.match_products(products[1:], 1000, journal=journal)
    assert calls == ["/products/MLA1"]
    assert set(BuscarLog(tmp_path).resolved("match")) == {"A", "B"}
    assert "MATCH asin=A" in capsys.readouterr().out


def test_identificadores_durables_y_error_visible(tmp_path, capsys):
    journal = BuscarLog(tmp_path)
    rows = [{"asin": "A"}]
    assert ml.agregar_identificadores(rows, lambda asins: {"A": {"identifiers": {"upc": "123"}}}, journal=journal) == 1
    def no_network(asins):
        pytest.fail("No debe volver a descargar el ASIN resuelto")
    assert ml.agregar_identificadores(rows, no_network, journal=BuscarLog(tmp_path)) == 1
    assert ml.agregar_identificadores([{"asin": "B"}], lambda asins: {}, journal=journal) == 0
    assert "IDENT asin=B estado=error" in capsys.readouterr().out
    assert "B" not in BuscarLog(tmp_path).resolved("ident")


def test_crecer_devuelve_error_y_reconoce_running_abandonado(tmp_path, monkeypatch):
    import worker
    logs = worker.DailyLog(tmp_path / "logs", io.StringIO())
    monkeypatch.setattr(sys, "stdout", logs)
    monkeypatch.setattr(crecer_ahora.rates, "get_rates", lambda: {"mep": 1000})
    monkeypatch.setattr(catalog_auto.ml_prices, "is_configured", lambda: False)
    (tmp_path / "catalog-auto-state.json").write_text(json.dumps({"status": "running", "slot": "2026-11-09", "ultimoCatalogId": "MLA1"}))
    assert crecer_ahora.main(tmp_path, "unused") == 1
    state = json.loads((tmp_path / "catalog-auto-state.json").read_text())
    assert state["status"] == "failed" and state["interruptedAt"]
    text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "logs").glob("worker-*.log"))
    assert "CATALOGO_INTERRUMPIDO" in text and "CATALOGO_ERROR" in text


def test_categoria_fallida_no_se_confunde_con_vacia(tmp_path, monkeypatch, capsys):
    import requests
    class Response:
        def raise_for_status(self):
            raise requests.HTTPError("HTTP 429")
    monkeypatch.setattr(ml, "_get", lambda path: Response())
    assert ml.categorias("MLA1", journal=BuscarLog(tmp_path)) == ["MLA1"]
    assert BuscarLog(tmp_path).resolved("categoria_error")
    assert "BUSCAR_CATEGORIA id=MLA1 estado=error" in capsys.readouterr().out


def test_buscar_completo_kill_entre_ids_y_reanudacion(tmp_path, monkeypatch):
    import worker
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([{"asin": "EXISTENTE", "slug": "existente", "category": "Almacenamiento"}]))
    catalog_auto.publicacion.guardar(tmp_path, {})
    monkeypatch.setattr(catalog_auto.ml_prices, "is_configured", lambda: True)
    monkeypatch.setattr(discovery, "discover_categories", lambda **kw: [])
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **kw: {"MLA1": "pc", "MLA2": "pc"})
    monkeypatch.setattr(catalog_auto.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(catalog_auto.ml_prices, "pause", lambda: None)
    visits = []
    def fetch(pid):
        visits.append(pid)
        if pid == "MLA2" and visits.count(pid) == 1:
            # La primera alta ya debe estar en disco antes de consultar este ID.
            assert len(json.loads((tmp_path / "altas-pendientes.json").read_text())) == 1
            raise KeyboardInterrupt()
        return [{"price": 200000, "condition": "new", "id": "MLA456"}]
    monkeypatch.setattr(catalog_auto.ml_prices, "fetch_items", fetch)
    ficha = {"name": "Samsung 990 PRO 1TB", "domain_id": "MLA-SOLID_STATE_DRIVES", "attributes": [
        {"id": "BRAND", "value_name": "Samsung"}, {"id": "MODEL", "value_name": "990 PRO"},
        {"id": "ALPHANUMERIC_MODEL", "value_name": "MZ-V9P1T0B"}]}
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return ficha
    monkeypatch.setattr(ml, "_get", lambda *a, **k: Response())
    monkeypatch.setattr(catalog_auto.amazon_prices, "fetch_ar_shipping", lambda *a: {
        "B000000001": {"identifiers": {"model_number": "MZ-V9P1T0B"}}})
    def get(*a, **kw):
        class Page(Response):
            def json(self):
                return {"items": [{"asin": "B000000001", "title": "Samsung 990 PRO 1TB MZ-V9P1T0B", "price": 150}]}
        return Page()
    monkeypatch.setattr(catalog_auto.requests, "get", get)
    monkeypatch.setattr(catalog_auto, "fetch_photo", lambda *a: True)
    log_stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", worker.DailyLog(tmp_path / "logs", log_stream))
    now = datetime.fromisoformat("2026-11-09T04:00:00-03:00")
    try:
        catalog_auto.maybe_grow(catalog, tmp_path, now, mep=1000)
    except KeyboardInterrupt:
        pass
    else:
        pytest.fail(log_stream.getvalue())
    first = BuscarLog(tmp_path, "2026-11-09")
    assert set(first.resolved("ml")) == {"MLA1"}
    assert set(first.resolved("match")) == {"B000000001"}
    assert catalog_auto.maybe_grow(catalog, tmp_path, now, mep=1000)
    assert visits == ["MLA1", "MLA2", "MLA2"]
    state = json.loads((tmp_path / "catalog-auto-state.json").read_text())
    assert state["status"] == "ok" and state["resolvedMl"] == 2
    assert state["added"] == 1
    assert len(json.loads((tmp_path / "altas-pendientes.json").read_text())) == 1
    text = "".join(p.read_text(encoding="utf-8") for p in (tmp_path / "logs").glob("worker-*.log"))
    for marker in ("BUSCAR_ML id=MLA1", "BUSCAR_ML id=MLA2", "MATCH asin=B000000001", "AMAZON_PAGINA", "CATALOGO_INTERRUMPIDO"):
        assert marker in text


@pytest.mark.parametrize("case,status", [("precio_error", "error_precio"), ("fuera", "fuera_de_rango"), ("ficha_error", "sin_ficha"), ("sin_nombre", "sin_ficha"), ("sin_pares", "sin_resultados")])
def test_ml_todos_los_descartes_tienen_dato_y_log(tmp_path, monkeypatch, capsys, case, status):
    import requests
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **k: {"MLA1": "cat"})
    def fetch(pid):
        if case == "precio_error":
            raise requests.ConnectionError("red caída")
        return [{"price": 100 if case == "fuera" else 200000, "condition": "new", "id": "MLA12"}]
    monkeypatch.setattr(ml.ml_prices, "fetch_items", fetch)
    class Response:
        def raise_for_status(self):
            if case == "ficha_error":
                raise requests.HTTPError("HTTP 503")
        def json(self):
            return {} if case == "sin_nombre" else {"name": "Samsung T9"}
    monkeypatch.setattr(ml, "_get", lambda path: Response())
    class Page:
        def raise_for_status(self):
            pass
        def json(self):
            return {"results": []}
    ml.candidatos(set(), set(), 1000, output=tmp_path, get=lambda *a, **k: Page())
    record = next(r for r in reversed(BuscarLog(tmp_path).records) if r["stage"] == "ml")
    assert ("MLA1" in BuscarLog(tmp_path).resolved("ml")) == (status == "fuera_de_rango")
    assert record["result"] == status and record["reason"]
    assert f"BUSCAR_ML id=MLA1 estado={status}" in capsys.readouterr().out


def test_ident_no_acepta_error_por_asin(tmp_path, capsys):
    assert ml.agregar_identificadores([{"asin": "A"}], lambda asins: {"A": {"error": "bloqueado"}}, journal=BuscarLog(tmp_path)) == 0
    assert "A" not in BuscarLog(tmp_path).resolved("ident")
    assert BuscarLog(tmp_path).resolved("ident_error")["A"]["reason"] == "bloqueado"
    assert "IDENT asin=A estado=error motivo=bloqueado" in capsys.readouterr().out


def test_revision_guardada_antes_del_siguiente_item(tmp_path):
    row = candidate(amazonIds={})
    def items():
        yield row
        assert json.loads((tmp_path / "altas-revision.json").read_text())[0]["asin"] == row["asin"]
        assert BuscarLog(tmp_path, "2026-11-09").resolved("alta")[row["asin"]]["result"] == "revision"
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        catalog_auto.add_accepted([], {"accepted": items()}, tmp_path, "2026-11-09", journal=BuscarLog(tmp_path, "2026-11-09"))


def test_ident_lote_persiste_aciertos_aunque_otro_falle(tmp_path):
    assert ml.agregar_identificadores([{"asin": "A"}, {"asin": "B"}], lambda asins: {
        "A": {"error": "bloqueado"}, "B": {"identifiers": {"upc": "123"}}}, journal=BuscarLog(tmp_path)) == 1
    assert set(BuscarLog(tmp_path).resolved("ident")) == {"B"}


@pytest.fixture(autouse=True)
def _modo_ml_manual(monkeypatch):
    """Estos tests cubren el recorrido ML→Amazon, que en la cadena diaria va apagado."""
    monkeypatch.setenv("CATALOG_AUTO_DESDE_ML", "1")
