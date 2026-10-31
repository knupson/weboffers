"""Casos de identidad y salida, sin red."""
import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import match_candidates as match  # noqa: E402
import apply_candidates  # noqa: E402


def amazon(**changes):
    row = {"asin": "B000000001", "store": "US", "amazonTitle": "Samsung 990 PRO 1TB MZ-V9P1T0B",
           "brand": "Samsung", "amazonCategory": "Data Storage", "amazonPriceUsd": 100,
           "ml": [{"catalogId": "MLA123", "name": "Samsung 990 PRO 1TB", "minPrice": 200000, "itemId": "MLA456"}]}
    row.update(changes)
    return row


def product(name="Samsung 990 PRO 1TB", **attrs):
    fields = {"BRAND": "Samsung", "MODEL": "990 PRO", "ALPHANUMERIC_MODEL": "MZ-V9P1T0B", "CAPACITY": "1 TB"}
    fields.update(attrs)
    return {"name": name, "attributes": [{"id": key, "value_name": val} for key, val in fields.items() if val is not None]}


@pytest.fixture(autouse=True)
def api(monkeypatch):
    get = Mock(return_value=product())
    monkeypatch.setattr(match.ml_prices, "get_json", get)
    monkeypatch.setattr(match.ml_prices, "pause", Mock())
    monkeypatch.setattr(requests, "get", Mock(side_effect=AssertionError("No se permite red en tests")))
    return get


def test_exact_match_and_apply_shape(api):
    result = match.match_products([amazon()], 1575)
    row = result["accepted"][0]
    assert row["evidence"]["brand"] == "samsung"
    assert row["evidence"]["model"] == ["990pro", "mzv9p1t0b"]
    assert row["evidence"]["capacity"] == ["1000gb"]
    assert row["summary"] == ""
    assert row["mlPrice"] == 200000
    assert row["name"] == "Samsung 990 PRO 1TB"
    assert result["summary"] == {"accepted": 1, "doubtful": 0, "rejected": 0, "byCategory": {"Almacenamiento": 1}}
    completed = {**row, "summary": "SSD de 1 TB."}
    assert apply_candidates.validate_and_build_entries([{"category": "Almacenamiento"}], [completed])[0]["slug"] == row["slug"]
    api.assert_called_once_with("/products/MLA123")


@pytest.mark.parametrize("ml,reason", [
    (product("Samsung 990 PRO 2TB", CAPACITY="2TB", ALPHANUMERIC_MODEL="MZ-V9P2T0B"), "capacidad"),
    (product("Samsung 990 EVO 1TB", MODEL="990 EVO", ALPHANUMERIC_MODEL=None), "familia"),
    (product(BRAND="Bestoss"), "marca"),
    (product("Case for Samsung 990 PRO 1TB"), "accesorio"),
])
def test_explicit_mismatch_rejected(api, ml, reason):
    api.return_value = ml
    result = match.match_products([amazon()], 1575)
    assert len(result["rejected"]) == 1
    assert reason in result["rejected"][0]["reason"]


def test_lexar_vs_bestoss(api):
    api.return_value = product("Bestoss NM790 1TB", BRAND="Bestoss", MODEL="NM790", ALPHANUMERIC_MODEL=None)
    result = match.match_products([amazon(brand="Lexar", amazonTitle="Lexar NM790 1TB")], 1575)
    assert result["rejected"][0]["reason"] == "marca distinta"


def test_variant_mini_doubtful(api):
    api.return_value = product("Razer Huntsman V3 Pro Mini", BRAND="Razer", MODEL="Huntsman V3 Pro Mini", ALPHANUMERIC_MODEL=None, CAPACITY=None)
    result = match.match_products([amazon(brand="Razer", amazonTitle="Razer Huntsman V3 Pro", amazonCategory="Keyboards")], 1575)
    assert "variante" in result["doubtful"][0]["reason"]


@pytest.mark.parametrize("price", [59000, 300001])
def test_bad_ratio(api, price):
    row = amazon()
    row["ml"][0]["minPrice"] = price
    assert match.match_products([row], 1000)["rejected"][0]["reason"] == "precio fuera de rango"


@pytest.mark.parametrize("price", [60000, 300000])
def test_ratio_boundaries(api, price):
    row = amazon()
    row["ml"][0]["minPrice"] = price
    assert len(match.match_products([row], 1000)["accepted"]) == 1


def test_amazon_accessory(api):
    result = match.match_products([amazon(amazonTitle="Samsung case for 990 PRO 1TB MZ-V9P1T0B")], 1575)
    assert result["rejected"][0]["reason"] == "accesorio"


def test_wd_alias_and_sn_family(api):
    api.return_value = product("Western Digital SN850X 1TB", BRAND="Western Digital", MODEL="SN850X", ALPHANUMERIC_MODEL=None)
    row = amazon(brand="WD", amazonTitle="WD SN850X 1000 GB")
    assert match.match_products([row], 1575)["accepted"][0]["evidence"]["brand"] == "western digital"
    row["amazonTitle"] = "WD SN770 1TB"
    assert "modelo" in match.match_products([row], 1575)["rejected"][0]["reason"]


