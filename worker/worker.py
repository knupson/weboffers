"""Daemon de Telegram; la cadena diaria actualiza los precios y las altas."""

from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
import traceback

import amazon_prices
import creators_api
import ml_prices
import ml_fichas
import publish
import rates
import telegram
from catalog import load_catalog
import catalog_auto


WORKER_DIR = Path(__file__).resolve().parent
stop_requested = False


def request_stop(signum, frame):
    global stop_requested
    stop_requested = True


def resolve_path(value):
    path = Path(value)
    return path if path.is_absolute() else WORKER_DIR / path


def run_once():
    catalog_path = resolve_path(os.environ.get("CATALOG_PATH", "../data/catalog.json"))
    output_dir = resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent
    catalog = load_catalog(catalog_path, output_dir / "catalog-auto.json")
    current_rates = rates.get_rates()
    eur_usd = rates.get_eur_usd(current_rates.get("oficial")) if current_rates else None
    mep = (current_rates or {}).get("mep")
    amazon_prices_path = resolve_path(os.environ.get("AMAZON_PRICES_PATH", "output/amazon-prices.json"))
    ml_prices_path = resolve_path(os.environ.get("ML_PRICES_PATH", "output/ml-prices.json"))
    # Telegram consume los precios que ya dejó la cadena diaria.
    try:
        telegram.maybe_post(
            with_ar_shipping(ml_prices.merge(
                catalog,
                ml_prices_path,
                amazon_prices_path,
                mep=mep,
                eur_usd=eur_usd,
                now=datetime.now(timezone.utc),
            ), amazon_prices_path),
            resolve_path(os.environ.get("TELEGRAM_STATE_PATH", "output/telegram-state.json")),
        )
    except Exception as exc:
        print(f"Falló Telegram ({type(exc).__name__}).", flush=True)


def with_ar_shipping(products, amazon_prices_path, now=None):
    """El envío vigente del relevamiento (arShipping, ≤14 días) manda sobre el del catálogo, como en el sitio."""
    try:
        data = json.load(open(amazon_prices_path, encoding="utf-8")) or {}
        shipping = amazon_prices.merge_ar_shipping(data, data.get("items") or {},
                                                   (now or datetime.now(timezone.utc)).astimezone(amazon_prices.ART).date())
    except (OSError, ValueError):
        shipping = {}
    out = []
    for p in products:
        ar = shipping.get(p.get("slug"))
        if isinstance(ar, dict) and isinstance(ar.get("ships"), bool):
            p = {**p, "shipsToAr": {"freeShipping": ar.get("free") is True, "checked": ar.get("checked")},
                 "shipsToArToday": ar["ships"]}
        out.append(p)
    return out


class DailyLog:
    """Copia todo lo que el worker imprime a output/logs/worker-AAAA-MM-DD.log (fecha ART).

    `docker logs` se pierde cada vez que se recrea el contenedor; output/ es un volumen y sobrevive.
    """

    KEEP_DAYS = 30

    def __init__(self, logs_dir, stream):
        self.dir = Path(logs_dir)
        self.stream = stream
        self.dir.mkdir(parents=True, exist_ok=True)
        self._purge()
        self._log_day = self._now_art().date()

    def _now_art(self):
        return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=-3)))

    def _purge(self):
        cutoff = time.time() - self.KEEP_DAYS * 86400
        for old in self.dir.glob("worker-*.log"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError:
                pass

    def write(self, text):
        self.stream.write(text)
        if text.strip():
            now = self._now_art()
            if now.date() != self._log_day:
                self._purge()
                self._log_day = now.date()
            try:
                with open(self.dir / f"worker-{now:%Y-%m-%d}.log", "a", encoding="utf-8") as fh:
                    for line in text.splitlines():
                        if line.strip():
                            fh.write(f"{now:%Y-%m-%d %H:%M:%S} {line}\n")
            except OSError:
                pass  # El log en disco nunca tumba al worker.
        return len(text)

    def flush(self):
        self.stream.flush()


def main():
    output_dir = resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent
    sys.stdout = DailyLog(output_dir / "logs", sys.stdout)
    sys.stderr = DailyLog(output_dir / "logs", sys.stderr)
    interval = float(os.environ.get("CHECK_INTERVAL_SECONDS", "3600"))
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("CHECK_INTERVAL_SECONDS debe ser un número positivo")
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    print("Worker iniciado.", flush=True)
    while not stop_requested:
        try:
            run_once()
        except Exception as exc:
            print(f"Falló el ciclo de actualización ({type(exc).__name__}).", flush=True)
        # Despierta al minuto 1 de cada hora (o antes si el intervalo es menor) para que Telegram salga en horario.
        to_next_hour = 3600 - time.time() % 3600 + 60
        deadline = time.monotonic() + min(interval, to_next_hour)
        while not stop_requested and time.monotonic() < deadline:
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
    print("Worker detenido.", flush=True)


if __name__ == "__main__":
    main()
