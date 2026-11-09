"""Auditoría 09/11 (F-20, F-29): fallas aisladas de ML no frenan el deploy del alta y los temporales de un KILL se limpian."""
from datetime import datetime, timedelta, timezone
import json
import os
import time

import pytest

import publish
import worker
from tools import refresh_ahora


# ----------------------------------------------------------------------------------------- F-29 temporales

def test_limpiar_temporales_borra_solo_los_viejos_de_un_write_atomic_cortado(tmp_path):
    (tmp_path / "historial").mkdir()
    (tmp_path / "dudosos").mkdir()
    viejos = [tmp_path / ".amazon-prices.json.ab12.tmp", tmp_path / "historial" / ".x-ml-prices.json.cd34.tmp",
              tmp_path / "dudosos" / ".d.json.ef56.tmp"]
    nuevo = tmp_path / ".ml-prices.json.gh78.tmp"
    otro = tmp_path / "amazon-prices.json"
    for archivo in (*viejos, nuevo, otro):
        archivo.write_text("x")
    hace_dos_horas = time.time() - 7200
    for archivo in viejos:
        os.utime(archivo, (hace_dos_horas, hace_dos_horas))
    os.utime(otro, (hace_dos_horas, hace_dos_horas))
    assert publish.limpiar_temporales(tmp_path) == 3
    assert not any(a.exists() for a in viejos)
    assert nuevo.exists() and otro.exists()  # una escritura en curso y los archivos reales no se tocan


def test_cada_paso_limpia_al_abrir_su_log_diario(tmp_path):
    viejo = tmp_path / ".ml-prices.json.zz99.tmp"
    viejo.write_text("x")
    antes = time.time() - 4 * 3600
    os.utime(viejo, (antes, antes))
    worker.DailyLog(tmp_path / "logs", open(os.devnull, "w"))
    assert not viejo.exists()


def test_write_atomic_sigue_sin_dejar_temporales_en_el_camino_feliz(tmp_path):
    publish.write_atomic(tmp_path / "x.json", {"a": 1})
    assert list(tmp_path.glob(".*.tmp")) == []


# ----------------------------------------------------------------------------------------- F-20 ML con fallas aisladas

def correr_ml(tmp_path, monkeypatch, items, failed):
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    monkeypatch.setenv("AMAZON_PRICES_PATH", str(tmp_path / "amazon-prices.json"))
    monkeypatch.setenv("ML_PRICES_PATH", str(tmp_path / "ml-prices.json"))
    monkeypatch.setattr(worker, "load_catalog", lambda *a: [])
    monkeypatch.setattr(worker.rates, "get_rates", lambda: {})

    def refresh(catalog, target, *args, **kwargs):
        target.write_text(json.dumps({"date": datetime.now(worker.ml_prices.ART).date().isoformat(),
                                      "items": {f"p{n}": {"price": 1} for n in range(items)},
                                      "failed": [f"f{n}" for n in range(failed)]}))

    monkeypatch.setattr(worker.ml_prices, "maybe_refresh", refresh)
    with monkeypatch.context() as streams:
        streams.setattr(refresh_ahora.sys, "stdout", refresh_ahora.sys.stdout)
        streams.setattr(refresh_ahora.sys, "stderr", refresh_ahora.sys.stderr)
        return refresh_ahora.main("ml")


def test_una_falla_aislada_de_ml_no_hace_fallar_el_paso_pero_deja_la_alarma_en_el_log(tmp_path, monkeypatch):
    assert correr_ml(tmp_path, monkeypatch, items=19, failed=1) == 0  # 1 de 20 = 5 %
    log = next((tmp_path / "logs").glob("worker-*.log")).read_text(encoding="utf-8")
    assert "ML corrida incompleta: 1 de 20 consultas sin precio de hoy (f0)" in log
    import re
    from tools import vigia_franquicia
    assert vigia_franquicia.MARCAS_FALLA.search(log)  # el vigía la levanta aunque el paso figure ok


def test_muchas_fallas_de_ml_siguen_haciendo_fallar_el_paso(tmp_path, monkeypatch):
    assert correr_ml(tmp_path, monkeypatch, items=10, failed=3) == 1  # 3 de 13 = 23 %
    assert "consultas pendientes: f0, f1, f2" in next((tmp_path / "logs").glob("worker-*.log")).read_text(encoding="utf-8")


def test_verificacion_con_precios_parciales_del_alta_falla(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "verificacion")
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    monkeypatch.setenv("AMAZON_PRICES_PATH", str(tmp_path / "amazon-prices.json"))
    monkeypatch.setattr(worker, "load_catalog", lambda *a: [])
    monkeypatch.setattr(worker.rates, "get_rates", lambda: {})

    def refresh(catalog, target, *args, **kwargs):
        target.write_text(json.dumps({"date": datetime.now(worker.amazon_prices.ART).date().isoformat(),
                                      "items": {"p": {"amount": 150}}, "completo": False}))

    monkeypatch.setattr(worker.amazon_prices, "maybe_refresh", refresh)
    with monkeypatch.context() as streams:
        streams.setattr(refresh_ahora.sys, "stdout", refresh_ahora.sys.stdout)
        streams.setattr(refresh_ahora.sys, "stderr", refresh_ahora.sys.stderr)
        assert refresh_ahora.main("amazon") == 1
    assert "completo: false" in next((tmp_path / "logs").glob("worker-*.log")).read_text(encoding="utf-8")
    # En el alta el parcial es lo esperado.
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    with monkeypatch.context() as streams:
        streams.setattr(refresh_ahora.sys, "stdout", refresh_ahora.sys.stdout)
        streams.setattr(refresh_ahora.sys, "stderr", refresh_ahora.sys.stderr)
        assert refresh_ahora.main("amazon") == 0
