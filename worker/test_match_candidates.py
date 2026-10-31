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
    monkeypatch.setattr(requests.sessions.Session, "request", Mock(side_effect=AssertionError("No se permite red en tests")))
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


@pytest.mark.parametrize("price", [59000, 600001])
def test_bad_ratio(api, price):
    row = amazon()
    row["ml"][0]["minPrice"] = price
    assert match.match_products([row], 1000)["rejected"][0]["reason"] == "precio fuera de rango"


@pytest.mark.parametrize("price", [60000, 300000, 500000, 600000])
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


def cached_product(name, brand, model, **attrs):
    """Formato reducido del caché real, sin atributos ajenos al caso."""
    return {"name": name, "attributes": [{"id": key, "name": key, "value": value}
            for key, value in {"BRAND": brand, "MODEL": model, **attrs}.items()]}


def cached_match(title, ml, brand="Samsung", category="Data Storage"):
    return match.match_products([amazon(amazonTitle=title, brand=brand, amazonCategory=category)],
                                1575, products_cache={"MLA123": ml})


def test_cache_complete_is_offline_and_does_not_mutate(api):
    cache = {"MLA123": cached_product("Samsung T9 1TB", "Samsung", "T9", CAPACITY="1TB")}
    before = json.dumps(cache)
    assert match.match_products([amazon(amazonTitle="Samsung T9 1TB")], 1575, products_cache=cache)["accepted"]
    assert json.dumps(cache) == before
    api.assert_not_called()
    match.ml_prices.pause.assert_not_called()


def test_partial_cache_fetches_only_missing_once(api):
    rows = [amazon(asin=f"B{i:09}") for i in range(3)]
    rows[1]["ml"][0]["catalogId"] = "MLA789"
    rows[2]["ml"][0]["catalogId"] = "MLA789"
    assert len(match.match_products(rows, 1575, products_cache={"MLA123": product()})["accepted"]) == 3
    api.assert_called_once_with("/products/MLA789")
    match.ml_prices.pause.assert_called_once()


def test_empty_cached_product_is_not_fetched_again(api):
    assert match.match_products([amazon()], 1575, products_cache={"MLA123": {}})["doubtful"]
    api.assert_not_called()


@pytest.mark.parametrize("cache", [[], {"MLA123": None}, {"MLA123": []}])
def test_invalid_products_cache(cache):
    with pytest.raises(ValueError, match="caché"):
        match.match_products([amazon()], 1575, products_cache=cache)


