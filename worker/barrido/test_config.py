import pytest
from .config import Config, load_config, validate_categories
from .models import normalize_product


def test_exclusiones_y_raices():
    body = load_config()
    assert set(body["stores"]) == {"US", "ES", "ML"}
    assert body["stores"]["US"]["nodes"][0]["kind"] == "root"
    assert validate_categories({"version": 1, "stores": {"US": {"nodes": [], "exclude": ["123"]}}})


@pytest.mark.parametrize("options", [{"pause": -1}, {"min_usd": 500}, {"max_usd": float("nan")}, {"consecutive_blocks": 0}])
def test_config_invalida_falla(options):
    with pytest.raises(ValueError):
        Config(**options)


def test_schema_evidencia_sin_precio():
    row = normalize_product({}, store="US", identity="FIXTURE", stamp="2026-11-07T10:00:00-03:00",
        currency="USD", rate={"value": 1, "source": "fixture", "observed_at": "2026-11-07T10:00:00-03:00"},
        provenance={"category_id": "fixture", "category_name": "Prueba", "page": 1, "url": "fixture"},
        shipping={"shipping_class": "desconocido"})
    assert row["price"] is None and row["price_usd"] is None and not row["eligible"]
    assert row["has_variations"] is None and row["variations"] is None
    assert set(row) == set("schema_version store id observed_at date title currency price price_usd exchange_rate condition shipping_text shipping_class located_ar has_variations variations_text variations known eligible rejection_reasons provenance raw".split())
