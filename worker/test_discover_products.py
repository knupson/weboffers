import json
from pathlib import Path
import sys
from unittest.mock import Mock

import pytest
import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import discover_products  # noqa: E402
import ml_prices  # noqa: E402


@pytest.fixture(autouse=True)
def no_pauses(monkeypatch):
    monkeypatch.setattr(discover_products, "SCRAPER_PAUSE_SECONDS", 0)
    monkeypatch.setattr(ml_prices, "PAUSE_SECONDS", 0)


def json_response(payload):
    resp = Mock()
    resp.json.return_value = payload
    resp.raise_for_status = Mock()
    return resp


def test_load_existing_asins_ignores_blank_and_trims(tmp_path):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(
        json.dumps([
            {"asin": " B001 ", "slug": "uno"},
            {"asin": "", "slug": "vacio"},
            {"slug": "sin-asin"},
            {"asin": "B002", "slug": "dos"},
        ]),
        encoding="utf-8",
    )
    assert discover_products.load_existing_asins(catalog) == {"B001", "B002"}


def test_discover_categories_expands_departments_and_filters_tech(monkeypatch):
    routes = {
        ("US", None): {
            "categories": [
                {"id": "electronics", "path": "electronics", "name": "Electronics"},
                {"id": "pc", "path": "pc", "name": "Computers & Accessories"},
                {"id": "kitchen", "path": "kitchen", "name": "Kitchen & Dining"},
            ]
        },
        ("US", "electronics"): {
            "categories": [
                {"id": "172541", "path": "electronics/172541", "name": "Headphones & Earbuds"},
                {"id": "10048700011", "path": "electronics/10048700011", "name": "Smartwatches"},
                {"id": "999", "path": "electronics/999", "name": "Gift Cards"},
            ]
        },
        ("US", "pc"): {
            "categories": [
                {"id": "1292110011", "path": "pc/1292110011", "name": "Data Storage"},
                {"id": "1292115011", "path": "pc/1292115011", "name": "Monitors"},
            ]
        },
    }

    def fake_get(url, params=None, timeout=None):
        assert url.endswith("/best-sellers/categories")
        key = (params.get("country"), params.get("category"))
        return json_response(routes[key])

    monkeypatch.setattr(discover_products.requests, "get", fake_get)
    cats = discover_products.discover_categories(base_url="http://scraper:8000")
    ids = [c["id"] for c in cats]
    assert ids == [
        "electronics/172541",
        "electronics/10048700011",
        "pc/1292110011",
        "pc/1292115011",
    ]


def test_discover_categories_falls_back_when_empty(monkeypatch):
    monkeypatch.setattr(
        discover_products.requests,
        "get",
        lambda url, params=None, timeout=None: json_response({"categories": []}),
    )
    cats = discover_products.discover_categories(base_url="http://scraper:8000")
    assert len(cats) == len(discover_products.FALLBACK_CATEGORIES)


