"""Alta en dos fases y relevamiento compartido, sin Chrome ni consultas reales."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tools import altas_chrome, confirmar_altas as confirmation
from test_catalog_auto import candidate, setup_job
import catalog_auto as auto
from catalog import read_catalog


@pytest.mark.parametrize("args,modo,esperado", [
    ([], None, "verificacion"), (["--pendientes"], None, "alta"),
    (["--pendientes"], "verificacion", "verificacion"), ([], "alta", "alta"),
])
def test_shell_pendientes_selecciona_alta_sin_pisar_modo_explicito(args, modo, esperado):
    shell = shutil.which("sh")
    if not shell:
        pytest.skip("Requiere sh para ejecutar el script real")
    env = dict(os.environ)
    env.pop("PUBLICACION_MODO", None)
    if modo is not None:
        env["PUBLICACION_MODO"] = modo
    source = (Path(__file__).parents[1] / "tools/envio_ar_chrome.sh").read_text(encoding="utf-8")
    # Sin productos: docker falso registra el modo recibido y evita consultas reales.
    source = 'docker() { printf "%s\\n" "$@" >&2; };\n' + source
    result = subprocess.run([shell, "-c", source, "envio_ar_chrome.sh", "--con-horarios", *args],
                            env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert f"PUBLICACION_MODO={esperado}" in result.stderr.splitlines()
    assert "ENVIO_AR_CHROME_OK sin productos para relevar" in result.stdout


TODAY = "2026-11-06"


def save(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def pending(asin="NUEVO", **changes):
    return dict(asin=asin, slug=asin.lower(), store="US", verified=True,
                ml={"catalogId": "MLA" + asin}, pendienteDesde="2026-11-05", image="/products/x.webp", **changes)


def snapshot(items, day=TODAY):
    return {"generado": day + "T03:30:00-03:00", "segundos": 1, "items": items}


@pytest.fixture
def state(tmp_path):
    import publicacion
    publicacion.guardar(tmp_path, {})
    repo = tmp_path / "catalog.json"
    save(repo, [{"asin": "REPO", "slug": "repo", "store": "US", "verified": True,
                 "ml": {"catalogId": "MLAREPO"}, "image": "/products/repo.webp"}])
    save(tmp_path / "catalog-auto.json", [pending("EXISTENTE")])
    save(tmp_path / "altas-pendientes.json", [pending()])
    return repo, tmp_path


@pytest.mark.parametrize("ships,free,price,reason", [
    (True, True, "$100.00", None), (True, True, "$400.00", None),
    (True, False, "$150.00", "envio_pago"),
    (False, None, None, "no_envia_ar"),
    (True, True, "$99.99", "precio_fuera_de_rango"),
    (True, True, "$400.01", "precio_fuera_de_rango"),
])
def test_decisiones_con_evidencia_y_sin_tocar_existentes(state, ships, free, price, reason, capsys):
    repo, output = state
    before = (output / "catalog-auto.json").read_bytes()
    item = {"ships": ships, "free": free, "precio": price, "text": "Evidencia de Amazon"}
    save(output / f"ar-chrome-{TODAY}.json", snapshot({"NUEVO": item}))
    result = confirmation.confirm(repo, output, TODAY)
    assert read_catalog(output / "altas-pendientes.json") == []
    catalog = read_catalog(output / "catalog-auto.json")
    assert catalog[0] == pending("EXISTENTE")
    if reason is None:
        assert result == {"promovidas": 1, "rechazadas": 0, "siguen_pendientes": 0}
        assert catalog[1]["shipsToAr"] == {"freeShipping": True, "checked": TODAY}
        assert "pendienteDesde" not in catalog[1]
        assert len(catalog) == 2
    else:
        assert (output / "catalog-auto.json").read_bytes() == before
        assert result == {"promovidas": 0, "rechazadas": 1, "siguen_pendientes": 0}
        rejection = json.loads((output / "altas-rechazadas.json").read_text())
        assert rejection["NUEVO"] == {"fecha": TODAY, "motivo": reason, "texto": item["text"]}
    log = capsys.readouterr().out
    assert "ALTA_PRODUCTO slug=nuevo asin=NUEVO" in log
    assert "ships=" in log and "free=" in log and "precio=" in log and "texto=" in log
    assert "ALTAS_OK promovidas=" in log
    assert confirmation.confirm(repo, output, TODAY) == {"promovidas": 0, "rechazadas": 0, "siguen_pendientes": 0}


@pytest.mark.parametrize("item", [
    {"ships": None, "free": None, "motivo": "ubicacion_no_ar"},
    {"ships": None, "motivo": "captcha"},
    {"ships": None, "motivo": "envio_sin_precio"},
    {"ships": True, "free": True, "precio": "EUR 150"},
    {"ships": True, "free": None, "precio": "$150"},
    {},
])
def test_sin_dato_primera_y_tercera_noche_sin_duplicar_intentos(state, item):
    repo, output = state
    for night in range(6, 9):
        day = f"2026-11-{night:02d}"
        save(output / f"ar-chrome-{day}.json", snapshot({"NUEVO": item}, day))
        result = confirmation.confirm(repo, output, day)
        if night < 8:
            assert result["siguen_pendientes"] == 1
            assert read_catalog(output / "altas-pendientes.json")[0]["nochesSinDato"] == night - 5
            confirmation.confirm(repo, output, day)
            assert read_catalog(output / "altas-pendientes.json")[0]["nochesSinDato"] == night - 5
        else:
            assert result["rechazadas"] == 1 and result["siguen_pendientes"] == 0
            assert json.loads((output / "altas-rechazadas.json").read_text())["NUEVO"]["motivo"] == "sin_dato_3_noches"


def test_no_promueve_evidencia_vieja_ni_sin_archivo(state):
    repo, output = state
    before = (output / "altas-pendientes.json").read_bytes()
    with pytest.raises(ValueError, match="No hay relevamiento de Chrome"):
        confirmation.confirm(repo, output, TODAY)
    save(output / f"ar-chrome-{TODAY}.json", snapshot({"NUEVO": {"ships": True, "free": True, "precio": "$150"}}, "2026-11-05"))
    with pytest.raises(ValueError, match="no es de hoy"):
        confirmation.confirm(repo, output, TODAY)
    assert (output / "altas-pendientes.json").read_bytes() == before


def test_lista_chrome_incluye_pendientes_y_modo_solo_pendientes(state, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    repo, output = state
    assert altas_chrome.asin_list(repo, output).split() == ["REPO:repo", "EXISTENTE:existente", "NUEVO:nuevo"]
    assert altas_chrome.asin_list(repo, output, pending_only=True) == "NUEVO:nuevo"
    save(output / "altas-pendientes.json", [pending("REPO"), pending()])
    assert altas_chrome.asin_list(repo, output).count("REPO:") == 1


def test_fusion_chrome_conserva_resto_y_actualiza_pendientes(state):
    _, output = state
    original = {"ships": False, "free": None}
    save(output / f"ar-chrome-{TODAY}.json", snapshot({"REPO": original, "NUEVO": original}))
    new = {"ships": True, "free": True, "precio": "$150"}
    altas_chrome.merge_chrome(output, TODAY, snapshot({"NUEVO": new}))
    merged = json.loads((output / f"ar-chrome-{TODAY}.json").read_text())
    assert merged["items"] == {"REPO": original, "NUEVO": new}
    before = (output / f"ar-chrome-{TODAY}.json").read_bytes()
    with pytest.raises(ValueError):
        altas_chrome.merge_chrome(output, TODAY, snapshot({"REPO": new}, "2026-11-05"))
    assert (output / f"ar-chrome-{TODAY}.json").read_bytes() == before


@pytest.mark.parametrize("days,skip", [(0, True), (6, True), (7, False)])
def test_descubrimientos_excluyen_rechazos_y_pendientes(setup_job, monkeypatch, days, skip):
    from datetime import datetime, timedelta
    from unittest.mock import Mock
    repo, output, discover = setup_job
    output.mkdir(exist_ok=True)
    now = datetime.fromisoformat("2026-11-08T23:30:00+00:00")
    save(output / "altas-rechazadas.json", {"RECHAZADO": {"fecha": (now.date() - timedelta(days=days)).isoformat()}})
    save(output / "altas-pendientes.json", [pending()])
    desde_ml = Mock(return_value=[])
    monkeypatch.setattr(auto.crecer_desde_ml, "candidatos", desde_ml)
    auto.maybe_grow(repo, output, now, mep=1000)
    for asins in (discover.call_args.kwargs["existing_asins"], desde_ml.call_args.args[0]):
        assert ("RECHAZADO" in asins) is skip
        assert "NUEVO" in asins and "EXISTENTE" in asins
    assert "MLANUEVO" in desde_ml.call_args.args[1]


@pytest.mark.parametrize("collision", ["asin", "slug", "catalogId"])
def test_fase_a_deduplica_con_pendientes(setup_job, collision, capsys):
    repo, output, _ = setup_job
    output.mkdir(exist_ok=True)
    row = candidate()
    entry = pending()
    if collision == "catalogId":
        entry["ml"]["catalogId"] = row[collision]
    else:
        entry[collision] = row[collision]
    save(output / "altas-pendientes.json", [entry])
    added, _ = auto.add_accepted(read_catalog(repo), {"accepted": [row]}, output, TODAY)
    assert not added
    assert read_catalog(output / "altas-pendientes.json") == [entry]
    assert "decision=descartado" in capsys.readouterr().out


def test_comando_diurno_encadena_y_shell_preserva_argumentos():
    root = Path(__file__).resolve().parents[1]
    host = (root / "tools/confirmar_altas.sh").read_text(encoding="utf-8")
    shell = (root / "tools/envio_ar_chrome.sh").read_text(encoding="utf-8")
    assert 'envio_ar_chrome.sh" --pendientes' in host
    assert host.index("envio_ar_chrome.sh") < host.index("/app/tools/confirmar_altas.py")
    assert 'listar "$@"' in shell and '*sys.argv[2:]' in shell
    assert "altas_chrome.py guardar --fecha" in shell
    assert shell.count("python3 /tmp/envio_ar_chrome.py") == 1


def test_altas_ok_cuenta_vencidos_con_los_mismos_requisitos_de_chrome(state, capsys):
    repo, output = state
    save(output / "altas-pendientes.json", [])
    productos = [pending(nombre) for nombre in ["VENCIDO", "HOY", "VIGENTE", "SINIMAGEN", "ESPANA"]]
    productos[3].pop("image")
    productos[4]["store"] = "ES"
    save(output / "catalog-auto.json", productos)
    import publicacion
    publicacion.guardar(output, {
        p["slug"]: {"asin": p["asin"], "situacion": "no_revisar", "desde": "2026-10-30",
                    "hasta": "2026-11-07" if p["asin"] == "VIGENTE" else TODAY if p["asin"] == "HOY" else "2026-11-05",
                    "ultimoIntento": None, "intentos": 0, "motivo": "sin_envio"}
        for p in productos
    })
    save(output / f"ar-chrome-{TODAY}.json", snapshot({p["asin"]: {"ships": True, "free": True} for p in productos}))
    confirmation.confirm(repo, output, TODAY)
    assert "vencidos=3" in capsys.readouterr().out
