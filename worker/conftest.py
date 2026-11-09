"""Las esperas de reintento dentro de un paso (F-21) no se duermen de verdad en los tests."""
import pytest


@pytest.fixture(autouse=True)
def sin_esperas_de_reintento(monkeypatch):
    import ml_prices
    monkeypatch.setattr(ml_prices, "RETRY_WAIT_SECONDS", 0.0)
