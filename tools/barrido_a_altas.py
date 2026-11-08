"""Barrido nuevo -> cola de altas de siempre (08/11/2026).

Lee lo que dejó el barrido (US-<fecha>.jsonl + ml-candidatos-<fecha>.jsonl), arma los pares en el formato
de discover_products ({asin, store, amazonTitle, brand, amazonCategory, amazonPriceUsd, ml:[...]}) y los
pasa por las MISMAS funciones del alta nocturna: tools.match_candidates.match_products (valida marca,
modelo y precio) y catalog_auto.add_accepted (foto, cola altas-pendientes.json). No publica nada: la
cadena tras-alta (confirmar envío en Chrome, precios del día, deploy) se dispara con alta-terminada.json,
como en el alta nocturna. Corre dentro del contenedor del worker:

  docker exec -i -w /app/worker franquicia400-weboffers-worker-1 python - <dir barrido> [--seco] < tools/barrido_a_altas.py
"""
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, "/app/worker")
sys.path.insert(0, "/app")
import requests  # noqa: E402

import catalog_auto  # noqa: E402
from alta_state import read_json  # noqa: E402
from catalog import load_catalog  # noqa: E402
import ml_prices  # noqa: E402
from tools import match_candidates as matching  # noqa: E402

ART = timezone(timedelta(hours=-3))


def log(msg):
    print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} BARRIDO_A_ALTAS {msg}", flush=True)


def productos(barrido, fecha):
    us = {}
    for line in (barrido / f"US-{fecha}.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        us[row["id"]] = row
    out = []
    for line in (barrido / f"ml-candidatos-{fecha}.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        amazon = us.get(rec.get("asin"))
        if not amazon or amazon.get("eligible") is not True or not rec.get("candidates"):
            continue
        prov = amazon.get("provenance")
        prov = prov[0] if isinstance(prov, list) and prov else (prov or {})
        out.append({
            "asin": amazon["id"], "store": "US", "amazonTitle": amazon.get("title") or "",
            "brand": (amazon.get("raw") or {}).get("brand") or "",
            "amazonCategory": prov.get("category_name") or "",
            "amazonPriceUsd": amazon.get("price_usd"),
            "ml": [{"catalogId": c["catalogId"], "name": c.get("name") or "", "minPrice": c.get("price_ars"),
                    "itemId": c.get("itemId") or ""} for c in rec["candidates"]],
        })
    return out


def main(argv):
    seco = "--seco" in argv
    barrido = Path([a for a in argv if not a.startswith("--")][0])
    fecha = datetime.now(ART).date().isoformat()
    output = Path("/app/output")
    pares = productos(barrido, fecha)
    log(f"INICIO fecha={fecha} pares_con_candidato={len(pares)} seco={seco}")
    if not pares:
        log("FIN sin pares: nada que cargar")
        return 0
    mep = requests.get("https://dolarapi.com/v1/dolares/bolsa", timeout=20).json()["venta"]
    catalog = load_catalog(Path("/app/data/catalog.json"), output / "catalog-auto.json")
    pending = read_json(output / "altas-pendientes.json", [])
    existentes = {p.get("asin") for p in catalog + pending}
    pares = [p for p in pares if p["asin"] not in existentes]
    log(f"MEP={mep} catalogo={len(catalog)} pendientes={len(pending)} pares_nuevos={len(pares)}")
    if not ml_prices.is_configured():
        log("FALLA faltan credenciales de ML")
        return 1
    matches = matching.match_products(pares, mep, catalog + pending)
    log(f"MATCHEO aceptados={len(matches['accepted'])} dudosos={len(matches['doubtful'])} rechazados={len(matches['rejected'])}")
    for row in matches["accepted"]:
        log(f"ACEPTADO {row['asin']} -> {row['catalogId']} | {row.get('amazonTitle', '')[:60]} | ML {row.get('mlName', '')[:60]}")
    if seco:
        log("FIN seco: no se escribe la cola")
        return 0
    added, failures = catalog_auto.add_accepted(catalog, matches, output, fecha)
    log(f"COLA pendientes_agregados={len(added)} fallas={len(failures)}")
    # Mismo aviso que el alta nocturna: dispara franquicia-tras-alta.path (confirma envío y despliega).
    (output / "alta-terminada.json").write_text(json.dumps(
        {"slot": f"{fecha}-barrido", "status": "ok", "added": len(added),
         "fin": datetime.now(ART).isoformat(timespec="seconds")}), encoding="utf-8")
    log(f"FIN alta-terminada.json escrito (added={len(added)})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
