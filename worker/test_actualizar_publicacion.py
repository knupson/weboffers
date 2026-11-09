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


def test_lectura_y_escritura_bajo_lock_compartido(tmp_path):
    from alta_state import update_state

    path = tmp_path / "publicacion.json"
    desglose = tmp_path / "desglose.log"
    desglose.write_text(producto("uno"), encoding="utf-8")
    # El aviso sale despu?s de importar la CLI, antes de entrar al lock real.
    script = (
        "from tools import actualizar_publicacion as cli; "
        "print('LISTO', flush=True); raise SystemExit(cli.main())"
    )
    process = None

    def bajo_lock():
        nonlocal process
        process = subprocess.Popen(
            [sys.executable, "-c", script, "--desglose", str(desglose)],
            cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8",
            env={**os.environ, "OUTPUT_PATH": str(tmp_path / "offers.json"),
                 "PYTHONIOENCODING": "utf-8"},
        )
        assert process.stdout.readline().strip() == "LISTO"
        with pytest.raises(subprocess.TimeoutExpired):
            process.communicate(timeout=1)
        assert not path.exists(), "La CLI escribi? mientras altas.lock estaba tomado"
        # Si leyera antes del lock, perder?a esta entrada al guardar.
        path.write_text(json.dumps({"previo": entrada()}), encoding="utf-8")

    try:
        # confirmar_altas usa exactamente update_state([], output / "altas.json", ...).
        # El decorador locked_refresh adquiere altas.lock (flock o msvcrt).
        update_state([], tmp_path / "altas.json", bajo_lock)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 0, stderr
        state = json.loads(path.read_text(encoding="utf-8"))
        assert state["uno"]["situacion"] == "publicado"
        assert state["previo"] == entrada()
        assert "PUBLICACION_OK publicados=2" in stdout
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=15)
