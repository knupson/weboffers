"""Contratos de lookup con fixtures sintéticos y red prohibida."""
import json
import requests
import pytest

from . import ml_lookup
from .config import Config
from .currency import StaleRate
from .events import now_art
from .ml_lookup import MLClient, amazon_rows, build_queries, run_ml_lookup
from .state import LookupState


def today():
    return now_art().date().isoformat()


def rate(*args):
    return dict(value=.001, source="MEP fixture", observed_at=today() + "T12:00:00-03:00")


def amazon(identity="B0FIXTURE1", **fields):
    return dict(dict(store="US", id=identity, date=today(), title='Samsung 27" Essential S3 (S36GD) Series FHD Curved Monitor',
                     price_usd=200, shipping_class="gratis", raw={}), **fields)


def write_input(path, rows, store="US"):
    path.mkdir(parents=True, exist_ok=True)
    (path / f"{store}-{today()}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_output(path):
    return [json.loads(line) for line in (path / f"ml-candidatos-{today()}.jsonl").read_text(encoding="utf-8").splitlines()]


def fixture_client(fixture_dir, calls=None, delays=None):
    calls = calls if calls is not None else []
    clock = [0.0]
    def sleep(seconds):
        clock[0] += seconds
        if delays is not None:
            delays.append(seconds)
    def get(path, params=None):
        calls.append((path, params))
        name = "ml_lookup.json" if path == "/products/search" else "ml_items.json"
        body = json.loads((fixture_dir / name).read_text(encoding="utf-8"))
        return body["search"] if name == "ml_lookup.json" else body
    return MLClient(Config(ml_pause=.7), get=get, sleep=sleep, clock=lambda: clock[0])


def test_queries_modelo_antes_de_limpiar_parentesis(fixture_dir):
    data = json.loads((fixture_dir / "ml_lookup.json").read_text(encoding="utf-8"))
    for example in data["titles"]:
        queries = build_queries(example["title"])
        assert queries[0] == example["query"]
        assert len(queries) == len(set(queries))
    assert build_queries("") == []


def test_oferta_local_nueva_mep_y_reanudacion_sin_duplicados(tmp_path, fixture_dir, capsys):
    write_input(tmp_path, [amazon(), amazon()])
    calls, delays = [], []
    client = fixture_client(fixture_dir, calls, delays)
    result = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    expected = dict(status="complete", total=1, con_candidatos=1, sin_resultados=0, errores=0,
                         requests_ml=2, requests_ml_por_producto=2, items_404=0,
                         productos_procesados=1, productos_con_candidato=1, alcance_metricas='ejecucion_actual')
    assert all(result[key] == value for key, value in expected.items())
    row = read_output(tmp_path)[0]
    assert row["candidates"] == [dict(catalogId="MLAFIXTURE1", name="Monitor Samsung S36GD", price_ars=200000,
                                      price_usd=200, itemId="MLA1001", condition="new")]
    assert set(row) == set("store asin amazon_title amazon_price_usd shipping_class queries_used candidates lookup_status error".split())
    assert calls[0] == ("/products/search", dict(status="active", site_id="MLA", q="Samsung S36GD"))
    assert delays == [.7]
    resumed = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=lambda *a: pytest.fail("Tasa ya congelada"))
    assert resumed['requests_ml'] == resumed['productos_procesados'] == 0
    assert resumed['requests_ml_por_producto'] is None
    assert len(calls) == 2 and len(read_output(tmp_path)) == 1
    lines = capsys.readouterr().out.splitlines()
    assert all("-03:00 " in line for line in lines)
    assert any("BARRIDO_ML_BUSQUEDA" in line for line in lines)
    assert any("BARRIDO_ML_OK" in line for line in lines)