def test_cli_products_cache_without_credentials(api, monkeypatch, tmp_path):
    for key in ("ML_CLIENT_ID", "ML_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    source, cache, output = (tmp_path / name for name in ("source.json", "cache.json", "result.json"))
    source.write_text(json.dumps([amazon()]), encoding="utf-8")
    cache.write_text(json.dumps({"MLA123": product()}), encoding="utf-8")
    monkeypatch.setattr(match.rates, "get_rates", Mock(side_effect=AssertionError("No consultar cotización")))
    assert match.main(["--input", str(source), "--products-cache", str(cache), "--output", str(output), "--mep", "1575"]) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["accepted"] == 1
    api.assert_not_called()


def test_cli_invalid_cache(api, tmp_path):
    source, cache = tmp_path / "source.json", tmp_path / "cache.json"
    source.write_text("[]", encoding="utf-8")
    cache.write_text("[]", encoding="utf-8")
    assert match.main(["--input", str(source), "--products-cache", str(cache), "--mep", "1575"]) == 1
    api.assert_not_called()


def test_import_without_network_or_credentials():
    import os
    import subprocess
    script = "import socket; deny=lambda *a, **k: (_ for _ in ()).throw(AssertionError('Sin red')); socket.socket.connect=deny; socket.socket.connect_ex=deny; socket.getaddrinfo=deny; import match_candidates"
    env = {key: value for key, value in os.environ.items() if key not in {"ML_CLIENT_ID", "ML_CLIENT_SECRET"}}
    completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT / "tools", env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("left,right", [
    ("Amazon", "Kindle"), ("Amazon", "Echo"), ("Amazon", "Fire"), ("Blink", "Amazon"),
    ("Ring", "Amazon"), ("eero", "Amazon"), ("WD_BLACK", "Western Digital"),
    ("HP", "Hewlett-Packard"), ("HP Inc.", "HP"), ("TP", "TP-Link"),
    ("GL.iNet", "Gl. Inet"), ("Logitech G", "Logitech"), ("soundcore", "Anker"),
])
def test_real_brand_aliases(left, right):
    # La equivalencia de marca nunca debe bastar para aceptar otro modelo.
    assert match.brand_key(left) == match.brand_key(right)
    ml = cached_product(f"{right} ZX200 1TB", right, "ZX200", CAPACITY="1TB")
    assert cached_match(f"{left} ZX100 1TB", ml, left)["rejected"]


@pytest.mark.parametrize("value,expected", [('27-inch', '27in'), ('16.1-inch', '16.1in'),
    ('7”', '7in'), ("7''", '7in'), ('2000 MB/s 1TB', '1000gb')])
def test_real_quantity_notation(value, expected):
    assert match.normalize(value) == expected


def test_cpu_supported_ram_and_cache_are_not_product_capacity():
    ml = cached_product("Procesador AMD Ryzen 7 9800X3D AM5", "AMD", "Ryzen 7 9800X3D",
                        MAX_RAM_MEMORY_SIZE_SUPPORTED="192 GB", CACHE="96 MB", TDP="120 W")
    assert cached_match("AMD Ryzen 7 9800X3D 8-Core Desktop Processor", ml, "AMD", "Computer Components")["accepted"]


def test_ssd_speed_is_not_capacity():
    ml = cached_product("Samsung T9 Portable 1TB Negro", "Samsung", "T9", CAPACITY="1TB")
    assert cached_match("Samsung T9 Portable SSD 1TB Up to 2,000 MB/s Black", ml)["accepted"]


@pytest.mark.parametrize("title,ml_name,model", [
    ("Razer Wolverine V2 Pro Wireless Black", "Razer Wolverine V2 Pro Wireless Negro", "Wolverine V2 Pro"),
    ("8Bitdo Ultimate 2 Bluetooth Controller Black", "8bitdo Ultimate 2 Bluetooth Controller Black", "Otros"),
    ("Beats Solo Buds Wireless Matte Black", "Beats Solo Buds Negro Mate", "Beats Solo Buds"),
])
def test_real_model_families(title, ml_name, model):
    brand = title.split()[0]
    assert cached_match(title, cached_product(ml_name, brand, model), brand, "Gaming")["accepted"]


def test_compatibility_platform_is_not_model():
    ml = cached_product("Scuf Omega Para PS5 Negro", "SCUF", "Omega")
    assert not cached_match("SCUF Reflex PS5 Controller Black", ml, "SCUF", "Gaming")["accepted"]


@pytest.mark.parametrize("title,name,model", [
    ("TP-Link AX3000 Range Extender RE715X", "TP-Link AX3000 Router", "AX3000"),
    ("TP-Link AX3000 Travel Router TL-WR3002X", "TP-Link TX50E AX3000 Adaptador", "TX50E"),
    ("TP-Link Archer AX73 AX5400", "TP-Link Archer AX72 Pro AX5400", "Archer AX72 Pro"),
])
def test_network_speed_class_never_proves_model(title, name, model):
    assert not cached_match(title, cached_product(name, "TP-Link", model), "TP", "Routers")["accepted"]


def test_wired_hero_is_not_wireless_lightspeed():
    ml = cached_product("Mouse Inalámbrico Logitech G502 Lightspeed Negro", "Logitech", "G502 Lightspeed")
    assert cached_match("Logitech G502 Hero Wired Gaming Mouse Black", ml, "Logitech", "Periféricos")["rejected"][0]["reason"] == "conectividad distinta"


@pytest.mark.parametrize("title,name,model", [
    ("Razer BlackShark V2 X Black", "Razer BlackShark V2 Negro", "BlackShark V2"),
    ("GameSir G7 Pro Wuchang Edition", "GameSir G7 Pro Shadow Ember", "G7 Pro"),
    ("Apple AirPods Max 2 Midnight", "Apple AirPods Max Plateado", "AirPods Max"),
    ("Turtle Beach Stealth 600 Headset White", "Turtle Beach Stealth 600 Gen 2 Blanco", "Stealth 600"),
    ("Razer Wolverine V2", "Razer BlackShark V2", "BlackShark V2"),
])
def test_editions_generations_and_families_are_not_interchangeable(title, name, model):
    brand = title.split()[0]
    assert not cached_match(title, cached_product(name, brand, model), brand, "Gaming")["accepted"]


@pytest.mark.parametrize("name", ["Libro: Echo Show", "Amazon Kindle User Guide", "Book: Samsung T9", "Samsung T9 Editorial Ejemplo"])
def test_books_are_rejected_even_with_shared_model(name):
    ml = cached_product(name, "Samsung", "T9")
    assert "libro" in cached_match("Samsung T9", ml)["rejected"][0]["reason"]


def test_headphone_jack_and_driver_size_are_not_capacity():
    ml = cached_product("Razer Blackshark V2 X Xbox Licensed Negro", "Razer", "Blackshark V2 X")
    assert cached_match("Razer BlackShark V2 X Xbox Headset Black 3.5mm Jack 50mm Drivers", ml, "Razer", "Gaming")["accepted"]


def test_lens_mount_and_packaging_suffix():
    ml = cached_product("Lente Sony FE 50mm F1.8 Negro", "Sony", "SEL50F18F")
    assert cached_match("Sony FE 50mm F1.8 Lens SEL50F18F/2 Black", ml, "Sony", "Lenses")["accepted"]
    assert "f1" not in match.model_tokens("F1.8")


def test_marketing_words_do_not_create_variants():
    ml = cached_product("JBL Go 5 Speaker Black", "JBL", "Go 5")
    assert cached_match("JBL Go 5 Ultra-portable Speaker Black", ml, "JBL", "Audio")["accepted"]


def test_blue_voice_is_not_headset_color():
    ml = cached_product("Logitech G733 Lightspeed Negro", "Logitech", "G733")
    assert cached_match("Logitech G733 Lightspeed Black | Blue VO!CE Mic", ml, "Logitech", "Gaming")["accepted"]


@pytest.mark.parametrize("left,right", [("Gray", "Gris"), ("Silver", "Plateado"), ("Purple", "Violeta")])
def test_translated_colors(left, right):
    ml = cached_product(f"Samsung T9 1TB {right}", "Samsung", "T9")
    assert cached_match(f"Samsung T9 1TB {left}", ml)["accepted"]


def test_unconfirmed_color_stays_doubtful():
    ml = cached_product("Samsung T9 1TB Blanco", "Samsung", "T9")
    assert cached_match("Samsung T9 1TB", ml)["doubtful"]


def test_best_rejected_candidate_is_auditable(api):
    row = amazon()
    row["ml"].append({**row["ml"][0], "catalogId": "MLA789", "minPrice": 10000})
    api.side_effect = [product(BRAND="Bestoss"), product()]
    rejected = match.match_products([row], 1575)["rejected"][0]
    assert rejected["catalogId"] == "MLA789"
    assert rejected["mlName"] == "Samsung 990 PRO 1TB"
    assert rejected["mlBrand"] == "Samsung"
    assert rejected["mlModel"] == "990 PRO"
    assert rejected["reason"] == "precio fuera de rango"
    assert len(rejected["candidates"]) == 2


def test_bundle_after_description_is_not_lost():
    ml = cached_product("Samsung T9 1TB", "Samsung", "T9")
    assert cached_match("Samsung T9 1TB | Bundle with cable", ml)["doubtful"]


def test_prefix_does_not_hide_a_different_model():
    assert match.family_conflict({"sn850", "pc100"}, {"sn850x", "pc100"})
    assert not match.family_conflict({"q2n4k"}, {"q2n4k", "q2n"})


@pytest.mark.parametrize("devices,status", [("Xbox Series X, Computadoras", "doubtful"), ("PC, PlayStation 5", "accepted")])
def test_catalog_platform_contradiction(devices, status):
    ml = cached_product("Razer Wolverine V2 Pro Wireless Para PS5 Negro", "Razer", "Wolverine V2",
                        COMPATIBLE_DEVICES=devices)
    assert cached_match("Razer Wolverine V2 Pro Wireless PlayStation Controller Black", ml, "Razer", "Gaming")[status]
