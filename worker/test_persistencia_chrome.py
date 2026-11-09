"""Auditoría 09/11 (F-06, F-17, F-29): el relevamiento de Chrome se guarda ASIN por ASIN y un corte no pierde lo leído.

Sin Chrome ni red reales: el lector de páginas y `docker` son dobles; el resto (parcial, fusión, lista, script sh) es real.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock

import pytest

from tools import altas_chrome


class Kill(BaseException):
    """Simula SIGKILL: no la atrapa ningún `except Exception`."""


def cargar_envio_ar_chrome():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "envio_ar_chrome", Path(__file__).resolve().parents[1] / "tools" / "envio_ar_chrome.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


def test_cada_asin_queda_anotado_y_el_kill_pierde_solo_el_que_estaba_en_curso(tmp_path, monkeypatch, capsys):
    import asyncio
    chrome_mod = cargar_envio_ar_chrome()
    parcial = tmp_path / "parcial.jsonl"

    async def leer(c, s, asin):
        if asin == "A3":
            raise Kill()
        return {"deliver": "Deliver to Argentina", "buybox": True, "envio": "FREE delivery to Argentina",
                "precio": "$150.00", "titulo": "x", "lang": "en-us"}

    async def pestana(c, ctx):
        return "tid", "sid"

    monkeypatch.setattr(chrome_mod, "leer_producto", leer)
    monkeypatch.setattr(chrome_mod, "nueva_pestana", pestana)
    slugs = {"A1": ["s1"], "A2": ["s2"], "A3": ["s3"], "A4": ["s4"]}
    with pytest.raises(Kill):
        asyncio.run(chrome_mod.recorrer(Mock(), "ctx", "tid", "sid", list(slugs), slugs, {}, str(parcial)))
    lineas = [json.loads(linea) for linea in parcial.read_text(encoding="utf-8").splitlines()]
    assert [x["asin"] for x in lineas] == ["A1", "A2"]  # el A3 (en curso) no está; nada más se perdió
    assert lineas[0]["item"]["ships"] is True and lineas[0]["slugs"] == ["s1"] and lineas[0]["t"].endswith("-03:00")
    assert capsys.readouterr().err.count("CHROME_PRODUCTO") == 2  # una línea por ASIN, en el momento

    # Un KILL a mitad de escritura deja una última línea truncada: se ignora, el resto se conserva.
    with parcial.open("a", encoding="utf-8") as archivo:
        archivo.write('{"t": "2026-11-09T05:00:09-03:00", "asin": "A3", "sl')
    snap = altas_chrome.snapshot_desde_parcial(parcial.read_text(encoding="utf-8"))
    assert sorted(snap["items"]) == ["A1", "A2"] and snap["generado"] == lineas[1]["t"]


def test_reintento_del_dia_salta_lo_ya_leido_y_pide_lo_que_quedo_sin_dato(tmp_path, monkeypatch):
    import publicacion
    hoy = altas_chrome.hora()[:10]
    catalogo = [{"asin": f"A{n}", "slug": f"s{n}", "store": "US", "verified": True, "image": "/x.webp",
                 "ml": {"catalogId": f"MLA{n}"}} for n in range(1, 5)]
    repo = tmp_path / "catalog.json"
    repo.write_text(json.dumps(catalogo), encoding="utf-8")
    (tmp_path / "catalog-auto.json").write_text("[]", encoding="utf-8")
    publicacion.guardar(tmp_path, {p["slug"]: {"situacion": "publicado", "desde": hoy, "hasta": None, "intentos": 0,
                                               "ultimoIntento": None, "motivo": "", "asin": p["asin"]} for p in catalogo})
    monkeypatch.setenv("PUBLICACION_MODO", "verificacion")
    monkeypatch.delenv("CHROME_REHACER", raising=False)
    assert altas_chrome.asin_list(repo, tmp_path).split() == ["A1:s1", "A2:s2", "A3:s3", "A4:s4"]
    # El corte dejó A1 y A2 leídos (A2 sin dato) y se fusionó como lo hace el .sh.
    parcial = "\n".join(json.dumps(x) for x in [
        {"t": f"{hoy}T05:00:00-03:00", "asin": "A1", "slugs": ["s1"], "item": {"ships": True, "free": True, "precio": "$150"}},
        {"t": f"{hoy}T05:00:05-03:00", "asin": "A2", "slugs": ["s2"], "item": {"ships": None, "motivo": "captcha"}}])
    altas_chrome.merge_chrome(tmp_path, hoy, altas_chrome.snapshot_desde_parcial(parcial))
    assert altas_chrome.asin_list(repo, tmp_path).split() == ["A2:s2", "A3:s3", "A4:s4"]
    monkeypatch.setenv("CHROME_REHACER", "1")
    assert len(altas_chrome.asin_list(repo, tmp_path).split()) == 4


FAKE_DOCKER = r"""#!/bin/sh
echo "docker $*" >> "$FAKE_DIR/llamadas"
case "$*" in
  *"altas_chrome.py listar"*) echo "A1:s1 A2:s2 A3:s3" ;;
  *"curl -s -m3"*) exit 0 ;;
  "cp "*) exit 0 ;;
  *"envio_ar_chrome.py A1"*)
     if [ "${FAKE_MODO:-corte}" != "corte" ]; then cat "$FAKE_DIR/completo.json"; rm -f "$FAKE_DIR/parcial"; exit 0; fi
     printf '%s\n' '{"t":"2026-11-09T05:00:00-03:00","asin":"A1","slugs":["s1"],"item":{"ships":true,"free":true,"precio":"$150"}}' \
       '{"t":"2026-11-09T05:00:05-03:00","asin":"A2","slugs":["s2"],"item":{"ships":null,"motivo":"captcha"}}' \
       '{"t":"2026-11-09T05:00:09-03:00","asin":"A3","slu' > "$FAKE_DIR/parcial"
     exit 137 ;;
  *"cat /tmp/ar-chrome-parcial"*) cat "$FAKE_DIR/parcial" 2>/dev/null || exit 1 ;;
  *"altas_chrome.py guardar"*--jsonl*) cat > "$FAKE_DIR/guardado_jsonl" ;;
  *"altas_chrome.py guardar"*) cat > "$FAKE_DIR/guardado_json" ;;
  *"rm -f /tmp/ar-chrome-parcial"*) rm -f "$FAKE_DIR/parcial" ;;
