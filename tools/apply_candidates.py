#!/usr/bin/env python3
"""Aplica pares aprobados de Amazon + Mercado Libre al catálogo (data/catalog.json).

Valida slugs (kebab-case y únicos), ASINs únicos y categorías existentes antes de escribir.
Con --dry-run muestra los cambios que haría sin modificar el archivo.

Uso:
  python tools/apply_candidates.py approved.json --dry-run
  docker exec -i franquicia400-weboffers-worker-1 python /app/tools/apply_candidates.py /app/output/approved.json --catalog /data/catalog.json
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
ART = timezone(timedelta(hours=-3))
KEBAB_CASE_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AFFILIATE_QUERY = "matt_word=ale_benzoni&matt_tool=58527537"

REQUIRED_STRING_FIELDS = (
    "asin",
    "store",
    "catalogId",
    "itemId",
    "slug",
    "name",
    "brand",
    "category",
    "summary",
)


def default_catalog_path():
    repo_catalog = ROOT / "data" / "catalog.json"
    if repo_catalog.exists():
        return str(repo_catalog)
    env_catalog = os.getenv("CATALOG_PATH")
    if env_catalog and Path(env_catalog).exists():
        return env_catalog
    if Path("/data/catalog.json").exists():
        return "/data/catalog.json"
    return str(repo_catalog)


def art_today(now=None):
    current = now or datetime.now(timezone.utc)
    return current.astimezone(ART).strftime("%Y-%m-%d")


def is_kebab_case(slug):
    return isinstance(slug, str) and bool(KEBAB_CASE_RE.match(slug))


def build_ml_url(catalog_id, item_id):
    return (
        f"https://www.mercadolibre.com.ar/p/{catalog_id}"
        f"?pdp_filters=item_id%3A{item_id}&{AFFILIATE_QUERY}"
    )


def validate_and_build_entries(catalog, candidates, today=None):
    """Valida los candidatos contra el catálogo existente y devuelve las nuevas entradas."""
    if not isinstance(catalog, list):
        raise ValueError("El catálogo debe ser una lista JSON.")
    if not isinstance(candidates, list):
        raise ValueError("La entrada de candidatos debe ser una lista JSON.")

    checked_date = today or art_today()
    existing_slugs = {
        entry["slug"].strip()
        for entry in catalog
        if isinstance(entry, dict) and isinstance(entry.get("slug"), str) and entry["slug"].strip()
    }
    existing_asins = {
        entry["asin"].strip()
        for entry in catalog
        if isinstance(entry, dict) and isinstance(entry.get("asin"), str) and entry["asin"].strip()
    }
    valid_categories = {
        entry["category"].strip()
        for entry in catalog
        if isinstance(entry, dict) and isinstance(entry.get("category"), str) and entry["category"].strip()
    }

    seen_slugs = set()
    seen_asins = set()
    built = []

    for idx, raw in enumerate(candidates):
        if not isinstance(raw, dict):
            raise ValueError(f"Candidato #{idx}: debe ser un objeto JSON.")

        for field in REQUIRED_STRING_FIELDS:
            val = raw.get(field)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"Candidato #{idx}: el campo '{field}' es obligatorio y no puede estar vacío.")

        asin = raw["asin"].strip()
        store = raw["store"].strip()
        catalog_id = raw["catalogId"].strip()
        item_id = raw["itemId"].strip()
        slug = raw["slug"].strip()
        name = raw["name"].strip()
        brand = raw["brand"].strip()
        category = raw["category"].strip()
        summary = raw["summary"].strip()
        ml_price = raw.get("mlPrice")

        if not is_kebab_case(slug):
            raise ValueError(f"Candidato '{slug}': el slug debe estar en formato kebab-case (ej. 'mi-producto-1').")
        if slug in existing_slugs:
            raise ValueError(f"Candidato '{slug}': el slug ya existe en el catálogo.")
        if slug in seen_slugs:
            raise ValueError(f"Candidato '{slug}': el slug está duplicado en la lista de candidatos.")

        if asin in existing_asins:
            raise ValueError(f"Candidato '{slug}': el ASIN '{asin}' ya existe en el catálogo.")
        if asin in seen_asins:
            raise ValueError(f"Candidato '{slug}': el ASIN '{asin}' está duplicado en la lista de candidatos.")

        if category not in valid_categories:
            sorted_cats = ", ".join(sorted(valid_categories))
            raise ValueError(
                f"Candidato '{slug}': la categoría '{category}' no existe en el catálogo. "
                f"Categorías válidas: {sorted_cats}"
            )

        if (
            not isinstance(ml_price, (int, float))
            or isinstance(ml_price, bool)
            or not math.isfinite(ml_price)
            or ml_price <= 0
        ):
            raise ValueError(f"Candidato '{slug}': mlPrice inválido ({ml_price!r}).")

        seen_slugs.add(slug)
        seen_asins.add(asin)

        built.append({
            "asin": asin,
            "store": store,
            "slug": slug,
            "name": name,
            "brand": brand,
            "category": category,
            "summary": summary,
            "verified": True,
            "ml": {
                "price": int(round(ml_price)),
                "url": build_ml_url(catalog_id, item_id),
                "checked": checked_date,
                "catalogId": catalog_id,
            },
        })

    return built


def apply_candidates(catalog_path, candidates, dry_run=False, today=None):
    """Valida e incorpora los candidatos aprobados en catalog_path."""
    cat_file = Path(catalog_path)
    catalog = json.loads(cat_file.read_text(encoding="utf-8"))
    if isinstance(candidates, (str, Path)):
        candidates = json.loads(Path(candidates).read_text(encoding="utf-8"))

    new_entries = validate_and_build_entries(catalog, candidates, today=today)

    if dry_run:
        print(
            f"[DRY-RUN] Se agregarían {len(new_entries)} productos a {cat_file} "
            f"(total pasaría de {len(catalog)} a {len(catalog) + len(new_entries)}):",
            flush=True,
        )
        for entry in new_entries:
            print(
                f"  + {entry['slug']} (ASIN {entry['asin']}, {entry['category']}, "
                f"ML ${entry['ml']['price']} / {entry['ml']['catalogId']})",
                flush=True,
            )
        return new_entries

    updated = [*catalog, *new_entries]
    cat_file.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"Se agregaron {len(new_entries)} productos a {cat_file} (total={len(updated)}).",
        flush=True,
    )
    return new_entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input_pos", nargs="?", default=None, help="Ruta al JSON de candidatos aprobados")
    parser.add_argument("--input", "-i", dest="input_opt", default=None, help="Ruta al JSON de candidatos aprobados")
    parser.add_argument("--catalog", default=default_catalog_path(), help="Ruta a data/catalog.json")
    parser.add_argument("--dry-run", action="store_true", help="Muestra qué cambiaría sin modificar el catálogo")
    parser.add_argument("--today", default=None, help="Fecha YYYY-MM-DD para ml.checked (default: hoy ART)")
    args = parser.parse_args(argv)

    input_path = args.input_opt or args.input_pos
    if not input_path:
        parser.error("Debés indicar el archivo JSON de candidatos (posicional o con --input).")

    try:
        apply_candidates(
            catalog_path=args.catalog,
            candidates=input_path,
            dry_run=args.dry_run,
            today=args.today,
        )
    except ValueError as exc:
        print(f"Error de validación: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
