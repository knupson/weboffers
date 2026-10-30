"""Cotizaciones actuales, sin valores de respaldo."""

from datetime import datetime, timezone
import math

import requests


def get_rates():
    try:
        rates = {}
        for key, endpoint in (("mep", "bolsa"), ("tarjeta", "tarjeta"), ("oficial", "oficial")):
            response = requests.get(
                f"https://dolarapi.com/v1/dolares/{endpoint}", timeout=20
            )
            response.raise_for_status()
            value = response.json()["venta"]
            if isinstance(value, bool):
                return None
            value = float(value)
            if not math.isfinite(value) or value <= 0:
                return None
            rates[key] = value
        return {
            **rates,
            "fetchedAt": datetime.now(timezone.utc).isoformat(),
            "source": "dolarapi.com",
        }
    except Exception:
        return None
