"""Corre el alta automática de productos AHORA, fuera de la ventana nocturna (05/11). Dentro del worker:
  docker exec -d -w /app/worker franquicia400-weboffers-worker-1 python /app/tools/crecer_ahora.py
Deja el resultado en output/catalog-auto-state.json y la línea CATALOGO_OK / DEPLOY_FAIL en el log del worker.
Los pares quedan en output/altas-pendientes.json. Para confirmar su envío durante
el día, el host ejecuta tools/confirmar_altas.sh (Chrome → promoción).
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "/app/worker")
import catalog_auto  # noqa: E402
import rates  # noqa: E402
import worker  # noqa: E402  (redirige la salida al log diario persistente)
import amazon_prices  # noqa: E402

# Pausa entre páginas de Amazon para esta corrida (s). Medido 05/11: 1.095 consultas sin pausa en 14 min, 0 cortes.
amazon_prices.PAUSE_SECONDS = float(os.getenv("CRECER_PAUSA_S", "5"))

out = Path("/app/output")
sys.stdout = worker.DailyLog(out / "logs", sys.stdout)
mep = (rates.get_rates() or {}).get("mep")
print(f"Catálogo: alta forzada a pedido, MEP={mep}.", flush=True)
catalog_auto.maybe_grow("/app/data/catalog.json", out, datetime.now(timezone.utc), mep=mep, force=True)
