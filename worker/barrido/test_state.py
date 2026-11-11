import json
import pytest
from . import state as module
from .state import State, acquire_run_lock


def payload(category="A"):
    return {"page": 1, "complete": True, "products": [{"id": "FIXTURE", "provenance": [{"category_id": category}]}]}


def test_corte_antes_checkpoint(tmp_path, monkeypatch):
    state = State(tmp_path, "2026-11-07", "US")
    original = module.write_atomic
    def fail(path, body, **options):
        if path.name == "checkpoint.json":
            raise OSError("corte fixture antes del checkpoint")
        return original(path, body, **options)
    monkeypatch.setattr(module, "write_atomic", fail)
    with pytest.raises(OSError, match="corte fixture"):
        state.commit_page("A", 1, payload())
    resumed = State(tmp_path, "2026-11-07", "US")
    assert resumed.load_checkpoint("A") is None
    assert len(resumed.materialize_jsonl()) == 1


def test_reanudacion_sin_duplicados(tmp_path):
    state = State(tmp_path, "2026-11-07", "US")
    state.commit_page("A", 1, payload())
    state.commit_page("B", 1, payload("B"))
    rows = state.materialize_jsonl()
    assert len(rows) == 1 and len(rows[0]["provenance"]) == 2
    assert len(state.materialize_jsonl()) == 1
    assert len((tmp_path / "US-2026-11-07.jsonl").read_text().splitlines()) == 1


def test_materializar_sin_filas_en_memoria_escribe_lo_mismo(tmp_path):
    # 11/11: el runner materializa con return_rows=False (una página en memoria a la vez).
    state = State(tmp_path, "2026-11-07", "US")
    state.commit_page("A", 1, {"page": 1, "complete": False, "products": [
        {"id": "X", "provenance": [{"category_id": "A"}]}, {"id": "Y", "provenance": [{"category_id": "A"}]}]})
    state.commit_page("B", 1, payload("B") | {"products": [{"id": "X", "provenance": [{"category_id": "B"}]}]})
    rows = state.materialize_jsonl(known={"Y"})
    archivo = (tmp_path / "US-2026-11-07.jsonl").read_text(encoding="utf-8")
    assert state.materialize_jsonl(known={"Y"}, return_rows=False) == 2
    assert (tmp_path / "US-2026-11-07.jsonl").read_text(encoding="utf-8") == archivo
    assert [json.loads(l) for l in archivo.splitlines()] == rows
    assert rows[0]["provenance"] == [{"category_id": "A"}, {"category_id": "B"}]
    assert [r["known"] for r in rows] == [False, True]


def test_fecha_nueva_no_reutiliza(tmp_path):
    State(tmp_path, "2026-11-07", "US").commit_page("A", 1, payload())
    assert State(tmp_path, "2026-11-08", "US").load_checkpoint("A") == 1


def test_bloqueo_corridas_simultaneas(tmp_path):
    with acquire_run_lock(tmp_path):
        with pytest.raises(FileExistsError):
            with acquire_run_lock(tmp_path):
                pytest.fail("No debe adquirir segundo lock")
    assert not (tmp_path / "run.lock").exists()


def test_contexto_incompatible_y_pagina_inmutable(tmp_path):
    state = State(tmp_path, "2026-11-07", "US")
    state.freeze({"config": 1})
    with pytest.raises(ValueError, match="incompatible"):
        state.freeze({"config": 2})
    state.commit_page("A", 1, payload())
    with pytest.raises(ValueError, match="inmutable"):
        state.commit_page("A", 1, {**payload(), "complete": False})
