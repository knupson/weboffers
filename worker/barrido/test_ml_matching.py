"""Regresiones de identidad y descarte antes de consultar ofertas; sin red."""
import json

import pytest

from .ml_matching import amazon_identity, build_queries, candidate_score, model_tokens, starts_without_brand


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


def test_marca_declarada_por_ml_con_submarca():
    # Caso real 07/11: ML declara BRAND «Logitech G»; Amazon dice «Logitech».
    identity = amazon_identity({'title': 'Logitech G PRO X2 SUPERSTRIKE Wireless Gaming Mouse - Black/White'})
    producto = {'name': 'Mouse Inalámbrico Gaming Logitech G Pro X2 Superstrike Blanco Con Negro',
                'attributes': [{'id': 'BRAND', 'value_name': 'Logitech G'}]}
    assert candidate_score(identity, producto)[0] is not None
    otra = {'name': 'Mouse Gaming Pro X2 Superstrike', 'attributes': [{'id': 'BRAND', 'value_name': 'Redragon'}]}
    assert candidate_score(identity, otra)[0] is None


def test_marca_confirmada_por_ml_y_modelo_numerico():
    # 10/11: Amazon no trae marca; «Games» no es la marca de Games Workshop.
    identity = amazon_identity({'title': 'LEGO Harry Potter Knockturn Alley Wizarding Shops 76471'})
    assert identity['models'] == ['76471']
    assert candidate_score(identity, {'name': 'Set Lego Harry Potter 76471 Callejón Knockturn'})[0] is not None
    assert candidate_score(identity, {'name': 'Set Lego Harry Potter 76470'})[0] is None
    gw = amazon_identity({'title': 'Games Workshop Warhammer 40K Combat Patrol 71089'})
    producto = {'name': 'Patrulla De Combate 71089 Warhammer',
                'attributes': [{'id': 'BRAND', 'value_name': 'Games Workshop'}]}
    assert candidate_score(gw, producto)[0] is not None
    otra_marca = {'name': 'Patrulla De Combate 71089', 'attributes': [{'id': 'BRAND', 'value_name': 'Hasbro'}]}
    assert candidate_score(gw, otra_marca)[0] is None


def test_pies_son_medida_y_anios_no_son_modelo():
    # 10/11: «9.4ft» se tomó como modelo «4ft» y validó unas tiras Govee de 16.4ft.
    assert amazon_identity({'title': 'Govee Outdoor Net Lights 2.8 x 9.4ft RGBIC'})['models'] == []
    assert model_tokens('Edition 2026') == []


def test_titulo_que_empieza_con_medida_no_tiene_marca():
    for t in ('14K Gold Cross Pendant', '1500W 48V Power Supply', '30 Inch Wig', '13X6 Lace Wig', '925 Silver'):
        assert starts_without_brand(t), t
    for t in ('Timbuk2 Closer Laptop Briefcase', 'T3 CurlWrap', '8BitDo Pro 2', 'Insta360 X4',
              'PD4060CSV 60 Amp Converter', 'XB-450i Bead Breaker', '4-in-1 Kit'):
        assert not starts_without_brand(t), t
