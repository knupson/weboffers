"""Contrato de la CLI posterior al deploy, sin servicios externos."""
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from publicacion import ART


ROOT = Path(__file__).resolve().parents[1]


def producto(slug, resultado="PUBLICADO", motivo=""):
    return (f"PRODUCTO {slug} asin=B{slug} origen=repo {resultado} "
            + (f"{motivo}=FALLA(dato ausente)" if motivo else ""))


def entrada(situacion="publicado"):
    return dict(situacion=situacion, desde="2026-11-01", hasta=None,
                intentos=0, ultimoIntento=None, motivo="", asin="Bprevio")


def correr(tmp_path, texto, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/actualizar_publicacion.py"),
         "--desglose", *(args or ["-"])],
        input=texto, text=True, encoding="utf-8", capture_output=True,
        cwd=ROOT / "worker",
        env={**os.environ, "OUTPUT_PATH": str(tmp_path / "offers.json"),
             "PYTHONIOENCODING": "utf-8"},
    )


def test_cli_escribe_estado_y_resumen(tmp_path):
    antes = datetime.now(ART).date().isoformat()
    result = correr(tmp_path, "\n".join([
        producto("uno"), producto("dos"), producto("tres", "FILTRADO", "envio")]))
    assert result.returncode == 0, result.stderr
    state = json.loads((tmp_path / "publicacion.json").read_text(encoding="utf-8"))
    assert {s: i["situacion"] for s, i in state.items()} == {
        "uno": "publicado", "dos": "publicado", "tres": "no_revisar"}
    assert state["uno"]["asin"] == "Buno"
    assert state["uno"]["desde"] in {antes, datetime.now(ART).date().isoformat()}
    assert "PUBLICACION_CAMBIO uno ausente->publicado motivo=" in result.stdout
    assert "PUBLICACION_CAMBIO tres ausente->no_revisar motivo=envio" in result.stdout
    assert "PUBLICACION_OK publicados=2 republicacion=0 no_revisar=1 salieron=0 republicados=0" in result.stdout
    assert all(re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d ", line)
               for line in result.stdout.splitlines())
    assert "PUBLICACION_OK" in next((tmp_path / "logs").glob("worker-*.log")).read_text(encoding="utf-8")


@pytest.mark.parametrize("existe", [True, False])
def test_cli_desglose_vacio_no_toca_estado(tmp_path, existe):
    path = tmp_path / "publicacion.json"
    original = json.dumps({"previo": entrada()}).encode()
    if existe:
        path.write_bytes(original)
    result = correr(tmp_path, "sin productos\nPRODUCTO incompleto\n")
    assert result.returncode == 1
    assert "PUBLICACION_OK" not in result.stdout
    assert path.read_bytes() == original if existe else not path.exists()


@pytest.mark.parametrize("cantidad", [10, 11])
def test_alerta_mas_de_10(tmp_path, cantidad):
    state = {f"p{i}": entrada() for i in range(cantidad)}
    (tmp_path / "publicacion.json").write_text(json.dumps(state), encoding="utf-8")
    result = correr(tmp_path, "\n".join(
        producto(s, "FILTRADO", "envio" if i < 6 else "precio")
        for i, s in enumerate(state)))
    assert result.returncode == 0, result.stderr
    alertas = [l for l in result.stdout.splitlines() if "PUBLICACION_ALERTA " in l]
    if cantidad == 11:
        assert len(alertas) == 1
        assert "PUBLICACION_ALERTA salieron=11 motivos=envio:6,precio:5" in alertas[0]
    else:
        assert alertas == []
    assert f"PUBLICACION_OK publicados=0 republicacion={cantidad} no_revisar=0 salieron={cantidad} republicados=0" in result.stdout


def test_cli_lee_archivo_y_no_registra_cambios_inexistentes(tmp_path):
    (tmp_path / "publicacion.json").write_text(json.dumps({"previo": entrada()}), encoding="utf-8")
    path = tmp_path / "desglose.log"
    path.write_text(producto("previo"), encoding="utf-8")
    result = correr(tmp_path, "", str(path))
    assert result.returncode == 0, result.stderr
    assert "PUBLICACION_CAMBIO" not in result.stdout
    assert "PUBLICACION_OK publicados=1" in result.stdout


def test_lectura_y_escritura_bajo_lock_compartido(tmp_path, monkeypatch):
    from tools import actualizar_publicacion as cli

    dentro = False
    eventos = []

    def lock(catalog, lock_path, operation):
        nonlocal dentro
        assert catalog == []
        assert lock_path == tmp_path / "altas.json"
        dentro = True
        try:
            return operation()
        finally:
            dentro = False

    def cargar(output):
        assert dentro and output == tmp_path
        eventos.append("lectura")
        return {}

    def guardar(output, estado):
        assert dentro and output == tmp_path
        assert estado["uno"]["desde"] == "2026-11-09"
        eventos.append("escritura")

    monkeypatch.setattr(cli.alta_state, "update_state", lock)
    monkeypatch.setattr(cli.publicacion, "cargar", cargar)
    monkeypatch.setattr(cli.publicacion, "guardar", guardar)
    cli.actualizar(producto("uno"), tmp_path, "2026-11-09")
    assert eventos == ["lectura", "escritura"]
