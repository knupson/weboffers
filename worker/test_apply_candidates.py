import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import apply_candidates  # noqa: E402


INITIAL_CATALOG = [
    {
        "asin": "B0BHJF2VRN",
        "store": "US",
        "slug": "samsung-990-pro-1tb",
        "name": "Samsung SSD 990 PRO 1TB",
        "brand": "Samsung",
        "category": "Almacenamiento",
        "summary": "SSD NVMe 1 TB.",
        "verified": True,
        "ml": {
            "price": 620496,
            "url": "https://www.mercadolibre.com.ar/p/MLA2073440644?pdp_filters=item_id%3AMLA3050478612&matt_word=ale_benzoni&matt_tool=58527537",
            "checked": "2026-10-30",
            "catalogId": "MLA2073440644",
        },
    },
    {
        "asin": "",
        "store": "US",
        "slug": "producto-sin-asin",
        "name": "Mouse Gamer",
        "brand": "Logitech",
        "category": "Periféricos",
        "summary": "Mouse inalámbrico.",
        "verified": False,
    },
]


def make_candidate(**overrides):
    base = {
        "asin": "B09V3KXJPB",
        "store": "US",
        "catalogId": "MLA1999888",
        "itemId": "MLA1456789012",
        "mlPrice": 489999,
        "slug": "samsung-990-pro-2tb",
        "name": "Samsung SSD 990 PRO 2TB PCIe 4.0 M.2",
        "brand": "Samsung",
        "category": "Almacenamiento",
        "summary": "SSD interno NVMe de 2 TB PCIe 4.0 con lectura de hasta 7.450 MB/s.",
    }
    base.update(overrides)
    return base


def write_temp_catalog(tmp_path):
    cat = tmp_path / "catalog.json"
    cat.write_text(json.dumps(INITIAL_CATALOG, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return cat


def test_apply_candidates_appends_with_exact_shape_and_formatting(tmp_path):
    cat_path = write_temp_catalog(tmp_path)
    candidates_path = tmp_path / "approved.json"
    candidates_path.write_text(json.dumps([make_candidate()], ensure_ascii=False), encoding="utf-8")

    rc = apply_candidates.main([
        str(candidates_path),
        "--catalog",
        str(cat_path),
        "--today",
        "2026-10-31",
    ])
    assert rc == 0

    raw_text = cat_path.read_text(encoding="utf-8")
    assert raw_text.endswith("\n")
    assert "\n  {\n" in raw_text  # indent=2

    updated = json.loads(raw_text)
    assert len(updated) == 3
    added = updated[2]
    assert added == {
        "asin": "B09V3KXJPB",
        "store": "US",
        "slug": "samsung-990-pro-2tb",
        "name": "Samsung SSD 990 PRO 2TB PCIe 4.0 M.2",
        "brand": "Samsung",
        "category": "Almacenamiento",
        "summary": "SSD interno NVMe de 2 TB PCIe 4.0 con lectura de hasta 7.450 MB/s.",
        "verified": True,
        "ml": {
            "price": 489999,
            "url": (
                "https://www.mercadolibre.com.ar/p/MLA1999888"
                "?pdp_filters=item_id%3AMLA1456789012&matt_word=ale_benzoni&matt_tool=58527537"
            ),
            "checked": "2026-10-31",
            "catalogId": "MLA1999888",
        },
    }
    for forbidden in ("image", "listPrice", "shipsToAr", "verdict"):
        assert forbidden not in added


def test_dry_run_prints_changes_and_does_not_modify_catalog(tmp_path, capsys):
    cat_path = write_temp_catalog(tmp_path)
    before = cat_path.read_text(encoding="utf-8")

    added = apply_candidates.apply_candidates(
        cat_path,
        [make_candidate()],
        dry_run=True,
        today="2026-10-31",
    )
    assert len(added) == 1
    assert cat_path.read_text(encoding="utf-8") == before
    out = capsys.readouterr().out
    assert "[DRY-RUN]" in out
    assert "samsung-990-pro-2tb" in out


@pytest.mark.parametrize(
    "override,expected_msg",
    [
        ({"slug": "samsung-990-pro-1tb"}, "el slug ya existe en el catálogo"),
        ({"asin": "B0BHJF2VRN"}, "el ASIN 'B0BHJF2VRN' ya existe en el catálogo"),
        ({"category": " Electrodomésticos "}, "la categoría 'Electrodomésticos' no existe"),
        ({"slug": "Samsung_990_Pro"}, "formato kebab-case"),
        ({"slug": "-guion-inicial"}, "formato kebab-case"),
        ({"slug": "guion-final-"}, "formato kebab-case"),
        ({"slug": "con--doble-guion"}, "formato kebab-case"),
        ({"mlPrice": 0}, "mlPrice inválido"),
        ({"store": "UK"}, "la tienda 'UK' no es válida"),
        ({"store": "us"}, "la tienda 'us' no es válida"),
    ],
)
def test_validation_rejects_invalid_candidates_and_leaves_catalog_untouched(tmp_path, override, expected_msg):
    cat_path = write_temp_catalog(tmp_path)
    before = cat_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match=expected_msg):
        apply_candidates.apply_candidates(
            cat_path,
            [make_candidate(**override)],
            today="2026-10-31",
        )
    assert cat_path.read_text(encoding="utf-8") == before


def test_validation_rejects_duplicates_within_candidate_batch(tmp_path):
    cat_path = write_temp_catalog(tmp_path)
    c1 = make_candidate(slug="item-uno", asin="B000000001")
    c2_same_slug = make_candidate(slug="item-uno", asin="B000000002")
    with pytest.raises(ValueError, match="slug está duplicado"):
        apply_candidates.apply_candidates(cat_path, [c1, c2_same_slug], today="2026-10-31")

    c2_same_asin = make_candidate(slug="item-dos", asin="B000000001")
    with pytest.raises(ValueError, match="ASIN 'B000000001' está duplicado"):
        apply_candidates.apply_candidates(cat_path, [c1, c2_same_asin], today="2026-10-31")


def test_validation_accepts_us_and_es_and_rejects_uk_store(tmp_path):
    cat_path = write_temp_catalog(tmp_path)
    before = cat_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="la tienda 'UK' no es válida"):
        apply_candidates.apply_candidates(
            cat_path,
            [make_candidate(store="UK")],
            today="2026-10-31",
        )
    assert cat_path.read_text(encoding="utf-8") == before

    added = apply_candidates.apply_candidates(
        cat_path,
        [
            make_candidate(slug="item-us", asin="B000000011", store="US"),
            make_candidate(slug="item-es", asin="B000000012", store="ES"),
        ],
        today="2026-10-31",
    )
    assert [entry["store"] for entry in added] == ["US", "ES"]

