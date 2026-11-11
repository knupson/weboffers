"""CDP simulado y fixtures locales: ninguna prueba abre Chrome ni usa red."""
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip('curl_cffi', reason='dependencias del barrido: correr en su contenedor')
from .bootstrap import load_vendor
from . import amazon_source, chrome_search
from .amazon_source import AmazonSource, SourceError
from .chrome_search import ChromeSearch, ChromeBlocked, ChromeLocationError
from .config import Config
from .events import now_art


@pytest.fixture
def site():
    load_vendor()
    from amazon import sites
    return sites.site('US')


class FakePage:
    def __init__(self, fixture_dir, *, location='chrome_ar.html', search='us_search.html', status=200,
                 change=True, confirm=True):
        self.fixture_dir = fixture_dir
        self.location, self.search = location, search
        self.status, self.change, self.confirm = status, change, confirm
        self.url, self.navigations, self.evaluations, self.waits = '', [], [], []

    def goto(self, url, **kwargs):
        self.url = url
        self.navigations.append(url)
        return SimpleNamespace(status=self.status if '/s?' in url else 200)

    def locator(self, selector):
        assert selector == '#glow-ingress-line2'
        from bs4 import BeautifulSoup
        content = (self.fixture_dir / self.location).read_text(encoding='utf-8')
        return SimpleNamespace(text_content=lambda: BeautifulSoup(content, 'html.parser').select_one(selector).get_text())

    def content(self):
        filename = self.search if '/s?' in self.url else self.location
        return (self.fixture_dir / filename).read_text(encoding='utf-8')

    def evaluate(self, script, argument):
        self.evaluations.append((script, argument))
        return self.change

    def reload(self, **kwargs):
        if self.confirm:
            self.location = 'chrome_ar.html'

    def wait_for_function(self, script, **kwargs):
        self.waits.append(script)

    def set_default_timeout(self, timeout):
        assert timeout == 30000


def connected(page):
    chrome = ChromeSearch('http://weboffers-chrome:9222')
    chrome.page = page
    return chrome


def test_una_conexion_contexto_y_pestana(monkeypatch, fixture_dir, site):
    page = FakePage(fixture_dir)
    context = SimpleNamespace(pages=[page], new_page=Mock())
    browser = SimpleNamespace(contexts=[context])
    playwright = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=Mock(return_value=browser)), stop=Mock())
    response = Mock()
    response.json.return_value = {'webSocketDebuggerUrl': 'ws://localhost:9222/devtools/browser/FIXTURE'}
    discovery = Mock(return_value=response)
    monkeypatch.setattr(chrome_search.requests, 'get', discovery)
    start = Mock(return_value=playwright)
    chrome = ChromeSearch('http://weboffers-chrome:9222', start=start)
    first = site['base'] + '/s?rh=n:541966&page=1'
    second = first.replace('page=1', 'page=2')
    assert chrome.search(first, site, reason='captcha tras 4 sesiones')[1] == 200
    assert chrome.search(second, site, reason='captcha tras 4 sesiones')[1] == 200
    assert start.call_count == discovery.call_count == 1
    playwright.chromium.connect_over_cdp.assert_called_once_with(
        'ws://weboffers-chrome:9222/devtools/browser/FIXTURE', timeout=30000)
    context.new_page.assert_not_called()
    assert page.navigations == [site['base'] + '/', first, second]
    assert len(page.waits) == 2
    chrome.close()
    playwright.stop.assert_called_once()


def test_cambia_destino_con_glow_y_verifica(fixture_dir, site):
    page = FakePage(fixture_dir, location='chrome_us.html')
    chrome = connected(page)
    html, status = chrome.search(site['base'] + '/s?page=2', site, reason='503 dogs page')
    assert status == 200 and 'B0FIXTURE1' in html
    assert len(page.evaluations) == 1
    script, argument = page.evaluations[0]
    assert argument == {'token': 'FIXTURE_TOKEN'}
    assert "countryCode: 'AR'" in script and "locationType: 'COUNTRY'" in script
    assert 'address-change?actionSource=glow' in script
    assert page.location == 'chrome_ar.html'


@pytest.mark.parametrize('change,confirm,location', [
    (False, True, 'chrome_us.html'), (True, False, 'chrome_us.html'), (True, True, 'chrome_dogs.html'),
])
def test_destino_sin_confirmar_corta_antes_de_buscar(fixture_dir, site, capsys, change, confirm, location):
    page = FakePage(fixture_dir, location=location, change=change, confirm=confirm)
    with pytest.raises(ChromeLocationError):
        connected(page).search(site['base'] + '/s?page=2', site, reason='captcha')
    assert not any('/s?' in url for url in page.navigations)
    log = capsys.readouterr().out
    assert 'BARRIDO_UBICACION_FALLIDA' in log
    assert 'BARRIDO_CHROME_INICIO' in log and 'BARRIDO_CHROME_FIN' in log
    assert 'FIXTURE_TOKEN' not in log


