"""Consultas filtradas sin la preconsulta repetida del wrapper upstream."""
import re
import os
import time
from urllib.parse import urlencode
from .bootstrap import configure_transport
from .currency import usd_bounds
from .events import emit_event, vendor_observer, set_context, wait, action
from .refinements import load_refinements, delivery_refinements
from .shipping import session_is_ar, delivery_from_card
from .models import normalize_product


NON_NEW = re.compile(r"\b(?:Amazon\s+Renewed|Renewed|Refurbished|Used|Pre[\s‐‑–-]+Owned|"
                     r"Reacondicionad[oa]s?|Usad[oa]s?|Open[\s‐‑–-]+Box|"
                     r"Caja\s+abierta|De\s+segunda\s+mano)\b", re.I)


class SourceError(RuntimeError):
    def __init__(self, message, *, http=None, blocked=False, transient=False):
        super().__init__(message)
        self.http, self.blocked, self.transient = http, blocked, transient


class EmptySearchPage(Exception):
    """La preconsulta vacía no necesita refinamientos ni otra solicitud."""
    def __init__(self, parsed):
        self.parsed = parsed


def build_search_params(node, page, bounds, refinements=None):
    rh = [f"n:{node}"] + list(dict.fromkeys(v for v in (refinements or {}).values() if v))
    return {"rh": ",".join(rh), "fs": "true", "low-price": bounds[0], "high-price": bounds[1], "page": str(page)}


