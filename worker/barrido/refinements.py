"""IDs observados en la barra lateral, cacheados por contexto diario."""
import json
from urllib.parse import urlparse, parse_qs
from .state import write_atomic, context_key
from .events import emit_event, now_art


def discover_refinements(page):
    result = {"new": None, "ar": None}
    for facet in page.get("refinements") or []:
        for option in facet.get("options") or []:
            name = (option.get("name") or "").strip().lower()
            if facet.get("id") == "p_n_condition-type" and name in ("new", "nuevo", "nuevos"):
                if option.get("value"):
                    result["new"] = f"{facet['id']}:{option['value']}"
            # Sólo un enlace que explícitamente identifica destino Argentina, nunca Prime.
            if "argentina" in name and any(x in name for x in ("ship", "deliver", "env", "entrega")):
                rh = parse_qs(urlparse(option.get("link") or "").query).get("rh", [""])[0]
                picks = [part for part in rh.split(",") if part.startswith(str(facet.get("id")) + ":")]
                if picks:
                    result["ar"] = picks[-1]
    if not result["new"]:
        raise ValueError("No apareció el refinamiento de condición nueva; no se omite el filtro")
    return result


def load_refinements(directory, context, fetch, refresh=False):
    path = directory / (context_key(context) + ".json")
    if path.exists() and not refresh:
        body = json.loads(path.read_text(encoding="utf-8"))
        if body["context"] == context:
            return body["refinements"]
    result = discover_refinements(fetch())
    write_atomic(path, {"context": context, "refinements": result, "observed_at": now_art().isoformat()})
    if result["ar"] is None:
        emit_event("BARRIDO_SIN_FILTRO_AR", **context)
    return result
