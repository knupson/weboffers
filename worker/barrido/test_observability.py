"""Contratos de observabilidad con reloj, transporte y señales simulados; sin red."""
import json
from pathlib import Path
import signal
import threading
from types import SimpleNamespace

import pytest
import requests

from . import events
from .config import Config
from .logs import read_events, summarize
from .runner import retry_page, run_all
from .amazon_source import AmazonSource, SourceError
from .ml_lookup import MLClient
from .state import write_summary


def entries(output):
    path = output.parent / 'logs' / f'barrido-{events.now_art().date()}.log'
    return list(read_events(path))


def response(status=200, text='{}', url='https://fixture.invalid/s'):
    result = requests.Response()
    result.status_code, result._content, result.url = status, text.encode(), url
    return result


def test_inicio_antes_de_bloquear_y_fin_con_mismo_id(tmp_path):
    output = tmp_path / 'barrido'
    def transport(method, url, **kw):
        recorded = entries(output)
        assert recorded[-1]['evento'] == 'BARRIDO_HTTP_INICIO'
        assert recorded[-1]['datos']['params']['access_token'] == '[OCULTO]'
        return response(503, 'Sorry! Something went wrong')
    with events.observe_run(output, Config(), {}):
        events.set_context(etapa='amazon_us', tienda='US', categoria='A', pagina=1)
        events.http_call(transport, 'GET', 'https://fixture.invalid/s?access_token=secreto',
                         store='US', session_id='sesion-fixture', located=False,
                         params={'page': 1}, block_reason=lambda _: '503 dogs page')
    records = [e for e in entries(output) if e['evento'].startswith('BARRIDO_HTTP_')]
    start, end = [e['datos'] for e in records]
    assert start['request_id'] == end['request_id']
    assert end['status'] == 503 and end['bytes'] > 0 and end['ms'] >= 0
    assert end['bloqueo'] == '503 dogs page' and end['categoria'] == 'A'
    assert 'secreto' not in json.dumps(records)


def test_error_de_transporte_cierra_request_y_traza_completa(tmp_path):
    output = tmp_path / 'barrido'
    def broken(*args, **kwargs):
        raise TimeoutError('timeout literal fixture')
    with pytest.raises(TimeoutError):
        with events.observe_run(output, Config(), {}):
            events.http_call(broken, 'GET', 'https://fixture.invalid/s', store='US', session_id='S')
    records = entries(output)
    end = next(e['datos'] for e in records if e['evento'] == 'BARRIDO_HTTP_FIN')
    assert end['status'] is None and end['error'] == 'timeout literal fixture'
    exception = next(e['datos'] for e in records if e['evento'] == 'BARRIDO_EXCEPCION')
    assert 'Traceback' in exception['traceback'] and 'broken' in exception['traceback']
    assert records[-1]['evento'] == 'BARRIDO_PROCESO_FIN'


def test_latido_atomico_no_cuenta_como_avance_y_captura_pila(tmp_path, monkeypatch):
    output = tmp_path / 'barrido'
    clock = [0.0]
    with events.observe_run(output, Config(stall_seconds=300), {}) as runtime:
        runtime.clock = lambda: clock[0]
        runtime.progress = runtime.action_started = 0
        events.set_context(etapa='amazon_us', tienda='US', categoria='A', pagina=2)
        with events.action('esperando HTTP'):
            clock[0] = 301
            runtime.heartbeat()
            saved = json.loads((output / 'latido.json').read_text())
            assert saved['segundos_sin_avance'] == 301 and '301 s' in saved['accion']
            runtime.heartbeat()
            assert runtime.progress == 0
    stalled = [e['datos'] for e in entries(output) if e['evento'] == 'BARRIDO_SIN_AVANCE']
    assert len(stalled) == 2 and 'test_latido_atomico' in stalled[0]['stack_principal']
    assert not list(output.glob('*.tmp'))


def test_latido_thread_espera_60_s_sin_dormir(tmp_path):
    runtime = events.Runtime(tmp_path, Config())
    calls = []
    class Stop:
        def wait(self, seconds):
            calls.append(seconds)
            return len(calls) > 1
    runtime.stop = Stop()
    runtime.heartbeat = lambda: calls.append('latido')
    runtime.loop()
    assert calls == [60, 'latido', 60]


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT])
def test_senales_registran_estado_y_restauran_handler(tmp_path, sig):
    output = tmp_path / 'barrido'
    original = signal.getsignal(sig)
    with pytest.raises(SystemExit) as exc:
        with events.observe_run(output, Config(), {}):
            signal.getsignal(sig)(sig, None)  # No se envía una señal real al proceso de pytest.
    assert exc.value.code == 128 + sig and signal.getsignal(sig) == original
    cut = next(e['datos'] for e in entries(output) if e['evento'] == 'BARRIDO_CORTADO')
    assert cut['senal'] == signal.Signals(sig).name and cut['estado']['pid']


