import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest


@pytest.fixture
def probe(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("probe_test_module", Path(__file__).resolve().parents[1] / "tools" / "probar_scraper.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "VISTOS", tmp_path / "vistos.json")
    monkeypatch.setattr(module, "catalogo_asins", lambda: {"FIXTURE_KNOWN"})
    return module


def test_conserva_control_asins(probe, monkeypatch, capsys):
    def fail(*a, **k):
        pytest.fail("No debe consultar ASIN desconocido")
    monkeypatch.setattr(probe.requests, "get", fail)
    assert probe.main(["products/details", "product=FIXTURE_UNKNOWN"]) == 1
    assert "NO_CONSULTADO" in capsys.readouterr().out


def test_muestra_moneda_y_usd(probe):
    assert "EUR 150 USD None SIN_PRECIO" == probe.price_label({"price": {"amount": 150, "currency": "EUR"}})
    assert "EUR 150 USD 165 DENTRO" == probe.price_label({"price": {"amount": 150, "currency": "EUR"}, "price_usd": 165})


def test_error_completo(probe, monkeypatch, capsys):
    literal = "error fixture\n" + "x" * 4000 + "FIN_LITERAL"
    monkeypatch.setattr(probe.requests, "get", lambda *a, **k: SimpleNamespace(status_code=502, text=literal))
    assert probe.main(["search"]) == 1
    out = capsys.readouterr().out
    assert "FIN_LITERAL" in out and "\\n" in out
    assert all("-03:00 " in line for line in out.splitlines())


def test_paginacion_anidada(probe, monkeypatch, capsys):
    body = {"results": [{"asin": "FIXTURE_FOUND", "price": {"amount": 150, "currency": "USD"}}],
            "pagination": {"total_pages": 9, "total_count": 199}}
    monkeypatch.setattr(probe.requests, "get", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: body))
    assert probe.main(["search"]) == 0
    assert "total_pages=9 count=199" in capsys.readouterr().out
    assert "FIXTURE_FOUND" in probe.VISTOS.read_text()


def test_probe_ruta_servicio(probe, monkeypatch):
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200, json=lambda: {"stores": {"US": {"status": "complete"}}})
    monkeypatch.setattr(probe.requests, "get", get)
    assert probe.main(["barrido/probe", "node=541966"]) == 0
    assert calls == ["http://weboffers-barrido:8002/barrido/probe"]
