"""CLI sin scheduler; el encadenado se implementa en la tarea 10."""
import argparse
import json
from pathlib import Path
from .config import Config, load_config
from .events import emit_event
from .runner import run_all


def main(argv=None):
    parser = argparse.ArgumentParser(description="Barrido diario de productos")
    parser.add_argument("--categories")
    parser.add_argument("--store", choices=("US", "ES", "ML"), action="append")
    parser.add_argument("--category", action="append", help="ID explícito del archivo de categorías")
    parser.add_argument("--output", default="/app/output/barrido")
    parser.add_argument("--catalog", default="/app/data/catalog.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh-refinements", action="store_true")
    parser.add_argument("--max-pages", type=int)
    for key, default in vars(Config()).items():
        parser.add_argument("--" + key.replace("_", "-"), type=int if key in ("consecutive_blocks", "variation_limit") else float, default=default)
    args = parser.parse_args(argv)
    try:
        config = Config(**{key: getattr(args, key) for key in vars(Config())})
        categories = load_config(args.categories)
        if args.max_pages is not None and args.max_pages < 1:
            raise ValueError("max-pages debe ser positivo")
        if args.category:
            found = set()
            for definition in categories["stores"].values():
                definition["nodes"] = [node for node in definition["nodes"] if node["id"] in args.category]
                found.update(node["id"] for node in definition["nodes"])
            if found != set(args.category):
                raise ValueError("Hay categorías solicitadas que no están en el archivo")
        known = set()
        catalog = Path(args.catalog)
        if catalog.exists():
            for product in json.loads(catalog.read_text(encoding="utf-8")):
                known.update(filter(None, (product.get("asin"), product.get("mlCatalogId"))))
        result = run_all(categories, config, args.output, stores=args.store, dry_run=args.dry_run,
                         refresh=args.refresh_refinements, max_pages=args.max_pages, known=known)
        return 0 if all(item["status"] == "complete" for item in result.values()) else 1
    except Exception as exc:
        emit_event("BARRIDO_FALLA", tipo=type(exc).__name__, motivo=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