esac
"""


@pytest.fixture
def sh_con_docker_falso(tmp_path):
    shell = shutil.which("sh")
    if not shell:
        pytest.skip("Requiere sh para ejecutar el script real")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "docker").write_bytes(FAKE_DOCKER.replace("\r\n", "\n").encode("utf-8"))
    (bin_dir / "docker").chmod(0o755)
    (tmp_path / "completo.json").write_text(json.dumps({"generado": "2026-11-09T05:30:00-03:00", "items": {}}))

    def correr(modo, tope="100"):
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(tmp_path),
               "FAKE_MODO": modo, "CADENA_TIMEOUT": tope}
        script = Path(__file__).resolve().parents[1] / "tools" / "envio_ar_chrome.sh"
        return subprocess.run([shell, str(script), "--con-horarios", "--pendientes"], env=env, capture_output=True, encoding="utf-8", errors="replace",
                              text=True, timeout=30)

    return correr, tmp_path


def test_sh_corte_guarda_lo_leido_propaga_el_codigo_y_descuenta_la_preparacion(sh_con_docker_falso):
    correr, tmp_path = sh_con_docker_falso
    r = correr("corte", tope="100")
    assert r.returncode == 137, r.stderr
    assert "ENVIO_AR_CHROME_CORTADO c" in r.stdout and "ENVIO_AR_CHROME_RECUPERO" in r.stdout
    guardado = (tmp_path / "guardado_jsonl").read_text(encoding="utf-8")
    assert '"asin":"A1"' in guardado and '"asin":"A2"' in guardado  # lo leído hasta el corte llegó a guardar
    assert not (tmp_path / "parcial").exists() and not (tmp_path / "guardado_json").exists()
    llamadas = (tmp_path / "llamadas").read_text(encoding="utf-8")
    # F-17: el timeout interno es menor que el tope externo (100 s menos el margen de 10 s y lo gastado al preparar).
    interno = int(next(x for x in llamadas.splitlines() if "envio_ar_chrome.py A1" in x).split("timeout -s KILL ")[1].split()[0])
    assert 1 <= interno <= 90
    assert "-e AR_CHROME_PARCIAL=/tmp/ar-chrome-parcial-" in llamadas


def test_sh_corrida_completa_guarda_el_json_y_borra_el_parcial(sh_con_docker_falso):
    correr, tmp_path = sh_con_docker_falso
    (tmp_path / "parcial").write_text("x")  # el parcial de esta corrida, ya fusionado en el JSON final
    r = correr("completo")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "guardado_json").exists() and not (tmp_path / "parcial").exists()
    assert "ENVIO_AR_CHROME_CORTADO" not in r.stdout


def test_sh_limpia_temporales_viejos_de_corridas_anteriores(sh_con_docker_falso):
    correr, tmp_path = sh_con_docker_falso
    shell = shutil.which("sh")
    # El /tmp que ve sh no es el de Python en Windows: el temporal viejo se crea y se mira desde sh.
    crear = "echo x > /tmp/ar-chrome-envio.VIEJOTEST && touch -d '4 hours ago' /tmp/ar-chrome-envio.VIEJOTEST"
    assert subprocess.run([shell, "-c", crear]).returncode == 0
    correr("completo")
    existe = subprocess.run([shell, "-c", "test -e /tmp/ar-chrome-envio.VIEJOTEST"]).returncode == 0
    subprocess.run([shell, "-c", "rm -f /tmp/ar-chrome-envio.VIEJOTEST"])
    assert not existe