def test_esperas_y_backoff_con_reintento(tmp_path):
    output = tmp_path / 'barrido'
    attempts, delays = [], []
    def operation():
        attempts.append(1)
        if len(attempts) == 1:
            raise SourceError('503 dogs page fixture', http=503, blocked=True)
        return {}
    with events.observe_run(output, Config(), {}):
        retry_page(operation, Config(), store='US', category='A', page=1, sleep=delays.append)
    assert delays == [30]
    wait = next(e['datos'] for e in entries(output) if e['evento'] == 'BARRIDO_ESPERA')
    assert wait['motivo'] == 'backoff_bloqueo' and wait['hasta'].endswith('-03:00')


def test_persistencia_append_y_rotacion_de_fecha_art(tmp_path, monkeypatch):
    from datetime import datetime
    output = tmp_path / 'barrido'
    first = datetime.fromisoformat('2026-11-07T23:59:59-03:00')
    second = datetime.fromisoformat('2026-11-08T00:00:00-03:00')
    monkeypatch.setattr(events, 'now_art', lambda: first)
    with events.observe_run(output, Config(), {}):
        events.emit_event('BARRIDO_PRUEBA', valor=1)
        monkeypatch.setattr(events, 'now_art', lambda: second)
        events.emit_event('BARRIDO_PRUEBA', valor=2)
    path = tmp_path / 'logs/barrido-2026-11-08.log'
    previous = path.read_bytes()
    with events.observe_run(output, Config(), {}):
        events.emit_event('BARRIDO_PRUEBA', valor=3)
    assert path.read_bytes().startswith(previous)
    assert (tmp_path / 'logs/barrido-2026-11-07.log').exists()


def test_redaccion_headers_payload_query_y_errores(tmp_path):
    output = tmp_path / 'barrido'
    with events.observe_run(output, Config(), {}):
        events.http_call(lambda *a, **kw: response(), 'POST',
                         'https://usuario:clave@fixture.invalid/oauth/token?amzn=oculto',
                         store='ML', session_id='S', data={'client_secret': 'secreto'},
                         headers={'Authorization': 'Bearer credencial'})
        events.emit_event('BARRIDO_ERROR', motivo='access_token=privado Bearer secreto2',
                          client_secret='secreto3', cookie='secreto4')
    literal = json.dumps(entries(output))
    for secret in ('usuario', 'clave', 'oculto', 'secreto', 'credencial', 'privado'):
        assert secret not in literal


def test_ml_instrumenta_oauth_y_request_real_con_fixture(tmp_path, monkeypatch):
    import ml_prices
    monkeypatch.setenv('ML_CLIENT_ID', 'fixture-id')
    monkeypatch.setenv('ML_CLIENT_SECRET', 'fixture-secreto')
    monkeypatch.setattr(ml_prices, '_token_cache', {'value': None, 'expires_at': 0})
    client = MLClient(Config(ml_pause=0), sleep=lambda _: None)
    calls = []
    def fake(method, url, **kw):
        calls.append((method, url))
        return response(text='{"access_token":"fixture-token"}' if url.endswith('/oauth/token') else '{"results":[]}')
    monkeypatch.setattr(client.transport, 'request', fake)
    output = tmp_path / 'barrido'
    with events.observe_run(output, Config(), {}):
        assert client.search('fixture') == []
    records = [e for e in entries(output) if e['evento'] == 'BARRIDO_HTTP_FIN']
    assert [e['datos']['path'] for e in records] == ['/oauth/token', '/products/search']
    assert len(calls) == 2 and 'fixture-token' not in json.dumps(records)


