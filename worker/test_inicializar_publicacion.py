"""Inicialización desde desgloses históricos, sin servicios externos."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from zlib import crc32


ROOT = Path(__file__).resolve().parents[1]
HOY = date(2026, 11, 9)


def producto(slug, estado="FILTRADO"):
    return f"PRODUCTO {slug} asin=B{slug} origen=repo {estado} envio=FALLA(sin envío)"


def bloque(fecha, *lineas):
    return f"### /logs/desglose-{fecha}-1200.log\n" + "\n".join(lineas) + "\n"


def correr(output, texto, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / "tools/inicializar_publicacion.py"),
         "--hoy", HOY.isoformat(), *args],
        input=texto, capture_output=True, text=True, encoding="utf-8",
        cwd=ROOT / "worker", env={**os.environ,
            "OUTPUT_PATH": str(output / "offers.json"), "PYTHONIOENCODING": "utf-8"},
    )


def test_inicial_reparte_los_tres_grupos(tmp_path):
    # El orden de stdin no debe reemplazar el orden de las fechas.
    texto = (
        bloque("2026-11-09", producto("actual", "PUBLICADO"),
               producto("reciente"), producto("viejo"), producto("nuevo"))
        + bloque("2026-11-05", producto("viejo", "PUBLICADO"))
        + bloque("2026-11-08", producto("reciente", "PUBLICADO"))
    )
    result = correr(tmp_path, texto)
    assert result.returncode == 0, result.stderr
    estado = json.loads((tmp_path / "publicacion.json").read_text(encoding="utf-8"))
    assert {s: i["situacion"] for s, i in estado.items()} == {
        "actual": "publicado", "reciente": "republicacion",
        "viejo": "no_revisar", "nuevo": "no_revisar"}
    assert estado["reciente"]["desde"] == "2026-11-09"
    assert estado["reciente"]["hasta"] is None
    assert estado["viejo"]["hasta"] == "2026-11-16"
    assert estado["nuevo"]["hasta"] == (
        HOY + timedelta(days=crc32(b"Bnuevo") % 7 + 1)).isoformat()
    for slug, item in estado.items():
        assert set(item) == {"situacion", "desde", "hasta", "intentos",
                             "ultimoIntento", "motivo", "asin"}
        assert item["asin"] == f"B{slug}"
        assert item["motivo"] == ("" if slug == "actual" else "envio")
    assert "PUBLICACION_INICIAL publicados=1 republicacion=1 no_revisar=2" in result.stdout


def test_producto_ausente_del_ultimo_desglose_no_entra(tmp_path):
    texto = (
        bloque("2026-11-09", producto("actual", "PUBLICADO")).replace(
            "-1200.log", "-1300.log")
        + bloque("2026-11-08", producto("retirado", "PUBLICADO"))
        + bloque("2026-11-09", producto("retirado_hoy", "PUBLICADO"),
                 producto("filtrado_retirado"))
    )
    result = correr(tmp_path, texto)
    assert result.returncode == 0, result.stderr
    estado = json.loads((tmp_path / "publicacion.json").read_text(encoding="utf-8"))
    assert set(estado) == {"actual"}


def test_escalonado_en_7_dias(tmp_path):
    result = correr(tmp_path, bloque("2026-11-09", *(producto(str(i)) for i in range(100))))
    assert result.returncode == 0, result.stderr
    estado = json.loads((tmp_path / "publicacion.json").read_text(encoding="utf-8"))
    assert len(estado) == 100
    assert {i["hasta"] for i in estado.values()} == {
        (HOY + timedelta(days=d)).isoformat() for d in range(1, 8)}
    for item in estado.values():
        assert item["hasta"] == (HOY + timedelta(
            days=crc32(item["asin"].encode()) % 7 + 1)).isoformat()
        assert item["intentos"] == 0
        assert item["ultimoIntento"] is None


def test_no_pisa_estado_existente(tmp_path):
    path = tmp_path / "publicacion.json"
    original = b'{"existente": {}}'
    path.write_bytes(original)
    texto = bloque("2026-11-09", producto("actual", "PUBLICADO"))
    result = correr(tmp_path, texto)
    assert result.returncode == 1
    assert path.read_bytes() == original
    result = correr(tmp_path, texto, "--forzar")
    assert result.returncode == 0, result.stderr
    assert set(json.loads(path.read_text(encoding="utf-8"))) == {"actual"}
