import pytest
pytest.importorskip('curl_cffi', reason='dependencias del barrido: correr en su contenedor')
from .bootstrap import load_vendor
from .amazon_source import parse_search_page
from .refinements import discover_refinements, load_refinements


def test_cache_evitar_preconsulta(tmp_path, fixture_dir):
    load_vendor()
    from amazon import sites
    calls = []
    page = parse_search_page((fixture_dir / "us_search.html").read_text(encoding="utf-8"), sites.site("US"))
    def fetch():
        calls.append(1)
        return page
    context = dict(date="2026-11-07", store="US", node="fixture", language="en_US", destination="AR")
    assert load_refinements(tmp_path, context, fetch)["new"] == "p_n_condition-type:FIXTURE_NEW"
    load_refinements(tmp_path, context, fetch)
    assert len(calls) == 1
    load_refinements(tmp_path, context, fetch, refresh=True)
    assert len(calls) == 2


def test_condicion_ausente_no_se_omite():
    with pytest.raises(ValueError, match="condición nueva"):
        discover_refinements({"refinements": []})
