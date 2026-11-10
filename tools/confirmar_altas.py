#!/usr/bin/env python3
"""Promueve pendientes sólo con envío gratis y precio USD 100–400 vistos hoy en Chrome.

Corre dentro del worker, después del relevamiento del host. No consulta la red.
Los intentos sin dato cuentan una sola vez por fecha ART, incluso con reintentos.
"""
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from alta_state import duplicate, read_json, update_state
from article_log import alta_line
from catalog import load_catalog
from publish import write_atomic
import publicacion
from requisitos import motivo_total

ART = timezone(timedelta(hours=-3))
# Noches seguidas en que Chrome no llegó a un pendiente: pasado este tope se rechaza igual, con su propio motivo,
# para que un ASIN que nunca se releva no quede pendiente para siempre.
MAX_NOCHES_SIN_CORRIDA = 7


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
    estado = publicacion.cargar(output)
    pending = read_json(output / "altas-pendientes.json", [])
    remaining, promoted = [], []
    rejected_count = 0
    catalog = load_catalog(catalog_path, output / "catalog-auto.json")
    vencidos = 0
    data = read_json(output / f"ar-chrome-{today}.json", {})
    chrome_corrio = True
    try:
        data = chrome_today(data, today)
    except (ValueError, TypeError):
        data = {"items": {}}
        chrome_corrio = False
    manana = (date.fromisoformat(today) + timedelta(days=1)).isoformat()
    for entry in catalog:
        item = estado.get(entry["slug"])
        if not item or item["situacion"] != "no_revisar" or item["hasta"] > today:
            continue
        motivo = motivo_total(entry, estado, today, "alta")
        evidencia = data["items"].get(entry["asin"]) or {}
        if not motivo and entry["asin"] not in data["items"]:
            # F-19: Chrome no corrió o no llegó a este ASIN (caída de infraestructura, no un dato del producto).
            # No se estira la exclusión 7 días por algo que nadie miró: queda excluido hoy (sin evidencia no se
            # consulta ni se publica) y se vuelve a mirar manana.
            estado[entry["slug"]] = {**item, "hasta": manana, "motivo": "chrome_no_corrio"}
            print(alta_line(entry, "pospuesta", "chrome_no_corrio" if not chrome_corrio else "chrome_sin_el_asin",
                            evidencia), flush=True)
            continue
        if not motivo and not (evidencia.get("ships") is True and evidencia.get("free") is True):
            motivo = "sin_envio_gratis_chrome_hoy"
        if motivo:
            estado[entry["slug"]] = publicacion._entrada("no_revisar", today, motivo, entry["asin"])
            print(alta_line(entry, "rechazada", motivo, evidencia), flush=True)
        else:
            vencidos += 1
            print(alta_line(entry, "confirmada", "envio_gratis_chrome_hoy", evidencia), flush=True)
    publicacion.guardar(output, estado)
    if pending:
        # Se reutiliza el resultado ya validado arriba; sin relevamiento de hoy, todos los pendientes pasan por el mismo
        # contador persistido (nochesSinCorrida) que un ASIN al que Chrome no llegó, en vez de abortar sin contarlos.
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
            if (entry["asin"] not in data["items"] and not motivo_total(entry, estado, today, "alta", stores=("US",))
                    and entry.get("nochesSinCorrida", 0) < MAX_NOCHES_SIN_CORRIDA):
                # F-19: Chrome no llegó a este ASIN (se cortó o falló el paso); no cuenta como «noche sin dato».
                if entry.get("ultimoIntentoEnvio") != today:
                    entry["nochesSinCorrida"] = entry.get("nochesSinCorrida", 0) + 1
                    entry["ultimoIntentoEnvio"] = today
                remaining.append(entry)
                print(alta_line(entry, "sin_cambio", "chrome_no_corrio", item), flush=True)
                continue
            if ships is False:
                reason = "no_envia_ar"
            elif ships is True and free is False:
                reason = "envio_pago"
            elif ships is True and price is not None and not 100 <= price <= 400:
                reason = "precio_fuera_de_rango"
            elif ships is True and free is True and price is not None:
                built = {k: v for k, v in entry.items()
                         if k not in ("pendienteDesde", "nochesSinDato", "nochesSinCorrida", "ultimoIntentoEnvio")}
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
          f"siguen_pendientes={len(remaining)} vencidos={vencidos}", flush=True)
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
