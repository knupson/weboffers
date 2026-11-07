"""IDs de filtros; la caché nunca guarda precios ni productos de otro día."""
import json
from datetime import datetime
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


def load_refinements(directory, context, fetch, refresh=False, ttl_days=7):
    context = {key: context[key] for key in ('store', 'node', 'language', 'destination')}
    path = directory / (context_key(context) + ".json")
    if path.exists() and not refresh:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            age = (now_art() - datetime.fromisoformat(body['observed_at'])).total_seconds()
            filters = body['refinements']
            valid = isinstance(filters, dict) and isinstance(filters.get('new'), str) and filters['new'].startswith('p_n_condition-type:')
            if valid and body["context"] == context and 0 <= age < ttl_days * 86400:
                return body["refinements"]
        except (ValueError, KeyError, TypeError):
            pass  # Caché inválida: redescubrir, sin omitir filtros.
    result = discover_refinements(fetch())
    write_atomic(path, {"context": context, "refinements": result, "observed_at": now_art().isoformat()})
    if result["ar"] is None:
        emit_event("BARRIDO_SIN_FILTRO_AR", **context)
    return result
