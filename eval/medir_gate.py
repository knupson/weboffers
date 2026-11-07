"""Mide el filtro con entradas offline, sin consultar ni completar identificadores."""
import contextlib
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "worker"), str(ROOT)]
from tools import match_candidates as matching
from tools.identifier_gate import ML_FIELDS, strong_identifier_match

MEP = 1587.9
EVAL = ROOT / "eval"


def read(name):
    return json.loads((EVAL / name).read_text(encoding="utf-8"))


def report(name, inputs, accepted, labels=None):
    automatic = [row for row in accepted if strong_identifier_match(row)]
    amazon_ids = sum(bool(row.get("amazonIds")) for row in inputs)
    print(f"{name}: entradas={len(inputs)} aceptados={len(accepted)} "
          f"automaticos={len(automatic)} revision={len(accepted) - len(automatic)}")
    print(f"Identificadores Amazon presentes: {amazon_ids}/{len(inputs)}; "
          f"aceptados con identificadores ML: {sum(bool(r.get('mlIds')) for r in accepted)}/{len(accepted)}.")
    if amazon_ids < len(inputs):
        print("Faltan identificadores Amazon en las entradas offline: llegan después desde /ar-shipping. "
              "Estos resultados no miden el rendimiento con esos datos; el filtro se valida con pruebas unitarias.")
    if labels is not None:
        wrong = [row["id"] for row in automatic if labels[row["id"]] == "distinto"]
        print(f"Banco etiquetado: distinto automaticos={len(wrong)}; ids={wrong}")
        return len(wrong)
    return 0


def main():
    print(f"MEP={MEP}")
    # Impedir que un faltante del caché provoque una consulta de red silenciosa.
    with patch.object(matching.ml_prices, "get_json", side_effect=AssertionError("Falta ficha offline")):
        night = read("discovery-noche-2026-11-07.json")
        with contextlib.redirect_stdout(io.StringIO()):
            result = matching.match_products(night, MEP, products_cache=read("ml-products-cache-noche.json"))
        report("Noche", night, result["accepted"])

        pairs, cache = read("pares.json"), read("ml-products-cache.json")
        labels = {row["id"]: row["etiqueta"] for row in read("etiquetas.json")}
        # pares.json omite tienda, categoría, marca Amazon e itemId: recuperarlos
        # del descubrimiento original evita inventar enlaces o alterar la aceptación.
        source = read("discovery-desde-ml.json")
        origins = {(row.get("amazonTitle", "").strip(), candidate.get("catalogId")): (row, candidate)
                   for row in source for candidate in row.get("ml", [])}
        accepted = []
        missing = []
        missing_origin = []
        for pair in pairs:
            if pair["catalogId"] not in cache:
                missing.append(pair["id"])
                continue
            origin = origins.get((pair["amazon"].strip(), pair["catalogId"]))
            if origin is None:
                missing_origin.append(pair["id"])
                continue
            amazon, candidate = origin
            amazon = dict(amazon)
            if str(amazon.get("amazonCategory", "")).startswith("ml:"):
                amazon["amazonCategory"] = amazon["amazonTitle"]
            product = cache[pair["catalogId"]]
            status, _, _ = matching.evaluate(amazon, candidate, product, MEP)
            if status == "accepted":
                attrs = matching.attributes(product)
                accepted.append({**pair, "amazonIds": amazon.get("amazonIds") or {},
                                 "mlIds": {key: value for key, value in attrs.items() if key in ML_FIELDS}})
        print("Banco: metadatos originales de eval/discovery-desde-ml.json; se evalúa cada par explícito sin inventar enlaces.")
        print(f"Pares sin ficha offline: {len(missing)}; ids={missing}")
        print(f"Pares sin metadatos de origen: {len(missing_origin)}; ids={missing_origin}")
        wrong = report("Banco", pairs, accepted, labels)
    return int(bool(wrong))


if __name__ == "__main__":
    raise SystemExit(main())
