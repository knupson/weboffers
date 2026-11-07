import json
from types import SimpleNamespace
from .bootstrap import load_vendor
from .amazon_source import AmazonSource
from .config import Config
from .events import now_art
from .runner import run_all


def test_a1_a4_con_parser_y_fuente_reales_sin_red(tmp_path, fixture_dir, monkeypatch):
    load_vendor()
    from amazon import fetch, products
    calls = []
    html = (fixture_dir / "us_search.html").read_text(encoding="utf-8")
    def page(country, path, params, **kwargs):
        calls.append(params.copy())
        fetch.OBSERVER(country=country, method="GET", path="https://www.amazon.com/s", http=200, seconds=.01, error=None)
        if params["page"] == "2":
            return html.replace("B0FIXTURE1", "B0FIXTURE2").replace(
                's-pagination-selected">1', 's-pagination-selected">2').replace(
                '<a class="s-pagination-item s-pagination-next" href="/s?page=2">Next</a>',
                '<span class="s-pagination-item s-pagination-next s-pagination-disabled">Next</span>').replace(
                "FREE delivery to Argentina", "Cannot be shipped to Argentina")
        return html
    monkeypatch.setattr(fetch, "page", page)
    monkeypatch.setattr(fetch, "session", lambda *args, **kw: SimpleNamespace(located="AR"))
    monkeypatch.setattr(products, "variations", lambda *args, **kw: json.loads((fixture_dir / "variations.json").read_text()))
    stamp = now_art().isoformat()
    rate = {"value": 1, "source": "fixture", "observed_at": stamp}
    config = Config(pause=0)
    categories = {"stores": {"US": {"nodes": [{"id": "FIXTURENODE", "name": "Prueba", "kind": "leaf"}]}}}
    factory = lambda store, date, conversion: AmazonSource(store, date, conversion, config, tmp_path / "cache")
    result = run_all(categories, config, tmp_path, source_factory=factory, rate_loader=lambda *a: rate,
                     sleep=lambda _: None, max_pages=1)
    assert result["US"]["status"] == "partial"
    result = run_all(categories, config, tmp_path, source_factory=factory, rate_loader=lambda *a: rate, sleep=lambda _: None)
    assert result["US"]["status"] == "complete"
    rows = [json.loads(line) for line in (tmp_path / f"US-{stamp[:10]}.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert [r["shipping_class"] for r in rows] == ["gratis", "no_envia"]
    assert [r["eligible"] for r in rows] == [True, False]
    assert all(100 <= r["price_usd"] <= 400 and r["raw"]["card_html"] for r in rows)
    assert len(calls) == 3  # Una preconsulta de refinamientos y dos páginas filtradas.
    assert all("p_n_condition-type:FIXTURE_NEW" in p["rh"] for p in calls[1:])
    assert rows[0]["variations"] is not None and rows[1]["variations"] is None