def test_amazon_vendor_bloqueo_reintento_y_contadores(tmp_path, fixture_dir, monkeypatch):
    pytest.importorskip('curl_cffi')
    from curl_cffi import requests as curl_requests
    from .bootstrap import load_vendor
    load_vendor()
    from amazon import fetch
    monkeypatch.setattr(fetch, '_local', threading.local())
    monkeypatch.setattr(fetch, 'OBSERVER', None)
    html = (fixture_dir / 'us_search.html').read_text(encoding='utf-8')
    dogs = (fixture_dir / 'dogs_503.html').read_text(encoding='utf-8')
    searches = []
    class Curl:
        def __init__(self, **kw):
            self.cookies = SimpleNamespace(set=lambda *a, **kw: None, jar=[])
        def request(self, method, url, **kw):
            if url.endswith('/s'):
                searches.append(1)
                return response(503, dogs, url) if len(searches) == 1 else response(200, html, url)
            return response(200, '<html>Portada fixture</html>', url)
        def get(self, url, **kw):
            return self.request('GET', url, **kw)
        def close(self):
            pass
    monkeypatch.setattr(curl_requests, 'Session', Curl)
    output = tmp_path / 'barrido'
    config = Config(pause=0, backoff=0)
    stamp = events.now_art().isoformat()
    rate = {'value': 1, 'source': 'fixture', 'observed_at': stamp}
    categories = {'stores': {'US': {'nodes': [{'id': 'A', 'name': 'Prueba', 'kind': 'leaf'}]}}}
    result = run_all(categories, config, output, dry_run=True, rate_loader=lambda *a: rate,
                     source_factory=lambda store, date, rate: AmazonSource(store, date, rate, config,
                        tmp_path / 'cache', sleep=lambda _: None), sleep=lambda _: None)
    records = entries(output)
    names = [e['evento'] for e in records]
    assert result['US']['products'] == 1
    assert 'BARRIDO_ROTACION' in names and names.count('BARRIDO_SESION') == 2
    assert 'BARRIDO_REINTENTO' in names and 'BARRIDO_CALENTAMIENTO_INICIO' in names
    assert names.count('BARRIDO_HTTP_INICIO') == names.count('BARRIDO_HTTP_FIN') == 5
    end = next(e['datos'] for e in records if e['evento'] == 'BARRIDO_ETAPA_FIN')
    assert end['requests_amazon'] == 5 and end['products'] == 1 and end['blocks'] == 1
    assert '<html' not in json.dumps(records)


def test_resumen_tasas_solo_con_comparaciones(tmp_path):
    output = tmp_path / 'barrido'
    output.mkdir()
    with events.observe_run(output, Config(), {}) as runtime:
        write_summary(output, '2026-11-07', {})
        path = output / 'resumen-2026-11-07.json'
        assert json.loads(path.read_text())['comparaciones_por_consulta'] is None
        runtime.counters.update(comparisons=4, queries=2)
        write_summary(output, '2026-11-07', {})
        assert json.loads(path.read_text())['comparaciones_por_consulta'] == 2


def test_lector_fixture_timeline_bloqueo_y_reintento(fixture_dir):
    records = list(read_events(fixture_dir / 'observabilidad.log'))
    result = summarize(records, alive=lambda _: True)
    assert result['esperas_segundos_por_motivo'] == {'backoff_bloqueo': 30}
    assert result['descartes_por_motivo'] == {'fuera_de_rango': 1}
    assert len(result['etapas']) == 2 and result['estado'] == 'finalizado'
    assert '503 dogs page' in json.dumps(result['errores_y_bloqueos'])


@pytest.mark.parametrize('living,age,progress,expected', [
    (True, 0, 0, 'vivo'), (True, 0, 301, 'vivo_sin_avance'),
    (False, 0, 0, 'no_vive'), (True, 121, 0, 'latido_vencido_identidad_no_confirmada')])
def test_lector_estado_proceso(living, age, progress, expected):
    from datetime import timedelta
    now = events.now_art()
    records = [dict(hora=(now - timedelta(seconds=age)).isoformat(), evento='BARRIDO_LATIDO',
                    datos=dict(pid=123, run_id='fixture', segundos_sin_avance=progress))]
    assert summarize(records, now=now, alive=lambda _: living)['estado'] == expected


def test_lector_linea_incompleta_y_filtro_desde(tmp_path):
    path = tmp_path / 'fixture.log'
    path.write_text('2026-11-07T10:00:00-03:00 BARRIDO_PRUEBA {}\n'
                    '2026-11-07T11:00:00-03:00 BARRIDO_PRUEBA {}\nfragmento', encoding='utf-8')
    records = list(read_events(path, '10:30'))
    assert len(records) == 2 and records[0]['hora'].startswith('2026-11-07T11:00')
    assert records[-1]['evento'] == 'LOG_INCOMPLETO'


def test_redirecciones_tienen_eventos_y_quitan_authorization_al_cambiar_host(tmp_path):
    output = tmp_path / 'barrido'
    calls = []
    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if len(calls) == 1:
            result = response(302)
            result.headers['Location'] = 'https://otro.invalid/destino'
            return result
        return response()
    with events.observe_run(output, Config(), {}):
        events.http_call(fake, 'POST', 'https://fixture.invalid/inicio', store='ML', session_id='S',
                         headers={'Authorization': 'Bearer fixture'}, data={'campo': 'valor'})
    assert calls[1][0] == 'GET' and calls[1][2]['headers'] == {} and 'data' not in calls[1][2]
    assert all(call[2]['allow_redirects'] is False for call in calls)
    assert len([e for e in entries(output) if e['evento'] == 'BARRIDO_HTTP_FIN']) == 2


