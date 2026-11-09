"""Revisión de Codex (09/11) sobre la persistencia: relevamiento que cruza la medianoche, cola truncada, retry de ML,
pendientes sin archivo de Chrome y dudosos con ficha y votos guardados de a uno. KILL simulado con BaseException."""
from datetime import datetime, timezone
import json
import threading
from unittest.mock import Mock

import pytest

import diario
import ml_prices
import publicacion
from tools import altas_chrome, confirmar_altas as confirmation, dudosos_nvidia as dudosos


class Kill(BaseException):
    """Simula SIGKILL."""


# ----------------------------------------------------------------------------------------- 1: medianoche

def test_relevamiento_que_cruza_la_medianoche_no_deja_lecturas_de_ayer_como_de_hoy(tmp_path, capsys):
    registros = [
        {"t": "2026-11-09T23:58:00-03:00", "asin": "AYER", "slugs": ["ayer"], "item": {"ships": True, "free": True, "precio": "$150"}},
        {"t": "2026-11-10T00:03:00-03:00", "asin": "HOY", "slugs": ["hoy"], "item": {"ships": True, "free": True, "precio": "$160"}},
    ]
    snap = altas_chrome.snapshot_desde_parcial("\n".join(json.dumps(r) for r in registros))
    assert snap["generado"] == "2026-11-10T00:03:00-03:00"
    altas_chrome.merge_chrome(tmp_path, "2026-11-10", snap)
    guardado = json.loads((tmp_path / "ar-chrome-2026-11-10.json").read_text())
    assert list(guardado["items"]) == ["HOY"]  # la lectura de las 23:58 del día anterior no se promueve como evidencia de hoy
    log = capsys.readouterr().out
    assert "ENVIO_AR_CHROME_DESCARTADO asin=AYER" in log and "2026-11-09T23:58:00-03:00" in log


def test_lectura_sin_hora_de_un_json_viejo_se_acepta(tmp_path):
    incoming = {"generado": "2026-11-10T04:00:00-03:00", "items": {"X": {"ships": True, "free": True}}}
    altas_chrome.merge_chrome(tmp_path, "2026-11-10", incoming)
    assert list(json.loads((tmp_path / "ar-chrome-2026-11-10.json").read_text())["items"]) == ["X"]


# ----------------------------------------------------------------------------------------- 8: cola truncada

def test_diario_repara_la_cola_truncada_antes_de_anexar(tmp_path):
    path = tmp_path / "x-diario-2026-11-09.jsonl"
    diario.anotar(path, {"n": 1})
    diario.anotar(path, {"n": 2})
    with path.open("ab") as archivo:  # un KILL a mitad de escritura
        archivo.write(b'{"n": 3, "te')
    diario.anotar(path, {"n": 4})  # no se pega al fragmento: se recorta y se anexa limpio
    assert [r["n"] for r in diario.leer(path)] == [1, 2, 4]
    assert path.read_bytes().endswith(b"\n") and path.read_bytes().count(b"\n") == 3


def test_diario_exclusion_mutua_entre_escritores(tmp_path):
    path = tmp_path / "x-diario-2026-11-09.jsonl"

    def escribir(prefijo):
        for n in range(25):
            diario.anotar(path, {"p": prefijo, "n": n})

    hilos = [threading.Thread(target=escribir, args=(p,)) for p in "ab"]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    registros = diario.leer(path)
    assert len(registros) == 50 and sorted(r["n"] for r in registros if r["p"] == "a") == list(range(25))


def test_parcial_de_chrome_repara_la_cola_antes_de_anexar(tmp_path):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "envio_ar_chrome", Path(__file__).resolve().parents[1] / "tools" / "envio_ar_chrome.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    ruta = str(tmp_path / "parcial.jsonl")
    modulo.guardar_parcial(ruta, "A1", ["s1"], {"ships": True, "leido": "2026-11-09T05:00:00-03:00"})
    with open(ruta, "ab") as archivo:
        archivo.write(b'{"t": "2026-11-09T05:00:09-03:00", "asin": "A2", "sl')
    modulo.guardar_parcial(ruta, "A3", ["s3"], {"ships": False})
    snap = altas_chrome.snapshot_desde_parcial(open(ruta, encoding="utf-8").read())
    assert sorted(snap["items"]) == ["A1", "A3"]  # el A3 recién terminado no se pierde junto con el fragmento


# ----------------------------------------------------------------------------------------- 7: ML retry lee el diario

