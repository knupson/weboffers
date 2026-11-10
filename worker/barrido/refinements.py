"""IDs de filtros; la caché nunca guarda precios ni productos de otro día."""
import json
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from .state import write_atomic, context_key
from .events import emit_event, now_art


FREE_SHIPPING_NAMES = {"eligible for free shipping", "envío gratis", "envio gratis"}


def delivery_refinements(doc):
    """Completa los sidebars que no usan los ul filter-* del parser upstream."""
    options = []
    for element in doc.select('#deliveryRefinements a[href], [id*="p_n_is_free_shipping"] a[href]'):
        name = element.get_text(" ", strip=True)
        rh = parse_qs(urlparse(element.get("href", "")).query).get("rh", [""])[0]
        for part in rh.split(","):
            if part.startswith("p_n_is_free_shipping:"):
                options.append(dict(name=name, value=part.split(":", 1)[1], link=element.get("href")))
    return [{"id": "p_n_is_free_shipping", "options": options}] if options else []


def discover_refinements(page):
    result = {"new": None, "ar": None, "free_shipping": None}
    for facet in page.get("refinements") or []:
        for option in facet.get("options") or []:
            name = (option.get("name") or "").strip().lower()
            fid = facet.get("id")
            if fid == "p_n_is_free_shipping" or (fid == "deliveryRefinements" and name in FREE_SHIPPING_NAMES):
                rh = parse_qs(urlparse(option.get("link") or "").query).get("rh", [""])[0]
                picks = [part for part in rh.split(",") if part.startswith("p_n_is_free_shipping:")]
                if picks:
                    result["free_shipping"] = picks[-1]
                elif fid == "p_n_is_free_shipping" and option.get("value"):
                    result["free_shipping"] = f"{fid}:{option['value']}"
            if facet.get("id") == "p_n_condition-type" and name in ("new", "nuevo", "nuevos"):
                if option.get("value"):
                    result["new"] = f"{facet['id']}:{option['value']}"
            # Sólo un enlace que explícitamente identifica destino Argentina, nunca Prime.
            if "argentina" in name and any(x in name for x in ("ship", "deliver", "env", "entrega")):
                rh = parse_qs(urlparse(option.get("link") or "").query).get("rh", [""])[0]
                picks = [part for part in rh.split(",") if part.startswith(str(facet.get("id")) + ":")]
                if picks:
                    result["ar"] = picks[-1]
    return result


def load_refinements(directory, context, fetch, refresh=False, ttl_days=7):
    context = {key: context[key] for key in ('store', 'node', 'language', 'destination')}
    path = directory / (context_key(context) + ".json")
    if path.exists() and not refresh:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
            age = (now_art() - datetime.fromisoformat(body['observed_at'])).total_seconds()
            filters = body['refinements']
            valid = isinstance(filters, dict) and 'new' in filters and (filters['new'] is None or
                    isinstance(filters['new'], str) and filters['new'].startswith('p_n_condition-type:'))
            if valid and body.get("version") == 2 and body["context"] == context and 0 <= age < ttl_days * 86400:
                return body["refinements"]
        except (ValueError, KeyError, TypeError):
            pass  # Caché inválida: redescubrir.
    result = discover_refinements(fetch())
    write_atomic(path, {"version": 2, "context": context, "refinements": result, "observed_at": now_art().isoformat()})
    if result["ar"] is None:
        emit_event("BARRIDO_SIN_FILTRO_AR", **context)
    return result
