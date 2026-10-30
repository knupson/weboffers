import json
import os
import signal
import sys
import time
import urllib.request
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

AMAZON_US_TAG = os.environ.get("AMAZON_US_TAG", "knunet-20")
AMAZON_ES_TAG = os.environ.get("AMAZON_ES_TAG", "knunet-21")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
SITE_URL = os.environ.get("SITE_URL", "https://ofertas.knunet.com")
CHECK_INTERVAL_SECONDS = int(os.environ.get("CHECK_INTERVAL_SECONDS", "21600"))

RUNNING = True


def handle_stop(signum, _frame):
    global RUNNING
    print(f"[INFO] Señal {signum} recibida. Deteniendo worker de FRANQUICIA 400 · KnuNet...")
    RUNNING = False


signal.signal(signal.SIGINT, handle_stop)
signal.signal(signal.SIGTERM, handle_stop)

DEALS_CATALOG = [
    {
        "asin": "B0C8Z6823P",
        "store": "US",
        "name": 'AOC Q27G3XMN 27" QHD Mini-LED 180Hz (336 Zonas · DisplayHDR 1000)',
        "priceUsd": 279,
        "previousPriceUsd": 319,
        "shippingUsd": 54,
        "vatRate": 0.105,
        "localArgentinaPriceArs": 890000,
    },
    {
        "asin": "B0CQ4W8B2J",
        "store": "US",
        "name": "GMKtec NucBox K6 AMD Ryzen 7 7840HS (32GB DDR5 + 1TB PCIe 4.0)",
        "priceUsd": 389,
        "previousPriceUsd": 479,
        "shippingUsd": 26,
        "vatRate": 0.105,
        "localArgentinaPriceArs": 1190000,
    },
    {
        "asin": "B0BZR9F1V9",
        "store": "US",
        "name": 'ASUS TUF Gaming 27" QHD (VG27AQ3A) 180Hz Fast IPS',
        "priceUsd": 219,
        "previousPriceUsd": 269,
        "shippingUsd": 48,
        "vatRate": 0.105,
        "localArgentinaPriceArs": 695000,
    },
    {
        "asin": "B0C7V9B8K2",
        "store": "ES",
        "name": "Roborock Q5 Pro Robot Aspirador LiDAR 5500 Pa DuoRoller (220V Europeo)",
        "priceUsd": 249,
        "previousPriceUsd": 349,
        "shippingUsd": 55,
        "vatRate": 0.21,
        "localArgentinaPriceArs": 940000,
    },
    {
        "asin": "B0D92X9Y5P",
        "store": "US",
        "name": "Meta Quest 3S 128GB Visor Realidad Mixta Inalambrico (Snapdragon XR2 Gen 2)",
        "priceUsd": 299,
        "previousPriceUsd": 349,
        "shippingUsd": 32,
        "vatRate": 0.21,
        "localArgentinaPriceArs": 890000,
    },
    {
        "asin": "B09VCHQZM7",
        "store": "ES",
        "name": "De'Longhi Dedica Arte EC885M Cafetera Express Manual 15 Bares (220V Nativo)",
        "priceUsd": 195,
        "previousPriceUsd": 259,
        "shippingUsd": 49,
        "vatRate": 0.21,
        "localArgentinaPriceArs": 680000,
    },
]


def get_dolar_rates() -> tuple[int, int]:
    mep = 1415
    tarjeta = 1840
    try:
        req_mep = urllib.request.Request(
            "https://dolarapi.com/v1/dolares/bolsa",
            headers={"User-Agent": "Mozilla/5.0 (RaspberryPi4; Linux arm64)"},
        )
        with urllib.request.urlopen(req_mep, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            mep = round(float(data.get("venta", 1415)))
    except Exception as exc:
        print(f"[WARN] Error consultando Dolar MEP ({exc}), usando fallback ${mep}.")

    try:
        req_tarj = urllib.request.Request(
            "https://dolarapi.com/v1/dolares/tarjeta",
            headers={"User-Agent": "Mozilla/5.0 (RaspberryPi4; Linux arm64)"},
        )
        with urllib.request.urlopen(req_tarj, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            tarjeta = round(float(data.get("venta", round(mep * 1.3))))
    except Exception:
        tarjeta = round(mep * 1.3)

    return mep, tarjeta


def build_affiliate_url(asin: str, store: str = "US") -> str:
    if store == "ES":
        return f"https://www.amazon.es/dp/{asin}?tag={AMAZON_ES_TAG}&linkCode=ll1"
    return f"https://www.amazon.com/dp/{asin}?tag={AMAZON_US_TAG}&linkCode=ll1&language=es_US"


def format_ars(amount: float) -> str:
    return "$" + f"{round(amount):,}".replace(",", ".")


def format_telegram_post(deal: dict, mep_rate: int, tarjeta_rate: int) -> str:
    fob = deal["priceUsd"]
    ship = deal["shippingUsd"]
    vat = deal["vatRate"]
    cif = fob + ship
    taxes = cif * vat if fob <= 400 else ((fob - 400) * 0.38 + cif * vat)
    final_usd = round(cif + taxes, 2)
    final_ars_mep = round(final_usd * mep_rate)
    final_ars_tarjeta = round(final_usd * tarjeta_rate)
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
        f"Si pagas con Dolar Tarjeta (${tarjeta_rate}): {format_ars(final_ars_tarjeta)}\n"
        f"Referencia retail local: <strike>{format_ars(local_ars)}</strike>\n"
        f"<b>Ahorro neto estimado: {format_ars(savings_ars)} (-{savings_pct}%)</b>\n\n"
        f"<a href='{aff_url}'>Ver unidad en Amazon ({deal['store']}) con envio Courier</a>\n"
        f"<a href='{SITE_URL}'>Simular liquidacion aduanera en ofertas.knunet.com</a>"
    )


def send_telegram_message(html_text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("\n--- [MODO MONITOREO LOCAL (Configurar TELEGRAM_BOT_TOKEN para publicar en canal)] ---")
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
        print("[OK] Despacho publicado en Telegram:", resp.status)


if __name__ == "__main__":
    cycle = 0
    print(
        f"[{datetime.now().isoformat()}] Worker FRANQUICIA 400 · KnuNet activo "
        f"(US={AMAZON_US_TAG}, ES={AMAZON_ES_TAG}, intervalo={CHECK_INTERVAL_SECONDS}s)"
    )

    while RUNNING:
        mep, tarjeta = get_dolar_rates()
        deal = DEALS_CATALOG[cycle % len(DEALS_CATALOG)]
        print(
            f"[{datetime.now().isoformat()}] Ciclo #{cycle + 1} | "
            f"MEP: ${mep} | Tarjeta: ${tarjeta} | ASIN: {deal['asin']} ({deal['store']})"
        )
        post = format_telegram_post(deal, mep, tarjeta)
        try:
            send_telegram_message(post)
        except Exception as exc:
            print(f"[ERROR] Fallo al despachar mensaje: {exc}")

        cycle += 1
        slept = 0
        while RUNNING and slept < CHECK_INTERVAL_SECONDS:
            time.sleep(min(5, CHECK_INTERVAL_SECONDS - slept))
            slept += 5
