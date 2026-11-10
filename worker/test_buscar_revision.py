"""Regresiones de la revisión: diario y recorrido reales; red sustituida."""
from datetime import datetime
import json

import pytest
import requests

import catalog_auto as auto
from buscar_log import BuscarLog
from tools import crecer_desde_ml as ml, discover_products as discovery, match_candidates as matching, cadena
from test_catalog_auto import candidate
from test_cadena import Reloj, Hijo


class Response:
    status_code = 200
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    """maybe_grow completo: categorías, fichas, matching, colas y diario reales."""
    monkeypatch.setenv("ML_CLIENT_ID", "prueba")
    monkeypatch.setenv("ML_CLIENT_SECRET", "prueba")
    monkeypatch.setattr(ml.ml_prices, "get_token", lambda: "prueba")
    monkeypatch.setattr(ml, "RAICES", ("MLA1648",))
    monkeypatch.setattr(discovery, "FALLBACK_CATEGORIES", [])
    monkeypatch.setattr(discovery, "SCRAPER_PAUSE_SECONDS", 0)
    monkeypatch.setattr(auto.amazon_prices, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(auto.amazon_prices, "BACKOFF_SECONDS", 0)
    monkeypatch.setattr(ml.ml_prices, "PAUSE_SECONDS", 0)
    path = tmp_path / "catalog.json"
    path.write_text("[]")
    auto.publicacion.guardar(tmp_path, {})
    from test_match_candidates import product
    data = dict(ids=["MLA1"], ficha=product(), pages=[], ident_error=True, requests=[])

    def get(url, **kw):
        data["requests"].append(url)
        if data.get("on_request"):
            data["on_request"](url)
        if url.endswith("/best-sellers/categories"):
            return Response({"categories": [{"id": "ropa", "name": "Clothing"}]})
        if "/categories/" in url:
            return Response({"children_categories": []})
        if "/highlights/" in url:
            return Response({"content": [{"id": pid, "type": "PRODUCT"} for pid in data["ids"]]})
        if url.endswith("/items"):
            return Response({"results": [{"price": 200000, "condition": "new", "id": "MLA456"}]})
        if url.endswith("/search"):
            if data["pages"]:
                payload = data["pages"].pop(0)
                if isinstance(payload, Exception):
                    raise payload
                return Response(payload)
            pid = len([u for u in data["requests"] if u.endswith("/search")])
            return Response({"results": [{"asin": f"B{pid:09d}", "title": "Samsung 990 PRO SSD 1TB", "price": 150}]})
        if url.endswith("/ar-shipping"):
            raise requests.ConnectionError("identificadores caídos")
        if "/products/" in url:
            if data.get("unique_name"):
                return Response({**data["ficha"], "name": data["ficha"]["name"] + " " + url.rsplit("/", 1)[-1]})
            return Response(data["ficha"])
        raise AssertionError(url)
    monkeypatch.setattr(auto.requests, "get", get)

    def run(day="2026-11-09"):
        auto.maybe_grow(path, tmp_path, datetime.fromisoformat(day + "T04:00:00-03:00"), mep=1000, force=True)
        return json.loads((tmp_path / "catalog-auto-state.json").read_text())
    return data, run


def test_i4_servicio_caido_encola_revision_sin_fatal(tmp_path, pipeline, capsys):
    data, run = pipeline
    assert run()["status"] == "ok"
    assert json.loads((tmp_path / "altas-revision.json").read_text())
    assert "IDENT asin=" in capsys.readouterr().out


def test_i5_dudosos_entran_revision(tmp_path, pipeline):
    # 10/11: proceso 3 de Alejandro (09/11) — los dudosos del matcheo se revisan; antes quedaban sólo en
    # match-results.json y dudosos_nvidia.py (que lee altas-revision.json) nunca los veía.
    from test_match_candidates import product
    data, run = pipeline
    data["ficha"] = product(MODEL=None, ALPHANUMERIC_MODEL=None, name="Samsung SSD 1TB")
    assert run()["status"] == "ok"
    dudosos = json.loads((tmp_path / "match-results.json").read_text())["doubtful"]
    assert dudosos
    cola = json.loads((tmp_path / "altas-revision.json").read_text())
    encolados = [r for r in cola if r.get("motivoRevision") == "dudoso_matcheo"]
    assert {(r["asin"], r["catalogId"]) for r in encolados} == {(r["asin"], r["catalogId"]) for r in dudosos}
    assert all(r["dudas"] and r["revisionDesde"] for r in encolados)


def test_m6_slugs_revision_distintos_incluso_al_reanudar(tmp_path, pipeline):
    data, run = pipeline
    data["ids"] = ["MLA1", "MLA2"]
    run()
    rows = json.loads((tmp_path / "altas-revision.json").read_text())
    assert len(rows) >= 2
    assert len({r["slug"] for r in rows}) == len(rows)
    data["ids"] = ["MLA3"]
    run("2026-11-10")
    rows2 = json.loads((tmp_path / "altas-revision.json").read_text())
    assert len(rows2) > len(rows) and len({r["slug"] for r in rows2}) == len(rows2)


@pytest.mark.parametrize("empty,total,failed", [(3, 10, False), (4, 10, True)])
def test_i6_umbral_paginas_de_la_corrida(tmp_path, pipeline, empty, total, failed):
    data, run = pipeline
    # La página de categorías es válida; una consulta por producto.
    data["ids"] = [f"MLA{i}" for i in range(total - 1)]
    data["ficha"] = {"name": "Samsung T9"}
    data["unique_name"] = True
    data["pages"] = [{"results": []}] * empty + [{"results": [{"asin": "duplicado", "title": "fuera", "price": 1}]}] * (total - 1 - empty)
    assert (run()["status"] == "failed") == failed


def test_m3_limite_paginas_termina_ok(tmp_path, pipeline, monkeypatch):
    monkeypatch.setenv("CATALOG_AUTO_MAX_PAGES", "0")
    _, run = pipeline
    state = run()
    assert state["status"] == "ok" and state["motivoFin"] == "limite_paginas"


def test_i7_plazo_cooperativo_guarda_y_deja_reanudar(tmp_path, pipeline, monkeypatch):
    import buscar_log
    data, run = pipeline
    data["ids"] = ["MLA1", "MLA2"]
    monkeypatch.setenv("BUSCAR_DEADLINE", "100")
    monkeypatch.setattr(buscar_log.time, "time", lambda: 0)
    def stop_after_first(url):
        if url.endswith("/MLA2/items"):
            monkeypatch.setattr(buscar_log.time, "time", lambda: 100)
    data["on_request"] = stop_after_first
    state = run()
    assert state["status"] == "ok" and state["motivoFin"] == "plazo_buscar"
    assert "MLA1" in BuscarLog(tmp_path, "2026-11-09").resolved("ml")
    first_rows = json.loads((tmp_path / "altas-revision.json").read_text())
    assert first_rows
    monkeypatch.delenv("BUSCAR_DEADLINE")
    assert run()["status"] == "ok"
    assert BuscarLog(tmp_path, "2026-11-09").resolved("match")
    assert "MLA2" in BuscarLog(tmp_path, "2026-11-09").resolved("ml")
    assert json.loads((tmp_path / "altas-revision.json").read_text()) == first_rows


def test_i1_matching_error_se_reintenta_sin_decision_durable(tmp_path, monkeypatch):
    from test_match_candidates import amazon, product
    visits = []
    def get(path):
        visits.append(path)
        if len(visits) == 1:
            raise requests.Timeout("timeout ficha")
        return product()
    monkeypatch.setattr(matching.ml_prices, "get_json", get)
    monkeypatch.setattr(matching.ml_prices, "pause", lambda: None)
    matching.match_products([amazon()], 1000, journal=BuscarLog(tmp_path))
    assert not BuscarLog(tmp_path).resolved("match")
    assert BuscarLog(tmp_path).resolved("match_error")
    matching.match_products([amazon()], 1000, journal=BuscarLog(tmp_path))
    assert len(visits) == 2 and BuscarLog(tmp_path).resolved("match")


def test_i1_amazon_sin_ml_por_error_no_queda_rechazado(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "scraper_pause", lambda: None)
    monkeypatch.setattr(discovery.ml_prices, "pause", lambda: None)
    visits = []
    def search(query):
        visits.append(query)
        if len(visits) == 1:
            raise requests.ConnectionError("ML caído")
        return []
    monkeypatch.setattr(discovery.ml_prices, "search_products", search)
    journal = BuscarLog(tmp_path)
    def process(row):
        matching.match_products([row], 1000, journal=journal)
    args = dict(categories=[{"id": "pc", "name": "Computers"}], existing_asins=set(),
        get=lambda *a, **k: Response({"items": [{"asin": "A", "title": "Samsung 990 PRO", "price": 150}]}),
        journal=journal, on_product=process)
    discovery.discover_products("unused", tmp_path / "discovery.json", **args)
    assert not journal.resolved("amazon") and not journal.resolved("match")
    discovery.discover_products("unused", tmp_path / "discovery.json", **args)
    assert len(visits) == 2 and journal.resolved("amazon")


def test_i2_pagina_invalida_no_impide_revisar_siguiente_producto(tmp_path, pipeline):
    data, run = pipeline
    data["ids"] = ["MLA1", "MLA2"]
    data["ficha"] = {"name": "Samsung T9"}
    data["pages"] = [[], [], {"results": [{"asin": "A", "title": "fuera", "price": 1}]}]
    assert run()["status"] == "failed"  # 2/4 páginas inválidas; el recorrido igual continúa.
    journal = BuscarLog(tmp_path, "2026-11-09")
    assert "MLA1" not in journal.resolved("ml")
    assert journal.resolved("ml")["MLA2"]["result"] == "sin_pares"


def test_i8_par_sin_matching_no_se_salta_al_dia_siguiente(tmp_path):
    journal = BuscarLog(tmp_path, "2026-11-08")
    journal.append("ml", "MLA1", "con_pares", pairs=[{"asin": "A"}])
    journal.append("match_error", "A", "error", "HTTP 503")
    assert "MLA1" not in BuscarLog(tmp_path, "2026-11-09").resolved("ml")
    journal.append("match", "A", "doubtful", row={"asin": "A"})
    assert "MLA1" in BuscarLog(tmp_path, "2026-11-09").resolved("ml")


def test_i7_cadena_da_deadline_y_continua_despues_de_buscar(tmp_path):
    # 10/11: el alta diaria es el barrido (buscar/crecer_ahora queda manual; su BUSCAR_DEADLINE lo cubre
    # test_cadena.test_buscar_tiene_plazo_propio_sin_corte_interno). La cadena sigue hasta altas y no cruza el día.
    clock = Reloj()
    commands = []
    def spawn(command, **kw):
        commands.append(command)
        out = "DEPLOY_SKIP\n" if "/app/deploy.mjs" in command else "ALTAS_OK promovidas=0 vencidos=0\n"
        return Hijo(clock, seconds=1, out=out)
    runner = cadena.Cadena(tmp_path, spawn, clock.clock, clock.now, clock.sleep)
    assert runner.run() == 0
    records = runner.summary["pasos"]
    assert [r["estado"] for r in records if r["paso"].startswith("alta:barrido_")] == ["ok", "ok", "ok"]
    assert any(r["paso"] == "alta:altas" and r["estado"] == "ok" for r in records)
    assert not any("crecer_ahora.py" in arg for c in commands for arg in c)
    assert clock.now().date().isoformat() == runner.fecha


def test_i7_cadena_frena_antes_de_medianoche(tmp_path, monkeypatch):
    clock = Reloj()
    commands = []
    def spawn(command, **kw):
        commands.append(command)
        return Hijo(clock, seconds=1 if len(commands) < 3 else 10000)
    runner = cadena.Cadena(tmp_path, spawn, clock.clock, clock.now, clock.sleep)
    runner.alta_deadline = 50  # Mismo mecanismo de plazo absoluto, a 50 s del cierre.
    monkeypatch.setattr(cadena.os, "killpg", lambda *a: None, raising=False)
    # Los hijos falsos tienen kill local; POSIX no participa en este test.
    monkeypatch.setattr(cadena.os, "name", "nt")
    assert runner.run() == 1
    assert clock.clock() == 50
    assert not any("crecer_ahora.py" in arg for c in commands for arg in c)


@pytest.mark.parametrize("stage,status", [("ml", "error_precio"), ("ml", "sin_ficha"),
    ("ml", "sin_resultados"), ("amazon", "error"), ("ficha_ml", "sin_ficha")])
def test_i1_transitorios_no_resueltos(tmp_path, stage, status):
    journal = BuscarLog(tmp_path)
    journal.append(stage, "A", status, "red caída")
    assert "A" not in BuscarLog(tmp_path).resolved(stage)


def test_i2_respuesta_mala_no_corta_producto_siguiente(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **kw: {"A": "pc", "B": "pc"})
    monkeypatch.setattr(ml.ml_prices, "fetch_items", lambda pid: [{"price": 200000, "condition": "new", "id": "MLA1"}])
    monkeypatch.setattr(ml, "_get", lambda path: Response({"name": "Samsung T9"}))
    responses = iter([Response([]), Response({"results": []})])
    failures = []
    ml.candidatos(set(), set(), 1000, output=tmp_path, failures=failures, get=lambda *a, **k: next(responses))
    assert failures
    assert {r["id"] for r in BuscarLog(tmp_path).records if r["stage"] == "ml"} == {"A", "B"}


def test_i3_categoria_fallida_sigue_y_cuenta(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "RAICES", ("A", "B"))
    def get(path):
        if path.endswith("/A"):
            raise requests.HTTPError("HTTP 503")
        return Response({"children_categories": [], "content": [{"type": "PRODUCT", "id": "MLA1"}]})
    monkeypatch.setattr(ml, "_get", get)
    journal = BuscarLog(tmp_path)
    failures = []
    assert "MLA1" in ml.mas_vendidos_ml(set(), journal=journal, failures=failures)
    assert failures and journal.resolved("categoria_error")


@pytest.mark.parametrize("payload", [{}, {"A": {"error": "bloqueado"}}])
def test_i4_identificador_fallido_conserva_par(tmp_path, payload):
    rows = [{"asin": "A"}]
    journal = BuscarLog(tmp_path)
    assert ml.agregar_identificadores(rows, lambda asins: payload, journal=journal) == 0
    assert rows[0]["amazonIds"] == {} and "A" not in journal.resolved("ident")


def test_i6_todas_vacias_reintenta(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **kw: {"A": "pc"})
    visits = []
    monkeypatch.setattr(ml.ml_prices, "fetch_items", lambda pid: visits.append(pid) or [{"price": 200000, "condition": "new", "id": "MLA1"}])
    monkeypatch.setattr(ml, "_get", lambda path: Response({"name": "Samsung T9"}))
    for _ in range(2):
        ml.candidatos(set(), set(), 1000, output=tmp_path, get=lambda *a, **k: Response({"results": []}))
    assert visits == ["A", "A"]
    assert BuscarLog(tmp_path).records[-1]["result"] == "sin_resultados"


def test_i8_ventana_siete_dias(tmp_path):
    for day, identity, result in [("2026-11-02", "vencido", "fuera_de_rango"),
                                  ("2026-11-03", "vigente", "fuera_de_rango"),
                                  ("2026-11-08", "transitorio", "error_precio")]:
        BuscarLog(tmp_path, day).append("ml", identity, result)
    assert set(BuscarLog(tmp_path, "2026-11-09").resolved("ml")) == {"vigente"}


def test_m1_offers_cubre_red_lenta(tmp_path):
    clock = Reloj()
    child = Hijo(clock, seconds=210)
    runner = cadena.Cadena(tmp_path, lambda *a, **k: child, clock.clock, clock.now, clock.sleep)
    runner.step("offers", cadena.OFFERS_TIMEOUT)
    assert runner.summary["pasos"][-1]["estado"] == "ok"


def test_m2_alta_manual_no_escribe_buscar(tmp_path):
    auto.add_accepted([], {"accepted": [candidate(amazonIds={})]}, tmp_path, "2026-11-09")
    assert not list(tmp_path.glob("buscar-*.jsonl"))


def test_m2_diario_corrupto_se_conserva_y_recupera(tmp_path):
    path = tmp_path / "buscar-2026-11-09.jsonl"
    path.write_text('{"stage":"ml","id":"A","result":"sin_precio"}\nroto\n{"stage":"ml","id":"B","result":"sin_precio"}\n')
    journal = BuscarLog(tmp_path, "2026-11-09")
    assert list(tmp_path.glob("*.corrupto-*"))
    assert set(journal.resolved("ml")) == {"A", "B"}


def test_m3_presupuesto_corta_ordenado(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **kw: {"A": "pc"})
    monkeypatch.setattr(ml.ml_prices, "fetch_items", lambda pid: [{"price": 200000, "condition": "new", "id": "MLA1"}])
    monkeypatch.setattr(ml, "_get", lambda path: Response({"name": "Samsung T9"}))
    def exhausted(*a, **k):
        raise discovery.PageBudgetExhausted()
    journal = BuscarLog(tmp_path)
    assert ml.candidatos(set(), set(), 1000, journal=journal, get=exhausted) == []
    assert "A" not in journal.resolved("ml")


def test_i7_m3_no_pierde_consulta_positiva_al_cortar(tmp_path, monkeypatch):
    monkeypatch.setattr(ml, "mas_vendidos_ml", lambda *a, **kw: {"A": "pc"})
    monkeypatch.setattr(ml.ml_prices, "fetch_items", lambda pid: [{"price": 200000, "condition": "new", "id": "MLA1"}])
    monkeypatch.setattr(ml, "_get", lambda path: Response({"name": "Samsung T9 SSD", "attributes": [
        {"id": "BRAND", "value_name": "Samsung"}, {"id": "MODEL", "value_name": "T9"}]}))
    calls = []
    def get(url, **kw):
        calls.append(kw["params"]["query"])
        if len(calls) == 2:
            raise discovery.PageBudgetExhausted()
        return Response({"results": [{"asin": "A", "title": "Samsung T9 SSD", "price": 150}]})
    ml.candidatos(set(), set(), 1000, journal=BuscarLog(tmp_path), get=get)
    assert BuscarLog(tmp_path).resolved("amazon_busqueda") and not BuscarLog(tmp_path).resolved("ml")
    rows = ml.candidatos(set(), set(), 1000, journal=BuscarLog(tmp_path), get=get)
    assert calls == ["Samsung T9 SSD", "Samsung T9", "Samsung T9"]
    assert rows and rows[0]["asin"] == "A"


def test_m4_indice_incremental_no_recorre_historial(tmp_path):
    journal = BuscarLog(tmp_path)
    journal.append("ml", "A", "sin_precio")
    class NoScan(list):
        def __iter__(self):
            raise AssertionError("Recorrido completo del diario")
    journal.records = NoScan(journal.records)
    assert "A" in journal.resolved("ml")
    journal.append("ml", "B", "fuera_de_rango")
    assert len(journal.resolved("ml")) == 2


def test_m5_salteos_tienen_log(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "scraper_pause", lambda: None)
    discovery.collect_amazon_candidates(set(), categories=[{"id": "ropa", "name": "Clothing"}], journal=BuscarLog(tmp_path))
    matching.match_products([{"asin": "A", "ml": [None]}], 1000)
    log = capsys.readouterr().out
    assert "departamento_excluido" in log and "candidato_invalido" in log


def test_i2_m5_error_categoria_amazon_registra_y_sigue(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(discovery, "scraper_pause", lambda: None)
    visits = []
    def get(url, **kw):
        cat = kw["params"]["category"]
        visits.append(cat)
        if cat == "mala":
            raise ValueError("JSON inválido")
        return Response({"items": [{"asin": "A", "title": "Samsung T9 SSD", "price": 150}]})
    journal, failures = BuscarLog(tmp_path), []
    rows = discovery.collect_amazon_candidates(set(), categories=["mala", "buena"], get=get, journal=journal, failures=failures)
    assert visits == ["mala", "buena"] and rows[0]["asin"] == "A"
    assert len(failures) == 1 and "mala" in journal.resolved("amazon_error")
    assert "BUSCAR_AMAZON categoria=mala estado=error motivo=JSON inválido" in capsys.readouterr().out


def test_i8_filtros_definitivos_tambien_duran_siete_dias(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "scraper_pause", lambda: None)
    journal = BuscarLog(tmp_path, "2026-11-08")
    discovery.collect_amazon_candidates({"duplicado"}, categories=["pc"], journal=journal,
        get=lambda *a, **k: Response({"items": [
            {"asin": "barato", "title": "Samsung T9 SSD", "price": 1},
            {"asin": "duplicado", "title": "Samsung T9 SSD", "price": 150}]}))
    # El existente/duplicado no se graba como resuelto: su aparición válida no puede quedar salteada 7 días.
    assert set(BuscarLog(tmp_path, "2026-11-09").resolved("amazon")) == {"barato"}


@pytest.fixture(autouse=True)
def _modo_ml_manual(monkeypatch):
    """Estos tests cubren el recorrido ML→Amazon, que en la cadena diaria va apagado."""
    monkeypatch.setenv("CATALOG_AUTO_DESDE_ML", "1")
