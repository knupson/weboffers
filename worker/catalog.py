"""Catálogo persistente: las entradas del repositorio tienen prioridad."""
import json
from pathlib import Path


def merge_catalogs(repo, automatic):
    merged = list(repo)
    asins = {p.get("asin") for p in repo if p.get("asin")}
    slugs = {p.get("slug") for p in repo if p.get("slug")}
    for entry in automatic:
        if entry.get("asin") in asins or entry.get("slug") in slugs:
            continue
        merged.append(entry)
        if entry.get("asin"):
            asins.add(entry["asin"])
        if entry.get("slug"):
            slugs.add(entry["slug"])
    return merged


def read_catalog(path):
    entries = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(entries, list) or any(not isinstance(p, dict) for p in entries):
        raise ValueError("El catálogo debe ser una lista de productos.")
    return entries


def load_catalog(repo_path, auto_path):
    return merge_catalogs(read_catalog(repo_path), read_catalog(auto_path) if Path(auto_path).exists() else [])