@pytest.mark.parametrize("category,expected", [
    ("Headphones & Earbuds", "Audio y video"), ("Computer Components", "Componentes"),
    ("Keyboards, Mice & Input Devices", "Periféricos"), ("Smartwatches", "Relojes"),
    ("Mini Desktop PCs", "Mini PCs"), ("Networking Products", "Redes"),
    ("Tablets", "Tablets y lectores"), ("Digital Cameras", "Cámaras"),
    ("Video Games", "Gaming"), ("Portable Power Banks", "Carga y energía"),
    ("Kitchen & Dining", "Cocina"), ("Personal Care", "Cuidado personal"),
    ("Tools & Home Improvement", "Herramientas"), ("Sports & Outdoors", "Deportes"),
    ("Toys & Games", "Juguetes"), ("Musical Instruments", "Instrumentos"),
    ("Office Products", "Oficina"), ("Cell Phones & Accessories", "Celulares"),
    ("Baby", "Bebés"), ("Pet Supplies", "Mascotas"), ("Beauty", "Belleza"),
    ("Automotive", "Auto"), ("Patio, Lawn & Garden", "Jardín"), ("Health & Household", "Salud"),
    ("Home Decor", "Hogar"), ("Monitors", "Monitores"), ("Books", None), ("Electronics", None),
])
def test_category_mapping(category, expected):
    assert match.category_for(category) == expected


@pytest.mark.parametrize("category", ["Herramientas", "Deportes", "Juguetes", "Instrumentos", "Oficina", "Celulares", "Bebés", "Mascotas", "Belleza", "Auto", "Jardín", "Salud"])
def test_new_categories_apply_and_art(category):
    row = match.match_products([amazon(amazonCategory=category)], 1575)["accepted"][0]
    apply_candidates.validate_and_build_entries([], [{**row, "summary": "Descripción pendiente."}])
    config = (ROOT / "src" / "config.ts").read_text(encoding="utf-8")
    assert f'{category}: "/art/cat-hogar.webp", // TODO: ilustración propia' in config


def test_unknown_category_is_doubtful(api):
    result = match.match_products([amazon(amazonCategory="Miscellaneous")], 1575)
    assert result["doubtful"][0]["reason"] == "categoría"
    assert result["doubtful"][0]["category"] == ""


def test_unique_slugs_and_cache(api):
    initial = match.match_products([amazon()], 1575)["accepted"][0]["slug"]
    api.reset_mock()
    result = match.match_products([amazon(), amazon(asin="B000000002")], 1575, [{"slug": initial}])
    assert [row["slug"] for row in result["accepted"]] == [initial + "-2", initial + "-3"]
    assert all(apply_candidates.is_kebab_case(row["slug"]) for row in result["accepted"])
    api.assert_called_once()
    assert match.ml_prices.pause.call_count == 2


@pytest.mark.parametrize("value,expected", [("1 tb", "1000gb"), ("1TB", "1000gb"), ("1000gb", "1000gb"),
    ('27"', "27in"), ("27 pulgadas", "27in"), ("27 in", "27in"), ("40 mm", "40mm"),
    ("5000 mAh", "5000mah"), ("65 W", "65w"), ("ÁUDIO_wf-1000xm5/negro", "audio wf 1000xm5 negro")])
def test_normalization(value, expected):
    assert match.normalize(value) == expected


@pytest.mark.parametrize("value", ["WF-1000XM5", "WF 1000XM5", "wf_1000xm5", "wf/1000xm5"])
def test_model_separators(value):
    assert match.model_tokens(value) == {"wf1000xm5"}


@pytest.mark.parametrize("ml", [product(MODEL=None, ALPHANUMERIC_MODEL=None, name="Samsung SSD 1TB"), {}, {"attributes": [None, {"id": "BRAND"}, "ruido"]}])
def test_missing_attributes_doubtful(api, ml):
    api.return_value = ml
    assert len(match.match_products([amazon()], 1575)["doubtful"]) == 1


def test_api_error_cached_and_doubtful(api):
    api.side_effect = requests.Timeout()
    result = match.match_products([amazon(), amazon(asin="B000000002")], 1575)
    assert len(result["doubtful"]) == 2
    api.assert_called_once()
    match.ml_prices.pause.assert_called_once()


def test_candidates_in_order_accept_after_doubt_and_rejection(api):
    row = amazon()
    row["ml"] = [{**row["ml"][0], "catalogId": f"MLA{i}"} for i in range(4)]
    api.side_effect = [product(BRAND="Bestoss"), product(MODEL=None, ALPHANUMERIC_MODEL=None, name="Samsung SSD 1TB"), product()]
    result = match.match_products([row], 1575)
    assert result["accepted"][0]["catalogId"] == "MLA2"
    assert api.call_count == 3


def test_best_doubt_and_no_candidates(api):
    row = amazon(amazonCategory="Unknown")
    row["ml"].append({**row["ml"][0], "catalogId": "MLA789"})
    api.side_effect = [{}, product()]
    result = match.match_products([row, amazon(asin="B000000002", ml=[])], 1575)
    assert result["doubtful"][0]["catalogId"] == "MLA789"
    assert result["rejected"][0]["reason"] == "sin candidatos"


