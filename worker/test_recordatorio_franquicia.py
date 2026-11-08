"""Controles de publicación sin enviar mensajes ni consultar la red."""
from datetime import datetime
import json

import pytest
from tools import recordatorio_franquicia as reminder


def download(state):
    def get(url):
        if url.endswith("estado.json"):
            return json.dumps(state)
        return '"2026-11-03"' + '"@type":"ListItem"' * 100
    return get


@pytest.mark.parametrize("mode", ["sitio", "sitio13"])
@pytest.mark.parametrize("prices", [None, "2026-11-02"])
def test_estado_requires_today_prices(mode, prices):
    now = datetime.fromisoformat("2026-11-03T15:30:00-03:00")
    text = reminder.control(mode, now, download({"preciosDe": prices, "amazon": {}}))
    assert "estado.json no tiene los precios de hoy" in text


def test_missing_worker_data_alerts_even_with_hundred_products():
    now = datetime.fromisoformat("2026-11-03T07:30:00-03:00")
    assert "sin datos del worker" in reminder.control("sitio", now, download({"preciosDe": "2026-11-03", "amazon": None}))
    assert not reminder.control("sitio", now, download({"preciosDe": "2026-11-03", "amazon": {}}))


def test_extra_check_skips_regular_days_and_checks_minimum():
    assert not reminder.control("sitio13", datetime.fromisoformat("2026-11-05T15:30:00-03:00"),
                                lambda _: pytest.fail("No debe consultar"))
    now = datetime.fromisoformat("2026-11-03T15:30:00-03:00")
    assert "mínimo 100" in reminder.control("sitio13", now, lambda url: json.dumps(
        {"preciosDe": "2026-11-03", "amazon": {}}) if url.endswith(".json") else '"2026-11-03"')


def test_failed_catalog_alerts_even_with_additions():
    state = {"catalogo": {"week": "2026-W45", "status": "failed", "added": 2, "motivos": ["sin_foto"]}}
    text = reminder.control_catalogo(datetime.fromisoformat("2026-11-09T07:30:00-03:00"), download(state))
    assert "falló" in text and "altas=2" in text and "sin_foto" in text


def test_calendario_sin_vencimiento_despues_de_noviembre():
    """El esqueleto semanal sigue en diciembre (antes vencía el 30/11)."""
    import datetime as _dt
    assert "armá el Reel del día" in reminder.mensaje(_dt.date(2026, 12, 8))  # martes
    assert "armá el carrusel" in reminder.mensaje(_dt.date(2026, 12, 7))  # lunes


def test_reel19_controla_tambien_los_reels_especiales(monkeypatch):
    import datetime as _dt
    monkeypatch.setattr(reminder, "leer_meta_env", lambda: (_ for _ in ()).throw(RuntimeError("se consultó Meta")))
    viernes_normal = _dt.datetime(2026, 11, 6, 19, 10, tzinfo=reminder.ART)
    assert reminder.control("reel19", viernes_normal) == ""
    black_friday = _dt.datetime(2026, 11, 27, 19, 10, tzinfo=reminder.ART)
    assert "no pude comprobar el Reel" in reminder.control("reel19", black_friday)  # el día especial se controla


def test_no_manda_whatsapp_antes_de_las_7(monkeypatch):
    # Alejandro, 07/11: ningún WhatsApp antes de las 7. El vigía guarda el aviso como pendiente y sale a las 07:00.
    llamados = []
    monkeypatch.setattr(reminder.urllib.request, "urlopen", lambda *a, **k: llamados.append(a))
    with pytest.raises(SystemExit):
        reminder.enviar("aviso", "prueba", ahora=datetime.fromisoformat("2026-11-07T06:59:00-03:00"))
    assert llamados == []


def test_manda_whatsapp_desde_las_7(monkeypatch):
    class Resp:
        def read(self):
            return b"{}"
    llamados = []
    monkeypatch.setattr(reminder, "leer_env", lambda: {"WAHA_URL": "https://waha", "WA_NOTIFY_CHAT_ID": "chat"})
    monkeypatch.setattr(reminder.urllib.request, "urlopen", lambda *a, **k: llamados.append(a) or Resp())
    reminder.enviar("aviso", "prueba", ahora=datetime.fromisoformat("2026-11-07T07:00:00-03:00"))
    assert len(llamados) == 1


def test_cola_de_revision_pide_revisar_las_altas_solo_a_las_0730():
    now = datetime.fromisoformat("2026-11-03T07:30:00-03:00")
    base = {"preciosDe": "2026-11-03", "amazon": {}}
    assert not reminder.control("sitio", now, download({**base, "catalogo": {"revision": 0}}))
    assert "«revisá las altas»" in reminder.control("sitio", now, download({**base, "catalogo": {"revision": 3}}))
    assert "revisá las altas" not in reminder.control("sitio13", now, download({**base, "catalogo": {"revision": 3}}))


def _estado(amazon):
    return lambda url: json.dumps({"amazon": amazon})


def test_causa_amazon_informa_lo_que_falta_tras_los_reintentos():
    """08/11: el aviso decía «Amazon dejó 39 sin precio» cuando el reintento de las 05:04 ya había recuperado 36."""
    run = {"fallas": 39, "motivos": {"sin_stock": 23, "sin_precio_ni_vendedor": 15, "precio_inverosimil": 1},
           "reintento": {"recuperados": 36, "pendientes": 1},
           "faltan": {"total": 1, "motivos": {"precio_inverosimil": 1}}}
    texto = reminder.causa_amazon(_estado(run))
    assert "faltan 1 sin precio de Amazon (1 precio_inverosimil)" in texto
    assert "la corrida dejó 39" in texto and "los reintentos recuperaron 36" in texto
    assert "Amazon dejó 39" not in texto


def test_causa_amazon_sin_faltantes_dice_que_no_es_amazon():
    run = {"fallas": 5, "motivos": {"sin_stock": 5}, "reintento": {"recuperados": 5}, "faltan": {"total": 0, "motivos": {}}}
    texto = reminder.causa_amazon(_estado(run))
    assert "no faltan precios de Amazon" in texto


def test_causa_amazon_formato_viejo_sigue_andando():
    run = {"fallas": 3, "motivos": {"sin_stock": 3}}
    assert "Amazon dejó 3 sin precio" in reminder.causa_amazon(_estado(run))