@pytest.mark.parametrize('status,filename', [(503, 'chrome_dogs.html'), (200, 'chrome_dogs.html')])
def test_chrome_tambien_bloqueado(fixture_dir, site, capsys, status, filename):
    page = FakePage(fixture_dir, search=filename, status=status)
    with pytest.raises(ChromeBlocked) as exc:
        connected(page).search(site['base'] + '/s?page=2', site, reason='503 tras 4 sesiones')
    assert exc.value.http == status
    log = capsys.readouterr().out
    assert 'BARRIDO_CHROME_FIN' in log and 'bloqueo' in log
    assert 'bytes' in log and 'ms' in log and 'motivo_fallback' in log


def test_bloqueos_sucesivos_no_se_convierten_en_error_de_ubicacion(fixture_dir, site):
    page = FakePage(fixture_dir, search='chrome_dogs.html', status=503)
    chrome = connected(page)
    chrome._is_ar = Mock(return_value=True)
    for _ in range(2):
        with pytest.raises(ChromeBlocked):
            chrome.search(site['base'] + '/s?page=2', site, reason='captcha')
    chrome._is_ar.assert_called_once()


def test_cabecera_ausente_en_resultados_detiene_tienda(fixture_dir, site, capsys):
    chrome = connected(FakePage(fixture_dir))
    chrome._is_ar = Mock(side_effect=[True, TimeoutError('cabecera ausente')])
    with pytest.raises(ChromeLocationError):
        chrome.search(site['base'] + '/s?page=2', site, reason='captcha')
    assert 'BARRIDO_UBICACION_FALLIDA' in capsys.readouterr().out


@pytest.mark.parametrize('html,status,reason', [
    ('<form action="/errors/validateCaptcha">captcha</form>', 200, 'captcha'),
    ('<script>gokuProps={}</script>', 202, '202 AWS WAF challenge'),
    ('<script>gokuProps={}</script>', 200, 'AWS WAF challenge'),
    ('<script>bm-verify /_sec/verify</script>', 200, 'intersticial bm-verify'),
])
def test_marcadores_de_bloqueo(site, html, status, reason):
    assert chrome_search.blocked_reason(html, status, site['base'] + '/s') == reason


def make_source(monkeypatch, tmp_path, site, *, endpoint='http://weboffers-chrome:9222'):
    from amazon import fetch
    monkeypatch.setenv('BARRIDO_CHROME_CDP', endpoint)
    transport = Mock()
    transport.page.side_effect = fetch.AmazonBlocked('503 dogs page (after 4 sessions)')
    transport.session.return_value = SimpleNamespace(located='US')
    monkeypatch.setattr(amazon_source, 'configure_transport', lambda *a: transport)
    source = AmazonSource('US', now_art().date().isoformat(), {'value': 1}, Config(pause=0), tmp_path, sleep=lambda _: None)
    return source, transport


def test_fallback_misma_url_parser_y_evidencia_por_tarjeta(monkeypatch, tmp_path, fixture_dir, site, capsys):
    source, transport = make_source(monkeypatch, tmp_path, site)
    html = (fixture_dir / 'us_search.html').read_text(encoding='utf-8')
    chrome = Mock()
    chrome.search.side_effect = [(html, 200), (html.replace('FREE delivery to Argentina', 'See options'), 200)]
    constructor = Mock(return_value=chrome)
    monkeypatch.setattr(chrome_search, 'ChromeSearch', constructor)
    source.filters['541966'] = {'new': 'p_n_condition-type:2224371011', 'free_shipping': 'p_n_is_free_shipping:10236242011'}
    category = {'id': '541966', 'name': 'Prueba'}
    first = source.fetch_search_page(category, 1, now_art().isoformat())
    second = source.fetch_search_page(category, 2, now_art().isoformat())
    assert first['located_ar'] is True and first['products'][0]['eligible'] is True
    assert second['products'][0]['eligible'] is False
    assert second['products'][0]['shipping_class'] == 'desconocido'
    constructor.assert_called_once()
    assert transport.page.call_count == 1
    for number, call in enumerate(chrome.search.call_args_list, 1):
        params = parse_qs(urlsplit(call.args[0]).query)
        assert params['page'] == [str(number)]
        assert 'p_n_is_free_shipping:10236242011' in params['rh'][0]
        assert call.kwargs['reason'] == '503 dogs page (after 4 sessions)'
    source.close()
    chrome.close.assert_called_once()


