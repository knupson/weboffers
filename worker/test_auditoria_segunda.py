"""Regresiones de la segunda tanda: sin publicaciones ni consultas reales."""
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import worker
import telegram
from test_telegram import CATALOG, noon_art

spec = importlib.util.spec_from_file_location("meta_segunda", Path(__file__).parents[1] / "tools/meta/meta_publicar.py")
meta = importlib.util.module_from_spec(spec)
spec.loader.exec_module(meta)


def test_falla_telegram_no_dispara_precios_ni_alta(tmp_path, monkeypatch, capsys):
    failed = "Telegram"
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    monkeypatch.setattr(worker, "load_catalog", lambda *a: [])
    monkeypatch.setattr(worker.rates, "get_rates", lambda: None)
    monkeypatch.setattr(worker.ml_prices, "merge", lambda *a, **kw: [])
    calls = []
    def task(name):
        def run(*a, **kw):
            calls.append(name)
            if name == failed:
                raise RuntimeError("prueba")
        return run
    for obj, attr, name in [(worker.publish, "publish", "publish"),
                            (worker.amazon_prices, "maybe_refresh", "Amazon"),
                            (worker.ml_prices, "maybe_refresh", "ML"),
                            (worker.telegram, "maybe_post", "Telegram"),
                            (worker.catalog_auto, "maybe_grow", "catálogo semanal")]:
        monkeypatch.setattr(obj, attr, task(name))
    worker.run_once()
    assert calls == ["Telegram"]
    assert f"Falló {failed} (RuntimeError)" in capsys.readouterr().out


