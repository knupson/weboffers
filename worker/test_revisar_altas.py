"""Revisión manual con archivos temporales y sin consultas reales."""
from datetime import datetime
import json
from unittest.mock import Mock

import pytest
import requests

import catalog_auto as auto
from alta_state import read_json, rejected_asins
from test_catalog_auto import candidate
from tools import revisar_altas as revision

TODAY = "2026-11-07"


def save(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def state(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog.json"
    save(catalog, [{"asin": "EXISTENTE", "slug": "existente", "category": "Almacenamiento"}])
    row = candidate(amazonIds={}, revisionDesde="2026-11-06", motivoRevision="sin_identificador_fuerte")
    save(tmp_path / "altas-revision.json", [row])
    photo = Mock(side_effect=lambda entry, output: entry.update(
        image=f"/products/{entry['slug']}.webp", imageSource="https://http2.mlstatic.com/foto.jpg") or True)
    monkeypatch.setattr(auto, "fetch_photo", photo)
    return catalog, tmp_path, row, photo


def run(state, action="aprobar", pairs=None):
    catalog, output, row, _ = state
    return revision.review(catalog, output, action, pairs or [revision.pair_key(row)], "Mismo modelo", today=TODAY)


@pytest.mark.parametrize("item_id", ["MLA456", None])
def test_listar_texto_y_json(state, capsys, item_id):
    catalog, output, row, photo = state
    row["itemId"] = item_id
    row["amazonTitle"] = "Samsung\nT9 SSD"
    save(output / "altas-revision.json", [row])
    before = (output / "altas-revision.json").read_bytes()
    assert revision.review(catalog, output, "listar") == 0
    text = capsys.readouterr().out
    assert len(text.splitlines()) == 1
    for field in ("index", "asin", "catalogId", "amazonTitle", "mlName", "mlPrice", "amazonPriceUsd", "revisionDesde"):
        assert f"{field}=" in text
    assert "https://www.amazon.com/dp/" + row["asin"] in text
    assert "https://www.mercadolibre.com.ar/p/" + row["catalogId"] in text
    assert ("pdp_filters=item_id%3A" in text) is bool(item_id)
    assert revision.review(catalog, output, "listar", as_json=True) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["index"] == 1
    assert listed[0]["mlName"] == row["name"]
    assert listed[0]["asin"] == row["asin"]
    assert listed[0]["mlUrl"] == revision.item_url(row["catalogId"], item_id)
    assert (output / "altas-revision.json").read_bytes() == before
    photo.assert_not_called()


def test_aprobar_misma_entrada_que_alta_automatica(state, tmp_path, capsys):
    catalog, output, row, photo = state
    automatic_output = tmp_path / "automatico"
    strong = candidate()
    added, failures = auto.add_accepted(read_json(catalog, []), {"accepted": [strong]}, automatic_output, TODAY)
    assert not failures
    before = catalog.read_bytes()
    assert run(state) == 0
    expected = {**added[0], "aprobadoPor": "revision-claude", "motivoAprobacion": "Mismo modelo"}
    assert read_json(output / "altas-pendientes.json", []) == [expected]
    assert read_json(output / "altas-revision.json", None) == []
    assert expected["pendienteDesde"] == TODAY
    assert catalog.read_bytes() == before
    assert not (output / "catalog-auto.json").exists()
    assert photo.call_count == 2
    log = capsys.readouterr().out
    assert "motivo=aprobada_en_revision" in log and "decision=pendiente_envio" in log
    assert "REVISION_OK aprobadas=1 rechazadas=0 siguen=0" in log


def test_rechazar_conserva_rechazos_y_ventana_de_7_dias(state, capsys):
    _, output, row, photo = state
    previous = {"fecha": "2026-11-06", "motivo": "envio_pago", "texto": "Prueba"}
    save(output / "altas-rechazadas.json", {"OTRO": previous})
    assert run(state, "rechazar") == 0
    assert read_json(output / "altas-rechazadas.json", {}) == {
        "OTRO": previous, row["asin"]: {"fecha": TODAY, "motivo": "revision: Mismo modelo", "texto": ""}}
    assert read_json(output / "altas-revision.json", None) == []
    assert row["asin"] in rejected_asins(output, "2026-11-13")
    assert row["asin"] not in rejected_asins(output, "2026-11-14")
    assert not (output / "altas-pendientes.json").exists()
    photo.assert_not_called()
    assert "REVISION_OK aprobadas=0 rechazadas=1 siguen=0" in capsys.readouterr().out


@pytest.mark.parametrize("action", ["aprobar", "rechazar"])
def test_par_desconocido_exit_1_sin_modificar_archivos(state, action, capsys):
    catalog, output, _, photo = state
    before = (output / "altas-revision.json").read_bytes()
    assert revision.main(["--catalog", str(catalog), "--output", str(output),
                          action, "NO:EXISTE", "--motivo", "Revisado"]) == 1
    assert (output / "altas-revision.json").read_bytes() == before
    assert "motivo=par_desconocido" in capsys.readouterr().out
    photo.assert_not_called()


@pytest.mark.parametrize("source", ["catalog.json", "catalog-auto.json", "altas-pendientes.json"])
@pytest.mark.parametrize("field", ["asin", "slug", "catalogId", "modelo"])
def test_duplicados_quedan_intactos(state, source, field, capsys):
    _, output, row, photo = state
    existing = {"asin": "OTRO", "slug": "otro", "category": "Almacenamiento", "ml": {"catalogId": "MLAOTRO"}}
    if field == "catalogId":
        existing["ml"]["catalogId"] = row[field]
    elif field == "modelo":
        existing.update(name=row["name"], brand=row["brand"])
    else:
        existing[field] = row[field]
    save(output / source, [existing])
    before = {path: path.read_bytes() for path in output.glob("*.json")}
    assert run(state) == 1
    assert all(path.read_bytes() == data for path, data in before.items())
    photo.assert_not_called()
    assert ("motivo=modelo_duplicado" if field == "modelo" else "motivo=duplicado") in capsys.readouterr().out


@pytest.mark.parametrize("failure", ["precio", "foto", "excepcion", "rechazado", "slug"])
def test_controles_normales_no_quitan_el_par(state, failure, capsys):
    _, output, row, photo = state
    if failure == "precio":
        row["amazonPriceUsd"] = 99
    elif failure == "foto":
        photo.side_effect = None
        photo.return_value = False
    elif failure == "excepcion":
        photo.side_effect = requests.RequestException("Fallo de descarga")
    elif failure == "rechazado":
        save(output / "altas-rechazadas.json", {row["asin"]: {"fecha": TODAY}})
    else:
        row["slug"] = "Slug inválido"
    save(output / "altas-revision.json", [row])
    before = (output / "altas-revision.json").read_bytes()
    assert run(state) == 1
    assert (output / "altas-revision.json").read_bytes() == before
    assert not (output / "altas-pendientes.json").exists()
    assert "REVISION_OK aprobadas=0 rechazadas=0 siguen=1" in capsys.readouterr().out


def test_lote_parcial_y_deduplicacion_entre_aprobaciones(state, capsys):
    _, output, row, photo = state
    other = {**row, "catalogId": "MLAOTRO"}
    save(output / "altas-revision.json", [row, other])
    assert run(state, pairs=[revision.pair_key(row), revision.pair_key(other), "NO:EXISTE"]) == 1
    assert read_json(output / "altas-revision.json", []) == [other]
    assert len(read_json(output / "altas-pendientes.json", [])) == 1
    photo.assert_called_once()
    assert "REVISION_OK aprobadas=1 rechazadas=0 siguen=1" in capsys.readouterr().out


def test_usa_bloqueo_compartido_y_guarda_destino_antes_de_origen(state, monkeypatch):
    catalog, output, row, _ = state
    lock_held = False
    writes = []
    real_write = revision.write_atomic

    def locked(catalog, lock_path, operation):
        nonlocal lock_held
        assert lock_path == output / "altas.json"
        lock_held = True
        return operation()

    def write(path, data):
        assert lock_held
        writes.append(path.name)
        real_write(path, data)

    monkeypatch.setattr(revision, "update_state", locked)
    monkeypatch.setattr(revision, "write_atomic", write)
    assert run(state) == 0
    assert writes == ["altas-pendientes.json", "altas-revision.json"]


def test_fecha_art_y_argumentos_del_comando(state, monkeypatch):
    catalog, output, row, _ = state

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat("2026-11-08T01:00:00+00:00").astimezone(tz)

    monkeypatch.setattr(revision, "datetime", Clock)
    assert revision.main(["--catalog", str(catalog), "--output", str(output), "aprobar",
                          revision.pair_key(row), "--motivo", "Revisado"]) == 0
    assert read_json(output / "altas-pendientes.json", [])[0]["pendienteDesde"] == TODAY