def test_should_keep_amazon_item_filters_asin_price_stock_and_accessories():
    existing = {"B0EXISTE01"}
    seen = {"B0VISTO001"}

    # Válido (incluso auriculares con "with Charging Case")
    assert discover_products.should_keep_amazon_item(
        {
            "asin": "B0VALID001",
            "title": "Sony WF-1000XM5 Truly Wireless Noise Canceling Earbuds with Charging Case",
            "price": {"amount": 248.0, "currency": "USD"},
            "in_stock": True,
        },
        existing,
        seen,
    )

    # ASIN ya existente en catálogo o repetido
    assert not discover_products.should_keep_amazon_item(
        {"asin": "B0EXISTE01", "title": "Logitech MX Master 3S Mouse", "price": {"amount": 99, "currency": "USD"}},
        existing,
        seen,
    )
    assert not discover_products.should_keep_amazon_item(
        {"asin": "B0VISTO001", "title": "Logitech MX Master 3S Mouse", "price": {"amount": 99, "currency": "USD"}},
        existing,
        seen,
    )

    # Precio fuera de rango (< 30 o > 2000) o moneda no USD
    assert not discover_products.should_keep_amazon_item(
        {"asin": "B0BARATO01", "title": "SanDisk 64GB Flash Drive", "price": {"amount": 29.99, "currency": "USD"}},
        existing,
    )
    assert not discover_products.should_keep_amazon_item(
        {"asin": "B0CARO0001", "title": "ASUS ROG Gaming Laptop RTX 4090", "price": {"amount": 2000.01, "currency": "USD"}},
        existing,
    )
    assert not discover_products.should_keep_amazon_item(
        {"asin": "B0EUR00001", "title": "Samsung 990 PRO 2TB SSD", "price": {"amount": 150, "currency": "EUR"}},
        existing,
    )

    # Sin stock
    assert not discover_products.should_keep_amazon_item(
        {"asin": "B0NOSTOCK1", "title": "AMD Ryzen 7 7800X3D Processor", "price": {"amount": 399, "currency": "USD"}, "in_stock": False},
        existing,
    )
    assert not discover_products.should_keep_amazon_item(
        {"asin": "B0NOSTOCK2", "title": "AMD Ryzen 7 7800X3D Processor", "price": {"amount": 399, "currency": "USD"}, "availability": "Currently unavailable."},
        existing,
    )

    # Accesorios, cables, fundas, repuestos, reacondicionados, "compatible with"
    excluded_titles = [
        "Spigen Tough Armor Protective Case for iPhone 16 Pro",
        "Anker USB-C to USB-C Charging Cable 6ft",
        "amFilm Tempered Glass Screen Protector 3-Pack",
        "iFixit Replacement Parts Battery Kit",
        "Apple iPad Air 5th Gen (Renewed)",
        "Dell Latitude 7420 Laptop (Refurbished)",
        "Stylus Pen Compatible with iPad Pro",
        "Silicone Keyboard Cover for MacBook Air",
    ]
    for idx, bad_title in enumerate(excluded_titles):
        assert not discover_products.should_keep_amazon_item(
            {"asin": f"B0BAD{idx:05d}", "title": bad_title, "price": {"amount": 45, "currency": "USD"}},
            existing,
        ), f"Debió filtrarse: {bad_title}"


def test_infer_brand_and_clean_title_for_ml():
    item = {
        "asin": "B09V3KXJPB",
        "brand": "Visit the Samsung Store",
        "title": "All-New Samsung 990 PRO Series - 2TB PCIe Gen4. X4 NVMe 2.0c - M.2 Internal SSD (MZ-V9P2T0B/AM), Works with Alexa",
    }
    brand = discover_products.infer_brand(item)
    assert brand == "Samsung"
    cleaned = discover_products.clean_title_for_ml(item["title"], brand)
    assert "Samsung" in cleaned
    assert "990 PRO" in cleaned
    assert "2TB" in cleaned
    assert "All-New" not in cleaned
    assert "Works with Alexa" not in cleaned


def test_find_ml_candidates_takes_top_5_and_keeps_only_priced_new(monkeypatch):
    search_results = [
        {"id": f"MLA{i}", "name": f"Producto {i}"}
        for i in range(1, 8)
    ]
    monkeypatch.setattr(ml_prices, "search_products", Mock(return_value=search_results))

    items_by_id = {
        "MLA1": [{"price": 300000, "condition": "new", "item_id": "MLA1001"}],
        "MLA2": [{"price": 150000, "condition": "used", "item_id": "MLA2001"}],  # sólo usado -> sin precio nuevo
        "MLA3": requests.ConnectionError("timeout"),  # falla red -> se ignora
        "MLA4": [{"price": 280000, "condition": "new", "item_id": "MLA4001"}, {"price": 250000, "condition": "new", "item_id": "MLA4002"}],
        "MLA5": [],
    }

    def fake_fetch_items(cid):
        val = items_by_id[cid]
        if isinstance(val, Exception):
            raise val
        return val

    fetch_mock = Mock(side_effect=fake_fetch_items)
    monkeypatch.setattr(ml_prices, "fetch_items", fetch_mock)

    candidates = discover_products.find_ml_candidates("Samsung 990 PRO 2TB")
    assert fetch_mock.call_count == 5  # top 5 de los 7 resultados
    assert candidates == [
        {"catalogId": "MLA1", "name": "Producto 1", "minPrice": 300000, "itemId": "MLA1001"},
        {"catalogId": "MLA4", "name": "Producto 4", "minPrice": 250000, "itemId": "MLA4002"},
    ]


