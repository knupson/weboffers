"""Dos pasadas sin red: búsqueda por API y ofertas del Chrome con perfil."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from .config import Config
from .ml_lookup import run_ml_lookup
from .test_ml_lookup import amazon, rate, read_output, today, write_input

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import ml_chrome


def test_dos_pasadas_conservan_filtros_y_checkpoint(tmp_path, monkeypatch):
    from .ml_chrome import ChromeLookup
    write_input(tmp_path, [amazon()])
    calls = []

    def get(path, params=None):
        calls.append(path)
        assert path == '/products/search'
        return {'results': [{'id': 'MLA123456', 'name': 'Monitor Samsung S36GD'}]}

    plan = ChromeLookup(Config(ml_pause=0), tmp_path, prepare=True, get=get)
    run_ml_lookup(Config(), tmp_path, client=plan, dry_run=True, limit=100000, rate_loader=rate)
    assert not (tmp_path / f'ml-candidatos-{today()}.jsonl').exists()
    assert json.loads(plan.path.read_text())['catalogos'] == ['MLA123456']
    items = [dict(item_id=f'MLA{100000 + n}', price=price, currency_id=currency, condition=condition)
             for n, (price, currency, condition) in enumerate([
                 (10, 'ARS', 'new'), (20, 'ARS', 'used'), (30, 'USD', 'new'),
                 (0, 'ARS', 'new'), (200000, 'ARS', 'new')])]
    pagina = dict(catalogo='MLA123456', items=items,
                  ofertas=[dict(ids=[i['item_id']], cbt=n == 0) for n, i in enumerate(items)])

    async def leer(*args):
        return pagina

    monkeypatch.setattr(ml_chrome, 'leer_pagina', leer)
    results, motivo, paginas = asyncio.run(ml_chrome.leer_catalogo(None, None, 'MLA123456'))
    (tmp_path.parent / f'ml-chrome-{today()}.json').write_text(json.dumps(dict(date=today(), items={
        'MLA123456': dict(results=results, motivo=motivo, paginas=paginas, leido=today() + 'T12:00:00-03:00')})))
    client = ChromeLookup(Config(), tmp_path, get=lambda *a, **kw: pytest.fail('No se repite la búsqueda'))
    result = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    assert result['con_candidatos'] == 1
    assert read_output(tmp_path)[0]['candidates'][0]['price_ars'] == 200000
    assert client.cheapest('MLA123456') == (200000, 'MLA100004')
    resumed = run_ml_lookup(Config(), tmp_path, client=client, rate_loader=rate)
    assert resumed['productos_procesados'] == 0
    assert calls == ['/products/search', '/products/search']  # la preparación cubre ambas consultas posibles


@pytest.mark.parametrize('entry', [None, {'results': None, 'motivo': 'verificacion_ml'},
                                  {'results': [], 'leido': '2000-01-01T12:00:00-03:00'}])
def test_lectura_ausente_fallida_o_vieja_es_error(tmp_path, entry):
    from .ml_chrome import ChromeLookup
    from .amazon_source import SourceError
    (tmp_path.parent / f'ml-chrome-{today()}.json').write_text(json.dumps(dict(date=today(), items={'MLA123': entry})))
    with pytest.raises(SourceError):
        ChromeLookup(Config(), tmp_path).cheapest('MLA123')


def test_tope_catalogos_no_confirma_sin_resultados(tmp_path):
    from .ml_chrome import ChromeLookup
    from .ml_lookup import MLBudget
    client = ChromeLookup(Config(), tmp_path, prepare=True, max_catalogs=1)
    assert client.cheapest('MLA123') is None
    with pytest.raises(MLBudget):
        client.cheapest('MLA456')
    assert json.loads(client.path.read_text())['catalogos'] == ['MLA123']


def test_presupuesto_persiste_y_reanuda_la_fila_pendiente(tmp_path, monkeypatch):
    from .ml_chrome import ChromeLookup
    write_input(tmp_path, [amazon('A1'), amazon('A2')])
    catalog = tmp_path / 'catalog.json'
    catalog.write_text(json.dumps([dict(asin='A1', ml=dict(catalogId='MLA123')),
                                   dict(asin='A2', ml=dict(catalogId='MLA456'))]))
    path = tmp_path.parent / f'ml-chrome-{today()}.json'
    entry = dict(results=[dict(item_id='MLA100', price=200000, currency_id='ARS', condition='new')],
                 leido=today() + 'T12:00:00-03:00', motivo='ok')
    path.write_text(json.dumps(dict(date=today(), items={'MLA123': entry})))
    result = run_ml_lookup(Config(), tmp_path, client=ChromeLookup(Config(), tmp_path),
                           catalog_path=catalog, rate_loader=rate)
    assert result['presupuesto_agotado'] and result['errores'] == 0
    assert [r['asin'] for r in read_output(tmp_path)] == ['A1']
    path.write_text(json.dumps(dict(date=today(), items={'MLA456': entry})))
    resumed = run_ml_lookup(Config(), tmp_path, client=ChromeLookup(Config(), tmp_path),
                            catalog_path=catalog, rate_loader=rate)
    assert resumed['productos_procesados'] == 1 and resumed['con_candidatos'] == 2
    assert [r['asin'] for r in read_output(tmp_path)] == ['A1', 'A2']


def test_reintentos_no_duermen_mas_que_el_presupuesto(tmp_path, monkeypatch):
    from .ml_chrome import ChromeLookup
    from .ml_lookup import MLBudget
    monkeypatch.setenv('BARRIDO_ML_SEGUNDOS', '10')
    client = ChromeLookup(Config(), tmp_path, prepare=True,
                          sleep=lambda s: pytest.fail('No debe esperar fuera de presupuesto'))
    with pytest.raises(MLBudget):
        client.sleep(30)


def test_pagina_cdp_falsa_se_lee_con_el_parser_compartido(monkeypatch):
    class Page:
        def __init__(self):
            self.urls = []

        async def call(self, method, params, *args, **kwargs):
            if method == 'Page.navigate':
                self.urls.append(params['url'])
                return {}
            assert method == 'Runtime.evaluate' and params['expression'] == ml_chrome.LEER
            return {'result': {'value': json.dumps({'catalogo': 'MLA123', 'items': []})}}

    async def sleep(*args):
        pass

    monkeypatch.setattr(ml_chrome.asyncio, 'sleep', sleep)
    page = Page()
    data = asyncio.run(ml_chrome.leer_pagina(page, 'perfil', 'https://www.mercadolibre.com.ar/p/MLA123/s'))
    assert page.urls[0] == 'about:blank'
    assert ml_chrome.interpretar([data], 'MLA123') == (None, 'sin_items')


def test_lista_barrido_omite_solo_lecturas_buenas_de_hoy(tmp_path, monkeypatch, capsys):
    from tools import ml_chrome_listar
    from .ml_chrome import ChromeLookup
    output = tmp_path / 'barrido'
    client = ChromeLookup(Config(), output, prepare=True)
    for cid in ('MLA123', 'MLA456', 'MLA789'):
        client.cheapest(cid)
    data = dict(date=today(), items={
        'MLA123': dict(results=[], leido=today() + 'T12:00:00-03:00'),
        'MLA456': dict(results=None, leido=today() + 'T12:00:00-03:00'),
        'MLA789': dict(results=[], leido='2000-01-01T12:00:00-03:00')})
    (tmp_path / f'ml-chrome-{today()}.json').write_text(json.dumps(data))
    monkeypatch.setattr(ml_chrome_listar, 'salida', lambda: tmp_path)
    ml_chrome_listar.listar(barrido=True)
    assert capsys.readouterr().out.splitlines() == ['MLA456', 'MLA789']


def test_tope_global_cancela_catalogo_sin_guardar_precio_parcial(monkeypatch):
    tiempos = iter([0, 0, 6])
    monkeypatch.setattr(ml_chrome, 'time', SimpleNamespace(monotonic=lambda: next(tiempos)))
    monkeypatch.setattr(ml_chrome, 'INICIO', 0)
    monkeypatch.setattr(ml_chrome, 'TOPE', 5)

    async def wait_for(coroutine, timeout):
        coroutine.close()
        assert timeout == 5
        raise asyncio.TimeoutError()

    monkeypatch.setattr(ml_chrome.asyncio, 'wait_for', wait_for)
    items = {}
    async def run():
        with pytest.raises(ml_chrome.TopeML):
            await ml_chrome.recorrer(None, None, 'tab', 'perfil', ['MLA123'], items)
    asyncio.run(run())
    assert items == {}


def test_timeout_de_catalogo_es_falla_y_se_registra_con_hora(monkeypatch, capsys):
    monkeypatch.setenv('ML_CHROME_BARRIDO', '--barrido')
    monkeypatch.setattr(ml_chrome, 'time', SimpleNamespace(monotonic=lambda: 0))
    monkeypatch.setattr(ml_chrome, 'INICIO', 0)
    monkeypatch.setattr(ml_chrome, 'TOPE', 300)

    async def wait_for(coroutine, timeout):
        coroutine.close()
        assert timeout == 120
        raise asyncio.TimeoutError()

    async def sleep(*args):
        pass

    monkeypatch.setattr(ml_chrome.asyncio, 'wait_for', wait_for)
    monkeypatch.setattr(ml_chrome.asyncio, 'sleep', sleep)
    items = {}
    asyncio.run(ml_chrome.recorrer(None, None, 'tab', 'perfil', ['MLA123'], items))
    assert items['MLA123']['results'] is None and items['MLA123']['motivo'] == 'timeout_catalogo'
    log = capsys.readouterr().err
    assert ' BARRIDO_ML_CHROME_CATALOGO catalogo=MLA123 ' in log
    assert log.startswith(today())


def test_respuesta_tardia_no_rompe_la_sesion_cdp():
    async def messages():
        yield json.dumps({'id': 1})
        yield json.dumps({'id': 2, 'result': {}})

    async def run():
        client = ml_chrome.Cdp(messages())
        first = asyncio.get_running_loop().create_future()
        first.cancel()
        second = asyncio.get_running_loop().create_future()
        client.pend = {1: first, 2: second}
        await client.run()
        assert second.result()['id'] == 2 and not client.pend

    asyncio.run(run())
