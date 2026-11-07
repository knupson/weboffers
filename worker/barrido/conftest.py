import sys
from pathlib import Path
import pytest

# También permite ejecutar el directorio sin que otro test haya agregado worker a sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    import requests

    def fail(*args, **kwargs):
        raise AssertionError("Los tests del barrido no pueden consultar la red")

    monkeypatch.setattr(requests.sessions.Session, "request", fail)
    from curl_cffi import requests as curl_requests
    monkeypatch.setattr(curl_requests.Session, "request", fail)


@pytest.fixture
def fixture_dir():
    return Path(__file__).with_name("fixtures")
