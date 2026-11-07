"""Evaluador local del validador (sin contenedor): igual a tools/evaluar_validador.py con MEP fijo.
Uso (raíz del repo): python -I -X utf8 eval/evaluar_local.py [modulo.py]
Banco: eval/pares.json + eval/etiquetas.json (150 pares etiquetados, 05/11). Los cachés grandes no están en git:
copiar a eval/ desde E:/Repositorios/Personal/_datos/weboffers/eval-validador/ (ml-products-cache.json,
discovery-desde-ml.json; para comparar_noche.py también discovery-noche-*.json y ml-products-cache-noche.json).
Línea de base 07/11: antes 22 «mismo» aceptados y 1 erróneo (Starlink); después 29 y 0.
"""
import importlib.util, json, sys
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "worker"), str(ROOT)]
MEP = 1587.9  # MEP del 07/11 (match-results-2026-11-07.json)
if len(sys.argv) > 1:
    spec = importlib.util.spec_from_file_location("match_candidates", sys.argv[1]); matching = importlib.util.module_from_spec(spec); spec.loader.exec_module(matching)
else:
    from tools import match_candidates as matching
E = ROOT / "eval"
origen = json.load(open(E / "discovery-desde-ml.json", encoding="utf-8"))
pares = {p["id"]: p for p in json.load(open(E / "pares.json", encoding="utf-8"))}
etiquetas = {e["id"]: e["etiqueta"] for e in json.load(open(E / "etiquetas.json", encoding="utf-8"))}
for row in origen:
    if str(row.get("amazonCategory", "")).startswith("ml:"):
        row["amazonCategory"] = row.get("amazonTitle") or ""
cache = json.load(open(E / "ml-products-cache.json", encoding="utf-8"))  # fichas ML del banco (bajadas en la VM el 07/11)
res = matching.match_products(origen, MEP, [], products_cache=cache)
decision = {}
for estado in ("accepted", "doubtful", "rejected"):
    for r in res.get(estado, []):
        decision[((r.get("amazonTitle") or "").strip(), (r.get("mlName") or "").strip())] = (estado, r.get("reason") or "")
conf, perdidos, malos = Counter(), [], []
for i, p in pares.items():
    clave = ((p.get("amazon") or "").strip(), (p.get("ml") or "").strip())
    if clave not in decision:
        conf[("no_reproducido", etiquetas.get(i))] += 1; continue
    estado, motivo = decision[clave]; conf[(estado, etiquetas.get(i))] += 1
    if etiquetas.get(i) == "mismo" and estado != "accepted": perdidos.append((i, estado, motivo, p["amazon"][:70], p["ml"][:60]))
    if etiquetas.get(i) in ("distinto", "duda") and estado == "accepted": malos.append((i, etiquetas.get(i), p["amazon"][:70], p["ml"][:60]))
print("matriz (decisión, etiqueta):", dict(sorted(conf.items())))
print("ACEPTADOS ERRÓNEOS (distinto o duda aceptado):", len(malos)); [print("   !!", m) for m in malos]
print("MISMO no aceptados:", len(perdidos)); [print("   -", x) for x in perdidos]
