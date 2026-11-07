import pytest
from .bootstrap import load_vendor
from .amazon_source import build_search_params, parse_search_page, next_page, SourceError


def test_url_nodo_precio_condicion_envio():
    params = build_search_params("FIXTURE_NODE", 2, ("100", "400"), {"new": "p_n_condition-type:FIXTURE_NEW", "ar": "fixture_ship:FIXTURE_AR"})
    assert params == {"rh": "n:FIXTURE_NODE,p_n_condition-type:FIXTURE_NEW,fixture_ship:FIXTURE_AR", "fs": "true", "page": "2", "low-price": "100", "high-price": "400"}


@pytest.mark.parametrize("store,filename,currency", [("US", "us_search.html", "USD"), ("ES", "es_search.html", "EUR")])
def test_conserva_campos_y_html(fixture_dir, store, filename, currency):
    load_vendor()
    from amazon import sites
    result = parse_search_page((fixture_dir / filename).read_text(encoding="utf-8"), sites.site(store))
    row = result["results"][0]
    assert row["price"]["currency"] == currency
    assert row["price"]["amount"] == 199.99
    assert row["has_variations"] is True and row["variations_text"]
    assert "data-component-type" in row["card_html"]
    assert next_page(result, 1) == (2 if store == "US" else None)


def test_siguiente_pagina():
    assert next_page({"has_next": True}, 5) == 6
    assert next_page({"has_next": False}, 5) is None
    with pytest.raises(SourceError, match="metadatos"):
        next_page({}, 1)
    with pytest.raises(SourceError, match="distinta"):
        next_page({"current_page": 1}, 2)
