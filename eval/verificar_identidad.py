"""Reproduce los cruces de identidad reportados, sin red.

Uso: python -I -X utf8 eval/verificar_identidad.py
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "worker"), str(ROOT)]
from tools import match_candidates as matching


def main():
    cases = json.loads((ROOT / "eval/regresiones-identidad.json").read_text(encoding="utf-8"))
    wrong = 0
    for case in cases:
        amazon = {"asin": "B000000001", "store": "US", "amazonTitle": case["title"],
                  "brand": case["amazon_brand"], "amazonCategory": case["category"], "amazonPriceUsd": 100}
        candidate = {"minPrice": 200000, "itemId": "MLA456"}
        product = {"name": case["name"], "attributes": [
            {"id": "BRAND", "value_name": case["brand"]}, {"id": "MODEL", "value_name": case["model"]}]}
        status, reason, _ = matching.evaluate(amazon, candidate, product, 1575)
        wrong += status == "accepted"
        print(f"{datetime.now(timezone.utc).isoformat()} caso {case['id']}: {status}; {reason}")
    print(f"Casos: {len(cases)}; aceptados erróneos: {wrong}")
    return bool(wrong)


if __name__ == "__main__":
    sys.exit(main())
