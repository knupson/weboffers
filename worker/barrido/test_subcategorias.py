from barrido.subcategorias import hojas_de


def test_hojas_usa_solo_hijas_con_id_y_nombre():
    arbol = {"children": [{"name": "Monitors", "node_id": "1292115011"},
                          {"name": "Any Department", "node_id": None},
                          {"name": "", "node_id": "123"}]}
    buenas, sin_id = hojas_de(arbol)
    assert buenas == [{"id": "1292115011", "name": "Monitors"}]
    assert len(sin_id) == 2