def test_telegram_intento_persistido_no_se_repite(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prueba")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "canal")
    path = tmp_path / "telegram.json"
    def send(product):
        assert telegram.load_state(path)["attempt"] == {
            "estado": "intentando", "slug": "con-foto", "slot": "2026-10-30T12"}
        raise TimeoutError()
    send_mock = Mock(side_effect=send)
    monkeypatch.setattr(telegram, "send", send_mock)
    with pytest.raises(TimeoutError):
        telegram.maybe_post(CATALOG, path, noon_art())
    assert telegram.maybe_post(CATALOG, path, noon_art()) is None
    assert telegram.maybe_post(CATALOG, path, noon_art()) is None
    send_mock.assert_called_once()
    assert "TELEGRAM_INCIERTO con-foto" in capsys.readouterr().out
    # Un intento incierto consume sólo su turno, no el siguiente.
    monkeypatch.setattr(telegram, "send", Mock())
    assert telegram.maybe_post(CATALOG, path, noon_art() + timedelta(hours=8)) == "con-foto"
    assert telegram.load_state(path)["attempt"] is None


def test_telegram_no_envia_si_no_puede_persistir(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prueba")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "canal")
    send = Mock()
    monkeypatch.setattr(telegram, "send", send)
    monkeypatch.setattr(telegram, "save_state", Mock(side_effect=OSError()))
    with pytest.raises(OSError):
        telegram.maybe_post(CATALOG, tmp_path / "state", noon_art())
    send.assert_not_called()


@pytest.mark.parametrize("last", ["published", "error", "processing"])
def test_fb_espera_publicacion_o_error_o_seis_minutos(monkeypatch, last):
    clock = [0]
    monkeypatch.setattr(meta.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(meta.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    pending = {"video_status": "ready", "publishing_phase": {"status": "in_progress"}}
    final = {"video_status": "ready", "publishing_phase": {"publish_status": last}}
    get = Mock(side_effect=[{"status": pending}] + [{"status": final}] * 40)
    monkeypatch.setattr(meta, "graph_get", get)
    if last == "published":
        meta.esperar_fb_publicado("video", "token")
        assert clock[0] == 10
    else:
        with pytest.raises(meta.MetaError, match="status="):
            meta.esperar_fb_publicado("video", "token")
        assert clock[0] == (10 if last == "error" else 360)
    assert get.call_args.args[:2] == ("/video", {"fields": "status"})


def test_fb_reel_consulta_despues_de_finish(monkeypatch):
    events = []
    def post(path, data, token):
        events.append(data["upload_phase"])
        return {"video_id": "v"}
    monkeypatch.setattr(meta, "graph_post", post)
    resp = Mock()
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    resp.read.return_value = b'{"success":true}'
    monkeypatch.setattr(meta.urllib.request, "urlopen", Mock(return_value=resp))
    monkeypatch.setattr(meta, "esperar_fb_publicado", lambda *a: events.append("published"))
    assert meta.publicar_fb_reel("page", "https://video", "texto", "token") == "v"
    assert events == ["start", "finish", "published"]


def test_alertar_devuelve_resultado(monkeypatch):
    monkeypatch.setattr(meta, "ENV", {"WAHA_URL": "https://waha", "WA_NOTIFY_CHAT_ID": "chat"})
    resp = Mock()
    resp.__enter__ = Mock(return_value=resp)
    resp.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(meta.urllib.request, "urlopen", Mock(return_value=resp))
    mediodia = meta.datetime.datetime(2026, 11, 7, 12, 0, tzinfo=meta.ART)
    assert meta.alertar("aviso", ahora=mediodia) is True
    monkeypatch.setattr(meta.urllib.request, "urlopen", Mock(side_effect=OSError()))
    assert meta.alertar("aviso", ahora=mediodia) is False


def test_alertar_no_manda_antes_de_las_7(monkeypatch):
    # Alejandro, 07/11: ningún WhatsApp antes de las 7; queda alertado=False y sale en la pasada de las 07:00.
    monkeypatch.setattr(meta, "ENV", {"WAHA_URL": "https://waha", "WA_NOTIFY_CHAT_ID": "chat"})
    urlopen = Mock()
    monkeypatch.setattr(meta.urllib.request, "urlopen", urlopen)
    assert meta.alertar("aviso", ahora=meta.datetime.datetime(2026, 11, 7, 6, 59, tzinfo=meta.ART)) is False
    urlopen.assert_not_called()


@pytest.mark.parametrize("expired", [True, False])
def test_alerta_fallida_se_reintenta_sin_republicar(tmp_path, monkeypatch, expired):
    now = datetime.now(timezone.utc)
    entry = {"id": "pieza", "cuando": (now - timedelta(hours=7 if expired else 1)).isoformat(), "destinos": ["fb"]}
    (tmp_path / "cola_meta.json").write_text(json.dumps([entry]))
    initial = {} if expired else {"pieza|fb": {"estado": "error", "intentos": 3, "ultimo_error": "falló", "alertado": False}}
    (tmp_path / "estado_meta.json").write_text(json.dumps(initial))
    monkeypatch.setattr(meta, "cargar_env", lambda *a: {"META_SYSTEM_TOKEN": "token"})
    monkeypatch.setattr(meta, "fcntl", None)
    publish = Mock(side_effect=AssertionError("No republicar"))
    monkeypatch.setattr(meta, "publicar", publish)
    alert = Mock(side_effect=[False, True])
    monkeypatch.setattr(meta, "alertar", alert)
    for expected in [False, True]:
        assert meta.main([], str(tmp_path)) == 0
        state = json.loads((tmp_path / "estado_meta.json").read_text())
        assert state["pieza|fb"]["alertado"] is expected
    assert alert.call_count == 2
    publish.assert_not_called()

def test_telegram_caida_al_confirmar_no_republica(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prueba")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "canal")
    path = tmp_path / "state.json"
    save = telegram.save_state
    calls = [0]
    def save_once(*args):
        calls[0] += 1
        if calls[0] == 2:
            raise OSError("se cortó al confirmar")
        save(*args)
    monkeypatch.setattr(telegram, "save_state", save_once)
    send = Mock()
    monkeypatch.setattr(telegram, "send", send)
    with pytest.raises(OSError):
        telegram.maybe_post(CATALOG, path, noon_art())
    assert telegram.maybe_post(CATALOG, path, noon_art()) is None
    send.assert_called_once()
    assert "TELEGRAM_INCIERTO con-foto" in capsys.readouterr().out


def test_alerta_ultimo_intento_fallido_se_reintenta(tmp_path, monkeypatch):
    entry = {"id": "pieza", "cuando": datetime.now(timezone.utc).isoformat(), "destinos": ["fb"]}
    (tmp_path / "cola_meta.json").write_text(json.dumps([entry]))
    (tmp_path / "estado_meta.json").write_text(json.dumps({"pieza|fb": {"estado": "fallo", "intentos": 2}}))
    monkeypatch.setattr(meta, "cargar_env", lambda *a: {"META_SYSTEM_TOKEN": "token", "META_PAGE_ID": "page"})
    monkeypatch.setattr(meta, "fcntl", None)
    monkeypatch.setattr(meta, "graph_get", Mock(return_value={"access_token": "page-token"}))
    publish = Mock(side_effect=meta.MetaError("falló"))
    monkeypatch.setattr(meta, "publicar", publish)
    alert = Mock(side_effect=[False, True])
    monkeypatch.setattr(meta, "alertar", alert)
    for expected in [False, True]:
        meta.main([], str(tmp_path))
        assert json.loads((tmp_path / "estado_meta.json").read_text())["pieza|fb"]["alertado"] is expected
    assert alert.call_count == 2
    publish.assert_called_once()


def test_telegram_error_claro_reintenta_en_el_ciclo_siguiente(tmp_path, monkeypatch):
    import telegram
    from datetime import datetime, timezone
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "prueba")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "canal")
    state = tmp_path / "telegram-state.json"
    monkeypatch.setattr(telegram, "pick", lambda catalog, posted, now: {"slug": "p1"})
    llamadas = []

    def falla(product):
        llamadas.append(product["slug"])
        raise RuntimeError("Telegram 502")
    monkeypatch.setattr(telegram, "send", falla)
    now = datetime(2026, 11, 5, 15, 5, tzinfo=timezone.utc)  # 12:05 ART
    try:
        telegram.maybe_post([], state, now)
    except RuntimeError:
        pass
    import json
    assert not json.loads(state.read_text(encoding="utf-8")).get("attempt")
    monkeypatch.setattr(telegram, "send", lambda product: llamadas.append("ok"))
    telegram.maybe_post([], state, now)
    assert llamadas == ["p1", "ok"]
