"""Resumen por escalón de las mediciones en /app/output/limites (sin la carpeta previo/)."""
import collections
import glob
import json

for f in sorted(glob.glob("/app/output/limites/*.jsonl")):
    pasos = collections.OrderedDict()
    for linea in open(f, encoding="utf-8"):
        r = json.loads(linea)
        p = pasos.setdefault(r["paso"], {"n": 0, "items": 0, "ok": 0, "vac": 0, "err": collections.Counter(),
                                         "http": collections.Counter(), "lat": [], "desde": r["hora"][11:19]})
        p["n"] += 1
        p["items"] += r.get("pedidos_items", 1)
        p["ok"] += r.get("ok", 0)
        p["vac"] += r.get("vacias", 0)
        p["lat"].append(r.get("lat_ms") or 0)
        p["http"][str(r.get("http"))] += 1
        p["hasta"] = r["hora"][11:19]
        if r.get("error"):
            p["err"][r["error"]] += 1
    print(f.rsplit("/", 1)[-1])
    for k, p in pasos.items():
        lat = sorted(p["lat"])
        print(f"  {k:32} {p['desde']}-{p['hasta']} pedidos={p['n']} items={p['items']} ok={p['ok']} "
              f"vacias={p['vac']} http={dict(p['http'])} err={dict(p['err'])} lat_med={lat[len(lat) // 2]}ms")
for f in sorted(glob.glob("/app/output/limites/*.latido")):
    print("latido", f.rsplit("/", 1)[-1], open(f, encoding="utf-8").read().strip())
