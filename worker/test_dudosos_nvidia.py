"""Revisión de dudosos sin consultas de red."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock

import pytest
import requests

from tools import dudosos_nvidia as d
from tools import vigia_franquicia as v


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "clave-falsa")
    monkeypatch.setattr(requests.sessions.Session, "request", Mock(side_effect=AssertionError("Red prohibida")))


def post_falso(content):
    return Mock(return_value=Mock(json=lambda: {"choices": [{"message": {"content": content}}]}))


def voto(decision="aprobar", motivo="Mismo modelo"):
    return json.dumps({"decision": decision, "motivo": motivo})


def test_dos_aprobar_aprueba():
    post = post_falso(voto())
    assert d.decidir([d.votar(modelo, {}, post=post) for modelo in d.MODELOS]) == "aprobar"
    for call, modelo in zip(post.call_args_list, d.MODELOS):
        assert call.args == ("https://integrate.api.nvidia.com/v1/chat/completions",)
        assert call.kwargs["timeout"] == d.NVIDIA_TIMEOUT == 300
        assert call.kwargs["json"]["max_tokens"] == 4000
        assert call.kwargs["json"]["temperature"] == 0
        assert call.kwargs["json"]["model"] == modelo


def test_desacuerdo_va_a_alejandro():
    assert d.decidir([d.votar("a", {}, post=post_falso(voto())),
                      d.votar("b", {}, post=post_falso(voto("rechazar")))]) == "alejandro"


@pytest.mark.parametrize("content", ["sin JSON", None, "", "  ", "[]", "null", "{}",
    '{"decision":"aprobar","motivo":""}', '{"decision":"aprobar","motivo":3}',
    '{"decision":"quizas","motivo":"No sé"}'])
def test_json_invalido_va_a_alejandro(content):
    invalid = d.votar("a", {}, post=post_falso(content))
    assert invalid[0] == "invalido"
    assert d.decidir([("aprobar", "Igual"), invalid]) == "alejandro"


@pytest.mark.parametrize("error", [requests.Timeout(), requests.HTTPError(), ValueError()])
def test_timeout_va_a_alejandro(error):
    assert d.decidir([("aprobar", "Igual"), d.votar("a", {}, post=Mock(side_effect=error))]) == "alejandro"


def test_limpia_cercos_markdown():
    assert d.votar("a", {}, post=post_falso("```json\n" + voto() + "\n```")) == ("aprobar", "Mismo modelo")


@pytest.mark.parametrize("votos", [[], [("aprobar", "sí")], [("aprobar", "sí")] * 3,
                                  [("invalido", "x")] * 2])
def test_consenso_exige_exactamente_dos_validos(votos):
    assert d.decidir(votos) == "alejandro"


def test_sin_clave_no_frena(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("NVIDIA_API_KEY")
    assert d.run(tmp_path / "catalog.json", tmp_path) == 0
    assert "DUDOSOS_SIN_CLAVE" in capsys.readouterr().out


def test_cola_vacia_no_frena(tmp_path, capsys):
    assert d.run(tmp_path / "catalog.json", tmp_path) == 0
    assert "DUDOSOS_OK revisados=0 aprobados=0 rechazados=0 para_alejandro=0" in capsys.readouterr().out


def test_evidencia_lado_a_lado():
    # ASIN y marca reales; atributos sintéticos: no hay fichas reales disponibles localmente.
    row = {"asin": "B0HFR45YLX", "catalogId": "MLA79995974", "brand": "Ottocast",
           "amazonTitle": "Título guardado", "name": "Título ML guardado", "amazonIds": {"upc": "123"}}
    amazon = {"title": "Título Amazon", "details": {"model_number": "MODELO", "color": "Negro"},
              "identifiers": {"ean": "456"}}
    ml = {"name": "Título ML", "attributes": [
        {"id": "BRAND", "value_name": "Ottocast"}, {"id": "MODEL", "value_name": "MODELO"},
        {"id": "COLOR", "value_name": "Negro"}, {"id": "STORAGE_CAPACITY", "value_name": "64 GB"},
        {"id": "GTIN", "value_name": "456"}, {"id": "MPN", "value_name": "MODELO"}]}
    result = d.evidencia(row, amazon, ml)
    assert result["amazon"]["titulo"] == "Título Amazon"
    assert result["ml"]["titulo"] == "Título ML"
    assert result["amazon"]["modelo"] == result["ml"]["modelo"] == "MODELO"
    assert result["amazon"]["marca"] == "Ottocast"
    assert result["ml"]["capacidad"] == "64 GB"
    assert result["ml"]["identificadores"]["MPN"] == "MODELO"
    assert result["amazon"]["identificadores"]["UPC"] == "123"
    assert result["amazon"]["color"] == "Negro"
    assert "variante" in result["amazon"] and "variante" in result["ml"]
    assert d.evidencia(row, {}, ml)["amazon"]["titulo"] == "Título guardado"


@pytest.mark.parametrize("action", ["aprobar", "rechazar", "alejandro"])
def test_cola_revision_y_evidencia(tmp_path, monkeypatch, capsys, action):
    row = {"asin": "B0HFR45YLX", "catalogId": "MLA79995974", "amazonTitle": "Ottocast"}
    queue = tmp_path / "altas-revision.json"
    queue.write_text(json.dumps([row]), encoding="utf-8")
    fetch = Mock(return_value={"name": "Ottocast"})
    review = Mock(return_value=0)
    monkeypatch.setattr(d.ml_prices, "get_json", fetch)
    monkeypatch.setattr(d.revisar_altas, "review", review)
    # Los dos votos van en paralelo: la respuesta depende del modelo, no del orden de llegada.
    respuestas = {d.MODELOS[0]: voto("aprobar" if action == "alejandro" else action, "Uno"),
                  d.MODELOS[1]: voto("rechazar" if action == "alejandro" else action, "Dos")}
    post = Mock(side_effect=lambda *a, **kw: post_falso(respuestas[kw["json"]["model"]])())
    assert d.run(tmp_path / "catalog.json", tmp_path, post=post) == 0
    fetch.assert_called_once_with("/products/MLA79995974")
    saved = list((tmp_path / "dudosos").glob("*.json"))
    assert len(saved) == 1
    evidence = json.loads(saved[0].read_text(encoding="utf-8"))
    assert evidence["evidencia"]["amazon"]["titulo"] == "Ottocast"
    assert len(evidence["votos"]) == 2
    if action == "alejandro":
        review.assert_not_called()
        assert json.loads(queue.read_text()) == [row]
    else:
        review.assert_called_once_with(tmp_path / "catalog.json", tmp_path, action,
                                       ["B0HFR45YLX:MLA79995974"], "nvidia: Uno | Dos", False)
    text = capsys.readouterr().out
    assert f"DUDOSO_DECISION par=B0HFR45YLX:MLA79995974 decision={action}" in text
    assert ("DUDOSO_PARA_ALEJANDRO" in text) == (action == "alejandro")


def test_falla_ml_conserva_par_y_sigue(tmp_path, monkeypatch, capsys):
    rows = [{"asin": "A", "catalogId": "MLA1"}, {"asin": "B", "catalogId": "MLA2"}]
    (tmp_path / "altas-revision.json").write_text(json.dumps(rows))
    monkeypatch.setattr(d.ml_prices, "get_json", Mock(side_effect=[requests.Timeout(), {"name": "Ficha"}]))
    review = Mock(return_value=1)
    monkeypatch.setattr(d.revisar_altas, "review", review)
    assert d.run(tmp_path / "catalog.json", tmp_path, post=post_falso(voto())) == 0
    assert "DUDOSOS_OK revisados=2 aprobados=0 rechazados=0 para_alejandro=2" in capsys.readouterr().out
    assert review.call_count == 1


def test_vigia_detecta_dudoso_para_alejandro():
    # 12/11: el vigía lo resume (DUDOSO_PAR, un aviso con la cantidad) en vez de tratarlo como falla.
    linea = "2026-11-09 06:00:00 DUDOSO_PARA_ALEJANDRO par=A:MLA1"
    assert v.DUDOSO_PAR.search(linea).group(1) == "A:MLA1"
    assert not v.MARCAS_FALLA.search(linea)


@pytest.mark.parametrize("action", ["aprobar", "rechazar"])
def test_aplica_review_real_sin_publicar(tmp_path, monkeypatch, action):
    from test_catalog_auto import candidate

    row = candidate(amazonIds={})
    catalog = tmp_path / "catalog.json"
    initial = json.dumps([{"asin": "EXISTENTE", "slug": "existente", "category": "Almacenamiento"}])
    catalog.write_text(initial, encoding="utf-8")
    (tmp_path / "altas-revision.json").write_text(json.dumps([row]), encoding="utf-8")
    monkeypatch.setattr(d.ml_prices, "get_json", lambda path: {"name": row["name"]})
    monkeypatch.setattr(d.revisar_altas.catalog_auto, "fetch_photo", lambda entry, output:
                        entry.update(image="/products/prueba.webp") or True)
    assert d.run(catalog, tmp_path, post=post_falso(voto(action))) == 0
    assert json.loads((tmp_path / "altas-revision.json").read_text()) == []
    if action == "aprobar":
        pending = json.loads((tmp_path / "altas-pendientes.json").read_text())
        assert pending[0]["motivoAprobacion"] == "nvidia: Mismo modelo | Mismo modelo"
    else:
        rejected = json.loads((tmp_path / "altas-rechazadas.json").read_text())
        assert rejected[row["asin"]]["motivo"] == "revision: nvidia: Mismo modelo | Mismo modelo"
    assert catalog.read_text() == initial
    assert not (tmp_path / "catalog-auto.json").exists()


@pytest.mark.parametrize("key", ["", "clave-falsa"])
def test_cli_desde_worker(tmp_path, key):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "NVIDIA_API_KEY": key, "OUTPUT_PATH": str(tmp_path / "offers.json")}
    result = subprocess.run([sys.executable, str(root / "tools/dudosos_nvidia.py")],
                            cwd=root / "worker", env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert ("DUDOSOS_SIN_CLAVE" if not key else "DUDOSOS_OK revisados=0") in result.stdout


# --- 12/11: alta:dudosos cortaba a los 5400 s (39 de 65 pares, un par a la vez, votos en serie) ---

def _cola(tmp_path, n, desde="2026-11-10"):
    rows = [{"asin": f"B{i}", "catalogId": f"MLA{i}", "amazonTitle": f"Producto {i}", "revisionDesde": desde}
            for i in range(n)]
    (tmp_path / "altas-revision.json").write_text(json.dumps(rows), encoding="utf-8")
    return rows


def _post_concurrente(registro, espera=0.05, contenido=None):
    import threading
    import time
    lock = threading.Lock()
    def post(*a, **kw):
        with lock:
            registro["en_vuelo"] += 1
            registro["max"] = max(registro["max"], registro["en_vuelo"])
            registro["modelos"].append(kw["json"]["model"])
        time.sleep(espera)
        with lock:
            registro["en_vuelo"] -= 1
        return post_falso(contenido or voto("aprobar" if kw["json"]["model"] == d.MODELOS[0] else "rechazar"))()
    return post


def test_votos_y_pares_en_paralelo_con_tope_de_pedidos(tmp_path, monkeypatch):
    import threading
    _cola(tmp_path, 4)
    monkeypatch.setattr(d.ml_prices, "get_json", lambda path: {"name": "Ficha"})
    monkeypatch.setattr(d, "PARES_EN_PARALELO", 3)
    monkeypatch.setattr(d, "_nvidia", threading.BoundedSemaphore(3))
    registro = {"en_vuelo": 0, "max": 0, "modelos": []}
    assert d.run(tmp_path / "catalog.json", tmp_path, post=_post_concurrente(registro)) == 0
    assert len(registro["modelos"]) == 8
    assert registro["max"] == 3  # en paralelo, pero nunca más de NVIDIA_EN_VUELO pedidos a la vez


def test_cada_voto_queda_en_disco_y_la_decision_usa_el_modelo_correcto(tmp_path, monkeypatch, capsys):
    _cola(tmp_path, 1)
    monkeypatch.setattr(d.ml_prices, "get_json", lambda path: {"name": "Ficha"})
    registro = {"en_vuelo": 0, "max": 0, "modelos": []}
    assert d.run(tmp_path / "catalog.json", tmp_path, post=_post_concurrente(registro)) == 0
    evidencia = json.loads(next((tmp_path / "dudosos").glob("*.json")).read_text(encoding="utf-8"))
    assert [v["modelo"] for v in evidencia["votos"]] == list(d.MODELOS)
    assert {v["prompt"] for v in evidencia["votos"]} == {d.PROMPT_VERSION} and evidencia["decision"] == "alejandro"
    assert "DUDOSO_PARA_ALEJANDRO par=B0:MLA0" in capsys.readouterr().out


def _previo(tmp_path, par, fecha="2026-11-10", prompt=None, votos=None, decision="alejandro", aplicada=True):
    import hashlib
    carpeta = tmp_path / "dudosos"
    carpeta.mkdir(exist_ok=True)
    asin, mla = par.split(":")
    record = {"fecha": fecha, "fila": {"asin": asin, "catalogId": mla}, "evidencia": {"par": par}, "fichaOk": True,
              "decision": decision, "aplicada": aplicada,
              "votos": votos if votos is not None else [
                  {"modelo": d.MODELOS[0], "decision": "rechazar", "motivo": "Falta UPC"},
                  {"modelo": d.MODELOS[1], "decision": "aprobar", "motivo": "Mismo modelo"}]}
    for v in record["votos"]:
        v.setdefault("prompt", prompt or d.PROMPT_VERSION)
    path = carpeta / f"{fecha}-{hashlib.sha256(par.encode()).hexdigest()[:20]}.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


def test_no_vuelve_a_votar_lo_que_ya_fue_a_alejandro(tmp_path, monkeypatch, capsys):
    _cola(tmp_path, 1)
    _previo(tmp_path, "B0:MLA0")
    monkeypatch.setattr(d.ml_prices, "get_json", Mock(side_effect=AssertionError("no hace falta la ficha")))
    post = Mock(side_effect=AssertionError("no se vuelve a votar"))
    assert d.run(tmp_path / "catalog.json", tmp_path, post=post) == 0
    out = capsys.readouterr().out
    assert "DUDOSO_SALTEO par=B0:MLA0 motivo=ya_para_alejandro desde=2026-11-10" in out
    assert "DUDOSO_PARA_ALEJANDRO par=B0:MLA0 origen=anterior" in out  # el vigía lo sigue contando
    assert "saltados_hoy=1" in out


def test_con_otro_criterio_de_prompt_se_vota_una_vez_mas(tmp_path, monkeypatch):
    _cola(tmp_path, 1)
    _previo(tmp_path, "B0:MLA0", prompt="otro-criterio")
    monkeypatch.setattr(d.ml_prices, "get_json", lambda path: {"name": "Ficha"})
    post = post_falso(voto())
    d.run(tmp_path / "catalog.json", tmp_path, post=post)
    assert post.call_count == 2


def test_voto_invalido_de_otro_dia_pide_solo_el_que_falta(tmp_path, monkeypatch):
    _cola(tmp_path, 1)
    _previo(tmp_path, "B0:MLA0", votos=[
        {"modelo": d.MODELOS[0], "decision": "invalido", "motivo": "falló la respuesta (ReadTimeout)"},
        {"modelo": d.MODELOS[1], "decision": "aprobar", "motivo": "Mismo modelo"}])
    monkeypatch.setattr(d.ml_prices, "get_json", Mock(side_effect=AssertionError("ficha ya guardada")))
    monkeypatch.setattr(d.revisar_altas, "review", Mock(return_value=0))
    post = post_falso(voto())
    d.run(tmp_path / "catalog.json", tmp_path, post=post)
    assert [c.kwargs["json"]["model"] for c in post.call_args_list] == [d.MODELOS[0]]


def test_invalido_registra_codigo_http_y_finish_reason():
    response = requests.Response()
    response.status_code, response._content = 429, b'{"status":429,"title":"Too Many Requests"}'
    error = requests.HTTPError("429", response=response)
    decision, motivo = d.votar("a", {}, post=Mock(return_value=Mock(raise_for_status=Mock(side_effect=error))))
    assert decision == "invalido" and "HTTPError 429" in motivo and "Too Many Requests" in motivo
    vacio = Mock(return_value=Mock(json=lambda: {
        "choices": [{"message": {"content": "", "reasoning_content": "pensando..."}, "finish_reason": "length"}],
        "usage": {"completion_tokens": 4000}}))
    decision, motivo = d.votar("a", {}, post=vacio)
    assert decision == "invalido"
    assert "finish_reason=length" in motivo and "completion_tokens=4000" in motivo and "razonamiento=11" in motivo


def test_prompt_mantiene_el_criterio_original_y_los_votos_viejos_cuentan():
    # Replay 12/11: el prompt laxo hizo que un modelo aprobara productos distintos; se mantiene «ante la duda, rechazá».
    assert "Si faltan datos para confirmar que es el mismo producto, rechazá" in d.PROMPT
    assert d.PROMPT_VERSION == d.PROMPT_ORIGINAL  # votos guardados sin «prompt» siguen valiendo


def test_par_que_volvio_a_la_cola_despues_de_resolverse_se_vota_de_nuevo(tmp_path, monkeypatch):
    # Revisor 12/11: la evidencia es anterior a la entrada actual del par en la cola (revisionDesde).
    _cola(tmp_path, 1, desde="2026-11-20")
    _previo(tmp_path, "B0:MLA0", fecha="2026-11-10")
    monkeypatch.setattr(d.ml_prices, "get_json", lambda path: {"name": "Ficha"})
    monkeypatch.setattr(d.revisar_altas, "review", Mock(return_value=0))
    post = post_falso(voto())
    d.run(tmp_path / "catalog.json", tmp_path, post=post)
    assert post.call_count == 2


def test_429_se_reintenta_una_vez(monkeypatch):
    monkeypatch.setattr(d.time, "sleep", lambda s: None)
    response = requests.Response()
    response.status_code, response._content = 429, b"too many"
    ok = post_falso(voto())()
    ok.status_code = 200
    malo = Mock(status_code=429, raise_for_status=Mock(side_effect=requests.HTTPError("429", response=response)))
    post = Mock(side_effect=[malo, ok])
    assert d.votar("a", {}, post=post) == ("aprobar", "Mismo modelo") and post.call_count == 2
    post = Mock(side_effect=[malo, malo])
    assert d.votar("a", {}, post=post)[0] == "invalido" and post.call_count == 2


def test_version_del_prompt_sale_del_texto():
    import hashlib
    assert d.PROMPT_VERSION == hashlib.sha256(d.PROMPT.encode()).hexdigest()[:12]
