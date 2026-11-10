import pytest
from .currency import validate_rate, usd_bounds, load_daily_rates


def test_limites_eur_hacia_afuera():
    assert usd_bounds(100, 400, {"value": 1.1}) == ("90.90", "363.64")


@pytest.mark.parametrize("stamp", ["2026-11-06T15:00:00Z", "2026-11-08T15:00:00Z", "2026-11-07T15:00:00"])
def test_rechaza_cotizacion_vieja(stamp):
    with pytest.raises(ValueError):
        validate_rate({"value": 1, "observed_at": stamp}, "2026-11-07")


def test_us_no_necesita_tasas_remotas():
    assert load_daily_rates("US", "2026-11-07")["value"] == 1