def test_structured_capacity_and_size_mismatch(api):
    ml = product("Samsung SM-R900 44mm", MODEL="SM-R900", CAPACITY=None, ALPHANUMERIC_MODEL=None)
    ml["attributes"].append({"id": "CASE_SIZE", "value_struct": {"number": 44, "unit": "mm"}})
    api.return_value = ml
    row = amazon(amazonTitle="Samsung SM-R900 40mm")
    assert "tamaño" in match.match_products([row], 1575)["rejected"][0]["reason"]


def test_cli_atomic_output_limit_rates_and_progress(api, monkeypatch, tmp_path, capsys):
    source, output, catalog = (tmp_path / name for name in ("input.json", "output.json", "catalog.json"))
    source.write_text(json.dumps([amazon(asin=f"B{i:09}") for i in range(52)]), encoding="utf-8")
    catalog.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(match, "default_catalog_path", lambda: catalog)
    get_rates = Mock(return_value={"mep": 1575})
    monkeypatch.setattr(match.rates, "get_rates", get_rates)
    atomic = Mock(wraps=match.publish.write_atomic)
    monkeypatch.setattr(match.publish, "write_atomic", atomic)
    assert match.main(["--input", str(source), "--output", str(output), "--limit", "50"]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["summary"]["accepted"] == 50
    assert "Procesados 50/50" in capsys.readouterr().out
    atomic.assert_called_once()
    get_rates.assert_called_once()
    api.assert_called_once()


@pytest.mark.parametrize("mep", ["0", "-1", "nan", "inf"])
def test_cli_invalid_mep_no_fetch(api, mep):
    assert match.main(["--mep", mep]) == 1
    api.assert_not_called()


def test_cli_missing_rate(api, monkeypatch):
    monkeypatch.setattr(match.rates, "get_rates", lambda: None)
    assert match.main([]) == 1
    api.assert_not_called()


def test_clean_name(api):
    api.return_value = product("  Samsung 990 PRO 1TB | Envío gratis  ")
    assert match.match_products([amazon()], 1575)["accepted"][0]["name"] == "Samsung 990 PRO 1TB"


def test_wd_black_alias_is_not_a_color(api):
    api.return_value = product("Western Digital SN850X 1TB", BRAND="Western Digital", MODEL="SN850X", ALPHANUMERIC_MODEL=None)
    assert match.match_products([amazon(brand="WD_BLACK", amazonTitle="WD_BLACK SN850X 1TB")], 1575)["accepted"]


@pytest.mark.parametrize("left,right", [("Pro", "Pro Mini"), ("Pro", "Pro 2-pack"), ("Pro", "Pro Renewed"), ("Pro", "Pro Kit")])
def test_variants_with_shared_model_are_doubtful(api, left, right):
    api.return_value = product(f"Samsung AX100 {right} 1TB", MODEL="AX100", ALPHANUMERIC_MODEL=None)
    result = match.match_products([amazon(amazonTitle=f"Samsung AX100 {left} 1TB")], 1575)
    assert "variante" in result["doubtful"][0]["reason"]


def test_color_difference_doubtful(api):
    api.return_value = product("Samsung 990 PRO 1TB", COLOR="Blanco")
    result = match.match_products([amazon(amazonTitle="Samsung 990 PRO 1TB MZ-V9P1T0B Black")], 1575)
    assert "color" in result["doubtful"][0]["reason"]


def test_attribute_value_list_and_malformed_values(api):
    ml = product()
    ml["attributes"] = [
        {"id": "BRAND", "values": [{"name": "Samsung"}, None]},
        {"id": "MODEL", "values": [{"name": "990 PRO"}]},
        {"id": "ALPHANUMERIC_MODEL", "value_name": "MZ-V9P1T0B", "values": 123},
        {"id": "CAPACITY", "value_struct": {"number": 1, "unit": "TB"}},
        None, "ruido", {"id": None},
    ]
    api.return_value = ml
    assert match.match_products([amazon()], 1575)["accepted"]


@pytest.mark.parametrize("price", [None, True, -1, float("nan"), float("inf")])
def test_invalid_price_doubtful_and_json_safe(api, price):
    row = amazon()
    row["ml"][0]["minPrice"] = price
    result = match.match_products([row], 1575)
    assert "precio" in result["doubtful"][0]["reason"]
    json.dumps(result, allow_nan=False)


def test_nonmatching_model_even_with_variant_difference(api):
    api.return_value = product("Samsung BY200 Mini 1TB", MODEL="BY200", ALPHANUMERIC_MODEL=None)
    assert match.match_products([amazon(amazonTitle="Samsung AX100 1TB")], 1575)["rejected"]


def test_missing_capacity_is_doubtful(api):
    api.return_value = product("Samsung 990 PRO", CAPACITY=None)
    assert "capacidad" in match.match_products([amazon()], 1575)["doubtful"][0]["reason"]


def test_brand_falls_back_to_first_word(api):
    assert match.match_products([amazon(brand="")], 1575)["accepted"][0]["brand"] == "Samsung"