HOY = "2026-10-30"
AFTER_SEVEN = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def test_ml_el_reintento_cortado_se_retoma_desde_el_diario_del_mismo_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    monkeypatch.setenv("ML_CLIENT_ID", "id")
    monkeypatch.setenv("ML_CLIENT_SECRET", "secret")
    monkeypatch.setattr(ml_prices, "PAUSE_SECONDS", 0)
    slugs = ["a", "b", "c"]
    catalogo = [{"slug": s, "name": s, "store": "US", "verified": True, "verdict": "ml", "image": "/p.webp", "asin": "B0" + s,
                 "ml": {"price": 1, "catalogId": "MLA" + s}, "shipsToAr": {"freeShipping": True}} for s in slugs]
    publicacion.guardar(tmp_path, {})
    (tmp_path / "amazon-prices.json").write_text(json.dumps({"date": HOY, "items": {
        s: {"amount": 200.0, "currency": "USD", "checked": HOY} for s in slugs}}), encoding="utf-8")
    prices = tmp_path / "ml-prices.json"
    # Pasada completa del slot de las 06 con «a» fallida: queda failed=[a] y el archivo existe (los próximos son reintentos).
    prices.write_text(json.dumps({"date": HOY, "slot": "2026-10-30T06", "items": {
        "b": {"catalogId": "MLAb", "price": 1, "checked": HOY}}, "absent": [], "failed": ["a"], "attempts": 1}), encoding="utf-8")
    pedidos, cortar = [], [True]

    def fetch(catalog_id):
        pedidos.append(catalog_id)
        if cortar[0] and catalog_id == "MLAc":
            raise Kill()
        return [{}]

    monkeypatch.setattr(ml_prices, "fetch_items", fetch)
    monkeypatch.setattr(ml_prices, "cheapest_new", lambda found: (400000, "MLA1"))
    # Reintento con un producto nuevo («c», force): «a» se recupera (queda en el diario) y «c» recibe el KILL.
    with pytest.raises(Kill):
        ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN, force=True)
    assert [(r["slug"], r["slot"]) for r in diario.leer(diario.ruta(prices, HOY))] == [("a", "2026-10-30T06")]
    pedidos.clear()
    cortar[0] = False
    ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN, force=True)
    assert pedidos == ["MLAc"]  # «a» no se vuelve a pedir
    saved = json.loads(prices.read_text())
    assert sorted(saved["items"]) == ["a", "b", "c"] and saved["failed"] == []


# ----------------------------------------------------------------------------------------- 4: sin archivo de Chrome

def test_sin_archivo_de_chrome_los_pendientes_cuentan_noches_y_no_quedan_para_siempre(tmp_path):
    repo = tmp_path / "catalog.json"
    repo.write_text("[]", encoding="utf-8")
    (tmp_path / "catalog-auto.json").write_text("[]", encoding="utf-8")
    publicacion.guardar(tmp_path, {})
    fila = dict(asin="NUEVO", slug="nuevo", store="US", verified=True, ml={"catalogId": "MLANUEVO"},
                pendienteDesde="2026-11-01", image="/products/x.webp")
    (tmp_path / "altas-pendientes.json").write_text(json.dumps([fila]), encoding="utf-8")
    for dia in range(1, 11):  # nunca hay ar-chrome-*.json
        confirmation.confirm(repo, tmp_path, f"2026-11-{dia:02d}")
        pendientes = json.loads((tmp_path / "altas-pendientes.json").read_text())
        if pendientes:
            assert pendientes[0]["nochesSinCorrida"] == min(dia, confirmation.MAX_NOCHES_SIN_CORRIDA)
    rechazadas = json.loads((tmp_path / "altas-rechazadas.json").read_text())
    assert rechazadas["NUEVO"]["motivo"] == "sin_dato_3_noches" and pendientes == []


# ----------------------------------------------------------------------------------------- 5 y 6: dudosos

def voto(decision="aprobar", motivo="Mismo modelo"):
    return json.dumps({"decision": decision, "motivo": motivo})


class Nvidia:
    """Doble de la red de NVIDIA: guarda qué modelo se consultó y puede cortar en el n-ésimo voto."""

    def __init__(self, contenidos, kill_en=None):
        self.contenidos, self.kill_en, self.modelos = list(contenidos), kill_en, []

    def __call__(self, url, headers=None, json=None, timeout=None):
        if self.kill_en is not None and len(self.modelos) + 1 == self.kill_en:
            raise Kill()
        self.modelos.append(json["model"])
        contenido = self.contenidos.pop(0)
        return Mock(json=lambda: {"choices": [{"message": {"content": contenido}}]})


