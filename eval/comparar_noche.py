"""Compara cada par nocturno contra main y el validador local, sin red.

Uso: python -I -X utf8 eval/comparar_noche.py
"""
import contextlib
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "worker"), str(ROOT)]
from tools import match_candidates as matching

MEP = 1587.9
E = ROOT / "eval"


def read_inputs(timeout=600):
    """Espera archivos completos si la descarga todavía está en curso."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            rows = json.loads((E / "discovery-noche-2026-11-07.json").read_text(encoding="utf-8"))
            cache = json.loads((E / "ml-products-cache-noche.json").read_text(encoding="utf-8"))
            if not isinstance(rows, list) or not isinstance(cache, dict):
                raise ValueError("La entrada debe ser una lista y el caché un diccionario")
            missing = {c["catalogId"] for row in rows for c in row.get("ml", [])} - cache.keys()
            if missing:
                raise ValueError(f"Faltan {len(missing)} fichas en el caché")
            return rows, cache
        except (OSError, ValueError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"No se pudo completar la comparación nocturna: {exc}") from exc
            print(f"{datetime.now(timezone.utc).isoformat()} Esperando archivos nocturnos: {exc}", flush=True)
            time.sleep(min(20, max(0, deadline - time.monotonic())))


def load_baseline():
    # La comparación local no necesita credenciales ni configuración personal de Git.
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull)
    source = subprocess.run(["git", "show", "main:tools/match_candidates.py"], cwd=ROOT,
                            env=env, check=True, capture_output=True, encoding="utf-8").stdout
    old = types.ModuleType("match_candidates_main")
    old.__file__ = str(ROOT / "tools" / "match_candidates.py")
    exec(compile(source, old.__file__, "exec"), old.__dict__)
    return old


def compare(rows, cache, old, new):
    changes = []
    for row in rows:
        for candidate in row.get("ml", []):
            product = cache[candidate["catalogId"]]
            before = old.evaluate(row, candidate, product, MEP)
            after = new.evaluate(row, candidate, product, MEP)
            if before[0] != after[0]:
                changes.append({"old": before[0], "new": after[0],
                    "amazonTitle": row.get("amazonTitle", ""),
                    "mlName": product.get("name") or candidate.get("name", ""),
                    "catalogId": candidate["catalogId"],
                    "reason": {"old": before[1], "new": after[1]}})
    return changes


def main():
    rows, cache = read_inputs()
    old = load_baseline()
    # Fallar si por un cambio futuro se intenta salir a la red.
    def no_network(*args, **kwargs):
        raise AssertionError("La comparación nocturna no permite consultas de red")
    matching.ml_prices.get_json = no_network
    with contextlib.redirect_stdout(io.StringIO()):
        before = old.match_products(rows, MEP, [], products_cache=cache)
        after = matching.match_products(rows, MEP, [], products_cache=cache)
    print(f"Entrada: {len(rows)} productos; {sum(len(r.get('ml', [])) for r in rows)} pares; MEP {MEP}")
    print("Resumen anterior:", json.dumps(before["summary"], ensure_ascii=False, sort_keys=True))
    print("Resumen nuevo:", json.dumps(after["summary"], ensure_ascii=False, sort_keys=True))
    changes = compare(rows, cache, old, matching)
    print("Pares con cambio de estado:", len(changes))
    for change in changes:
        print(json.dumps(change, ensure_ascii=False))


if __name__ == "__main__":
    main()
