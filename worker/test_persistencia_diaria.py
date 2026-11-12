"""Auditoría 09/11 (F-06 a F-31): lo consultado se guarda al obtenerlo y una corrida cortada se retoma el mismo día.

Cada bloque simula un KILL a mitad del bucle (BaseException que ningún `except Exception` atrapa) y vuelve a correr:
lo ya hecho queda en disco y no se vuelve a consultar. Sin mocks de la función bajo prueba: sólo la red y la pausa.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import ml_fichas
from tools import confirmar_altas as confirmation
from tools import dudosos_nvidia as dudosos


class Kill(BaseException):
    """Simula SIGKILL: no la atrapa ningún `except Exception`."""


# ----------------------------------------------------------------------------------------- F-24 fichas ML

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)


def producto(n):
    return {"slug": f"p{n}", "name": f"Producto {n}", "ml": {"catalogId": f"MLA{n}"}}


def cuerpo(n):
    return {"name": f"Producto {n}", "attributes": [{"id": "MODEL", "name": "Modelo", "value_name": f"M{n}"}],
            "main_features": []}


def test_fichas_cada_ficha_queda_en_disco_y_el_reintento_retoma(tmp_path, monkeypatch, capsys):
    path = tmp_path / "ml-fichas.json"
    monkeypatch.setattr(ml_fichas.ml_prices, "is_configured", lambda: True)
    monkeypatch.setattr(ml_fichas.ml_prices, "pause", lambda: None)
    pedidos = []

    def get_json(url, kill_en=None):
        n = int(url.rsplit("MLA", 1)[1])
        if kill_en == n:
            raise Kill()
        pedidos.append(n)
        return cuerpo(n)

    monkeypatch.setattr(ml_fichas.ml_prices, "get_json", lambda url: get_json(url, kill_en=3))
    with pytest.raises(Kill):
        ml_fichas.refresh([producto(n) for n in range(1, 6)], path, NOW)
    # Se pierde a lo sumo la ficha en curso (la 3): las dos anteriores ya están guardadas.
    assert sorted(json.loads(path.read_text())["items"]) == ["MLA1", "MLA2"]
    log = capsys.readouterr().out
    assert log.count("FICHA_OK") == 2 and "FICHA_OK p1 id=MLA1" in log and "2026-11-09 09:00:00" in log

    pedidos.clear()
    monkeypatch.setattr(ml_fichas.ml_prices, "get_json", lambda url: get_json(url))
    ml_fichas.refresh([producto(n) for n in range(1, 6)], path, NOW)
    assert pedidos == [3, 4, 5]
    assert sorted(json.loads(path.read_text())["items"]) == [f"MLA{n}" for n in range(1, 6)]


# ----------------------------------------------------------------------------------------- F-25 / F-31 dudosos

def voto(decision="aprobar", motivo="Mismo modelo"):
    return json.dumps({"decision": decision, "motivo": motivo})


def post_falso(*contenidos):
    contenidos = iter(contenidos)
    return Mock(side_effect=lambda *a, **kw: Mock(json=lambda: {"choices": [{"message": {"content": next(contenidos)}}]}))


@pytest.fixture
def cola(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "clave")
    filas = [{"asin": f"A{n}", "catalogId": f"MLA{n}", "revisionDesde": f"2026-11-0{n}"} for n in range(1, 5)]
    (tmp_path / "altas-revision.json").write_text(json.dumps(filas), encoding="utf-8")
    return tmp_path, filas


def test_dudosos_kill_a_mitad_conserva_lo_decidido_y_el_reintento_no_lo_repite(cola, monkeypatch, capsys):
    output, filas = cola
    pedidos, cortar = [], [True]

    def ficha(url):
        pedidos.append(url)
        if url.endswith("MLA2") and cortar[0]:
            raise Kill()
        return {"name": "Ficha"}

    monkeypatch.setattr(dudosos.ml_prices, "get_json", ficha)
    monkeypatch.setattr(dudosos.revisar_altas, "review", Mock(return_value=1))  # sin aplicar: siguen en la cola
    # 12/11: los pares van en paralelo; con uno a la vez el orden es determinista y se ve exacto qué conserva el corte.
    monkeypatch.setattr(dudosos, "PARES_EN_PARALELO", 1)
    # Orden esperado: primero la fila más nueva (revisionDesde descendente): A4, A3, A2 (kill), A1.
    with pytest.raises(Kill):
        dudosos.run(output / "catalog.json", output, post=post_falso(*[voto("aprobar"), voto("rechazar")] * 4))
    assert pedidos == ["/products/MLA4", "/products/MLA3", "/products/MLA2"]
    assert len(list((output / "dudosos").glob("*.json"))) == 2  # A4 y A3 guardadas al decidir
    log = capsys.readouterr().out
    assert log.count("DUDOSO_DECISION") == 2 and "par=A4:MLA4" in log

    pedidos.clear()
    cortar[0] = False
    assert dudosos.run(output / "catalog.json", output, post=post_falso(*[voto("aprobar"), voto("rechazar")] * 2)) == 0
    assert pedidos == ["/products/MLA2", "/products/MLA1"]  # A4 y A3 ya estaban decididas hoy
    out = capsys.readouterr().out
    assert out.count("DUDOSO_SALTEO") == 2 and "saltados_hoy=2" in out
    assert len(list((output / "dudosos").glob("*.json"))) == 4


def test_dudosos_voto_invalido_se_reintenta_el_mismo_dia(cola, monkeypatch):
    output, _ = cola
    monkeypatch.setattr(dudosos.ml_prices, "get_json", lambda url: {"name": "Ficha"})
    monkeypatch.setattr(dudosos.revisar_altas, "review", Mock(return_value=1))
    assert dudosos.run(output / "catalog.json", output, post=post_falso(*["sin JSON"] * 8)) == 1
    pedidos = []
    monkeypatch.setattr(dudosos.ml_prices, "get_json", lambda url: pedidos.append(url) or {"name": "Ficha"})
    post = post_falso(*[voto(), voto()] * 4)
    dudosos.run(output / "catalog.json", output, post=post)
    assert post.call_count == 8  # ningún voto era válido: nada contó como «ya decidido», se votó de nuevo
    assert pedidos == []  # la ficha ML ya estaba guardada de la primera pasada


def test_dudosos_sin_clave_y_con_cola_falla(cola, monkeypatch, capsys):
    output, _ = cola
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert dudosos.run(output / "catalog.json", output) == 1
    assert "DUDOSOS_SIN_CLAVE cola=4" in capsys.readouterr().out


def test_dudosos_todas_invalidas_falla_pero_una_valida_no(cola, monkeypatch):
    output, _ = cola
    monkeypatch.setattr(dudosos.ml_prices, "get_json", Mock(side_effect=requests.Timeout()))
    assert dudosos.run(output / "catalog.json", output, post=post_falso()) == 1
    for archivo in (output / "dudosos").glob("*.json"):
        archivo.unlink()
    monkeypatch.setattr(dudosos.ml_prices, "get_json", Mock(side_effect=[requests.Timeout(), {"name": "F"}, {"name": "F"}, {"name": "F"}]))
    monkeypatch.setattr(dudosos.revisar_altas, "review", Mock(return_value=1))
    assert dudosos.run(output / "catalog.json", output, post=post_falso(*[voto(), voto()] * 3)) == 0


# ----------------------------------------------------------------------------------------- F-19 confirmar altas

HOY = "2026-11-09"


def pendiente(asin, **cambios):
    return dict(asin=asin, slug=asin.lower(), store="US", verified=True, ml={"catalogId": "MLA" + asin},
                pendienteDesde="2026-11-08", image="/products/x.webp", **cambios)


@pytest.fixture
def altas(tmp_path):
    import publicacion
    repo = tmp_path / "catalog.json"
    repo.write_text("[]", encoding="utf-8")
    (tmp_path / "catalog-auto.json").write_text("[]", encoding="utf-8")
    publicacion.guardar(tmp_path, {})
    return repo, tmp_path


def chrome(output, items, dia=HOY):
    (output / f"ar-chrome-{dia}.json").write_text(
        json.dumps({"generado": dia + "T04:00:00-03:00", "items": items}), encoding="utf-8")


def test_pendiente_que_chrome_no_alcanzo_no_cuenta_noche_sin_dato(altas, capsys):
    repo, output = altas
    (output / "altas-pendientes.json").write_text(json.dumps([pendiente("VISTO"), pendiente("CORTADO")]), encoding="utf-8")
    chrome(output, {"VISTO": {"ships": None, "free": None, "motivo": "captcha"}})  # el relevamiento se cortó antes de CORTADO
    assert confirmation.confirm(repo, output, HOY)["siguen_pendientes"] == 2
    filas = {p["asin"]: p for p in json.loads((output / "altas-pendientes.json").read_text())}
    assert filas["VISTO"]["nochesSinDato"] == 1  # Chrome lo miró y no obtuvo dato: cuenta
    assert "nochesSinDato" not in filas["CORTADO"] and filas["CORTADO"]["nochesSinCorrida"] == 1
    assert "decision=sin_cambio" in capsys.readouterr().out
    confirmation.confirm(repo, output, HOY)  # mismo día: no se duplica
    assert json.loads((output / "altas-pendientes.json").read_text())[1]["nochesSinCorrida"] == 1


def test_pendiente_nunca_relevado_se_rechaza_con_su_propio_motivo_tras_el_tope(altas):
    repo, output = altas
    (output / "altas-pendientes.json").write_text(
        json.dumps([pendiente("CORTADO", nochesSinCorrida=confirmation.MAX_NOCHES_SIN_CORRIDA)]), encoding="utf-8")
    chrome(output, {})
    # Pasado el tope vuelve al camino de «sin dato»: 3 noches más para rechazar, nunca pendiente para siempre.
    for _ in range(3):
        for dia in ("2026-11-09", "2026-11-10", "2026-11-11"):
            chrome(output, {}, dia)
            confirmation.confirm(repo, output, dia)
    assert json.loads((output / "altas-rechazadas.json").read_text())["CORTADO"]["motivo"] == "sin_dato_3_noches"


def test_no_revisar_vencido_sin_chrome_no_estira_siete_dias(altas, capsys):
    import publicacion
    repo, output = altas
    entrada = pendiente("VENCIDO")
    (output / "catalog-auto.json").write_text(json.dumps([entrada]), encoding="utf-8")
    (output / "altas-pendientes.json").write_text("[]", encoding="utf-8")
    publicacion.guardar(output, {"vencido": {"asin": "VENCIDO", "situacion": "no_revisar", "desde": "2026-11-01",
                                             "hasta": "2026-11-08", "ultimoIntento": None, "intentos": 0, "motivo": "sin_envio"}})
    confirmation.confirm(repo, output, HOY)  # no hay ar-chrome de hoy: Chrome no corrió
    estado = publicacion.cargar(output)["vencido"]
    assert estado["hasta"] == "2026-11-10" and estado["motivo"] == "chrome_no_corrio"  # mañana, no dentro de 7 días
    log = capsys.readouterr().out
    assert "decision=pospuesta" in log and "motivo=chrome_no_corrio" in log
    # Con Chrome corrido y el ASIN con dato negativo, la exclusión de 7 días se mantiene.
    publicacion.guardar(output, {"vencido": {**estado, "hasta": "2026-11-09"}})
    chrome(output, {"VENCIDO": {"ships": True, "free": False, "precio": "$150"}})
    confirmation.confirm(repo, output, HOY)
    assert publicacion.cargar(output)["vencido"]["hasta"] == "2026-11-16"