@pytest.fixture
def una_fila(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "clave")
    (tmp_path / "altas-revision.json").write_text(json.dumps([{"asin": "A1", "catalogId": "MLA1"}]), encoding="utf-8")
    return tmp_path


def test_dudosos_ficha_y_cada_voto_quedan_en_disco_y_el_reintento_pide_solo_lo_que_falta(una_fila, monkeypatch, capsys):
    fichas = []
    monkeypatch.setattr(dudosos.ml_prices, "get_json", lambda url: fichas.append(url) or {"name": "Ficha"})
    review = Mock(return_value=0)
    monkeypatch.setattr(dudosos.revisar_altas, "review", review)
    primera = Nvidia([voto()], kill_en=2)  # KILL durante el segundo voto
    with pytest.raises(Kill):
        dudosos.run(una_fila / "catalog.json", una_fila, post=primera)
    guardado = json.loads(next((una_fila / "dudosos").glob("*.json")).read_text(encoding="utf-8"))
    assert guardado["fichaOk"] is True and guardado["evidencia"]["ml"]["titulo"] == "Ficha"
    assert [v["modelo"] for v in guardado["votos"]] == [dudosos.MODELOS[0]]  # el primer voto sobrevivió
    log = capsys.readouterr().out
    assert "DUDOSO_FICHA par=A1:MLA1 estado=ok" in log and "DUDOSO_VOTO" in log and log.count("DUDOSO_VOTO") == 1
    review.assert_not_called()

    segunda = Nvidia([voto()])
    assert dudosos.run(una_fila / "catalog.json", una_fila, post=segunda) == 0
    assert fichas == ["/products/MLA1"]  # la ficha no se vuelve a pedir
    assert segunda.modelos == [dudosos.MODELOS[1]]  # sólo el voto que faltaba
    review.assert_called_once()
    final = json.loads(next((una_fila / "dudosos").glob("*.json")).read_text(encoding="utf-8"))
    assert final["decision"] == "aprobar" and final["aplicada"] is True and len(final["votos"]) == 2


def test_dudosos_decision_guardada_y_no_aplicada_se_aplica_al_reanudar_sin_volver_a_votar(una_fila, monkeypatch, capsys):
    monkeypatch.setattr(dudosos.ml_prices, "get_json", lambda url: {"name": "Ficha"})
    review = Mock(side_effect=[Kill(), 0])  # KILL justo al aplicar; el segundo intento anda
    monkeypatch.setattr(dudosos.revisar_altas, "review", review)
    primera = Nvidia([voto(), voto()])
    with pytest.raises(Kill):
        dudosos.run(una_fila / "catalog.json", una_fila, post=primera)
    guardado = json.loads(next((una_fila / "dudosos").glob("*.json")).read_text(encoding="utf-8"))
    assert guardado["decision"] == "aprobar" and guardado["aplicada"] is False

    segunda = Nvidia([])
    assert dudosos.run(una_fila / "catalog.json", una_fila, post=segunda) == 0
    assert segunda.modelos == []  # no se votó de nuevo
    assert review.call_count == 2
    assert json.loads(next((una_fila / "dudosos").glob("*.json")).read_text(encoding="utf-8"))["aplicada"] is True
    out = capsys.readouterr().out
    assert "DUDOSO_REANUDA par=A1:MLA1" in out and "DUDOSOS_OK revisados=1 aprobados=1" in out
    # Ya aplicada: una tercera corrida del día la saltea.
    dudosos.run(una_fila / "catalog.json", una_fila, post=segunda)
    assert review.call_count == 2


def test_dudosos_revision_que_falla_no_se_saltea_y_se_reintenta_sin_votar(una_fila, monkeypatch):
    monkeypatch.setattr(dudosos.ml_prices, "get_json", lambda url: {"name": "Ficha"})
    review = Mock(side_effect=[1, 0])  # primero «no se pudo aplicar», después sí
    monkeypatch.setattr(dudosos.revisar_altas, "review", review)
    dudosos.run(una_fila / "catalog.json", una_fila, post=Nvidia([voto("rechazar"), voto("rechazar")]))
    guardado = json.loads(next((una_fila / "dudosos").glob("*.json")).read_text(encoding="utf-8"))
    assert guardado["decision"] == "rechazar" and guardado["aplicada"] is False and guardado["error"]
    sin_votos = Nvidia([])
    dudosos.run(una_fila / "catalog.json", una_fila, post=sin_votos)
    assert sin_votos.modelos == [] and review.call_count == 2
