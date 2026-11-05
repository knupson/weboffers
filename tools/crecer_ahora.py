"""Corre el alta automática de productos AHORA, fuera de la ventana nocturna (05/11). Dentro del worker:
  docker exec -d -w /app/worker franquicia400-weboffers-worker-1 python /app/tools/crecer_ahora.py
Deja el resultado en output/catalog-auto-state.json y la línea CATALOGO_OK / DEPLOY_FAIL en el log del worker.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app/worker")
import catalog_auto  # noqa: E402
import rates  # noqa: E402
import worker  # noqa: E402  (redirige la salida al log diario persistente)

out = Path("/app/output")
sys.stdout = worker.DailyLog(out / "logs", sys.stdout)
mep = (rates.get_rates() or {}).get("mep")
print(f"Catálogo: alta forzada a pedido, MEP={mep}.", flush=True)
catalog_auto.maybe_grow("/app/data/catalog.json", out, datetime.now(timezone.utc), mep=mep, force=True)
