"""Absorbe una copia local de output/; el catálogo y las fotos del repo mandan."""
import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
from catalog import load_catalog, read_catalog
import publish


def sync_catalog(output, root=ROOT):
    output, root = Path(output), Path(root)
    automatic = read_catalog(output / "catalog-auto.json")
    dest = root / "public" / "products"
    for entry in automatic:
        slug = entry.get("slug", "")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug):
            raise ValueError("Slug inválido en catalog-auto.json")
        source = output / "products" / f"{slug}.webp"
        target = dest / source.name
        if not target.is_file() and not source.is_file():
            raise ValueError(f"Falta la foto de {slug}.")
    dest.mkdir(parents=True, exist_ok=True)
    for source in (output / "products").glob("*.webp"):
        target = dest / source.name
        if not target.exists():
            data = source.read_bytes()
            with target.open("xb") as handle:
                handle.write(data)
    catalog_path = root / "data" / "catalog.json"
    catalog = load_catalog(catalog_path, output / "catalog-auto.json")
    publish.write_atomic(catalog_path, catalog)
    print(f"Catálogo sincronizado: {len(catalog)} productos.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    sync_catalog(parser.parse_args().output)
