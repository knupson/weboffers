"""Inspección del banco local, sin red ni modificaciones de etiquetas."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "worker"), str(ROOT)]
from tools import match_candidates as match

E = ROOT / "eval"
rows = json.loads((E / "discovery-desde-ml.json").read_text(encoding="utf-8"))
cache = json.loads((E / "ml-products-cache.json").read_text(encoding="utf-8"))
pairs = json.loads((E / "pares.json").read_text(encoding="utf-8"))
labels = {p["id"]: p for p in json.loads((E / "etiquetas.json").read_text(encoding="utf-8"))}
for pair in pairs:
    if labels[pair["id"]]["etiqueta"] != "mismo" and pair["id"] != 40:
        continue
    for row in rows:
        if row.get("amazonTitle", "").strip() != pair["amazon"].strip():
            continue
        row = dict(row)
        if str(row.get("amazonCategory", "")).startswith("ml:"):
            row["amazonCategory"] = row["amazonTitle"]
        for candidate in row.get("ml", []):
            product = cache.get(candidate["catalogId"], {})
            if (product.get("name") or candidate.get("name", "")).strip() != pair["ml"].strip():
                continue
            status, reason, evidence = match.evaluate(row, candidate, product, 1587.9)
            if status == "accepted" and pair["id"] != 40:
                continue
            attrs = match.attributes(product)
            print(json.dumps({"id": pair["id"], "estado": status, "motivo": reason,
                "amazon": row["amazonTitle"], "marca": row.get("brand"), "categoria": row.get("amazonCategory"),
                "ml": product.get("name"), "atributos": {k:v for k,v in attrs.items() if k in
                    {"BRAND", "MODEL", "ALPHANUMERIC_MODEL", "LINE", "CAPACITY", "RAM_MEMORY", "SCREEN_SIZE", "COLOR"}},
                "modelos": [sorted(match.model_tokens(row["amazonTitle"])), sorted(match.model_tokens(product.get("name", "") + " " + attrs.get("MODEL", "") + " " + attrs.get("ALPHANUMERIC_MODEL", "")))],
                "variantes": [sorted(match.variant_words(row["amazonTitle"])), sorted(match.variant_words(product.get("name", "") + " " + attrs.get("MODEL", "") + " " + attrs.get("LINE", "")))],
                "etiqueta": labels[pair["id"]]}, ensure_ascii=False))
