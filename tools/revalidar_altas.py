"""Re-valida los pares ya descubiertos (sin volver a consultar Amazon) y da de alta los aceptados (05/11).

Dentro del worker:  python /app/tools/revalidar_altas.py
Lee output/discovery-candidates.json y output/discovery-desde-ml.json; corrige la categoría de los que vienen de ML
(antes "ml:<id>", que el validador no reconoce) y corre el mismo validador y la misma alta que catalog_auto.
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "/app/worker")
sys.path.insert(0, "/app")
import catalog_auto  # noqa: E402
import publish  # noqa: E402
import rates  # noqa: E402
from catalog import load_catalog, read_catalog  # noqa: E402
from tools import match_candidates as matching  # noqa: E402

out = Path("/app/output")
hoy = datetime.now(timezone(timedelta(hours=-3))).date().isoformat()
mep = (rates.get_rates() or {}).get("mep")
productos = []
for nombre in ("discovery-candidates.json", "discovery-desde-ml.json"):
    p = out / nombre
    if p.exists():
        for row in json.loads(p.read_text(encoding="utf-8")):
            if str(row.get("amazonCategory", "")).startswith("ml:"):
                row["amazonCategory"] = row.get("amazonTitle") or ""
            productos.append(row)
auto_path = out / "catalog-auto.json"
previos = read_catalog(auto_path) if auto_path.exists() else []
catalogo = load_catalog("/app/data/catalog.json", auto_path)
res = matching.match_products(productos, mep, catalogo)
publish.write_atomic(out / "match-results.json", res)
print("pares", len(productos), {k: len(v) for k, v in res.items() if isinstance(v, list)})
print("dudas", Counter(r.get("reason") for r in res.get("doubtful", [])).most_common(6))
altas, fallas = catalog_auto.add_accepted(catalogo, res, out, hoy)
publish.write_atomic(auto_path, previos + altas)
print("altas", len(altas), [a["slug"] for a in altas], "fallas", fallas)
