import json

from tools import actualizar_mas_vendidos as m


def escribir(tmp_path):
    repo = tmp_path / "catalog.json"
    repo.write_text(json.dumps([
        {"slug": "toshiba", "ml": {"catalogId": "MLA1"}, "hot": "2026-11-02"},
        {"slug": "viejo", "ml": {"catalogId": "MLA9"}, "hot": "2026-11-02"},
        {"slug": "sin-ml"},
    ]), encoding="utf-8")
    (tmp_path / "catalog-auto.json").write_text(json.dumps([
        {"slug": "jbl-charge-6", "ml": {"catalogId": "MLA2"}},
        {"slug": "otro", "ml": {"catalogId": "MLA3"}},
    ]), encoding="utf-8")
    return repo


def test_marca_los_destacados_de_hoy_del_repo_y_de_las_altas(tmp_path, capsys):
    repo = escribir(tmp_path)
    obtener = lambda fallas: fallas.append({"categoria": "MLA416199"}) or {"MLA1": "MLA430598", "MLA2": "MLA431428"}
    assert m.main(tmp_path, repo, obtener, hoy="2026-11-12") == 0
    guardado = json.loads((tmp_path / "mas-vendidos.json").read_text(encoding="utf-8"))
    assert guardado == {"fecha": "2026-11-12", "slugs": ["jbl-charge-6", "toshiba"], "destacadosMl": 2,
                        "categoriasConError": 1}
    assert "MAS_VENDIDOS_OK fecha=2026-11-12 slugs=2" in capsys.readouterr().out


def test_sin_destacados_no_escribe_nada(tmp_path, capsys):
    repo = escribir(tmp_path)
    (tmp_path / "mas-vendidos.json").write_text('{"fecha": "2026-11-05", "slugs": ["x"]}', encoding="utf-8")
    assert m.main(tmp_path, repo, lambda fallas: {}, hoy="2026-11-12") == 1
    # El archivo anterior queda como estaba: el sitio lo descarta solo por tener más de 7 días.
    assert json.loads((tmp_path / "mas-vendidos.json").read_text())["fecha"] == "2026-11-05"
    assert "MAS_VENDIDOS_FALLA" in capsys.readouterr().out


def test_calcular_ignora_entradas_sin_ficha():
    assert m.calcular([{"slug": "a"}, {"slug": "b", "ml": {"catalogId": "MLA1"}}, "basura"], {"MLA1": "x"}) == ["b"]
