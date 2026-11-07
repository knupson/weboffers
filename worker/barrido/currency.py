"""Cotizaciones estrictamente del día ART, con procedencia."""
from datetime import datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import requests
from .events import ART, now_art
from .models import positive


def validate_rate(rate, today):
    stamp = datetime.fromisoformat(rate["observed_at"].replace("Z", "+00:00"))
    if stamp.tzinfo is None or stamp.astimezone(ART).date().isoformat() != today or not positive(rate["value"]):
        raise ValueError(f"Cotización inválida o ajena al día {today}: {rate}")
    return rate


def load_daily_rates(store, today, get=requests.get):
    if store == "US":
        return {"value": 1, "source": "identidad USD", "observed_at": now_art().isoformat()}

    def quote(endpoint):
        response = get("https://dolarapi.com/v1/" + endpoint, timeout=20)
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text}")
        body = response.json()
        return validate_rate({"value": body["venta"], "source": response.url,
                              "observed_at": body["fechaActualizacion"]}, today)

    if store == "ML":
        mep = quote("dolares/bolsa")
        return {**mep, "value": 1 / mep["value"]}
    eur, usd = quote("cotizaciones/eur"), quote("dolares/oficial")
    return {"value": eur["value"] / usd["value"], "source": [eur["source"], usd["source"]],
            "observed_at": min(eur["observed_at"], usd["observed_at"])}


def usd_bounds(min_usd, max_usd, rate):
    factor = Decimal(str(rate["value"]))
    return (str((Decimal(str(min_usd)) / factor).quantize(Decimal(".01"), rounding=ROUND_FLOOR)),
            str((Decimal(str(max_usd)) / factor).quantize(Decimal(".01"), rounding=ROUND_CEILING)))
