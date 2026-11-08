import pytest
pytest.importorskip('curl_cffi', reason='dependencias del barrido: correr en su contenedor')
from .bootstrap import load_vendor
from .amazon_source import parse_search_page
from .refinements import discover_refinements, load_refinements


def test_cache_evitar_preconsulta(tmp_path, fixture_dir):
    load_vendor()
    from amazon import sites
    calls = []
    page = parse_search_page((fixture_dir / "us_search.html").read_text(encoding="utf-8"), sites.site("US"))
    def fetch():
        calls.append(1)
        return page
    context = dict(date="2026-11-07", store="US", node="fixture", language="en_US", destination="AR")
    assert load_refinements(tmp_path, context, fetch)["new"] == "p_n_condition-type:FIXTURE_NEW"
    load_refinements(tmp_path, context, fetch)
    assert len(calls) == 1
    load_refinements(tmp_path, context, fetch, refresh=True)
    assert len(calls) == 2


def test_condicion_ausente_no_se_omite():
    with pytest.raises(ValueError, match="condición nueva"):
        discover_refinements({"refinements": []})


@pytest.mark.parametrize('store,filename,expected', [
    ('US', 'sidebar_us_free_shipping.html', '10236242011'),
    ('ES', 'sidebar_es_free_shipping.html', 'ES_FREE'),
])
def test_sidebar_delivery_sin_ul_filter(fixture_dir, store, filename, expected):
    load_vendor()
    from amazon import sites
    from .amazon_source import build_search_params
    page = parse_search_page((fixture_dir / filename).read_text(encoding='utf-8'), sites.site(store))
    filters = discover_refinements(page)
    assert filters['free_shipping'] == f'p_n_is_free_shipping:{expected}'
    for number in (1, 2, 10):
        assert filters['free_shipping'] in build_search_params('541966', number, ('100', '400'), filters)['rh']
    assert 'PRIME' not in str(filters)


@pytest.mark.parametrize('fid,name,value,link', [
    ('p_n_is_free_shipping', 'Otra etiqueta', 'FREE_ID', None),
    ('deliveryRefinements', 'Eligible for Free Shipping', None, '/s?rh=p_n_is_free_shipping:FREE_ID'),
    ('deliveryRefinements', 'Envío gratis', None, '/s?rh=p_n_is_free_shipping:FREE_ID'),
    ('deliveryRefinements', 'Envío GRATIS', None, '/s?rh=p_n_is_free_shipping:FREE_ID'),
])
def test_filtro_por_id_o_nombre(fid, name, value, link):
    page = {'refinements': [
        {'id': 'p_n_condition-type', 'options': [{'name': 'New', 'value': 'NEW'}]},
        {'id': fid, 'options': [{'name': name, 'value': value, 'link': link}]},
    ]}
    assert discover_refinements(page)['free_shipping'] == 'p_n_is_free_shipping:FREE_ID'
    page['refinements'][1]['id'] = 'primeRefinements'
    assert discover_refinements(page)['free_shipping'] is None


def test_migra_cache_anterior_y_conserva_envio_gratis(tmp_path, fixture_dir):
    import json
    load_vendor()
    from amazon import sites
    from .events import now_art
    from .state import context_key
    context = dict(store='US', node='541966', language='en_US', destination='AR')
    path = tmp_path / (context_key(context) + '.json')
    path.write_text(json.dumps(dict(context=context, refinements={'new': 'p_n_condition-type:OLD', 'ar': None},
                                    observed_at=now_art().isoformat())), encoding='utf-8')
    calls = []
    def fetch():
        calls.append(1)
        return parse_search_page((fixture_dir / 'sidebar_us_free_shipping.html').read_text(encoding='utf-8'), sites.site('US'))
    assert load_refinements(tmp_path, context, fetch)['free_shipping'] == 'p_n_is_free_shipping:10236242011'
    assert load_refinements(tmp_path, context, fetch)['free_shipping'] == 'p_n_is_free_shipping:10236242011'
    assert len(calls) == 1