@pytest.mark.parametrize('endpoint,error,expected', [
    ('', 'blocked', True), ('http://weboffers-chrome:9222', 'upstream', False),
])
def test_sin_config_o_sin_bloqueo_no_hay_chrome(monkeypatch, tmp_path, site, endpoint, error, expected):
    from amazon import fetch
    source, transport = make_source(monkeypatch, tmp_path, site, endpoint=endpoint)
    if error == 'upstream':
        transport.page.side_effect = fetch.AmazonUpstreamError('HTTP 500')
    constructor = Mock()
    monkeypatch.setattr(chrome_search, 'ChromeSearch', constructor)
    with pytest.raises(SourceError) as exc:
        source.request({'page': '2'})
    assert exc.value.blocked is expected
    constructor.assert_not_called()


def test_bloqueo_chrome_se_propaga_como_bloqueo(monkeypatch, tmp_path, site):
    source, _ = make_source(monkeypatch, tmp_path, site)
    source.chrome = Mock()
    source.chrome.search.side_effect = ChromeBlocked('captcha', http=200)
    with pytest.raises(SourceError) as exc:
        source.request({'page': '2'})
    assert exc.value.blocked and exc.value.http == 200


def test_transporte_exitoso_no_hereda_destino_de_chrome(monkeypatch, tmp_path, fixture_dir, site):
    source, transport = make_source(monkeypatch, tmp_path, site)
    html = (fixture_dir / 'us_search.html').read_text(encoding='utf-8')
    source.chrome = Mock()
    source.chrome.search.return_value = (html, 200)
    source.filters['541966'] = {'new': 'p_n_condition-type:2224371011'}
    category = {'id': '541966', 'name': 'Prueba'}
    assert source.fetch_search_page(category, 1, now_art().isoformat())['located_ar'] is True
    def success(*a, **kw):
        source.http = 200
        return html
    source._chrome_until = 0
    source.probe_scraper = Mock(side_effect=lambda params: amazon_source.parse_search_page(success(), site))
    result = source.fetch_search_page(category, 2, now_art().isoformat())
    assert result['located_ar'] is False
    assert result['products'][0]['eligible'] is False
    assert source.chrome.search.call_count == 1


def test_ubicacion_fallida_detiene_tienda_y_cierra_fuente(monkeypatch, tmp_path, site):
    from .runner import run_store
    source, _ = make_source(monkeypatch, tmp_path, site)
    chrome = source.chrome = Mock()
    chrome.search.side_effect = ChromeLocationError('Destino no confirmado')
    categories = {'nodes': [{'id': '541966', 'name': 'Primera'}, {'id': 'OTRA', 'name': 'Segunda'}]}
    date = now_art().date().isoformat()
    result = run_store('US', categories, Config(pause=0), tmp_path, date,
        source_factory=lambda *a: source, rate_loader=lambda *a: {'value': 1, 'source': 'fixture', 'observed_at': now_art().isoformat()},
        sleep=lambda _: None)
    assert result['status'] == 'failed'
    assert chrome.search.call_count == 1
    # 11/11: la conexión se cierra al terminar la categoría; el cierre final de la tienda ya no la ve.
    chrome.close.assert_called_once()
    assert source.chrome is None


def test_fin_de_categoria_desconecta_playwright(monkeypatch, tmp_path, site):
    # 11/11: el driver sumó 52.824 kB en 19 páginas sin liberar; cada categoría usa una conexión nueva.
    source, _ = make_source(monkeypatch, tmp_path, site)
    chrome = source.chrome = Mock()
    source.end_category()
    chrome.close.assert_called_once()
    assert source.chrome is None


def test_fin_de_categoria_suelta_la_conexion_aunque_cerrar_falle(monkeypatch, tmp_path, site):
    source, _ = make_source(monkeypatch, tmp_path, site)
    source.chrome = Mock()
    source.chrome.close.side_effect = RuntimeError('playwright.stop fixture')
    with pytest.raises(RuntimeError):
        source.end_category()
    assert source.chrome is None
    source.close()  # el cierre final de la tienda ya no reintenta la conexión rota


def test_filtros_registrados_tambien_desde_cache(monkeypatch, tmp_path, fixture_dir, site, capsys):
    source, transport = make_source(monkeypatch, tmp_path, site)
    parsed = amazon_source.parse_search_page((fixture_dir / 'us_search.html').read_text(encoding='utf-8'), site)
    source.request = Mock(return_value=parsed)
    filters = {'new': 'p_n_condition-type:2224371011', 'free_shipping': 'p_n_is_free_shipping:10236242011'}
    monkeypatch.setattr(amazon_source, 'load_refinements', lambda *a, **kw: filters)
    source.fetch_search_page({'id': '541966', 'name': 'Prueba'}, 2, now_art().isoformat())
    log = capsys.readouterr().out
    assert 'BARRIDO_FILTROS' in log and '541966' in log and 'p_n_is_free_shipping:10236242011' in log
    assert source.request.call_args.args[0]['page'] == '2'
