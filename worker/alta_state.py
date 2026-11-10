"""Estado compartido del alta: pendientes, rechazos y exclusión entre procesos."""
from datetime import date
import json
from pathlib import Path
import publicacion

from refresh_lock import locked_refresh


def read_json(path, default):
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def rejected_asins(output, today):
    """El rechazo vence al cumplir 7 días; no excluye otros ASIN del mismo modelo."""
    rejected = read_json(Path(output) / "altas-rechazadas.json", {})
    return {asin for asin, item in rejected.items()
            if (date.fromisoformat(today) - date.fromisoformat(item["fecha"])).days < publicacion.NO_REVISAR_DIAS}


def duplicate(entry, catalog):
    catalog_id = entry.get("catalogId") or (entry.get("ml") or {}).get("catalogId")
    return any((entry.get("asin") and entry["asin"] == p.get("asin"))
               or (entry.get("slug") and entry["slug"] == p.get("slug"))
               or (catalog_id and catalog_id == (p.get("ml") or {}).get("catalogId"))
               for p in catalog)


@locked_refresh
def update_state(catalog, lock_path, operation):
    """Comparte altas.lock entre descubrimiento, revalidación y promoción."""
    return operation()
