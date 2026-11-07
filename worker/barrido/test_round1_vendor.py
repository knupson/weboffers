import pytest
pytest.importorskip('curl_cffi', reason='dependencias del barrido: correr en su contenedor')
from types import SimpleNamespace
from .bootstrap import configure_transport
from .amazon_source import AmazonSource
from .config import Config
from .test_runner import rate


def test_ubicacion_falla_una_vez_por_sesion(capsys):
    fetch = configure_transport()
    calls = []
    class Curl:
        def get(self, *a, **kw):
            calls.append(1)
            raise TimeoutError('glow timeout literal')
    session = SimpleNamespace(located=None, glow_token='token', site={'base': 'fixture'},
        curl=Curl(), headers=lambda *a: {})
    assert fetch.set_location(session, 'AR') is False
    assert fetch.set_location(session, 'AR') is False
    assert calls == [1] and session.located is None
    assert 'BARRIDO_UBICACION_FALLIDA' in capsys.readouterr().out


def test_pausa_despues_preconsulta(tmp_path, monkeypatch):
    events = []
    source = AmazonSource('US', '2026-11-07', rate('US', '2026-11-07'), Config(), tmp_path,
        sleep=lambda value: events.append(('sleep', value)))
    parsed = {'results': [{'asin': 'A', 'price': {'amount': 200, 'currency': 'USD'}, 'delivery': 'FREE delivery'}],
        'refinements': [{'id': 'p_n_condition-type', 'options': [{'name': 'New', 'value': 'fixture'}]}]}
    monkeypatch.setattr(source, 'request', lambda params: events.append(('request', params)) or parsed)
    monkeypatch.setattr(source.fetch, 'session', lambda *a: SimpleNamespace(located='AR'))
    source.fetch_search_page({'id': 'A', 'name': 'Prueba'}, 1, '2026-11-07T12:00:00-03:00')
    assert [e[0] for e in events] == ['request', 'sleep', 'request']


def test_preconsulta_categoria_vacia_sin_refinamientos(tmp_path, monkeypatch):
    source = AmazonSource('US', '2026-11-07', rate('US', '2026-11-07'), Config(), tmp_path, sleep=lambda _: None)
    calls = []
    monkeypatch.setattr(source, 'request', lambda params: calls.append(params) or {'results': [], 'count': 0})
    monkeypatch.setattr(source.fetch, 'session', lambda *a: SimpleNamespace(located='AR'))
    page = source.fetch_search_page({'id': 'A', 'name': 'Vacía'}, 1, '2026-11-07T12:00:00-03:00')
    assert page['products'] == [] and len(calls) == 1
