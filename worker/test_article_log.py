"""Desglose por artículo sin red: formatos, omisiones y resultados reales de cada flujo."""
from datetime import date, datetime, timezone
import io
import json

import pytest
import requests
import amazon_prices as amazon
import ml_prices as ml
from article_log import chrome_line, amazon_line, ml_line
from worker import DailyLog


def test_chrome_formato_y_daily_log(tmp_path):
    stream = io.StringIO()
    log = DailyLog(tmp_path, stream)
    line = chrome_line(['kindle', 'kindle-negro'], 'B0CFPJYX7P', {
        'ships': True, 'free': True, 'precio': '$159.99', 'text': 'FREE delivery\nto Argentina', 'motivo': None,
    })
    print(line, file=log, flush=True)
    assert line == 'CHROME_PRODUCTO slugs=kindle,kindle-negro asin=B0CFPJYX7P ships=true free=true precio=$159.99 motivo=ok texto="FREE delivery to Argentina"'
    text = next(tmp_path.glob('worker-*.log')).read_text(encoding='utf-8')
    datetime.strptime(text[:19], '%Y-%m-%d %H:%M:%S')
    assert line in text
    assert 'motivo=captcha' in chrome_line([], 'A', {'motivo': 'captcha'})


def test_amazon_omite_cada_producto_con_valor_y_motivo(capsys):
    products = [{'slug': s, 'asin': s.upper(), 'store': 'US'} for s in ['caro', 'sin-ml', 'ausente', 'bueno']]
    previous = {'outOfRange': {'caro': {'amount': 800, 'currency': 'USD'}, 'sin-ml': {'motivo': 'sin_ml_local'}}}
    keep, skipped = amazon.in_range(products, previous, date(2026, 11, 6), ml_prices={'date': '2026-11-05', 'absent': ['ausente']})
    assert keep == [products[-1]] and skipped == 3
    text = capsys.readouterr().out
    assert 'slug=caro asin=CARO store=US source=memoria amount=800 currency=USD' in text
    assert 'motivo=omitido_fuera_de_rango usd=800' in text
    assert 'motivo=omitido_sin_ml_local\n' in text
    assert 'motivo=omitido_sin_ml_local_ayer' in text


def test_pasada_sin_consulta_deja_una_sola_linea(tmp_path, monkeypatch, capsys):
    now = datetime(2026, 11, 6, 15, tzinfo=timezone.utc)
    product = {'slug': 'kindle', 'asin': 'B0CFPJYX7P', 'store': 'US', 'verified': True, 'ml': {'catalogId': 'MLA123'}}
    amz = tmp_path / 'amazon-prices.json'
    amz.write_text(json.dumps({'date': '2026-11-06', 'retryCount': 3, 'items': {'kindle': {'amount': 159.99, 'currency': 'USD', 'checked': '2026-11-06'}}}))
    local = tmp_path / 'ml-prices.json'
    local.write_text(json.dumps({'date': '2026-11-06', 'slot': '2026-11-06T06', 'items': {'kindle': {'price': 650000, 'checked': '2026-11-06'}}}))
    monkeypatch.setattr(amazon, 'scraper_url', lambda: 'http://sin-red')
    assert amazon.maybe_refresh([product], amz, now, force=True) is False
    assert ml.maybe_refresh([product], local, amz, 1200, now, force=True) is False
    text = capsys.readouterr().out
    # 06/11: sin consulta no se repite el detalle por artículo cada hora (ya quedó en la corrida que consultó).
    assert 'AMAZON_PRODUCTO' not in text and 'ML_PRODUCTO' not in text
    assert 'Amazon: sin consulta en esta pasada' in text
    assert 'Mercado Libre: sin consulta en esta pasada (slot 2026-11-06T06 ya ejecutado)' in text


