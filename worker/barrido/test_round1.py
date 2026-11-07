"""Regresiones de la primera revisión del barrido, sin transporte vendor."""
import json
import os
import time
from pathlib import Path
import pytest
from .config import Config
from .events import now_art
from .test_runner import FakeSource, rate, row
from .runner import run_store, retry_page, enrich_variations
from .state import State, acquire_run_lock
from .shipping import delivery_from_card
from .models import normalize_product
from .amazon_source import SourceError, next_page


@pytest.mark.parametrize('as_dict', [False, True])
@pytest.mark.parametrize('text,expected', [
    ('ENVÍO GRATIS en pedidos superiores a 99 €', 'gratis'),
    ('ENVÍO GRATIS el martes', 'gratis'), ('Entrega GRATIS el lunes', 'gratis'),
    ('Envío de 6,99 € el lunes', 'pago'),
])
def test_es_sin_pais(text, expected, as_dict):
    delivery = {'text': text} if as_dict else text
    assert delivery_from_card({'price': {'amount': 150}, 'delivery': delivery}, located=True)['shipping_class'] == expected


@pytest.mark.parametrize('shipping,reason', [('pago', 'envio_pago'), ('envia_costo_desconocido', 'envio_costo_desconocido')])
def test_solo_gratis_elegible_y_sin_presupuesto(shipping, reason, tmp_path):
    item = normalize_product({'price': 200, 'has_variations': True}, store='US', identity='A', stamp=now_art().isoformat(),
        currency='USD', rate=rate('US', now_art().date().isoformat()), provenance={}, condition='new', located=True,
        shipping={'shipping_class': shipping})
    assert not item['eligible'] and reason in item['rejection_reasons']
    enrich_variations([item], object(), State(tmp_path, 'hoy', 'US'), Config())
    assert not (tmp_path / 'state/hoy/US/variations.json').exists()


def options(source):
    return dict(source_factory=lambda *a: source, rate_loader=rate, sleep=lambda _: None)


def definition(*ids):
    return {'nodes': [dict(id=i, name=i, kind='leaf') for i in ids]}


def test_catalogo_cambia_y_categoria_no_envenena_contexto(tmp_path):
    today = now_art().date().isoformat()
    source = FakeSource(pages=1)
    assert run_store('US', definition('A'), Config(), tmp_path, today, known=['viejo'], **options(source))['status'] == 'complete'
    result = run_store('US', definition('A', 'B'), Config(), tmp_path, today, known=['nuevo'], **options(source))
    assert result['status'] == 'complete'
    assert source.calls == [('A', 1), ('B', 1)]
    metrics = result['categories']['B']
    assert metrics['envio_gratis'] == 1 and metrics['envio_pago'] == metrics['envio_desconocido'] == metrics['no_envia'] == 0


@pytest.mark.parametrize('error', [SourceError('HTTP 404 hoja literal', http=404), SourceError('Highlights sin content: {}'), SourceError('captcha literal', blocked=True)])
def test_categoria_falla_y_sigue(error, tmp_path, capsys):
    class Source(FakeSource):
        def fetch_search_page(self, category, page, stamp):
            if category['id'] == 'A':
                raise error
            return super().fetch_search_page(category, page, stamp)
    result = run_store('US', definition('A', 'B'), Config(backoff=0), tmp_path, now_art().date().isoformat(), **options(Source(pages=1)))
    assert result['status'] == 'partial'
    assert result['categories']['A']['status'] == 'failed'
    assert result['categories']['B']['productos'] == 1
    assert str(error) in capsys.readouterr().out


@pytest.mark.parametrize('error', [TimeoutError('timeout literal'), ConnectionError('conexion literal'), SourceError('HTTP 502 literal', http=502)])
def test_reintenta_transitorios(error, capsys):
    calls, delays = [], []
    def operation():
        calls.append(1)
        if len(calls) < 3:
            raise error
        return {}
    result = retry_page(operation, Config(backoff=30, backoff_cap=45), store='US', category='A', page=1, sleep=delays.append)
    assert result['retry_failures'] == 2 and delays == [30, 45]
    assert str(error) in capsys.readouterr().out


@pytest.mark.parametrize('count', [0, 1])
def test_sin_paginacion_es_final(count):
    assert next_page({'products': [row()] * count, 'count': count}, 1) is None


def test_categoria_vacia_y_pausa_entre_categorias(tmp_path, capsys):
    class Source:
        def fetch_search_page(self, *a):
            return {'products': [], 'count': 0}
    delays = []
    result = run_store('US', definition('A', 'B'), Config(), tmp_path, now_art().date().isoformat(),
        source_factory=lambda *a: Source(), rate_loader=rate, sleep=delays.append)
    assert result['status'] == 'complete' and delays == [5, 5]
    assert capsys.readouterr().out.count('BARRIDO_CATEGORIA_VACIA') == 2