def parse_search_page(html, site):
    from amazon import parsers as parser
    doc = parser.soup(html)
    result = parser.search_page(html, site)
    result["refinements"].extend(delivery_refinements(doc))
    cards = [card for card in doc.select('div[data-component-type="s-search-result"]') if card.get("data-asin")]
    for row, card in zip(result["results"], cards):
        row["card_html"] = str(card)
        text = card.get_text(" ", strip=True)
        marker = NON_NEW.search(text)
        row['non_new_marker'] = marker.group(0) if marker else None
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
    def __init__(self, store, date, rate, config, cache, refresh=False, known=(), sleep=time.sleep,
                 clock=time.monotonic):
        self.sleep = sleep
        self.clock = clock
        self.http = None
        self.fetch = configure_transport(self.observe)
        from amazon import sites
        self.site = sites.site(store)
        self.store, self.date, self.rate, self.config = store, date, rate, config
        self.cache, self.refresh, self.known = cache, refresh, set(known)
        self.bounds = usd_bounds(config.min_usd, config.max_usd, rate)
        self.filters = {}
        self.chrome_endpoint = os.environ.get("BARRIDO_CHROME_CDP", "").strip()
        self.chrome = None
        self._request_located_ar = None
        self._search_source = None
        self._chrome_until = None
        self._chrome_reason = None

    def search_source(self, source, why):
        if source != self._search_source:
            self._search_source = source
            emit_event('BARRIDO_FUENTE_BUSQUEDA', tienda=self.store, source=source, why=why)

    def prefer_chrome(self, params, reason):
        parsed = self.chrome_request(params, reason=reason)
        # Sólo un respaldo exitoso activa o renueva la ventana.
        self._chrome_until = self.clock() + self.config.chrome_search_ttl if self.config.chrome_search_ttl else float('inf')
        self._chrome_reason = reason
        self.search_source('chrome', reason)
        return parsed

    def probe_scraper(self, params):
        """Un solo /s observado, sin warm-up, redirecciones, ubicación ni reintentos."""
        from .chrome_search import blocked_reason
        session = self.fetch.session(self.store, 'page', self.site['language'])
        response = session.curl.request('GET', self.site['base'] + '/s', params=params,
                                      headers=self.fetch.PAGE_HEADERS, allow_redirects=False)
        self.http = response.status_code
        reason = blocked_reason(response.text, self.http, response.url)
        if not reason and self.fetch.is_fallback_render(session, response):
            reason = 'edge fallback render'
        if reason or self.http != 200:
            raise SourceError(reason or f'HTTP {self.http} en sondeo', http=self.http, blocked=bool(reason))
        with action('interpretando sondeo de busqueda Amazon'):
            return parse_search_page(response.text, self.site)

    def observe(self, **fields):
        result = vendor_observer(**fields)
        if fields.get('event') == 'request' and fields['url'].split('?')[0].endswith('/s'):
            self.http = result.status_code
        return result

    def request(self, params):
        from amazon import fetch
        self.http = None
        self._request_located_ar = None
        if self._search_source == 'chrome':
            if self.clock() < self._chrome_until:
                return self.chrome_request(params, reason=self._chrome_reason)
            try:
                parsed = self.probe_scraper(params)
            except Exception as exc:
                return self.prefer_chrome(params, reason=f'sondeo_scraper_fallido: {exc}')
            self.search_source('scraper', 'sondeo_scraper_exitoso_tras_vencimiento')
            self._chrome_until = None
            return parsed
        self.search_source('scraper', 'inicio_busquedas')
        try:
            html = self.fetch.page(self.store, "/s", params, language=self.site["language"], postal_code="AR")
        except Exception as exc:
            if isinstance(exc, fetch.AmazonBlocked) and self.chrome_endpoint:
                return self.prefer_chrome(params, reason=str(exc))
            raise SourceError(str(exc), http=self.http, blocked=isinstance(exc, fetch.AmazonBlocked),
                              transient=isinstance(exc, fetch.AmazonUpstreamError)) from exc
        if self.http != 200:
            if self.http in (403, 429, 503) and self.chrome_endpoint:
                return self.prefer_chrome(params, reason=f"HTTP {self.http} bloqueado al finalizar el transporte")
            raise SourceError(f"HTTP {self.http} en búsqueda Amazon", http=self.http, blocked=self.http in (403, 429, 503), transient=self.http is not None and self.http >= 500)
        with action('interpretando HTML de busqueda Amazon'):
            return parse_search_page(html, self.site)

    def chrome_request(self, params, reason):
        from .chrome_search import ChromeSearch, ChromeBlocked, ChromeLocationError
        if self.chrome is None:
            self.chrome = ChromeSearch(self.chrome_endpoint)
        url = self.site["base"] + "/s?" + urlencode(params)
        try:
            html, self.http = self.chrome.search(url, self.site, reason=reason)
        except ChromeLocationError as exc:
            error = SourceError(str(exc))
            error.stop_store = True
            raise error from exc
        except ChromeBlocked as exc:
            raise SourceError(str(exc), http=exc.http, blocked=True) from exc
        except Exception as exc:
            raise SourceError(f"Falló el acceso CDP: {type(exc).__name__}", transient=True) from exc
        self._request_located_ar = True
        with action('interpretando HTML de busqueda Chrome'):
            return parse_search_page(html, self.site)

    def close(self):
        if self.chrome is not None:
            self.chrome.close()

    def fetch_search_page(self, category, page, stamp):
        node = category["id"]
        set_context(tienda=self.store, categoria=node, pagina=page, asin=None)
        empty = None
        prequeried = None
        if node not in self.filters:
            context = dict(date=self.date, store=self.store, node=node, language=self.site["language"], destination="AR")
            def prequery():
                nonlocal prequeried
                try:
                    parsed = self.request(build_search_params(node, 1, self.bounds))
                    prequeried = parsed
                    if not parsed['results']:
                        raise EmptySearchPage(parsed)
                    return parsed
                finally:
                    wait(self.config.pause, 'pausa_refinamientos', sleep=self.sleep)
            try:
                self.filters[node] = load_refinements(self.cache, context, prequery, refresh=self.refresh,
                                                     ttl_days=self.config.refinements_ttl_days)
                emit_event("BARRIDO_FILTROS", tienda=self.store, categoria=node,
                           refinamientos=self.filters[node], ids=[value for value in self.filters[node].values() if value])
                if not self.filters[node].get('new'):
                    emit_event('BARRIDO_SIN_FILTRO_NUEVO', tienda=self.store, categoria=node,
                               motivo='No apareció el refinamiento de condición nueva; se decide por tarjeta')
            except EmptySearchPage as exc:
                empty = exc.parsed
        params = build_search_params(node, page, self.bounds, self.filters.get(node))
        # Igualdad exacta: no usar una página sin «nuevo»/AR cuando se agregaron esos filtros.
        reusable = prequeried is not None and params == build_search_params(node, 1, self.bounds)
        parsed = empty if empty is not None else prequeried if reusable else self.request(params)
        url = self.site["base"] + "/s?" + urlencode(params)
        session = self.fetch.session(self.store, "page", self.site["language"])
        located = getattr(self, '_request_located_ar', None)
        if located is None:
            located = session_is_ar(session)
        if not located:
            emit_event("BARRIDO_UBICACION_DESCONOCIDA", tienda=self.store, categoria=node)
        rows = [normalize_product(raw, store=self.store, identity=raw["asin"], stamp=stamp,
                    currency=self.site["currency"], rate=self.rate,
                    provenance=dict(category_id=node, category_name=category["name"], page=page, url=url),
                    shipping=delivery_from_card(raw, located=located), located=located,
                    condition="non_new" if raw.get('non_new_marker') else "new",
                    known=raw["asin"] in self.known, min_usd=self.config.min_usd, max_usd=self.config.max_usd)
                for raw in parsed["results"]]
        for row in rows:
            if (row.get('raw') or {}).get('non_new_marker'):
                row['rejection_reasons'] = ['no_nuevo' if reason == 'condicion_no_confirmada' else reason
                                            for reason in row['rejection_reasons']]
        return {**parsed, "products": rows, "http": self.http, "located_ar": located}

    def variations(self, identity):
        set_context(asin=identity)
        from amazon import products, fetch
        try:
            return products.variations(identity, self.store, language=self.site["language"])
        except Exception as exc:
            raise SourceError(str(exc), http=self.http, blocked=isinstance(exc, fetch.AmazonBlocked),
                              transient=isinstance(exc, fetch.AmazonUpstreamError)) from exc