def test_filtro_y_mismo_asin_en_ambas_tiendas(tmp_path):
    write_input(tmp_path, [amazon(), amazon("A2", shipping_class="desconocido"),
        amazon("A3", shipping_class="pago"), amazon("A4", shipping_class="no_envia"),
        amazon("A5", price_usd=99), amazon("A6", price_usd=401),
        amazon("A7", shipping_class="envia_costo_desconocido"), amazon("A8", date="2000-01-01"),
        amazon("A9", price_usd=None), amazon("A10", price_usd=100), amazon("A11", price_usd=400)])
    write_input(tmp_path, [amazon(store="ES")], store="ES")
    rows = list(amazon_rows(tmp_path, today(), Config()))
    assert [(row["store"], row["id"]) for row in rows] == [("US", "B0FIXTURE1"), ("US", "A2"), ("US", "A10"), ("US", "A11"), ("ES", "B0FIXTURE1")]


@pytest.mark.parametrize("http", [403, 429])
def test_bloqueo_corta_y_reanuda_el_asin_fallido(tmp_path, fixture_dir, capsys, http):
    write_input(tmp_path, [amazon(), amazon("B0FIXTURE2")])
    calls = []
    def get(path, params=None):
        calls.append(path)
        response = requests.Response()
        response.status_code, response._content = http, b'bloqueo literal\nsegunda linea'
        raise requests.HTTPError(f"{http} literal", response=response)
    client = MLClient(Config(), get=get, sleep=lambda _: None)
    result = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    assert result["status"] == "blocked"
    assert len(calls) == (Config().ml_consecutive_429 if http == 429 else 1)
    assert read_output(tmp_path)[0]["error"] == f"{http} literal: bloqueo literal\nsegunda linea"
    assert "BARRIDO_ML_BLOQUEADO" in capsys.readouterr().out
    run_ml_lookup(Config(), tmp_path, client=fixture_client(fixture_dir), rate_loader=rate)
    rows = read_output(tmp_path)
    assert len(rows) == 2 and all(row["lookup_status"] == "ok" for row in rows)


def test_fallback_titulo_y_corte_en_primera_oferta(tmp_path):
    write_input(tmp_path, [amazon()])
    class Client:
        def __init__(self):
            self.queries, self.offers = [], []
        def search(self, query):
            self.queries.append(query)
            return [] if len(self.queries) == 1 else [dict(id=f"MLA{i}", name="Monitor Samsung S36GD") for i in range(9)]
        def cheapest(self, identity):
            self.offers.append(identity)
            return 500000, "MLA1001"
    client = Client()
    run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    row = read_output(tmp_path)[0]
    assert row["queries_used"] == client.queries and len(client.queries) == 2
    assert len(client.offers) == len(row["candidates"]) == 1
    assert row["candidates"][0]["price_usd"] == 500  # El rango filtra Amazon, no ML.


def test_dry_run_limit_no_escribe_ni_checkpoint(tmp_path, fixture_dir):
    write_input(tmp_path, [amazon(), amazon("B0FIXTURE2")])
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    result = run_ml_lookup(Config(), tmp_path, dry_run=True, limit=1, client=fixture_client(fixture_dir), rate_loader=rate)
    assert result["total"] == 1
    assert {path.name: path.read_bytes() for path in tmp_path.iterdir() if path.name != 'latido.json'} == before
    assert (tmp_path / 'latido.json').exists()  # El dry-run también deja telemetría.


def test_recupera_registro_si_corta_antes_de_materializar(tmp_path, fixture_dir, monkeypatch):
    write_input(tmp_path, [amazon()])
    original = LookupState.materialize_jsonl
    def crash(self):
        if self.records():
            raise OSError("corte fixture")
        return original(self)
    monkeypatch.setattr(LookupState, "materialize_jsonl", crash)
    with pytest.raises(OSError, match="corte fixture"):
        run_ml_lookup(Config(), tmp_path, client=fixture_client(fixture_dir), rate_loader=rate)
    monkeypatch.setattr(LookupState, "materialize_jsonl", original)
    calls = []
    run_ml_lookup(Config(), tmp_path, client=fixture_client(fixture_dir, calls), rate_loader=rate)
    assert not calls and len(read_output(tmp_path)) == 1


