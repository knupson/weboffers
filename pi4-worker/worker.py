import json
import os
import sys
import urllib.request
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AMAZON_US_TAG = os.environ.get("AMAZON_US_TAG", "knunet-20")
AMAZON_ES_TAG = os.environ.get("AMAZON_ES_TAG", "knunet-21")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
SITE_URL = os.environ.get("SITE_URL", "https://ofertas.knunet.com")


def get_dolar_mep() -> int:
    try:
        req = urllib.request.Request(
            "https://dolarapi.com/v1/dolares/bolsa",
            headers={"User-Agent": "Mozilla/5.0 (RaspberryPi4; Linux arm64)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return round(float(data.get("venta", 1415)))
    except Exception as exc:
        print(f"[WARN] Error consultando DolarApi ({exc}), usando fallback.")
        return 1415


def build_affiliate_url(asin: str, store: str = "US") -> str:
    if store == "ES":
        return f"https://www.amazon.es/dp/{asin}?tag={AMAZON_ES_TAG}&linkCode=ll1"
    return f"https://www.amazon.com/dp/{asin}?tag={AMAZON_US_TAG}&linkCode=ll1&language=es_US"


def format_ars(amount: float) -> str:
    return "$" + f"{round(amount):,}".replace(",", ".")


def format_telegram_post(deal: dict, mep_rate: int) -> str:
    fob = deal["priceUsd"]
    ship = deal["shippingUsd"]
    vat = deal["vatRate"]
    cif = fob + ship
    taxes = cif * vat if fob <= 400 else ((fob - 400) * 0.38 + cif * vat)
    final_usd = round(cif + taxes, 2)
    final_ars_mep = round(final_usd * mep_rate)
    local_ars = deal["localArgentinaPriceArs"]
    savings_ars = max(0, local_ars - final_ars_mep)
    savings_pct = round((savings_ars / local_ars) * 100)
    aff_url = build_affiliate_url(deal["asin"], deal["store"])

    return (
        f"<b>[FRANQUICIA 400 · KNUNET] DESPACHO SUB-USD 400 ({deal['store']})</b>\n\n"
        f"<b>{deal['name']}</b>\n"
        f"Valor FOB Amazon: <b>USD {fob}</b> (lista USD {deal['previousPriceUsd']})\n"
        f"Flete + IVA Courier ({vat * 100:.1f}% exento de arancel): +USD {round(ship + taxes, 2)}\n\n"
        f"<b>TOTAL PUESTO EN ARGENTINA (MEP ${mep_rate}): {format_ars(final_ars_mep)}</b>\n"
        f"Referencia retail local: <strike>{format_ars(local_ars)}</strike>\n"
        f"<b>Ahorro neto estimado: {format_ars(savings_ars)} (-{savings_pct}%)</b>\n\n"
        f"<a href='{aff_url}'>Ver oferta en Amazon con envio a Argentina</a>\n"
        f"<a href='{SITE_URL}'>Simular liquidacion aduanera en ofertas.knunet.com</a>"
    )


def send_telegram_message(html_text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n--- [MODO SIMULACION TELEGRAM (Configurar TELEGRAM_BOT_TOKEN)] ---")
        print(html_text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": html_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print("[OK] Oferta enviada a Telegram:", resp.status)


if __name__ == "__main__":
    print(f"[{datetime.now().isoformat()}] Iniciando relevamiento en Raspberry Pi 4...")
    mep = get_dolar_mep()
    print(f"Cotizacion Dolar MEP actual: ${mep} ARS")

    sample_deal = {
        "asin": "B0BZR9F1V9",
        "store": "US",
        "name": 'ASUS TUF Gaming 27" 2K QHD (VG27AQ3A) 180Hz Fast IPS',
        "priceUsd": 219,
        "previousPriceUsd": 269,
        "shippingUsd": 48,
        "vatRate": 0.105,
        "localArgentinaPriceArs": 695000,
    }

    post = format_telegram_post(sample_deal, mep)
    send_telegram_message(post)