def test_amazon_reintento_registra_el_resultado_por_producto(tmp_path, monkeypatch, capsys):
    product = {'slug': 'kindle', 'asin': 'B0CFPJYX7P', 'store': 'US'}
    item = {'amount': 159.99, 'currency': 'USD', 'checked': '2026-11-06'}
    monkeypatch.setattr(amazon, 'prices_with_chrome', lambda *a: ({'kindle': item}, 1, 0))
    monkeypatch.setattr(amazon, 'shipping_candidates', lambda *a, **kw: [])
    monkeypatch.setattr(amazon, 'refresh_ar_shipping', lambda *a: {})
    monkeypatch.setattr(amazon, 'chrome_shipping', lambda *a: {})
    monkeypatch.setattr(amazon, 'failures', [])
    path = tmp_path / 'amazon-prices.json'
    local = datetime(2026, 11, 6, 12, tzinfo=amazon.ART)
    assert amazon.retry_missing({'date': '2026-11-06', 'items': {}}, [product], path, local, 'http://sin-red')
    assert amazon_line(product, 'retry', item) in capsys.readouterr().out


def test_amazon_chrome_scraper_exitos_y_fallas(tmp_path, monkeypatch, capsys):
    products = [{'slug': s, 'asin': s, 'store': 'US'} for s in ['chrome', 'sin-oferta', 'scraper', 'fallo', 'inverosimil']]
    path = tmp_path / 'amazon-prices.json'
    (tmp_path / 'ar-chrome-2026-11-06.json').write_text(json.dumps({'items': {
        'chrome': {'ships': True, 'free': True, 'precio': '$159.99', 'text': 'FREE delivery to Argentina'},
        'sin-oferta': {'ships': False, 'free': None, 'motivo': 'sin_oferta_ar'},
    }}))
    monkeypatch.setattr(amazon, 'pause', lambda: None)
    monkeypatch.setattr(amazon, 'plausible', lambda parsed, product: product['slug'] != 'inverosimil')
    monkeypatch.setattr(amazon, 'fetch_chunk', lambda *args: ({
        **{s: {'price': {'amount': 180, 'currency': 'USD'}, 'availability': {'is_in_stock': True}}
           for s in ['scraper', 'inverosimil']},
        'fallo': {'price': None, 'buybox': None}
    }, None))
    got, ok, missing = amazon.prices_with_chrome('http://sin-red', products, '2026-11-06', path)
    assert (ok, missing) == (2, 3)
    text = capsys.readouterr().out
    assert amazon_line(products[0], 'chrome', got['chrome']) in text
    assert 'source=chrome amount=ausente currency=ausente checked=ausente motivo=sin_oferta_ar_chrome' in text
    assert amazon_line(products[2], 'scraper', got['scraper']) in text
    assert 'motivo=sin_precio_ni_vendedor' in text
    assert 'motivo=precio_inverosimil' in text
    assert 'CHROME_PRODUCTO slugs=chrome' in text


@pytest.mark.parametrize('status', ['ok', 'absent', 'failed', 'variantConflict'])
def test_ml_resultados_por_producto(tmp_path, monkeypatch, capsys, status):
    p = {'slug': 'monitor', 'verified': True, 'ml': {'catalogId': 'MLA123', 'price': 650000}}
    monkeypatch.setattr(ml, 'is_configured', lambda: True)
    monkeypatch.setattr(ml, 'pause', lambda: None)
    monkeypatch.setattr(ml, 'functional_conflicts', lambda *a: ['color distinto'] if status == 'variantConflict' else [])
    def fetch(_id):
        if status == 'failed':
            raise requests.RequestException('simulado')
        return [] if status == 'absent' else [{'price': 650000, 'condition': 'new', 'id': 'MLA999'}]
    monkeypatch.setattr(ml, 'fetch_items', fetch)
    path = tmp_path / 'ml-prices.json'
    assert ml.maybe_refresh([p], path, tmp_path / 'amazon.json', 1200, datetime(2026, 11, 6, 15, tzinfo=timezone.utc), force=True)
    data = json.loads(path.read_text())
    item = data['items'].get('monitor')
    reason = {'ok': None, 'absent': 'sin_oferta_local_nueva', 'failed': 'consulta_RequestException', 'variantConflict': 'color distinto'}[status]
    assert ml_line(p, status, item, reason) in capsys.readouterr().out
    if status == 'ok':
        assert item['price'] == 650000 and item['checked'] == '2026-11-06'
    else:
        assert 'monitor' in data[status]