def test_sin_resultados_error_literal_y_tasa_ausente(tmp_path, capsys):
    write_input(tmp_path, [amazon(), amazon("B0FIXTURE2")])
    def get(path, params=None):
        if params["q"] == "Samsung S36GD":
            return dict(results=[])
        raise ValueError("respuesta inválida literal")
    result = run_ml_lookup(Config(), tmp_path, client=MLClient(Config(), get=get, sleep=lambda _: None), rate_loader=rate)
    assert result["errores"] == 2
    assert all(row["error"] == "respuesta inválida literal" for row in read_output(tmp_path))
    assert "BARRIDO_ML_ERROR" in capsys.readouterr().out
    client = MLClient(Config(), get=lambda *a, **kw: dict(results=[]), sleep=lambda _: None)
    result = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    assert result["sin_resultados"] == 2 and result["errores"] == 0
    def stale(*args):
        raise StaleRate("MEP de hoy ausente literal")
    with pytest.raises(StaleRate, match="MEP de hoy ausente literal"):
        run_ml_lookup(Config(), tmp_path / "otro", client=client, rate_loader=stale)


def test_ofertas_paginadas(fixture_dir):
    offsets = []
    def get(path, params=None):
        offsets.append(params["offset"])
        return dict(results=[dict(price=200 if params["offset"] == 0 else 150,
                                  currency_id="ARS", condition="new", item_id="MLA1001")], paging=dict(total=2))
    client = MLClient(Config(), get=get, sleep=lambda _: None)
    assert client.cheapest("MLAFIXTURE1") == (150, "MLA1001")
    assert offsets == [0, 1]


def test_limite_parcial_y_reanudacion_mismo_asin_us_es(tmp_path, fixture_dir):
    write_input(tmp_path, [amazon(), amazon("B0FIXTURE2")])
    write_input(tmp_path, [amazon(store="ES")], store="ES")
    result = run_ml_lookup(Config(), tmp_path, limit=1, client=fixture_client(fixture_dir), rate_loader=rate)
    assert result["status"] == "partial" and result["total"] == 1
    result = run_ml_lookup(Config(), tmp_path, client=fixture_client(fixture_dir), rate_loader=rate)
    assert result["status"] == "complete" and result["total"] == 3
    rows = read_output(tmp_path)
    assert {(row["store"], row["asin"]) for row in rows} == {("US", "B0FIXTURE1"), ("US", "B0FIXTURE2"), ("ES", "B0FIXTURE1")}


def test_cli_step_fecha_y_limit(monkeypatch, tmp_path):
    from . import __main__ as cli
    calls = []
    monkeypatch.setattr(cli, "run_ml_lookup", lambda *a, **kw: calls.append(kw) or dict(status="complete"))
    assert cli.main(["--step", "ml-lookup", "--date", today(), "--limit", "2", "--dry-run", "--output", str(tmp_path)]) == 0
    assert calls == [dict(date=today(), limit=2, dry_run=True, catalog_path='/app/data/catalog.json', catalog_auto_path=None)]
    with pytest.raises(SystemExit):
        cli.main(["--store", "ML"])


def test_mep_del_viernes_sirve_el_domingo_pero_no_a_los_4_dias():
    # PRODUCT.md: dólar MEP con respaldo de hasta 3 días. Caso real: domingo 08/11 00:10, MEP del viernes.
    import pytest
    from .currency import validate_rate, StaleRate, MEP_MAX_DIAS
    rate = {'value': 1 / 1587.9, 'source': 'dolarapi bolsa', 'observed_at': '2026-11-07T21:00:00.000Z'}
    assert validate_rate(rate, '2026-11-08', MEP_MAX_DIAS) is rate
    with pytest.raises(StaleRate):
        validate_rate(rate, '2026-11-12', MEP_MAX_DIAS)
    with pytest.raises(StaleRate):
        validate_rate(rate, '2026-11-08')  # euro de España: sigue exigiendo el mismo día
