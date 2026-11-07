"""CLI sin scheduler; el encadenado se implementa en la tarea 10."""
import argparse
import json
import sys
import traceback
from pathlib import Path
from .config import Config, load_config
from .events import emit_event, observe_run
from .runner import run_all
from .ml_lookup import run_ml_lookup


def main(argv=None):
    parser = argparse.ArgumentParser(description="Barrido diario de productos")
    parser.add_argument("--categories")
    parser.add_argument("--store", choices=("US", "ES"), action="append")
    parser.add_argument("--step", choices=("amazon", "ml-lookup"), default="amazon")
    parser.add_argument("--date", help="Fecha ART AAAA-MM-DD; sólo se consulta el día actual")
    parser.add_argument("--limit", type=int, help="Cantidad máxima de productos para ml-lookup")
    parser.add_argument("--category", action="append", help="ID explícito del archivo de categorías")
    parser.add_argument("--output", default="/app/output/barrido")
    parser.add_argument("--catalog", default="/app/data/catalog.json")
    parser.add_argument("--catalog-auto", help="Catálogo automático; por defecto junto al directorio del barrido")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--refresh-refinements", action="store_true")
    parser.add_argument("--max-pages", type=int)
    for key, default in vars(Config()).items():
        parser.add_argument("--" + key.replace("_", "-"), type=int if key in ("consecutive_blocks", "variation_limit", "transient_retries", "ml_consecutive_429") else float, default=default)
    args = parser.parse_args(argv)
    try:
        config = Config(**{key: getattr(args, key) for key in vars(Config())})
    except ValueError:
        with observe_run(args.output, Config(), vars(args)) as runtime:
            runtime.result_status = 'failed'
            emit_event('BARRIDO_EXCEPCION', traceback=traceback.format_exc())
        return 1
    with observe_run(args.output, config, {'argv': list(argv) if argv is not None else sys.argv[1:], **vars(args)}) as runtime:
        code = execute(args, config)
        runtime.result_status = 'complete' if code == 0 else 'failed'
        return code


def execute(args, config):
    try:
        if not args.dry_run and (config.min_usd, config.max_usd) != (Config().min_usd, Config().max_usd):
            raise ValueError("--min-usd/--max-usd sólo se permiten con --dry-run")
        if args.step == "ml-lookup":
            if args.store or args.category:
                raise ValueError("ml-lookup usa los JSONL de US y ES; no admite store ni category")
            result = run_ml_lookup(config, args.output, date=args.date, limit=args.limit, dry_run=args.dry_run)
            return 0 if result["status"] == "complete" else 1
        if args.limit is not None:
            raise ValueError("--limit sólo se admite con --step ml-lookup")
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
        auto_catalog = Path(args.catalog_auto) if args.catalog_auto else Path(args.output).parent / 'catalog-auto.json'
        for path in dict.fromkeys((catalog, auto_catalog)):
            if path.exists():
                for product in json.loads(path.read_text(encoding="utf-8")):
                    known.update(filter(None, (product.get("asin"), (product.get("ml") or {}).get("catalogId"))))
        result = run_all(categories, config, args.output, stores=args.store, dry_run=args.dry_run,
                         date=args.date, refresh=args.refresh_refinements, max_pages=args.max_pages, known=known)
        return 0 if all(item["status"] in ("complete", "skipped") for item in result.values()) else 1
    except Exception as exc:
        emit_event('BARRIDO_EXCEPCION', traceback=traceback.format_exc())
        emit_event("BARRIDO_FALLA", tipo=type(exc).__name__, motivo=str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
