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


def get_eur_usd(oficial=None):
    """Relación EUR -> USD cruzando euro y dólar oficial de DolarAPI (igual que fetchEurUsd en src/lib/dolar.ts)."""
    try:
        if isinstance(oficial, bool) or not isinstance(oficial, (int, float)) or not math.isfinite(oficial) or oficial <= 0:
            resp_of = requests.get("https://dolarapi.com/v1/dolares/oficial", timeout=20)
            resp_of.raise_for_status()
            oficial = resp_of.json()["venta"]
            if isinstance(oficial, bool):
                return None
            oficial = float(oficial)
            if not math.isfinite(oficial) or oficial <= 0:
                return None
        response = requests.get("https://dolarapi.com/v1/cotizaciones/eur", timeout=20)
        response.raise_for_status()
        eur = response.json()["venta"]
        if isinstance(eur, bool):
            return None
        eur = float(eur)
        if not math.isfinite(eur) or eur <= 0:
            return None
        ratio = eur / float(oficial)
        return ratio if math.isfinite(ratio) and ratio > 0 else None
    except Exception:
        return None
