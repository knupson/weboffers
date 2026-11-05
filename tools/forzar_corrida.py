"""Fuerza una corrida completa del día (Amazon + ML) como si fuera de madrugada (05/11, prueba punta a punta).

Corre DENTRO del worker: guarda copia de amazon-prices.json y ml-prices.json en output/forzado-<hora>/ y les
pone la fecha de ayer, así maybe_refresh vuelve a correr en el próximo ciclo (reiniciar el worker).
"""
import json
import os
import shutil
from datetime import datetime, timedelta, timezone

ART = timezone(timedelta(hours=-3))
ahora = datetime.now(ART)
ayer = (ahora - timedelta(days=1)).date().isoformat()
out = "/app/output"
copia = os.path.join(out, f"forzado-{ahora:%H%M%S}")
os.makedirs(copia)
for nombre in ("amazon-prices.json", "ml-prices.json"):
    p = os.path.join(out, nombre)
    shutil.copy2(p, copia)
    d = json.load(open(p, encoding="utf-8"))
    d["date"] = ayer
    d.pop("retried", None)
    json.dump(d, open(p + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
    os.replace(p + ".tmp", p)
    print("forzado", nombre, "-> date", ayer, "copia en", copia)
