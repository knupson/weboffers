"""Banco de prueba del validador de pares (05/11): mide contra un set etiquetado a mano.

Dentro del worker:
  python /app/tools/evaluar_validador.py <pares-origen.json> <pares-etiquetados.json> <etiquetas.json> [modulo.py]
- pares-origen: formato discover_products (con "ml": [...]).
- pares-etiquetados + etiquetas: set de prueba (amazon, ml, etiqueta mismo|distinto|duda).
- modulo.py (opcional): versión de match_candidates a probar (por defecto la instalada).
Salida: aceptados correctos/incorrectos y los «mismo» que no acepta, con su motivo.
"""
import importlib.util
import json
import sys
from collections import Counter

sys.path.insert(0, "/app/worker")
sys.path.insert(0, "/app")
import rates  # noqa: E402
from catalog import load_catalog  # noqa: E402

if len(sys.argv) > 4:
    spec = importlib.util.spec_from_file_location("match_candidates", sys.argv[4])
    matching = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matching)
else:
    from tools import match_candidates as matching  # noqa: E402

origen = json.load(open(sys.argv[1], encoding="utf-8"))
pares = {p["id"]: p for p in json.load(open(sys.argv[2], encoding="utf-8"))}
etiquetas = {e["id"]: e["etiqueta"] for e in json.load(open(sys.argv[3], encoding="utf-8"))}
for row in origen:
    if str(row.get("amazonCategory", "")).startswith("ml:"):
        row["amazonCategory"] = row.get("amazonTitle") or ""
mep = (rates.get_rates() or {}).get("mep")
catalogo = load_catalog("/app/data/catalog.json", "/app/output/catalog-auto.json")
res = matching.match_products(origen, mep, [])  # catálogo vacío: medir el criterio, no la deduplicación

decision = {}
for estado in ("accepted", "doubtful", "rejected"):
    for r in res.get(estado, []):
        decision[((r.get("amazonTitle") or "").strip(), (r.get("mlName") or "").strip())] = (estado, r.get("reason") or "")

conf, perdidos, malos = Counter(), [], []
for i, p in pares.items():
    clave = ((p.get("amazon") or "").strip(), (p.get("ml") or "").strip())
    if clave not in decision:
        conf[("no_reproducido", etiquetas.get(i))] += 1
        continue
    estado, motivo = decision[clave]
    conf[(estado, etiquetas.get(i))] += 1
    if etiquetas.get(i) == "mismo" and estado != "accepted":
        perdidos.append((estado, motivo, p["amazon"][:70], p["ml"][:60]))
    if etiquetas.get(i) == "distinto" and estado == "accepted":
        malos.append((p["amazon"][:70], p["ml"][:60]))
print("matriz (decisión, etiqueta):", dict(conf))
print("ACEPTADOS ERRÓNEOS (distinto aceptado):", len(malos))
for m in malos:
    print("   !!", m)
print("MISMO no aceptados:", len(perdidos))
for x in perdidos:
    print("   -", x)
