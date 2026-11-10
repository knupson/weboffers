"""Segunda ronda: fixtures locales; conftest prohíbe la red en toda la suite."""
from datetime import timedelta
import json
from types import SimpleNamespace

import pytest

from . import events, ml_lookup, amazon_source
from .config import Config
from .ml_lookup import MLClient, run_ml_lookup, enrich_ml_variations
from .refinements import load_refinements
from .runner import run_all
from .state import State, write_atomic
from .test_ml_lookup import amazon, today, rate, write_input, read_output
from .test_runner import row


@pytest.fixture
def sample(fixture_dir):
    return json.loads((fixture_dir / 'round2.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('fallback', [None, 'empty', 'used', 'international', '404'])
def test_atajo_real_y_fallback(tmp_path, sample, monkeypatch, capsys, fallback):
    write_input(tmp_path, [amazon(eligible=True)])
    catalog = tmp_path / 'catalog.json'
    write_atomic(catalog, sample['catalog'])
    calls = []
    def get(path, params=None):
        calls.append(path)
        if path == '/products/search':
            # Con «Monitor» en el nombre: el prefiltro exige que el tipo coincida con Amazon.
            return {'results': [{'id': 'MLA2069878284', 'name': 'Monitor Samsung S36GD'},
                                {'id': 'MLA999', 'name': 'Monitor Samsung S36GD'}]}
        if path == '/products/MLA2069878284/items' and fallback:
            if fallback == '404':
                from .test_ml_retries import http_error
                raise http_error(404)
            offer = {**sample['offer']}
            if fallback == 'used':
                offer['condition'] = 'used'
            if fallback == 'international':
                offer['international_delivery_mode'] = 'DDP'
            return {'results': [] if fallback == 'empty' else [offer]}
        return {'results': [sample['offer']]}
    if fallback is None:
        monkeypatch.setattr(ml_lookup, 'candidate_score', lambda *a: pytest.fail('El atajo no filtra candidatos'))
        monkeypatch.setattr(ml_lookup, 'build_queries', lambda *a, **kw: pytest.fail('El atajo no arma búsquedas'))
    client = MLClient(Config(ml_pause=0), get=get)
    result = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate, catalog_path=catalog)
    assert result['status'] == 'complete'
    assert calls == (['/products/MLA2069878284/items'] if fallback is None else
                     ['/products/MLA2069878284/items', '/products/search', '/products/MLA999/items'])
    output = read_output(tmp_path)[0]
    assert output['candidates'][0]['price_ars'] == 200000  # Nunca el precio viejo del catálogo.
    assert output['queries_used'] == ([] if fallback is None else ['Samsung S36GD'])
    log = capsys.readouterr().out
    assert 'BARRIDO_ML_ATAJO_CONOCIDO' in log and 'MLA2069878284' in log
    assert ('BARRIDO_ML_ATAJO_FALLBACK' in log) == (fallback is not None)
    assert result['requests_por_tipo']['ml_price'] == (1 if fallback is None else 2)
    assert result['requests_por_producto_elegible'] == (1 if fallback is None else 3)
    summary = json.loads((tmp_path / f'resumen-{today()}.json').read_text())['stores']['ML']
    end = json.loads(next(line.split('BARRIDO_ETAPA_FIN ', 1)[1] for line in log.splitlines() if 'BARRIDO_ETAPA_FIN ' in line))
    for key in events.stage_metrics():
        assert end[key] == summary[key] == result[key]


def test_amazon_no_pide_variantes_y_metricas_deduplican(tmp_path):
    item = row('A', variations=True)
    item['raw']['is_sponsored'] = True
    class Source:
        def fetch_search_page(self, *a):
            for path in ('/', '/s', '/dp/A', '/portal-migration/hz/glow/address-change'):
                events.emit_event('BARRIDO_HTTP_INICIO', tienda='US', path=path)
            return dict(products=[item, item], has_next=False, located_ar=True)
        def variations(self, *a):
            pytest.fail('Amazon no debe adquirir variantes antes de ML')
    result = run_all({'stores': {'US': {'nodes': [{'id': 'A', 'name': 'Prueba'}]}}},
                     Config(pause=0), tmp_path, source_factory=lambda *a: Source(),
                     rate_loader=lambda *a: dict(value=1, source='fixture', observed_at=events.now_art().isoformat()))['US']
    assert result['productos_unicos'] == result['duplicados'] == 1
    assert result['tarjetas_patrocinadas'] == 2
    assert result['requests_por_producto_elegible'] == 4
    assert all(result['requests_por_tipo'][key] == 1 for key in ('search', 'detail/variations', 'warm-up', 'location'))


def test_variantes_solo_con_ml_cupo_y_reanudacion(tmp_path, fixture_dir, capsys):
    rows = [row(identity, variations=True) for identity in ('A', 'B', 'C')]
    write_input(tmp_path, rows)
    state = State(tmp_path, today(), 'US')
    state.commit_page('A', 1, dict(page=1, complete=True, products=rows))
    calls, factories = [], []
    value = json.loads((fixture_dir / 'variations.json').read_text())
    class Source:
        def variations(self, identity):
            calls.append(identity)
            return value
    def factory(*a):
        factories.append(a[0])
        return Source()
    records = [dict(store='US', asin=identity, candidates=[{}] if identity != 'A' else []) for identity in ('A', 'B', 'C')]
    for _ in range(2):
        assert enrich_ml_variations(Config(variation_limit=1), tmp_path, today(), records,
                                    source_factory=factory, rate_loader=lambda *a: dict(value=1, source='fixture', observed_at=events.now_art().isoformat())) == 0
    assert calls == ['B'] and factories == ['US']
    materialized = {r['id']: r for r in state.materialize_jsonl()}
    assert materialized['B']['variations'] == value
    assert materialized['A']['variations'] is materialized['C']['variations'] is None
    assert 'variantes_sin_ml' in capsys.readouterr().out


def test_cache_siete_dias_clave_y_vencimiento(tmp_path, sample, monkeypatch):
    stamp = events.now_art()
    from . import refinements
    monkeypatch.setattr(refinements, 'now_art', lambda: stamp)
    calls = []
    def fetch():
        calls.append(1)
        return {'refinements': sample['refinements']}
    context = dict(date='ayer', store='US', node='A', language='en_US', destination='AR')
    load_refinements(tmp_path, context, fetch)
    context['date'] = 'hoy'
    stamp += timedelta(days=6)
    load_refinements(tmp_path, context, fetch)
    assert len(calls) == 1
    stamp += timedelta(days=1)
    load_refinements(tmp_path, context, fetch)
    assert len(calls) == 2
    load_refinements(tmp_path, context, fetch, refresh=True)
    assert len(calls) == 3
    for field, value in [('store', 'ES'), ('node', 'B'), ('language', 'es_ES'), ('destination', 'CL')]:
        load_refinements(tmp_path, {**context, field: value}, fetch)
    assert len(calls) == 7
    stamp += timedelta(days=1)
    load_refinements(tmp_path, context, fetch, ttl_days=1)
    assert len(calls) == 8


@pytest.mark.parametrize('filters,count', [({'new': 'p_n_condition-type:NEW'}, 2), ({'new': None, 'ar': None}, 1)])
def test_preconsulta_reutiliza_solo_parametros_iguales(tmp_path, monkeypatch, filters, count):
    source = object.__new__(amazon_source.AmazonSource)
    source.store, source.date, source.rate = 'US', today(), dict(value=1)
    source.site = dict(base='https://www.amazon.com', language='en_US', currency='USD')
    source.cache, source.refresh, source.filters, source.known = tmp_path, False, {}, set()
    source.config, source.bounds, source.http = Config(pause=0), ('100', '400'), 200
    source.sleep = lambda *a: None
    source.fetch = SimpleNamespace(session=lambda *a: SimpleNamespace(located='AR'))
    calls = []
    source.request = lambda params: calls.append(params) or dict(results=[{'asin': 'A'}])
    monkeypatch.setattr(amazon_source, 'normalize_product', lambda *a, **kw: {'id': kw['identity']})
    monkeypatch.setattr(amazon_source, 'delivery_from_card', lambda *a, **kw: {})
    # Simula una preconsulta válida cuyo conjunto final de filtros está controlado.
    def load(directory, context, fetch, **kw):
        fetch()
        return filters
    monkeypatch.setattr(amazon_source, 'load_refinements', load)
    source.fetch_search_page(dict(id='A', name='Prueba'), 1, events.now_art().isoformat())
    assert len(calls) == count


def test_lookup_encadena_variantes_y_reanuda_sin_red(tmp_path, sample):
    item = row('B0FIXTURE1', variations=True)
    state = State(tmp_path, today(), 'US')
    state.commit_page('A', 1, dict(page=1, complete=True, products=[item]))
    state.materialize_jsonl()
    catalog = tmp_path / 'catalog.json'
    write_atomic(catalog, sample['catalog'])
    calls = []
    def get(path, params=None):
        calls.append(path)
        return {'results': [sample['offer']]}
    class Source:
        def variations(self, identity):
            calls.append(identity)
            return {'products': [{'asin': 'VARIANTE'}]}
    client = MLClient(Config(ml_pause=0), get=get)
    options = dict(client=client, catalog_path=catalog, rate_loader=rate, source_factory=lambda *a: Source())
    assert run_ml_lookup(Config(), tmp_path, **options)['status'] == 'complete'
    assert run_ml_lookup(Config(), tmp_path, **options)['status'] == 'complete'
    assert calls == ['/products/MLA2069878284/items', 'B0FIXTURE1']
    assert state.materialize_jsonl()[0]['variations']['products'][0]['asin'] == 'VARIANTE'


def test_variantes_fallidas_se_reintentan_sin_consumir_otro_cupo(tmp_path):
    write_input(tmp_path, [row('A', variations=True)])
    calls = []
    class Source:
        def variations(self, identity):
            calls.append(identity)
            if len(calls) == 1:
                raise TimeoutError('Fixture de fallo transitorio')
            return {'products': []}
    records = [dict(store='US', asin='A', candidates=[{}])]
    options = dict(source_factory=lambda *a: Source(), rate_loader=rate)
    assert enrich_ml_variations(Config(variation_limit=1), tmp_path, today(), records, **options) == 1
    assert enrich_ml_variations(Config(variation_limit=1), tmp_path, today(), records, **options) == 0
    assert calls == ['A', 'A']


@pytest.mark.parametrize('identity', ['SINML', 'SINID', 'INVALIDO'])
def test_catalogo_sin_id_util_busca_normalmente(tmp_path, sample, identity, fixture_dir):
    from .test_ml_lookup import fixture_client
    write_input(tmp_path, [amazon(identity)])
    catalog = tmp_path / 'catalog.json'
    write_atomic(catalog, sample['catalog'])
    calls = []
    run_ml_lookup(Config(), tmp_path, catalog_path=catalog, client=fixture_client(fixture_dir, calls), rate_loader=rate)
    assert calls[0][0] == '/products/search'


def test_cache_corrupta_se_redescubre(tmp_path, sample):
    context = dict(store='US', node='A', language='en_US', destination='AR')
    calls = []
    def fetch():
        calls.append(1)
        return {'refinements': sample['refinements']}
    load_refinements(tmp_path, context, fetch)
    path = next(tmp_path.glob('*.json'))
    path.write_text('{', encoding='utf-8')
    load_refinements(tmp_path, context, fetch)
    assert len(calls) == 2
