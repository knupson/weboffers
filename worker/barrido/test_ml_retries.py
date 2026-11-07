"""Transporte simulado: límites, pausas y reintentos sin red ni espera real."""
from datetime import timedelta
from email.utils import format_datetime
import json

import pytest
import requests

from . import ml_lookup
from .config import Config
from .events import now_art
from .ml_lookup import MLClient, run_ml_lookup
from .test_ml_lookup import amazon, write_input, rate, read_output


class Clock:
    def __init__(self):
        self.value, self.delays = 0, []

    def __call__(self):
        return self.value

    def sleep(self, seconds):
        self.delays.append(seconds)
        self.value += seconds


def http_error(status=429, retry_after=None):
    response = requests.Response()
    response.status_code, response._content = status, b'{"message":"No winners found"}'
    if retry_after is not None:
        response.headers['Retry-After'] = retry_after
    return requests.HTTPError(str(status), response=response)


def test_intervalo_minimo_entre_inicios_descuenta_tiempo_http():
    clock = Clock()
    starts = []
    def get(*a, **kw):
        starts.append(clock())
        clock.value += .2
        return {'results': []}
    client = MLClient(Config(ml_pause=1), get=get, sleep=clock.sleep, clock=clock)
    client.search('primera')
    client.search('segunda')
    assert starts == [0, 1]
    assert clock.delays == [.8]


@pytest.mark.parametrize('header,expected', [('7', 7), ('0', 0), (None, 2),
    ('inválido', 2), ('NaN', 2), ('-1', 2)])
def test_429_reintenta_y_loguea_hasta(header, expected, capsys):
    clock, calls = Clock(), []
    def get(*a, **kw):
        calls.append(1)
        if len(calls) == 1:
            raise http_error(retry_after=header)
        return {'results': []}
    client = MLClient(Config(ml_pause=0, ml_backoff=2), get=get, sleep=clock.sleep, clock=clock)
    assert client.search('HP CF258A') == []
    assert clock.delays == [expected] and client.requests_ml == 2
    event = next(line for line in capsys.readouterr().out.splitlines()
                 if 'BARRIDO_ESPERA ' in line)
    assert 'backoff_429_ml' in event and '"hasta":' in event


def test_retry_after_fecha_y_racha_reiniciada(monkeypatch):
    stamp = now_art().replace(microsecond=0)
    monkeypatch.setattr(ml_lookup, 'now_art', lambda: stamp)
    clock, calls = Clock(), []
    def get(*a, **kw):
        calls.append(1)
        if len(calls) in (1, 3):
            raise http_error(retry_after=format_datetime(stamp + timedelta(seconds=9)))
        return {'results': []}
    client = MLClient(Config(ml_pause=0, ml_consecutive_429=2), get=get, sleep=clock.sleep, clock=clock)
    client.search('primera')
    client.search('segunda')
    assert clock.delays == [9, 9]


def test_un_429_no_bloquea_la_etapa(tmp_path):
    write_input(tmp_path, [amazon()])
    clock, calls = Clock(), []
    def get(path, params=None):
        calls.append(path)
        if len(calls) == 1:
            raise http_error()
        return {'results': []}
    client = MLClient(Config(ml_pause=0, ml_backoff=1), get=get, sleep=clock.sleep, clock=clock)
    result = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    assert result['status'] == 'complete' and result['errores'] == 0
    assert result['requests_ml'] == 3 and clock.delays == [1]


def test_agota_racha_guarda_error_y_reanuda_solo_pendiente(tmp_path, capsys):
    write_input(tmp_path, [amazon(), amazon('OTRO')])
    clock, attempts = Clock(), []
    def get(path, params=None):
        if path == '/products/search':
            return {'results': [{'id': 'MLA1', 'name': 'Monitor Samsung S36GD'}]}
        attempts.append(1)
        if len(attempts) > 1:
            raise http_error()
        return {'results': [{'price': 200000, 'condition': 'new', 'currency_id': 'ARS', 'item_id': 'MLA1'}]}
    config = Config(ml_pause=0, ml_consecutive_429=3, ml_backoff=2, ml_backoff_cap=3)
    client = MLClient(config, get=get, sleep=clock.sleep, clock=clock)
    result = run_ml_lookup(config, tmp_path, client=client, rate_loader=rate)
    assert result['status'] == 'blocked' and result['requests_ml'] == 6
    assert clock.delays == [2, 3]
    # El orden del archivo no está garantizado: se compara por producto.
    estados = {r['asin']: r['lookup_status'] for r in read_output(tmp_path)}
    assert estados.pop('OTRO') == 'error' and list(estados.values()) == ['ok']
    assert 'limite_429_consecutivos_ml' in capsys.readouterr().out
    calls = []
    def resumed(path, params=None):
        calls.append(path)
        return {'results': []}
    result = run_ml_lookup(config, tmp_path, client=MLClient(config, get=resumed,
                           sleep=clock.sleep, clock=clock), rate_loader=rate)
    assert result['status'] == 'complete' and result['productos_procesados'] == 1
    assert calls == ['/products/search', '/products/search']


