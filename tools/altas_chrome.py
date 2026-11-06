"""Lista ASIN para Chrome y fusiona su relevamiento sin pisar los otros productos."""
import argparse
import io
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alta_state import read_json, update_state
from article_log import chrome_line
from catalog import load_catalog
from publish import write_atomic
from tools.confirmar_altas import chrome_today


def asin_list(catalog_path, output, pending_only=False):
    output = Path(output)
    pending = read_json(output / "altas-pendientes.json", [])
    catalog = [] if pending_only else load_catalog(catalog_path, output / "catalog-auto.json")
    slugs = {}
    for entry in catalog + pending:
        if (entry.get("verified") and entry.get("asin") and entry.get("store") == "US"
                and (entry.get("ml") or {}).get("catalogId")):
            names = slugs.setdefault(entry["asin"], [])
            if entry["slug"] not in names:
                names.append(entry["slug"])
    return " ".join(asin + ":" + ",".join(names) for asin, names in slugs.items())


def merge_chrome(output, today, incoming):
    """Fusiona sólo la evidencia recibida; conserva los demás ASIN y metadatos."""
    output = Path(output)
    chrome_today(incoming, today)

    def merge():
        path = output / f"ar-chrome-{today}.json"
        previous = read_json(path, None)
        if previous is not None:
            chrome_today(previous, today)
        merged = {**(previous or {}), **incoming,
                  "items": {**((previous or {}).get("items") or {}), **incoming["items"]}}
        write_atomic(path, merged)
        return merged

    return update_state([], output / "ar-chrome.json", merge)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("listar", "guardar"))
    parser.add_argument("--pendientes", action="store_true")
    parser.add_argument("--fecha")
    args = parser.parse_args()
    output = Path("/app/output")
    if args.accion == "listar":
        print(asin_list("/app/data/catalog.json", output, args.pendientes))
    else:
        from worker import DailyLog
        data = json.load(sys.stdin)
        merge_chrome(output, args.fecha, data)
        log = DailyLog(output / "logs", io.StringIO())
        entries = load_catalog("/app/data/catalog.json", output / "catalog-auto.json")
        entries += read_json(output / "altas-pendientes.json", [])
        for asin, item in data["items"].items():
            slugs = [p["slug"] for p in entries if p.get("asin") == asin]
            log.write(chrome_line(slugs, asin, item) + "\n")
        items = list(data["items"].values())
        print(f"ENVIO_AR_CHROME_OK productos={len(items)} segundos={data.get('segundos')} "
              f"envia={sum(x.get('ships') is True for x in items)} "
              f"gratis={sum(x.get('free') is True for x in items)} "
              f"no_envia={sum(x.get('ships') is False for x in items)} "
              f"sin_dato={sum(x.get('ships') is None for x in items)}", flush=True)


if __name__ == "__main__":
    main()
