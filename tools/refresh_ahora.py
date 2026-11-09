"""Ejecuta un refresh de la cadena dentro del worker, con su log persistente."""
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
import worker
import publicacion
from requisitos import motivo_total, modo_actual as publicacion_modo


def main(paso):
    output = worker.resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent
    sys.stdout = worker.DailyLog(output / "logs", sys.stdout)
    sys.stderr = worker.DailyLog(output / "logs", sys.stderr)
    start = time.monotonic()
    print(f"REFRESH_INICIO {paso}", flush=True)
    try:
        catalog = worker.load_catalog(worker.resolve_path(os.environ.get("CATALOG_PATH", "../data/catalog.json")), output / "catalog-auto.json")
        if paso == "fichas":
            now = datetime.now(timezone.utc)
            estado = publicacion.cargar(output)
            today = now.astimezone(publicacion.ART).date().isoformat()
            catalog = [p for p in catalog if motivo_total(p, estado, today, "verificacion") is None]
            worker.ml_fichas.refresh_optional(catalog, output / "ml-fichas.json", now)
            print(f"REFRESH_OK {paso} {time.monotonic() - start:.1f}s", flush=True)
            return 0
        current = worker.rates.get_rates() or {}
        eur_usd = worker.rates.get_eur_usd(current.get("oficial")) if current else None
        amazon = worker.resolve_path(os.environ.get("AMAZON_PRICES_PATH", "output/amazon-prices.json"))
        ml = worker.resolve_path(os.environ.get("ML_PRICES_PATH", "output/ml-prices.json"))
        now = datetime.now(timezone.utc)
        if paso == "amazon":
            worker.amazon_prices.maybe_refresh(catalog, amazon, now, eur_usd=eur_usd, force=True)
            target = amazon
        else:
            worker.ml_prices.maybe_refresh(catalog, ml, amazon, current.get("mep"), now, eur_usd=eur_usd, force=True)
            target = ml
        data = json.loads(target.read_text(encoding="utf-8"))
        if data.get("date") != now.astimezone(worker.amazon_prices.ART).date().isoformat() or not data.get("items"):
            raise RuntimeError("no quedaron precios válidos de hoy")
        if data.get("completo") is False and publicacion_modo() == "verificacion":
            # F-15: el archivo de hoy es el parcial que dejó el alta; la verificación no corrió completa.
            raise RuntimeError("los precios de hoy son parciales (completo: false); la verificación no los completó")
        failed = data.get("failed") or []
        if paso == "ml" and failed:
            # F-20: una consulta de ML sin precio no deja un archivo inválido (el producto no se publica, la regla 1 se
            # cumple) y ya se reintentó dentro del paso (F-21). Una falla aislada no hace fallar el paso, porque eso frena
            # el deploy de las altas confirmadas; la alarma queda en el log con «corrida incompleta» (la ve el vigía).
            intentados = len(data["items"]) + len(failed)
            if len(failed) * 10 > intentados:
                raise RuntimeError(f"consultas pendientes: {', '.join(failed)}")
            print(f"ML corrida incompleta: {len(failed)} de {intentados} consultas sin precio de hoy "
                  f"({', '.join(failed)}); no se publican hoy.", flush=True)
        print(f"REFRESH_OK {paso} {time.monotonic() - start:.1f}s", flush=True)
        return 0
    except Exception as exc:
        traceback.print_exc()
        print(f"REFRESH_FAIL {paso} {time.monotonic() - start:.1f}s {exc}", flush=True)
        return 1


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paso", choices=("amazon", "ml", "fichas"))
    sys.exit(main(parser.parse_args().paso))
