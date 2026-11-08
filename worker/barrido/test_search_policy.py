"""Políticas de búsquedas con HTML, reloj y transporte simulados, sin red."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

pytest.importorskip('curl_cffi', reason='dependencias del barrido: correr en su contenedor')
from . import amazon_source, events
from .amazon_source import AmazonSource, NON_NEW, SourceError, parse_search_page
from .bootstrap import load_vendor
from .config import Config
from .runner import run_store


def source_fixture(monkeypatch, tmp_path, store='US', ttl=1800):
    load_vendor()
    from amazon import fetch
    transport = Mock()
    transport.is_fallback_render = fetch.is_fallback_render
    transport.session.return_value = SimpleNamespace(located='AR', curl=Mock())
    monkeypatch.setattr(amazon_source, 'configure_transport', lambda *a: transport)
    monkeypatch.setenv('BARRIDO_CHROME_CDP', 'http://fixture:9222')
    clock = [0]
    source = AmazonSource(store, events.now_art().date().isoformat(), {'value': 1},
                          Config(pause=0, chrome_search_ttl=ttl), tmp_path / 'cache',
                          sleep=lambda _: pytest.fail('No debe esperar el transporte'), clock=lambda: clock[0])
    source.chrome = Mock()
    return source, transport, clock


@pytest.mark.parametrize('store', ['US', 'ES'])
@pytest.mark.parametrize('refinement', [False, True])
def test_tarjetas_condicion_categoria_y_log(monkeypatch, tmp_path, fixture_dir, capsys, store, refinement):
    source, transport, _ = source_fixture(monkeypatch, tmp_path, store)
    source.sleep = lambda _: None
    html = (fixture_dir / f'{store.lower()}_search_no_condition.html').read_text(encoding='utf-8')
    if refinement:
        label = 'New' if store == 'US' else 'Nuevo'
        # Como en la página real: los filtros viven dentro de #s-refinements (vendor parsers.py:495).
        html = html.replace('<body>', '<body><div id="s-refinements"><div>Condition</div><ul id="filter-p_n_condition-type">'
                            f'<li id="p_n_condition-type/NEW"><a href="/s?rh=p_n_condition-type:NEW">'
                            f'<span class="a-size-base">{label}</span></a></li></ul></div>')
    parsed = parse_search_page(html, source.site)
    def request(params):
        source._request_located_ar = True
        source.http = 200
        return parsed
    source.request = Mock(side_effect=request)
    pages = []
    original = source.fetch_search_page
    def capture(*args):
        result = original(*args)
        pages.append(result)
        return result
    source.fetch_search_page = capture
    rate = {'value': 1, 'source': 'fixture', 'observed_at': events.now_art().isoformat()}
    result = run_store(store, {'nodes': [{'id': '2617941011', 'name': 'Artes'}]}, source.config,
                       tmp_path / 'output', source.date, source_factory=lambda *a: source,
                       rate_loader=lambda *a: rate, sleep=lambda _: None)
    assert result['status'] == 'complete'
    rows = pages[0]['products']
    assert len(rows) == 12
    assert [row['id'] for row in rows if row['eligible']] == ['B0COND0001', 'B0COND0012']
    assert all('no_nuevo' in row['rejection_reasons'] for row in rows[1:11])
    log = capsys.readouterr().out
    assert ('BARRIDO_SIN_FILTRO_NUEVO' in log) is (not refinement)
    for row in rows[1:11]:
        assert any('BARRIDO_DESCARTE' in line and '"motivo": "no_nuevo"' in line
                   and row['raw']['non_new_marker'] in line and row['id'] in line for line in log.splitlines())
    assert ('p_n_condition-type:NEW' in source.request.call_args.args[0]['rh']) is refinement
    assert source.request.call_count == (2 if refinement else 1)
    # La ausencia también se guarda en caché; no fuerza otra preconsulta.
    source.filters.clear()
    source.request.reset_mock()
    source.fetch_search_page({'id': '2617941011', 'name': 'Artes'}, 1, events.now_art().isoformat())
    assert source.request.call_count == 1
    assert ('BARRIDO_SIN_FILTRO_NUEVO' in capsys.readouterr().out) is (not refinement)


@pytest.mark.parametrize('text,marker', [
    ('Auriculares REFURBISHED', 'REFURBISHED'), ('Equipo pre-owned', 'pre-owned'),
    ('Caja OPEN-BOX', 'OPEN-BOX'), ('Auriculares reacondicionados', 'reacondicionados'),
    ('Notebook usada', 'usada'), ('Libros usados', 'usados'),
    ('Renewedness', None), ('Unused case', None), ('Uso profesional', None),
])
def test_limites_marcadores(text, marker):
    found = NON_NEW.search(text)
    assert (found.group(0) if found else None) == marker


@pytest.mark.parametrize('store', ['US', 'ES'])
@pytest.mark.parametrize('ttl', [1800, 0])
def test_chrome_persistente_sin_scraper_ni_esperas(monkeypatch, tmp_path, fixture_dir, capsys, store, ttl):
    load_vendor()
    from amazon import fetch
    source, transport, clock = source_fixture(monkeypatch, tmp_path, store, ttl)
    html = (fixture_dir / f'{store.lower()}_search_no_condition.html').read_text(encoding='utf-8')
    transport.page.side_effect = fetch.AmazonBlocked('503 dogs page')
    source.chrome.search.return_value = (html, 200)
    for number in range(1, 4):
        source.request({'rh': f'n:{number}', 'page': str(number)})
        clock[0] += 10
    assert transport.page.call_count == 1
    assert source.chrome.search.call_count == 3
    assert source._chrome_until == (1800 if ttl else float('inf'))
    switches = [line for line in capsys.readouterr().out.splitlines() if 'BARRIDO_FUENTE_BUSQUEDA' in line]
    assert len(switches) == 2
    assert '"source": "scraper"' in switches[0] and '"source": "chrome"' in switches[1]
    if ttl == 0:
        clock[0] = 10**9
        source.request({'page': '4'})
        assert transport.page.call_count == 1


@pytest.mark.parametrize('status,blocked', [(200, False), (503, True), (200, True), (500, False)])
def test_vencimiento_un_sondeo_y_restaura_fuente(monkeypatch, tmp_path, fixture_dir, status, blocked):
    load_vendor()
    from amazon import fetch
    source, transport, clock = source_fixture(monkeypatch, tmp_path, ttl=10)
    html = (fixture_dir / 'us_search_no_condition.html').read_text(encoding='utf-8')
    transport.page.side_effect = fetch.AmazonBlocked('503')
    source.chrome.search.return_value = (html, 200)
    source.request({'page': '1'})
    clock[0] = 10
    response = SimpleNamespace(status_code=status, text='validateCaptcha' if blocked else html, headers={},
                               url=source.site['base'] + '/s')
    curl = transport.session.return_value.curl
    curl.request.return_value = response
    source.request({'page': '2'})
    curl.request.assert_called_once_with('GET', source.site['base'] + '/s', params={'page': '2'},
                                         headers=transport.PAGE_HEADERS, allow_redirects=False)
    assert transport.page.call_count == 1
    success = status == 200 and not blocked
    assert source._search_source == ('scraper' if success else 'chrome')
    assert source._request_located_ar is (None if success else True)
    assert source.chrome.search.call_count == (1 if success else 2)
    if not success:
        source.request({'page': '3'})
        assert curl.request.call_count == 1
    else:
        def scraper_success(*args, **kwargs):
            source.http = 200
            return html
        transport.page.side_effect = scraper_success
        source.request({'page': '3'})
        assert transport.page.call_count == 2
        assert curl.request.call_count == 1
        assert source.chrome.search.call_count == 1


def test_preferencia_aislada_por_tienda(monkeypatch, tmp_path, fixture_dir):
    load_vendor()
    from amazon import fetch
    us, us_transport, _ = source_fixture(monkeypatch, tmp_path, 'US')
    es, es_transport, _ = source_fixture(monkeypatch, tmp_path, 'ES')
    us_html = (fixture_dir / 'us_search_no_condition.html').read_text(encoding='utf-8')
    es_html = (fixture_dir / 'es_search_no_condition.html').read_text(encoding='utf-8')
    us_transport.page.side_effect = fetch.AmazonBlocked('503')
    us.chrome.search.return_value = (us_html, 200)
    def es_success(*args, **kwargs):
        es.http = 200
        return es_html
    es_transport.page.side_effect = es_success
    us.request({'page': '1'})
    es.request({'page': '1'})
    us.request({'page': '2'})
    assert us._search_source == 'chrome' and es._search_source == 'scraper'
    assert us_transport.page.call_count == es_transport.page.call_count == 1
    es.chrome.search.assert_not_called()


def test_http_bloqueado_sin_excepcion_activa_chrome(monkeypatch, tmp_path, fixture_dir):
    source, transport, _ = source_fixture(monkeypatch, tmp_path)
    html = (fixture_dir / 'us_search_no_condition.html').read_text(encoding='utf-8')
    def blocked(*args, **kwargs):
        source.http = 403
        return ''
    transport.page.side_effect = blocked
    source.chrome.search.return_value = (html, 200)
    source.request({'page': '1'})
    source.request({'page': '2'})
    assert transport.page.call_count == 1
    assert source.chrome.search.call_count == 2


def test_respaldo_fallido_no_activa_ventana_y_no_afecta_detalle(monkeypatch, tmp_path):
    load_vendor()
    from amazon import fetch, products
    source, transport, _ = source_fixture(monkeypatch, tmp_path)
    transport.page.side_effect = fetch.AmazonBlocked('503')
    source.chrome.search.side_effect = RuntimeError('CDP sin conexión')
    with pytest.raises(SourceError):
        source.request({'page': '1'})
    assert source._search_source == 'scraper' and source._chrome_until is None
    detail = Mock(return_value=[])
    monkeypatch.setattr(products, 'variations', detail)
    source._search_source = 'chrome'
    assert source.variations('B0COND0001') == []
    detail.assert_called_once()


def test_metricas_separan_http_scraper_y_chrome(monkeypatch, tmp_path, fixture_dir):
    from .test_chrome_search import FakePage, connected
    load_vendor()
    from amazon import sites
    site = sites.site('US')
    with events.observe_run(tmp_path / 'output', Config(), {}):
        events.emit_event('BARRIDO_HTTP_INICIO', tienda='US', path='/s')
        chrome = connected(FakePage(fixture_dir))
        chrome.search(site['base'] + '/s?page=1', site, reason='bloqueo')
        metrics = events.stage_metrics()
        assert metrics['requests_por_fuente'] == {'scraper': 1, 'chrome': 1, 'ml': 0, 'other': 0}
        assert metrics['requests_por_tipo']['search'] == 2


def test_config_ventana_valida():
    assert Config().chrome_search_ttl == 1800
    for ttl in (-1, float('nan'), float('inf'), True):
        with pytest.raises(ValueError):
            Config(chrome_search_ttl=ttl)
