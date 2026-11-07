"""Carga única del paquete vendor sin mezclar otra instalación de amazon/config."""
import importlib
from pathlib import Path
import sys

VENDOR = Path(__file__).with_name("vendor").resolve()


def load_vendor():
    for name in ("amazon", "config", "scraper_errors", "schema_fields"):
        module = sys.modules.get(name)
        if module is not None and not Path(module.__file__).resolve().is_relative_to(VENDOR):
            raise RuntimeError(f"Importación incompatible: {name} desde {module.__file__}")
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    return importlib.import_module("amazon")


def configure_transport(observer=None):
    load_vendor()
    from amazon import fetch
    import config
    from amazon_shipping import apply_ar_location
    config.AMAZON_PROXY = None
    config.AMAZON_PROXY_COUNTRY = None
    config.AMAZON_EGRESS = "direct"
    fetch.RETRIES = 0
    fetch.BLOCK_RETRIES = 1
    fetch.OBSERVER = observer
    apply_ar_location()
    return fetch
