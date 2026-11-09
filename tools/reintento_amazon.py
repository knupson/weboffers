# Reintento de Amazon SOLO para los productos sin precio de hoy (2.a corrida del dia, parcial).
# Corre dentro del contenedor: docker exec -i -w /app/worker franquicia400-weboffers-worker-1 python - < este_archivo
import json, datetime
from pathlib import Path
import amazon_prices as a, publish
import publicacion

catalog = json.load(open("/app/data/catalog.json", encoding="utf-8"))
path = "/app/output/amazon-prices.json"
prev = json.load(open(path, encoding="utf-8"))
hoy = datetime.datetime.now(a.ART).date().isoformat()
assert prev.get("date") == hoy, "el archivo no es de hoy"
items = prev["items"]
# 08/11: mismos requisitos que la cadena (worker/requisitos.py) y nada que el Chrome de hoy vio sin envío gratis.
from requisitos import motivo_total, modo_actual
estado = publicacion.cargar(Path(path).parent)
modo = modo_actual()
sin_gratis = a.chrome_sin_envio_gratis(path, hoy)
cands = [p for p in catalog if not motivo_total(p, estado, hoy, modo, tuple(a.STORE_CURRENCY)) and p["slug"] not in items
         and not (p.get("store") == "US" and p.get("asin") in sin_gratis)]
print("faltaban:", len(cands), flush=True)
base = a.scraper_url()
ok = 0
for store in sorted({p["store"] for p in cands}):
    lst = [p for p in cands if p["store"] == store]
    for i in range(0, len(lst), a.BULK_MAX):
        chunk = lst[i:i + a.BULK_MAX]
        a.pause()
        try:
            got = a.fetch_bulk(base, [p["asin"] for p in chunk], store)
        except Exception as e:
            print("lote fallido", store, type(e).__name__, flush=True)
            got = {}
        for p in chunk:
            parsed = a.valid_price(got.get(p["asin"]), store)
            if parsed is not None and not a.plausible(parsed, p):
                parsed = None
            if parsed is not None:
                items[p["slug"]] = {"amount": parsed[0], "currency": parsed[1], "checked": hoy}
                ok += 1
publish.write_atomic(path, {**prev, "items": items})
print(f"REINTENTO_AMAZON recuperados={ok} de {len(cands)}; total con precio hoy={len(items)}", flush=True)
