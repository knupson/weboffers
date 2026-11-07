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
