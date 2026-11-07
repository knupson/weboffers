import hashlib
import json
from pathlib import Path
from .bootstrap import VENDOR, load_vendor, configure_transport


def test_importa_vendor_esperado():
    package = load_vendor()
    assert Path(package.__file__).resolve().is_relative_to(VENDOR)


def test_origen_y_hashes():
    original = json.loads((VENDOR / "upstream-hashes.json").read_text())
    changes = json.loads((VENDOR / "local-hashes.json").read_text())
    for name, expected in {**original, **changes}.items():
        assert hashlib.sha256((VENDOR / name).read_bytes()).hexdigest() == expected, name
    assert "Copyright (c) 2026 Chetan Jain" in (VENDOR / "LICENSE").read_text()
    assert "8ffd4f976c705d009ec06d8e4e3e15fc77e35cee" in (VENDOR / "UPSTREAM.md").read_text()


def test_salida_directa(monkeypatch):
    load_vendor()
    import config
    monkeypatch.setattr(config, "AMAZON_PROXY", "http://fixture.invalid")
    fetch = configure_transport()
    assert config.amazon_country_proxy("US") is None
    assert config.amazon_fallback_proxy("US") is None
    assert fetch.RETRIES == 0 and fetch.BLOCK_RETRIES == 1
