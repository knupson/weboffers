import datetime
import json
import os
import time

from tools.vigia_externo import vigia_externo as ve

AHORA = datetime.datetime(2026, 11, 5, 10, 0, tzinfo=ve.ART)


def sitio_ok(url):
    return json.dumps({"preciosDe": "2026-11-05", "publicados": 100})


def latido(tmp_path, texto="ok", hace_min=5):
    p = tmp_path / "latido.txt"
    p.write_text(texto, encoding="utf-8")
    t = AHORA.timestamp() - hace_min * 60
    os.utime(p, (t, t))
    return str(p)


def test_todo_bien(tmp_path):
    assert ve.chequeos(AHORA, latido(tmp_path), sitio_ok, lambda h, p: True) == {}


def test_latido_viejo_o_ausente(tmp_path):
    assert "latido" in ve.chequeos(AHORA, latido(tmp_path, hace_min=50), sitio_ok, lambda h, p: True)
    assert "latido" in ve.chequeos(AHORA, str(tmp_path / "no-existe"), sitio_ok, lambda h, p: True)


def test_sin_internet_y_waha_caido(tmp_path):
    p = ve.chequeos(AHORA, latido(tmp_path, "sin-internet"), sitio_ok, lambda h, p: False)
    assert {"internet", "waha"} <= set(p)


def test_sitio_bajo_minimo_solo_si_la_vm_no_puede_avisar(tmp_path):
    def bajo(url):
        return json.dumps({"preciosDe": "2026-11-05", "publicados": 97})
    assert ve.chequeos(AHORA, latido(tmp_path), bajo, lambda h, p: True) == {}
    assert "sitio-minimo" in ve.chequeos(AHORA, latido(tmp_path), bajo, lambda h, p: False)


def test_avisa_una_vez_y_cuando_se_resuelve(tmp_path):
    enviados = []
    est = str(tmp_path / "estado.json")
    ve.main(AHORA, enviar=enviados.append, chequear=lambda a: {"latido": "sin señales"}, estado_path=est)
    ve.main(AHORA, enviar=enviados.append, chequear=lambda a: {"latido": "sin señales"}, estado_path=est)
    ve.main(AHORA, enviar=enviados.append, chequear=lambda a: {}, estado_path=est)
    assert len(enviados) == 2 and "⚠️" in enviados[0] and "✅" in enviados[1]


def test_si_telegram_falla_reintenta(tmp_path):
    est = str(tmp_path / "estado.json")

    def falla(t):
        raise OSError("sin red")
    ve.main(AHORA, enviar=falla, chequear=lambda a: {"latido": "x"}, estado_path=est)
    enviados = []
    ve.main(AHORA, enviar=enviados.append, chequear=lambda a: {"latido": "x"}, estado_path=est)
    assert len(enviados) == 1
