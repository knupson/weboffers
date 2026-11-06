#!/usr/bin/env python3
"""Promueve pendientes sólo con envío gratis y precio USD 100–400 vistos hoy en Chrome.

Corre dentro del worker, después del relevamiento del host. No consulta la red.
Los intentos sin dato cuentan una sola vez por fecha ART, incluso con reintentos.
"""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from alta_state import duplicate, read_json, update_state
from article_log import alta_line
from catalog import load_catalog
from publish import write_atomic

ART = timezone(timedelta(hours=-3))


def chrome_today(data, today):
    """Rechaza evidencia de otro día aunque se haya copiado con el nombre de hoy."""
    if not data or not data.get("generado"):
        # Sin relevamiento (el paso chrome falló o no corrió): los pendientes quedan como están (06/11, revisión).
        raise ValueError(f"No hay relevamiento de Chrome de {today} (ar-chrome-{today}.json); los pendientes siguen pendientes.")
    generated = datetime.fromisoformat(data["generado"])
    if generated.tzinfo is None or generated.astimezone(ART).date().isoformat() != today:
        raise ValueError("El relevamiento de Chrome no es de hoy en ART.")
    if not isinstance(data.get("items"), dict):
        raise ValueError("El relevamiento de Chrome no tiene artículos válidos.")
    return data


def price_usd(raw):
    """Chrome fija USD; exigimos el mismo formato monetario que amazon_prices."""
    match = re.fullmatch(r"\s*\$\s*([\d,]+(?:\.\d+)?)\s*", str(raw or ""))
    return float(match.group(1).replace(",", "")) if match else None


def confirm(catalog_path, output, today=None):
    output = Path(output)
    today = today or datetime.now(ART).date().isoformat()
    return update_state([], output / "altas.json", lambda: _confirm(catalog_path, output, today))


def _confirm(catalog_path, output, today):
    pending = read_json(output / "altas-pendientes.json", [])
    remaining, promoted = [], []
    rejected_count = 0
    if pending:
        data = chrome_today(read_json(output / f"ar-chrome-{today}.json", {}), today)
        automatic = read_json(output / "catalog-auto.json", [])
        catalog = load_catalog(catalog_path, output / "catalog-auto.json")
        rejected = read_json(output / "altas-rechazadas.json", {})
        for entry in pending:
            item = data["items"].get(entry["asin"]) or {}
            ships, free = item.get("ships"), item.get("free")
            price = price_usd(item.get("precio"))
            reason = None
            if duplicate(entry, catalog + promoted):
                # Recuperación idempotente si se interrumpió entre guardar catálogo y limpiar pendientes.
                print(alta_line(entry, "descartado", "duplicado", item), flush=True)
                continue
            if ships is False:
                reason = "no_envia_ar"
            elif ships is True and free is False:
                reason = "envio_pago"
            elif ships is True and price is not None and not 100 <= price <= 400:
                reason = "precio_fuera_de_rango"
            elif ships is True and free is True and price is not None:
                built = {k: v for k, v in entry.items()
                         if k not in ("pendienteDesde", "nochesSinDato", "ultimoIntentoEnvio")}
                built["shipsToAr"] = {"freeShipping": True, "checked": today}
                promoted.append(built)
                print(alta_line(entry, "promovida", item=item), flush=True)
                continue
            else:
                if entry.get("ultimoIntentoEnvio") != today:
                    entry["nochesSinDato"] = entry.get("nochesSinDato", 0) + 1
                    entry["ultimoIntentoEnvio"] = today
                if entry["nochesSinDato"] >= 3:
                    reason = "sin_dato_3_noches"
                else:
                    remaining.append(entry)
                    print(alta_line(entry, "pendiente_envio",
                                    item.get("motivo") or "sin_dato", item), flush=True)
                    continue
            rejected[entry["asin"]] = {"fecha": today, "motivo": reason,
                                       "texto": str(item.get("text") or item.get("motivo") or "")[:160]}
            rejected_count += 1
            print(alta_line(entry, "rechazada", reason, item), flush=True)
        # Guardar decisiones antes de quitar pendientes permite retomar sin perder altas.
        write_atomic(output / "altas-rechazadas.json", rejected)
        if promoted:
            write_atomic(output / "catalog-auto.json", automatic + promoted)
        write_atomic(output / "altas-pendientes.json", remaining)
    stamp = datetime.now(ART).strftime("%Y-%m-%d %H:%M:%S")
    print(f"{stamp} ALTAS_OK promovidas={len(promoted)} rechazadas={rejected_count} "
          f"siguen_pendientes={len(remaining)}", flush=True)
    return {"promovidas": len(promoted), "rechazadas": rejected_count, "siguen_pendientes": len(remaining)}


def main():
    import worker
    output = worker.resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent
    sys.stdout = worker.DailyLog(output / "logs", sys.stdout)
    sys.stderr = worker.DailyLog(output / "logs", sys.stderr)
    catalog = worker.resolve_path(os.environ.get("CATALOG_PATH", "../data/catalog.json"))
    confirm(catalog, output)


if __name__ == "__main__":
    main()