def test_discover_products_checkpoints_every_50_and_supports_queries(tmp_path, monkeypatch, capsys):
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps([{"asin": "B0SKIP0000", "slug": "existente"}]), encoding="utf-8")
    output = tmp_path / "discovery-candidates.json"

    # 49 válidos en best-sellers + 1 existente (top 50 por categoría) + 4 de búsqueda (/search) = 53 válidos
    bestsellers_items = [
        {
            "asin": "B0SKIP0000",
            "title": "Samsung 980 PRO 1TB SSD",
            "price": {"amount": 99.0, "currency": "USD"},
            "in_stock": True,
        }
    ] + [
        {
            "asin": f"B0ITEM{i:04d}",
            "title": f"Logitech G Pro X Superlight {i} Wireless Gaming Mouse",
            "brand": "Logitech G",
            "price": {"amount": 100.0 + i, "currency": "USD"},
            "in_stock": True,
        }
        for i in range(1, 50)
    ]

    search_items = [
        {
            "asin": f"B0SEARCH{j:02d}",
            "title": f"Keychron Q{j} Pro Wireless Custom Mechanical Keyboard",
            "brand": "Keychron",
            "price": {"amount": 199.0 + j, "currency": "USD"},
            "in_stock": True,
        }
        for j in range(1, 5)
    ]

    def fake_get(url, params=None, timeout=None):
        if url.endswith("/best-sellers"):
            return json_response({"title": "Mice", "items": bestsellers_items})
        if url.endswith("/search"):
            assert params["query"] == "keychron q1"
            return json_response({"results": search_items})
        raise AssertionError(f"URL inesperada: {url}")

    monkeypatch.setattr(discover_products.requests, "get", fake_get)
    monkeypatch.setattr(
        ml_prices,
        "search_products",
        lambda q: [{"id": "MLA900", "name": f"ML {q}"}],
    )
    monkeypatch.setattr(
        ml_prices,
        "fetch_items",
        lambda cid: [{"price": 210000, "condition": "new", "item_id": "MLA9001"}],
    )

    write_calls = []
    real_write_atomic = discover_products.publish.write_atomic

    def spy_write_atomic(path, payload):
        write_calls.append(len(payload))
        return real_write_atomic(path, payload)

    monkeypatch.setattr(discover_products.publish, "write_atomic", spy_write_atomic)

    results = discover_products.discover_products(
        catalog_path=catalog,
        output_path=output,
        queries=["keychron q1"],
        categories=[{"id": "pc/mice", "name": "Gaming Mice"}],
        base_url="http://scraper:8000",
    )

    assert len(results) == 53
    # Se guardó un checkpoint a los 50 y el archivo final a los 53
    assert write_calls == [50, 53]
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert len(saved) == 53
    assert saved[0] == {
        "asin": "B0ITEM0001",
        "store": "US",
        "amazonTitle": "Logitech G Pro X Superlight 1 Wireless Gaming Mouse",
        "brand": "Logitech G",
        "amazonCategory": "Gaming Mice",
        "amazonPriceUsd": 101.0,
        "ml": [{"catalogId": "MLA900", "name": "ML Logitech G Pro X Superlight 1 Wireless Gaming", "minPrice": 210000, "itemId": "MLA9001"}],
    }
    assert saved[-1]["asin"] == "B0SEARCH04"
    assert saved[-1]["amazonCategory"] == "search:keychron q1"

    out = capsys.readouterr().out
    assert "Progreso: 20/53 productos procesados." in out
    assert "Progreso: 40/53 productos procesados." in out
    assert "Checkpoint guardado" in out


def test_excluded_departments():
    import discover_products as d
    assert d.is_excluded_department("Books") and d.is_excluded_department("Amazon Renewed")
    assert d.is_excluded_department("Clothing, Shoes & Jewelry")
    assert not d.is_excluded_department("Tools & Home Improvement")
    assert not d.is_excluded_department("Sports & Outdoors")
