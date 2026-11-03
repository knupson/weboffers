"""El Reel comparte las restricciones de publicación del sitio."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

spec = spec_from_file_location("audit_reel", Path(__file__).resolve().parents[1] / "brand/reel/hacer_reel.py")
reel = module_from_spec(spec)
spec.loader.exec_module(reel)


@pytest.mark.parametrize("checked,expected", [("2026-10-20", True), ("2026-10-19", False),
                                             ("2026-11-04", False), (None, False)])
def test_reel_requires_dated_confirmation(checked, expected):
    product = {"slug": "a", "asin": "A", "verified": True, "image": "/a.webp",
               "shipsToAr": {"freeShipping": True, "checked": checked}}
    ml = {"a": {"price": 500000, "checked": "2026-11-03"}}
    amazon = {"a": {"amount": 200, "currency": "USD", "checked": "2026-11-03"}}
    assert bool(reel.comparables(ml, amazon, [product], "2026-11-03", 1000, 1.08)) is expected


def test_survey_denial_overrides_catalog():
    product = {"slug": "a", "asin": "A", "verified": True, "image": "/a.webp",
               "shipsToAr": {"freeShipping": True, "checked": "2026-11-03"}}
    amazon = {"a": {"amount": 200, "currency": "USD", "checked": "2026-11-03",
                    "shipsToAr": {"ships": False, "free": False, "checked": "2026-11-03"}}}
    assert not reel.comparables({"a": {"price": 500000, "checked": "2026-11-03"}}, amazon,
                                [product], "2026-11-03", 1000, 1.08)


def test_reel_uses_cached_survey(monkeypatch):
    monkeypatch.setattr(reel, "leer", lambda path: {
        "ml-prices.json": {"date": "2026-11-03", "items": {}},
        "amazon-prices.json": {"date": "2026-11-03", "items": {"a": {"amount": 200}},
                               "arShipping": {"a": {"ships": True, "free": True, "checked": "2026-11-01"}}},
        "catalog.json": [],
    }[path.name])
    assert reel.datos_hoy("2026-11-03")[1]["a"]["shipsToAr"]["checked"] == "2026-11-01"
