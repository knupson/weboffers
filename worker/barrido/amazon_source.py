"""Consultas filtradas sin la preconsulta repetida del wrapper upstream."""
import re
import time
from urllib.parse import urlencode
from .bootstrap import configure_transport
from .currency import usd_bounds
from .events import emit_event
from .refinements import load_refinements
from .shipping import session_is_ar, delivery_from_card
from .models import normalize_product


class SourceError(RuntimeError):
    def __init__(self, message, *, http=None, blocked=False, transient=False):
        super().__init__(message)
        self.http, self.blocked, self.transient = http, blocked, transient


class EmptySearchPage(Exception):
    """La preconsulta vacía no necesita refinamientos ni otra solicitud."""
    def __init__(self, parsed):
        self.parsed = parsed


def build_search_params(node, page, bounds, refinements=None):
    rh = [f"n:{node}"] + [v for v in (refinements or {}).values() if v]
    return {"rh": ",".join(rh), "fs": "true", "low-price": bounds[0], "high-price": bounds[1], "page": str(page)}


def parse_search_page(html, site):
    from amazon import parsers as parser
    doc = parser.soup(html)
    result = parser.search_page(html, site)
    cards = [card for card in doc.select('div[data-component-type="s-search-result"]') if card.get("data-asin")]
    for row, card in zip(result["results"], cards):
        row["card_html"] = str(card)
        text = card.get_text(" ", strip=True)
        variation = re.search(r"(?:Options|Opciones):?\s*(.+)", text, re.I)
        if variation:
            row["has_variations"], row["variations_text"] = True, variation.group(1)
        elif not row.get("has_variations"):
            row["has_variations"] = None
    pagination = doc.select(".s-pagination-item")
    result["total_pages"] = result.get("total_pages") if pagination else None
    selected = doc.select_one(".s-pagination-selected")
    result["current_page"] = int(selected.get_text(strip=True)) if selected and selected.get_text(strip=True).isdigit() else None
    next_element = doc.select_one(".s-pagination-next")
    if next_element is not None:
        result["has_next"] = next_element.name == "a" and "s-pagination-disabled" not in next_element.get("class", []) and next_element.get("aria-disabled") != "true"
    else:
        result["has_next"] = None
    result["count"] = result.get("total_count")
    return result


def next_page(result, current):
    if result.get("current_page") not in (None, current):
        raise SourceError(f"Página devuelta {result['current_page']} distinta de solicitada {current}")
    if result.get("has_next") is not None:
        return current + 1 if result["has_next"] else None
    if result.get("total_pages") is not None:
        return current + 1 if current < result["total_pages"] else None
    if "products" in result or "results" in result:
        return None
    raise SourceError("Sin metadatos suficientes para decidir el final de paginación")


class AmazonSource:
    def __init__(self, store, date, rate, config, cache, refresh=False, known=(), sleep=time.sleep):
        self.sleep = sleep
        self.http = None
        self.fetch = configure_transport(self.observe)
        from amazon import sites
        self.site = sites.site(store)
        self.store, self.date, self.rate, self.config = store, date, rate, config
        self.cache, self.refresh, self.known = cache, refresh, set(known)
        self.bounds = usd_bounds(config.min_usd, config.max_usd, rate)
        self.filters = {}

    def observe(self, **fields):
        if fields["path"].endswith("/s"):
            self.http = fields["http"]
        emit_event("BARRIDO_HTTP", **fields)

    def request(self, params):
        from amazon import fetch
        self.http = None
        try:
            html = self.fetch.page(self.store, "/s", params, language=self.site["language"], postal_code="AR")
        except Exception as exc:
            raise SourceError(str(exc), http=self.http, blocked=isinstance(exc, fetch.AmazonBlocked),
                              transient=isinstance(exc, fetch.AmazonUpstreamError)) from exc
        if self.http != 200:
            raise SourceError(f"HTTP {self.http}: {html}", http=self.http, blocked=self.http in (403, 429, 503), transient=self.http is not None and self.http >= 500)
        return parse_search_page(html, self.site)

    def fetch_search_page(self, category, page, stamp):
        node = category["id"]
        empty = None
        if node not in self.filters:
            context = dict(date=self.date, store=self.store, node=node, language=self.site["language"], destination="AR")
            def prequery():
                try:
                    parsed = self.request(build_search_params(node, 1, self.bounds))
                    if not parsed['results']:
                        raise EmptySearchPage(parsed)
                    return parsed
                finally:
                    self.sleep(self.config.pause)
            try:
                self.filters[node] = load_refinements(self.cache, context, prequery, refresh=self.refresh)
            except EmptySearchPage as exc:
                empty = exc.parsed
        params = build_search_params(node, page, self.bounds, self.filters.get(node))
        parsed = empty if empty is not None else self.request(params)
        url = self.site["base"] + "/s?" + urlencode(params)
        session = self.fetch.session(self.store, "page", self.site["language"])
        located = session_is_ar(session)
        if not located:
            emit_event("BARRIDO_UBICACION_DESCONOCIDA", tienda=self.store, categoria=node)
        rows = [normalize_product(raw, store=self.store, identity=raw["asin"], stamp=stamp,
                    currency=self.site["currency"], rate=self.rate,
                    provenance=dict(category_id=node, category_name=category["name"], page=page, url=url),
                    shipping=delivery_from_card(raw, located=located), located=located, condition="new",
                    known=raw["asin"] in self.known, min_usd=self.config.min_usd, max_usd=self.config.max_usd)
                for raw in parsed["results"]]
        return {**parsed, "products": rows, "http": self.http, "located_ar": located}

    def variations(self, identity):
        from amazon import products, fetch
        try:
            return products.variations(identity, self.store, language=self.site["language"])
        except Exception as exc:
            raise SourceError(str(exc), http=self.http, blocked=isinstance(exc, fetch.AmazonBlocked),
                              transient=isinstance(exc, fetch.AmazonUpstreamError)) from exc