def test_descartes_por_motivo_y_conocidos_por_pagina(tmp_path):
    from .test_runner import row, rate
    output = tmp_path / 'barrido'
    rows = [row('fuera'), row('sin'), row('pago'), row('no'), row('ok'), row('ok')]
    rows[0].update(price_usd=450, rejection_reasons=['fuera_de_rango'], eligible=False)
    rows[1].update(price_usd=None, rejection_reasons=['sin_precio_validado'], eligible=False)
    rows[2].update(shipping_class='pago', rejection_reasons=['envio_pago'], eligible=False)
    rows[3].update(shipping_class='no_envia', rejection_reasons=['envio_no_confirmado'], eligible=False)
    rows[4]['known'] = True
    source = SimpleNamespace(fetch_search_page=lambda *a: dict(products=rows, located_ar=True, has_next=False))
    categories = {'stores': {'US': {'nodes': [{'id': 'A', 'name': 'Prueba', 'kind': 'leaf'}]}}}
    run_all(categories, Config(pause=0), output, dry_run=True, source_factory=lambda *a: source,
            rate_loader=rate, sleep=lambda _: None)
    counts = next(e['datos'] for e in entries(output) if e['evento'] == 'BARRIDO_PAGINA_CONTADORES')
    assert counts['conservados'] == 1 and counts['descartados'] == 5
    assert counts['descartes_por_motivo'] == dict(fuera_de_rango=1, sin_precio=1, envio_pago=1, no_envia=1, duplicado=1)
    assert counts['descartes_novedades_por_motivo'] == {'ya_conocido': 1}


def test_vendor_captcha_y_ubicacion_internos_sin_secretos(tmp_path, monkeypatch):
    pytest.importorskip('curl_cffi')
    from curl_cffi import requests as curl_requests
    from .bootstrap import configure_transport
    from .bootstrap import load_vendor
    load_vendor()
    from amazon import fetch
    monkeypatch.setattr(fetch, '_local', threading.local())
    monkeypatch.setattr(fetch, 'OBSERVER', None)
    form = ('<form action="/errors_page/validateCaptcha">'
            '<input type="hidden" name="amzn" value="privado-captcha"></form>'
            'anti-csrftoken-a2z":"privado-glow"')
    class Curl:
        def __init__(self, **kw):
            self.cookies = SimpleNamespace(set=lambda *a, **kw: None, jar=[])
        def request(self, method, url, **kw):
            if url.endswith('/'):
                return response(200, form, url)
            if 'validateCaptcha' in url:
                return response(302, '', url)
            if url.endswith('address-change'):
                return response(200, '{"isAddressUpdated":1,"address":{"countryCode":"AR"}}', url)
            return response(200, '{}', url)
        def get(self, url, **kw):
            return self.request('GET', url, **kw)
        def post(self, url, **kw):
            return self.request('POST', url, **kw)
    monkeypatch.setattr(curl_requests, 'Session', Curl)
    output = tmp_path / 'barrido'
    with events.observe_run(output, Config(), {}):
        transport = configure_transport(events.vendor_observer)
        transport.page('US', '/s', {}, postal_code='AR')
    records = entries(output)
    names = [e['evento'] for e in records]
    assert 'BARRIDO_CAPTCHA_INICIO' in names and 'BARRIDO_CAPTCHA_FIN' in names
    location = next(e['datos'] for e in records if e['evento'] == 'BARRIDO_UBICACION_FIN')
    assert location['confirmado'] and location['ubicacion_ar']
    assert names.count('BARRIDO_HTTP_FIN') == 6
    assert 'privado-captcha' not in json.dumps(records) and 'privado-glow' not in json.dumps(records)


def test_servidor_ocioso_no_pisa_latido_de_adquisicion(tmp_path):
    output = tmp_path / 'barrido'
    output.mkdir()
    (output / 'latido.json').write_text('{"corrida":"adquisicion"}')
    with events.observe_run(output, Config(), {'servidor': True}) as runtime:
        runtime.progress -= 301
        runtime.heartbeat()
        assert json.loads((output / 'latido.json').read_text()) == {'corrida': 'adquisicion'}
    assert not any(e['evento'] == 'BARRIDO_SIN_AVANCE' for e in entries(output))


def test_falla_de_persistencia_tambien_se_informa_en_stdout(tmp_path, monkeypatch, capsys):
    output = tmp_path / 'barrido'
    with events.observe_run(output, Config(), {}):
        original = Path.open
        def unavailable(path, *args, **kwargs):
            if path.suffix == '.log':
                raise OSError('disco lleno fixture')
            return original(path, *args, **kwargs)
        with monkeypatch.context() as scoped:
            scoped.setattr(Path, 'open', unavailable)
            events.emit_event('BARRIDO_PRUEBA', valor=1)
    literal = capsys.readouterr().out
    assert 'BARRIDO_LOG_ERROR' in literal and 'disco lleno fixture' in literal and 'BARRIDO_PRUEBA' in literal
