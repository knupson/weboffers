"""Filtros compartidos por las etapas de publicación."""
import json

import pytest

import publicacion
import requisitos
from alta_state import rejected_asins
from tools import altas_chrome


def producto(slug="producto", **changes):
    return {"slug": slug, "asin": slug.upper(), "verified": True,
            "image": "/producto.webp", "store": "US", "ml": {"catalogId": "MLA1"}, **changes}


def test_modo_actual(monkeypatch):
    monkeypatch.delenv("PUBLICACION_MODO", raising=False)
    assert requisitos.modo_actual() == "verificacion"
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    assert requisitos.modo_actual() == "alta"


@pytest.mark.parametrize("modo,situacion,hasta,esperado", [
    ("verificacion", "publicado", None, None),
    ("verificacion", "republicacion", None, None),
    ("verificacion", None, None, "no_publicado"),
    ("alta", "publicado", None, "verificado_en_otro_proceso"),
    ("alta", "republicacion", None, "verificado_en_otro_proceso"),
    ("alta", "no_revisar", "2026-11-10", "no_revisar"),
    ("alta", "no_revisar", "2026-11-09", None),
])
def test_motivo_total(modo, situacion, hasta, esperado):
    estado = {"producto": {"situacion": situacion, "hasta": hasta}} if situacion else {}
    assert requisitos.motivo_total(producto(), estado, "2026-11-09", modo) == esperado
    assert requisitos.motivo_total(producto(image=None), estado, "2026-11-09", modo) == "sin_imagen"
    assert requisitos.motivo_total(producto(store="ES"), estado, "2026-11-09", modo,
                                  stores=("US",)) == "tienda_no_admitida"


def test_chrome_alta_incluye_vencidos(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    monkeypatch.setattr(altas_chrome, "hora", lambda: "2026-11-09 00:01:00")
    catalog = [producto(s) for s in ("vencido", "vigente", "publicado", "sin_estado")]
    repo = tmp_path / "catalog.json"
    repo.write_text(json.dumps(catalog), encoding="utf-8")
    (tmp_path / "altas-pendientes.json").write_text(json.dumps([producto("pendiente")]), encoding="utf-8")
    publicacion.guardar(tmp_path, {
        s: publicacion._entrada("no_revisar" if s != "publicado" else "publicado", desde, "", s.upper())
        for s, desde in (("vencido", "2026-11-02"), ("vigente", "2026-11-03"), ("publicado", "2026-11-09"))})
    assert altas_chrome.asin_list(repo, tmp_path, pending_only=True).split() == [
        "VENCIDO:vencido", "PENDIENTE:pendiente"]


def test_rechazo_vence_a_7_dias(tmp_path):
    (tmp_path / "altas-rechazadas.json").write_text(json.dumps({
        "VENCIDO": {"fecha": "2026-11-02"}, "VIGENTE": {"fecha": "2026-11-03"}}), encoding="utf-8")
    assert rejected_asins(tmp_path, "2026-11-09") == {"VIGENTE"}


def test_chrome_verificacion_filtra_por_estado(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("PUBLICACION_MODO", raising=False)
    monkeypatch.setattr(altas_chrome, "hora", lambda: "2026-11-09 00:01:00")
    catalog = [producto(s) for s in ("publicado", "republicacion", "vigente", "nuevo")]
    repo = tmp_path / "catalog.json"
    repo.write_text(json.dumps(catalog), encoding="utf-8")
    publicacion.guardar(tmp_path, {
        s: publicacion._entrada(situacion, "2026-11-08", "", s.upper())
        for s, situacion in (("publicado", "publicado"), ("republicacion", "republicacion"),
                             ("vigente", "no_revisar"))})
    assert altas_chrome.asin_list(repo, tmp_path).split() == [
        "PUBLICADO:publicado", "REPUBLICACION:republicacion"]
    assert "motivos_salteo=no_publicado:1,no_revisar:1" in capsys.readouterr().err
