"""Tercera ronda: casos del 07/11 y presupuesto de búsquedas, sin red."""
import json

import pytest

from .ml_matching import amazon_identity, build_queries, candidate_score
from .ml_lookup import run_ml_lookup
from .config import Config
from .test_ml_lookup import amazon, write_input, rate


@pytest.fixture
def cases(fixture_dir):
    return json.loads((fixture_dir / 'ml_round3.json').read_text(encoding='utf-8'))


def test_casos_reales(cases):
    for case in cases['rejected']:
        assert candidate_score(amazon_identity(case), {'name': case['candidate']}) == (None, case['reason'])
    for case in cases['accepted']:
        assert candidate_score(amazon_identity(case), {'name': case['candidate']})[0] is not None, case
    for case in cases['queries'] + cases['accepted']:
        if 'query' in case:
            assert build_queries(case['title'], row=case)[0] == case['query']


@pytest.mark.parametrize('marker', ['compatible', 'alternativo', 'genérico', 'remanufacturado'])
def test_original_y_alternativo_en_ambos_sentidos(marker):
    original = {'title': 'Brother Genuine Drum DR630'}
    alternative = {'title': f'Brother Drum DR630 {marker}'}
    assert candidate_score(amazon_identity(original), {'name': alternative['title']})[0] is None
    assert candidate_score(amazon_identity(alternative), {'name': original['title']})[0] is None


@pytest.mark.parametrize('phrase', ['Para Brother', 'Compatible con Brother', 'For Brother', 'Compatible with Brother'])
def test_marca_de_compatibilidad_no_es_fabricante(phrase):
    identity = amazon_identity({'title': 'Brother DR630 Drum'})
    product = {'name': f'Drum Tecnovibe DR630 {phrase}',
               'attributes': [{'id': 'BRAND', 'value_name': 'Tecnovibe'},
                              {'id': 'MODEL', 'value_name': 'Brother DR630'}]}
    assert candidate_score(identity, product)[0] is None


@pytest.mark.parametrize('variant', ['Pro', 'Max', 'Plus', 'Mini', 'Ultra', 'Lite', 'SE', 'Flex', 'Duo'])
def test_variantes_no_se_mezclan(variant):
    identity = amazon_identity({'title': f'Jabra Evolve2 65 {variant} Headset'})
    assert candidate_score(identity, {'name': f'Headset Jabra Evolve2 65 {variant}'})[0] is not None
    assert candidate_score(identity, {'name': 'Headset Jabra Evolve2 65'})[0] is None
    assert candidate_score(identity, {'name': f'Headset Jabra Evolve2 75 {variant}'})[0] is None


@pytest.mark.parametrize('component', ['Mali-G57', 'Snapdragon 8 Gen 2', 'Helio G99',
    'Ryzen 7 5800H', 'Intel Core i7-12700H', 'GeForce RTX 4060', 'RTX4060'])
def test_componente_no_reemplaza_modelo_de_tablet(component):
    row = {'title': f'Lenovo Idea Tab - College Tablet {component}', 'raw': {'model': component}}
    assert build_queries(row['title'], row=row)[0] == 'Lenovo Idea Tab'
    assert amazon_identity(row)['models'] == []


def test_gpu_conserva_su_modelo():
    assert amazon_identity({'title': 'Nvidia GeForce RTX 4060 Graphics GPU',
                            'model': 'RTX4060'})['models'] == ['RTX4060']


def test_consultas_sin_tokens_duplicados(cases):
    for case in cases['queries']:
        queries = build_queries(case['title'], row=case)
        assert len(queries) <= 2
        for query in queries:
            tokens = query.lower().split()
            assert len(tokens) == len(set(tokens))


def test_consulta_conserva_submodelo():
    assert build_queries('Jabra Evolve2 65 Flex Wireless Stereo Headset')[0] == 'Jabra Evolve2 65 Flex'
    assert build_queries('Logitech G502 X Plus Wireless Mouse')[0] == 'Logitech G502 X Plus'


def test_linea_ssd_no_pierde_pieza_explicita():
    row = {'title': 'Samsung SSD 870 EVO SATA III 1TB', 'part_number': 'MZ-77E1T0'}
    identity = amazon_identity(row)
    assert identity['models'] == ['MZ-77E1T0']
    assert candidate_score(identity, {'name': 'SSD Samsung 870 EVO 1TB MZ-77E1T0'})[0] is not None
    assert candidate_score(identity, {'name': 'SSD Samsung 870 EVO 1TB MZ-77E2T0'})[0] is None


@pytest.mark.parametrize('first,reason', [
    ('empty', 'sin_resultados'), ('wrong', 'sin_candidato_valido'),
    ('no_offer', 'sin_oferta_local_nueva'), ('ok', None)])
def test_segunda_consulta_acotada_y_explicada(tmp_path, monkeypatch, first, reason):
    from . import ml_lookup
    write_input(tmp_path, [amazon()])
    events, queries, offers = [], [], []
    monkeypatch.setattr(ml_lookup, 'emit_event', lambda event, **data: events.append((event, data)))
    # Aun si el generador devolviera más, el consumidor limita las búsquedas.
    monkeypatch.setattr(ml_lookup, 'build_queries', lambda *a, **kw: ['uno', 'dos', 'tres'])

    class Client:
        def search(self, query):
            queries.append(query)
            if first == 'empty':
                return []
            return [{'id': query, 'name': 'Mouse otra marca' if first == 'wrong' else 'Monitor Samsung S36GD'}]

        def cheapest(self, identity):
            offers.append(identity)
            return None if first == 'no_offer' else (100000, 'MLA1')

    run_ml_lookup(Config(), tmp_path, client=Client(), rate_loader=rate)
    assert queries == (['uno'] if first == 'ok' else ['uno', 'dos'])
    fallback = [data for event, data in events if event == 'BARRIDO_ML_SEGUNDA_CONSULTA']
    assert [data['motivo'] for data in fallback] == ([] if reason is None else [reason])
    if first in ('empty', 'wrong'):
        assert offers == []


def test_descartados_reales_no_consultan_ofertas(tmp_path, cases):
    for index, case in enumerate(cases['rejected']):
        output = tmp_path / str(index)
        output.mkdir()
        write_input(output, [amazon(title=case['title'], brand=case.get('brand', ''))])

        class Client:
            def search(self, query):
                return [{'id': 'MLA1', 'name': case['candidate']}]

            def cheapest(self, identity):
                pytest.fail('Un producto distinto no debe consultar ofertas')

        result = run_ml_lookup(Config(), output, client=Client(), rate_loader=rate)
        assert result['sin_resultados'] == 1 and result['errores'] == 0
