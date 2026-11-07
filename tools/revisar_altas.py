#!/usr/bin/env python3
"""Revisa pares sin identificador fuerte dentro del contenedor del worker.

docker exec -w /app/worker franquicia400-weboffers-worker-1 python /app/tools/revisar_altas.py listar
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
import catalog_auto
from alta_state import read_json, rejected_asins, update_state
from article_log import alta_line
from catalog import read_catalog
from ml_prices import item_url
from publish import write_atomic

ART = catalog_auto.ART


def stamp():
    return datetime.now(ART).strftime("%Y-%m-%d %H:%M:%S")


def pair_key(row):
    return f"{row['asin']}:{row['catalogId']}"


def review(catalog_path, output, action, pairs=(), reason="", as_json=False, today=None):
    output = Path(output)
    today = today or datetime.now(ART).date().isoformat()
    return update_state([], output / "altas.json",
                        lambda: _review(catalog_path, output, action, pairs, reason, as_json, today))


def _review(catalog_path, output, action, pairs, reason, as_json, today):
    queue_path = output / "altas-revision.json"
    queue = read_json(queue_path, [])
    if action == "listar":
        rows = []
        for index, row in enumerate(queue, 1):
            rows.append({**row, "index": index,
                         "mlName": row.get("mlName") or row.get("name"),
                         "amazonUrl": f"https://www.amazon.com/dp/{row['asin']}",
                         "mlUrl": item_url(row["catalogId"], row.get("itemId"))})
        if as_json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            fields = ("index", "asin", "catalogId", "amazonTitle", "mlName", "mlPrice",
                      "amazonPriceUsd", "revisionDesde", "amazonUrl", "mlUrl")
            for row in rows:
                print(" ".join(f"{key}={json.dumps(row.get(key), ensure_ascii=False)}" for key in fields))
        return 0

    pending_path = output / "altas-pendientes.json"
    rejected_path = output / "altas-rechazadas.json"
    pending = read_json(pending_path, [])
    rejected = read_json(rejected_path, {})
    catalog = (read_catalog(catalog_path) + read_json(output / "catalog-auto.json", [])
               if action == "aprobar" else [])
    excluded = rejected_asins(output, today)
    approved_count = rejected_count = 0
    failed = False
    for pair in dict.fromkeys(pairs):
        row = next((row for row in queue if pair_key(row) == pair), None)
        if row is None:
            print(f"{stamp()} REVISION_ERROR par={pair} motivo=par_desconocido", flush=True)
            failed = True
            continue
        if action == "aprobar":
            rejection = catalog_auto.pending_rejection(row, catalog + pending, excluded)
            evidence = {"precio": row.get("amazonPriceUsd")}
            try:
                entry = None if rejection else catalog_auto.build_pending(row, catalog + pending, output, today)
                if not rejection and entry is None:
                    rejection = "sin_foto"
            except (catalog_auto.requests.RequestException, OSError, ValueError, KeyError, TypeError) as exc:
                rejection = type(exc).__name__
                evidence["text"] = str(exc)
            if rejection:
                print(alta_line(row, "descartado", rejection, evidence), flush=True)
                failed = True
                continue
            entry.update(aprobadoPor="revision-claude", motivoAprobacion=reason)
            # Persistir el destino antes de quitar el origen, igual que confirmar_altas.
            write_atomic(pending_path, pending + [entry])
            pending.append(entry)
            approved_count += 1
            decision, motive = "pendiente_envio", "aprobada_en_revision"
        else:
            motive = "revision: " + reason
            rejected[row["asin"]] = {"fecha": today, "motivo": motive, "texto": ""}
            write_atomic(rejected_path, rejected)
            rejected_count += 1
            decision = "rechazada"
        queue = [other for other in queue if pair_key(other) != pair]
        write_atomic(queue_path, queue)
        print(alta_line(row, decision, motive, {"precio": row.get("amazonPriceUsd")}), flush=True)
    print(f"{stamp()} REVISION_OK aprobadas={approved_count} rechazadas={rejected_count} siguen={len(queue)}", flush=True)
    return int(failed)


def nonempty_reason(raw):
    if not raw.strip():
        raise argparse.ArgumentTypeError("El motivo no puede estar vacío.")
    return raw.strip()


def main(argv=None):
    import worker
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path,
                        default=worker.resolve_path(os.environ.get("CATALOG_PATH", "../data/catalog.json")))
    parser.add_argument("--output", type=Path,
                        default=worker.resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent)
    commands = parser.add_subparsers(dest="action", required=True)
    listing = commands.add_parser("listar", help="Lista los pares en revisión.")
    listing.add_argument("--json", action="store_true", dest="as_json")
    for action in ("aprobar", "rechazar"):
        command = commands.add_parser(action)
        command.add_argument("pairs", nargs="+", metavar="asin:catalogId")
        command.add_argument("--motivo", required=True, type=nonempty_reason)
    args = parser.parse_args(argv)
    return review(args.catalog, args.output, args.action, getattr(args, "pairs", ()),
                  getattr(args, "motivo", ""), getattr(args, "as_json", False))


if __name__ == "__main__":
    sys.exit(main())
