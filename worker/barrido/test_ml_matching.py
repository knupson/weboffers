"""Regresiones de identidad y descarte antes de consultar ofertas; sin red."""
import json

import pytest

from .ml_matching import amazon_identity, build_queries, candidate_score


def examples(fixture_dir):
    return json.loads((fixture_dir / 'ml_matching.json').read_text(encoding='utf-8'))


def test_casos_reales_consulta_y_coincidencia(fixture_dir):
    for case in examples(fixture_dir):
        identity = amazon_identity(case)
        assert build_queries(case['title'], identity['brand'], case)[0] == case['query']
        assert candidate_score(identity, {'name': case['wrong']})[0] is None
        assert candidate_score(identity, {'name': case['right']})[0] is not None


@pytest.mark.parametrize('unit', ['2000MB/s', '1,050MB/s', '1.050MB/s', '1TB', '512 GB',
    '144Hz', '65W', '5000mAh', '27inch', '27-inch', '27 inches', '5000-mAh',
    '99%', '4K', '1080p', '10Gbps', '2.4GHz'])
def test_unidades_nunca_son_modelo(unit):
    identity = amazon_identity({'title': f'Samsung Portable SSD {unit}'})
    assert identity['models'] == []
    assert '050MB/s' not in build_queries(f'Samsung Portable SSD {unit}')[0]


@pytest.mark.parametrize('container', ['details', 'identifiers', 'overview'])
def test_campos_de_detalle_del_vendor(container):
    row = {'title': 'Targus Docking Station', 'raw': {'brand': {'name': 'Targus'},
           container: {'manufacturer_part_number': 'DOCK570USZ'}}}
    assert build_queries(row['title'], row=row)[0] == 'Targus DOCK570USZ'


def test_marca_modelo_tipo_y_capacidad_no_se_omiten():
    identity = amazon_identity({'title': 'Razer Naga V3 Pro Wireless Gaming Mouse'})
    for name in ['Mouse Logitech Naga V3 Pro', 'Mouse Razer V3 Pro',
                 'Teclado Razer Naga V3 Pro', 'Mouse Razer Naga V3',
                 'Mouse Razer Naga V30 Pro', 'Mouse Bungee Razer Naga V3 Pro']:
        assert candidate_score(identity, {'name': name})[0] is None
    disk = amazon_identity({'title': 'Sandisk Extreme Portable SSD 1TB'})
    assert candidate_score(disk, {'name': 'SSD Sandisk Extreme Portable 1000GB'})[0] is not None


def test_modelo_estructurado_no_pierde_la_linea():
    row = {'title': 'Razer Naga V3 Pro Wireless Mouse', 'raw': {'model': 'V3'}}
    assert build_queries(row['title'], row=row)[0] == 'Razer Naga V3 Pro'


def test_pieza_numerica_y_detalle_anidado():
    row = {'title': 'Logitech Wireless Mouse', 'detail': {'brand': {'name': 'Logitech'},
           'identifiers': {'part_number': '910-006123'}}}
    assert build_queries(row['title'], row=row)[0] == 'Logitech 910-006123'
    assert candidate_score(amazon_identity(row), {'name': 'Mouse Logitech 910 006123'})[0] is not None


def test_separadores_de_modelo_no_cambian_identidad():
    identity = amazon_identity({'title': 'Sony WH-1000XM5 Wireless Headphones'})
    assert candidate_score(identity, {'name': 'Auriculares Sony WH 1000XM5'})[0] is not None


def test_linea_en_campo_model_con_titulo_generico():
    row = {'title': 'Razer Wireless Mouse', 'raw': {'model': 'Naga V3 Pro'}}
    assert build_queries(row['title'], row=row)[0] == 'Razer Naga V3 Pro'
    identity = amazon_identity(row)
    assert candidate_score(identity, {'name': 'Mouse Razer V3 Pro'})[0] is None
    assert candidate_score(identity, {'name': 'Mouse Razer Naga V3 Pro'})[0] is not None


def test_modelo_sin_digitos_en_detalle():
    row = {'title': 'Sandisk Portable SSD 1TB',
           'raw': {'details': {'model': 'Extreme Portable SSD'}}}
    assert build_queries(row['title'], row=row)[0] == 'Sandisk Extreme Portable SSD'
    assert candidate_score(amazon_identity(row), {'name': 'SSD Sandisk Extreme Portable 1TB'})[0] is not None
    assert candidate_score(amazon_identity(row), {'name': 'SSD Sandisk Portable 1TB'})[0] is None


def test_modelo_en_atributos_de_ml_aunque_falte_en_el_nombre():
    identity = amazon_identity({'title': 'Lenovo 40AF0135US Thinkpad Docking Station Dual Monitor', 'brand': 'Lenovo'})
    sin_modelo = {'name': 'Dock Lenovo ThinkPad', 'attributes': []}
    con_modelo = {'name': 'Dock Lenovo ThinkPad',
                  'attributes': [{'id': 'MODEL', 'value_name': '40AF0135US'}, {'id': 'COLOR', 'value_name': 'Negro'}]}
    assert candidate_score(identity, sin_modelo)[0] is None
    assert candidate_score(identity, con_modelo)[0] is not None