@pytest.mark.parametrize('dry_run', [False, True])
@pytest.mark.parametrize('threshold,expected', [(.5, 'partial'), (1, 'complete')])
def test_ubicacion_mayoria_paginas_parcial(tmp_path, dry_run, threshold, expected):
    class Source(FakeSource):
        def fetch_search_page(self, *a):
            return {**super().fetch_search_page(*a), 'located_ar': False}
    config = Config(unlocated_page_ratio=threshold)
    result = run_store('US', definition('A'), config, tmp_path, now_art().date().isoformat(), dry_run=dry_run, **options(Source(pages=1)))
    assert result['status'] == expected
    if expected == 'partial':
        assert result['reason'] == 'ubicacion_ar_no_confirmada'
    result = run_store('US', definition('A'), config, tmp_path, now_art().date().isoformat(), dry_run=dry_run, **options(Source(pages=1)))
    assert result['status'] == expected


@pytest.mark.parametrize('dead,age', [(True, 0), (False, 9 * 3600)])
def test_recupera_lock_huerfano(dead, age, tmp_path, monkeypatch, capsys):
    from . import state
    monkeypatch.setattr(state, 'pid_alive', lambda pid: not dead, raising=False)
    (tmp_path / 'run.lock').write_text(json.dumps({'pid': os.getpid(), 'started_at': time.time() - age}))
    with acquire_run_lock(tmp_path):
        lock = json.loads((tmp_path / 'run.lock').read_text())
        assert lock['pid'] == os.getpid() and lock['started_at'] > time.time() - 5
    assert 'BARRIDO_LOCK_HUERFANO' in capsys.readouterr().out


def test_cli_rango_real_rechazado(monkeypatch, capsys):
    from . import __main__ as cli
    calls = []
    monkeypatch.setattr(cli, 'run_all', lambda *a, **kw: calls.append(kw) or {})
    assert cli.main(['--min-usd', '50']) == 1 and not calls
    assert '--dry-run' in capsys.readouterr().out
    assert cli.main(['--min-usd', '50', '--dry-run']) == 0


def test_cli_catalogos_anidados(tmp_path, monkeypatch):
    from . import __main__ as cli
    calls = []
    monkeypatch.setattr(cli, 'run_all', lambda *a, **kw: calls.append(kw) or {})
    (tmp_path / 'catalog.json').write_text(json.dumps([{'asin': 'A', 'ml': {'catalogId': 'MLA1'}}]))
    (tmp_path / 'catalog-auto.json').write_text(json.dumps([{'asin': 'B', 'ml': {'catalogId': 'MLA2'}}]))
    assert cli.main(['--catalog', str(tmp_path / 'catalog.json'), '--output', str(tmp_path / 'barrido')]) == 0
    assert calls[0]['known'] == {'A', 'B', 'MLA1', 'MLA2'}


def test_es_cotizacion_vieja_se_omite(tmp_path, capsys):
    from .currency import load_daily_rates
    class Response:
        ok, url = True, 'fixture'
        def json(self):
            return {'venta': 1000, 'fechaActualizacion': '2026-11-05T12:00:00-03:00'}
    result = run_store('ES', definition('A'), Config(), tmp_path, now_art().date().isoformat(),
        rate_loader=lambda store, date: load_daily_rates(store, date, get=lambda *a, **kw: Response()))
    assert result['status'] == 'skipped'
    log = capsys.readouterr().out
    assert 'BARRIDO_ES_SIN_COTIZACION' in log and '2026-11-05T12:00:00-03:00' in log


def test_docker_contexto_y_memoria():
    root = Path(__file__).resolve().parents[1]
    ignored = (root / '.dockerignore').read_text().splitlines()
    assert {'output/', '__pycache__/', '*.pyc', '.pytest_cache/'} <= set(ignored)
    service = (root / 'docker-compose.yml').read_text().split('  weboffers-barrido:')[1].split('  weboffers-deployer:')[0]
    assert 'mem_limit: 512m' in service


def test_reintentos_bloqueos_y_transitorios_independientes():
    failures = iter([TimeoutError('timeout'), SourceError('captcha', blocked=True),
        ConnectionError('conexión'), SourceError('captcha', blocked=True), None])
    def operation():
        error = next(failures)
        if error:
            raise error
        return {}
    data = retry_page(operation, Config(backoff=0), store='US', category='A', page=1, sleep=lambda _: None)
    assert data['retry_failures'] == 4
    assert data['block_failures'] == data['transient_failures'] == 2


def test_fuentes_puras_corren_sin_curl_cffi():
    import subprocess
    import sys
    script = '''
import importlib.abc, sys
class Missing(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname == 'curl_cffi' or fullname.startswith('curl_cffi.'):
            raise ModuleNotFoundError('curl_cffi ausente para la prueba', name='curl_cffi')
sys.meta_path.insert(0, Missing())
import pytest
raise SystemExit(pytest.main(['test_state.py', 'test_shipping.py',
    'test_currency.py', 'test_config.py', '-q', '-p', 'no:cacheprovider']))
'''
    # cwd = carpeta de este test: anda igual desde la raíz del repo y en el contenedor (que monta sólo worker/).
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
        cwd=Path(__file__).resolve().parent)
    assert result.returncode == 0, result.stdout + result.stderr