def test_prefiltro_orden_404_primera_oferta_y_metricas(tmp_path, fixture_dir, capsys):
    case = json.loads((fixture_dir / 'ml_matching.json').read_text(encoding='utf-8'))[0]
    write_input(tmp_path, [amazon(title=case['title'], raw=case['raw'])])
    calls = []
    def get(path, params=None):
        calls.append(path)
        if path == '/products/search':
            return {'results': [{'id': 'MAL', 'name': case['wrong']},
                {'id': 'VACIO', 'name': case['right']}, {'id': 'BUENO', 'name': case['right']},
                {'id': 'SOBRA', 'name': case['right']}]}
        if 'VACIO' in path:
            raise http_error(404)
        return {'results': [{'price': 200000, 'currency_id': 'ARS', 'condition': 'new', 'item_id': 'MLA1'}]}
    client = MLClient(Config(ml_pause=0), get=get, sleep=lambda _: None)
    result = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    assert calls == ['/products/search', '/products/VACIO/items', '/products/BUENO/items']
    assert result['requests_ml'] == result['requests_ml_por_producto'] == 3
    assert result['items_404'] == result['productos_procesados'] == result['productos_con_candidato'] == 1
    lines = capsys.readouterr().out.splitlines()
    assert any('candidato_no_coincide' in line and 'marca' not in line for line in lines)
    end = json.loads(next(line.split('BARRIDO_ETAPA_FIN ', 1)[1] for line in lines if 'BARRIDO_ETAPA_FIN ' in line))
    summary = json.loads((tmp_path / f'resumen-{now_art().date()}.json').read_text(encoding='utf-8'))['stores']['ML']
    for key in ['requests_ml', 'requests_ml_por_producto', 'items_404', 'productos_procesados', 'productos_con_candidato']:
        assert end[key] == summary[key] == result[key]


def test_mejor_puntaje_primero_y_tope_cinco_items(tmp_path):
    write_input(tmp_path, [amazon()])
    calls = []
    def get(path, params=None):
        calls.append(path)
        if path == '/products/search':
            return {'results': [{'id': f'MLA{i}', 'name': 'Monitor Samsung S36GD'} for i in range(8)] +
                    [{'id': 'MEJOR', 'name': 'Monitor Samsung Essential S3 S36GD Curved FHD'}]}
        return {'results': []}
    client = MLClient(Config(ml_pause=0), get=get, sleep=lambda _: None)
    run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    assert calls == ['/products/search', '/products/MEJOR/items',
                     *[f'/products/MLA{i}/items' for i in range(4)]]


def test_descartes_no_consumen_tope_y_no_repite_catalogo_en_fallback(tmp_path):
    write_input(tmp_path, [amazon()])
    calls = []
    def get(path, params=None):
        calls.append(path)
        if path == '/products/search':
            return {'results': [{'id': f'MAL{i}', 'name': 'Mochila Samsung'} for i in range(8)] +
                    [{'id': 'MLA1', 'name': 'Monitor Samsung S36GD'}]}
        raise http_error(404)
    result = run_ml_lookup(Config(), tmp_path, client=MLClient(Config(ml_pause=0), get=get,
                           sleep=lambda _: None), rate_loader=rate)
    assert calls == ['/products/search', '/products/MLA1/items', '/products/search']
    assert result['items_404'] == 1 and result['sin_resultados'] == 1


def test_404_en_pagina_siguiente_no_usa_oferta_parcial():
    calls = []
    def get(path, params=None):
        calls.append(params['offset'])
        if params['offset']:
            raise http_error(404)
        return {'results': [{'price': 200000, 'currency_id': 'ARS', 'condition': 'new',
                             'item_id': 'MLA1'}], 'paging': {'total': 2}}
    client = MLClient(Config(ml_pause=0), get=get, sleep=lambda _: None)
    assert client.cheapest('MLA1') is None
    assert calls == [0, 1] and client.items_404 == 1


def test_regresiones_rechazadas_no_consultan_items(tmp_path, fixture_dir):
    cases = json.loads((fixture_dir / 'ml_matching.json').read_text(encoding='utf-8'))
    write_input(tmp_path, [amazon(str(i), title=case['title'], raw=case.get('raw', {}))
                           for i, case in enumerate(cases)])
    calls = []
    def get(path, params=None):
        calls.append(path)
        assert path == '/products/search'
        return {'results': [{'id': str(i), 'name': case['wrong']} for i, case in enumerate(cases)]}
    result = run_ml_lookup(Config(), tmp_path, client=MLClient(Config(ml_pause=0), get=get,
                           sleep=lambda _: None), rate_loader=rate)
    assert result['sin_resultados'] == len(cases) and result['errores'] == 0
    assert result['items_404'] == 0 and all('/items' not in path for path in calls)


def test_pausa_y_429_oauth_tambien_se_contabilizan(tmp_path, monkeypatch):
    import ml_prices
    monkeypatch.setenv('ML_CLIENT_ID', 'fixture')
    monkeypatch.setenv('ML_CLIENT_SECRET', 'fixture')
    monkeypatch.setattr(ml_prices, '_token_cache', {'value': None, 'expires_at': 0})
    clock, calls = Clock(), []
    client = MLClient(Config(ml_pause=1, ml_backoff=2), sleep=clock.sleep, clock=clock)
    def request(method, url, **kw):
        calls.append((method, url, clock()))
        response = requests.Response()
        response.status_code = 429 if len(calls) == 1 else 200
        response._content = (b'{}' if len(calls) == 1 else b'{"access_token":"fixture"}'
                             if url.endswith('/oauth/token') else b'{"results":[]}')
        return response
    monkeypatch.setattr(client.transport, 'request', request)
    assert client.search('Samsung') == []
    assert [c[2] for c in calls] == [0, 2, 3]
    assert client.requests_ml == 3 and clock.delays == [2, 1]


@pytest.mark.parametrize('options', [{'ml_consecutive_429': 1}, {'ml_consecutive_429': 2.5},
    {'ml_backoff': -1}, {'ml_backoff_cap': -1}])
def test_configuracion_ml_invalida(options):
    with pytest.raises(ValueError):
        Config(**options)
