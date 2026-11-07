import json
import pytest
from .ml_source import MLSource
from .config import Config
from .amazon_source import SourceError


def test_highlights_product_precio_ars_mep_excluye_usado_cbt(fixture_dir):
    calls = []
    def get(path, params=None):
        calls.append((path, params))
        name = "ml_highlights.json" if path.startswith("/highlights") else "ml_items.json" if path.endswith("/items") else "ml_product.json"
        return json.loads((fixture_dir / name).read_text(encoding="utf-8"))
    source = MLSource("2026-11-07", {"value": .001, "source": "fixture", "observed_at": "2026-11-07T12:00:00-03:00"}, Config(), get=get, sleep=lambda _: None)
    rows = source.fetch_search_page({"id": "MLAFIXTURE", "name": "Prueba"}, 1, "2026-11-07T12:00:00-03:00")["products"]
    assert len(rows) == 1 and rows[0]["price_usd"] == 200 and rows[0]["eligible"]
    assert rows[0]["raw"]["selected_offer"]["item_id"] == "MLA1001"
    assert rows[0]['raw']['highlights'] == json.loads((fixture_dir / 'ml_highlights.json').read_text())['content'][0]
    page = source.fetch_search_page({'id': 'MLAFIXTURE', 'name': 'Prueba'}, 1, '2026-11-07T12:00:00-03:00')
    assert page['raw']['highlights']['content']
    source.fetch_search_page({"id": "MLAFIXTURE2", "name": "Otra"}, 1, "2026-11-07T12:00:00-03:00")
    assert len([path for path, _ in calls if path.endswith("/items")]) == 1
    assert not any("/sites/" in path for path, _ in calls)


def test_walk_categories_excluye_subarbol():
    calls = []
    def get(path, params=None):
        calls.append(path)
        return {"children_categories": [{"id": "MLALEAF", "name": "Hoja"}, {"id": "MLAEXCLUDE", "name": "Excluida"}]} if path.endswith("ROOT") else {"children_categories": []}
    source = MLSource("fixture", {}, Config(), get=get, sleep=lambda _: None)
    nodes = source.walk_categories({"nodes": [{"id": "MLAROOT", "name": "Raíz", "kind": "root"}], "exclude": ["MLAEXCLUDE"]})
    assert [n["id"] for n in nodes] == ["MLALEAF"]
    assert not any("EXCLUDE" in path for path in calls)


def test_error_categoria_visible():
    source = MLSource("fixture", {}, Config(), get=lambda *a, **kw: {}, sleep=lambda _: None)
    with pytest.raises(SourceError, match="sin content"):
        source.fetch_search_page({"id": "MLAFIXTURE", "name": "Prueba"}, 1, "fixture")


def test_ofertas_paginadas():
    calls = []
    def get(path, params=None):
        if not path.endswith("/items"):
            return {"name": "Prueba"}
        offset = params["offset"]
        calls.append(offset)
        return {"results": [{"id": str(offset)}], "paging": {"total": 2}}
    source = MLSource("fixture", {}, Config(), get=get, sleep=lambda _: None)
    assert len(source.fetch_product_offers("FIXTURE")[1]) == 2
    assert calls == [0, 1]
