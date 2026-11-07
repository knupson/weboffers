"""Busca contrapartes locales de los productos Amazon del día, sin emparejar ni publicar."""
import json
from collections import Counter
from pathlib import Path
import re
import time
from uuid import uuid4

import requests

from .amazon_source import SourceError
from .config import Config
from .currency import load_daily_rates, validate_rate
from .events import now_art, emit_event, http_call, wait, observed, set_context, set_action, action
from .models import positive
from .state import LookupState, acquire_run_lock, write_summary


def build_queries(title, brand=""):
    """El modelo se extrae ANTES de limpiar paréntesis, que pueden contenerlo."""
    title = title or ""
    brand = brand.strip() or (title.split()[0] if title.split() else "")
    tokens = re.findall(r"\b[A-Za-z0-9]+(?:[-/][A-Za-z0-9]+)*\b", title)
    models = [token for token in tokens if re.search(r"[A-Za-z]", token)
              and re.search(r"\d", token)
              and not re.fullmatch(r"\d+(?:GB|TB|MB|HZ|KHZ|MHZ|GHZ|INCH|P|K)", token, re.I)]
    # Evitar elegir S3 si el mismo título trae el código más específico S36GD.
    model = max(models, key=lambda token: (len(token), -tokens.index(token)), default="")
    cleaned = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title)
    cleaned = re.sub(r"\b(?:Amazon'?s Choice|Best Seller|Limited time deal)\b", " ", cleaned, flags=re.I)
    cleaned = re.split(r"\s*[|;–—]\s*|\s+-\s+|,\s*", cleaned)[0]
    cleaned = " ".join(cleaned.split()[:12])
    return list(dict.fromkeys(query for query in (f"{brand} {model}".strip() if model else "", cleaned) if query))


class MLClient:
    def __init__(self, config, *, get=None, sleep=time.sleep):
        import ml_prices
        self.ml, self.get = ml_prices, get or ml_prices.get_json
        self.config, self.sleep = config, sleep
        self.session_id = uuid4().hex
        self.transport = requests.Session() if get is None else None

    def _http(self, method, url, **kwargs):
        return http_call(self.transport.request, method, url, store='ML',
                         session_id=self.session_id, located=None, **kwargs)

    def request(self, path, params=None):
        wait(self.config.ml_pause, 'pausa_ml', sleep=self.sleep)
        try:
            if self.transport is not None:
                token = self.ml.get_token(request=lambda url, **kw: self._http('POST', url, **kw))
                response = self._http('GET', self.ml.API_BASE_URL + path, params=params,
                                      headers={'Authorization': f'Bearer {token}'}, timeout=30)
                response.raise_for_status()
                return response.json()
            return self.get(path, params=params)
        except requests.HTTPError as exc:
            response = exc.response
            http = response.status_code if response is not None else None
            # ML devuelve JSON; no anexar una eventual página HTML de WAF.
            literal = response.text if response is not None and not response.text.lstrip().startswith('<') else ''
            raise SourceError(f"{exc}: {literal}",
                              http=http, blocked=http in (403, 429)) from exc

    def search(self, query):
        set_context(pagina=1)
        body = self.request("/products/search", {"status": "active", "site_id": "MLA", "q": query})
        if not isinstance(body.get("results"), list):
            raise SourceError(f"Búsqueda ML sin results: {body}")
        return body["results"]

    def cheapest(self, identity):
        # fetch_items sólo lee la primera página; aquí recorremos todas antes de elegir.
        offers, seen, offset = [], set(), 0
        while True:
            set_context(pagina=offset // 100 + 1)
            try:
                body = self.request(f"/products/{identity}/items", {"offset": offset, "limit": 100})
            except SourceError as exc:
                if exc.http == 404 and "no winners" in str(exc).lower():
                    break
                raise
            batch = body.get("results")
            if not isinstance(batch, list):
                raise SourceError(f"Ofertas ML sin results: {body}")
            fingerprint = repr(batch)
            if batch and fingerprint in seen:
                raise SourceError(f"Ofertas ML repetidas: {identity} offset={offset}")
            seen.add(fingerprint)
            discarded = Counter()
            for item in batch:
                reason, value = self.offer_rejection(item)
                if reason:
                    discarded[reason] += 1
                    emit_event('BARRIDO_DESCARTE', motivo=reason, valor=value, catalogo=identity,
                               oferta=item.get('item_id') if isinstance(item, dict) else None)
            emit_event('BARRIDO_ML_PAGINA_CONTADORES', catalogo=identity, offset=offset,
                       productos=len(batch), conservados=len(batch) - sum(discarded.values()),
                       descartados=sum(discarded.values()), descartes_por_motivo=dict(discarded),
                       alcance='ofertas_validas')
            offers.extend(batch)
            if len(offers) >= (body.get("paging") or {}).get("total", len(offers)):
                break
            if not batch:
                raise SourceError(f"Ofertas ML incompletas: {identity} offset={offset}")
            offset += len(batch)
        # El helper compartido acepta campos ausentes; este contrato exige ambos explícitos.
        valid = [item for item in offers if self.offer_rejection(item)[0] is None]
        best = self.ml.cheapest_new(valid)
        for item in valid:
            emit_event('BARRIDO_CONSERVADO' if best and item['price'] == best[0] else 'BARRIDO_DESCARTE',
                       motivo='mejor_precio' if best and item['price'] == best[0] else 'oferta_mas_cara',
                       valor=item['price'], catalogo=identity, oferta=item.get('item_id'))
        return best

    def offer_rejection(self, item):
        return (
            ('oferta_invalida', type(item).__name__) if not isinstance(item, dict) else
            ('condicion_no_confirmada', item.get('condition')) if item.get('condition') != 'new' else
            ('moneda_incorrecta', item.get('currency_id')) if item.get('currency_id') != 'ARS' else
            ('oferta_internacional', item.get('international_delivery_mode') or item.get('tags')) if self.ml.is_international(item) else
            ('sin_precio', item.get('price')) if not positive(item.get('price')) else (None, None))


def amazon_rows(output, date, config):
    seen = set()
    for store in ("US", "ES"):
        path = Path(output) / f"{store}-{date}.jsonl"
        if not path.exists():
            continue  # ES puede no tener cotización del día; nunca buscar archivos anteriores.
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                key = (store, row["id"])
                price = row.get("price_usd")
                reason, value = (('duplicado', key) if key in seen else
                    ('tienda_incorrecta', row.get('store')) if row.get('store') != store else
                    ('fecha_incorrecta', row.get('date')) if row.get('date') != date else
                    ('sin_precio', price) if not positive(price) else
                    ('fuera_de_rango', price) if not config.min_usd <= price <= config.max_usd else
                    ('envio_pago' if row.get('shipping_class') == 'pago' else 'no_envia' if row.get('shipping_class') == 'no_envia' else 'envio_no_confirmado', row.get('shipping_class'))
                    if row.get('shipping_class') not in ('gratis', 'desconocido') else (None, None))
                if reason:
                    emit_event('BARRIDO_DESCARTE', asin=row.get('id'), motivo=reason, valor=value, origen=store)
                    continue
                seen.add(key)
                yield row


@observed
def run_ml_lookup(config, output, *, date=None, limit=None, dry_run=False,
                  client=None, rate_loader=load_daily_rates):
    date = date or now_art().date().isoformat()
    if date != now_art().date().isoformat():
        raise ValueError("Sólo se adquiere evidencia del día ART actual")
    if limit is not None and (isinstance(limit, bool) or limit < 1):
        raise ValueError("limit debe ser positivo")
    if not dry_run and (config.min_usd, config.max_usd) != (Config().min_usd, Config().max_usd):
        raise ValueError("El rango real debe ser 100–400 USD")
    # El dry-run no crea lock, checkpoint ni archivo oficial.
    from contextlib import nullcontext
    with nullcontext() if dry_run else acquire_run_lock(output, config.max_run_hours):
        set_action('leyendo evidencia Amazon y cotizacion ML')
        state = None if dry_run else LookupState(output, date)
        context = state.root / "context.json" if state else None
        rate = (json.loads(context.read_text(encoding="utf-8"))["rate"]
                if context and context.exists() else rate_loader("ML", date))
        validate_rate(rate, date)
        if state:
            state.freeze({"rate": rate, "min_usd": config.min_usd, "max_usd": config.max_usd})
        client = client or MLClient(config)
        records = state.materialize_jsonl() if state else []
        done = {(row["store"], row["asin"]) for row in records if row["lookup_status"] != "error"}
        processed, blocked, limited = [], False, False
        for amazon in amazon_rows(output, date, config):
            set_action('evaluando producto Amazon para lookup ML')
            set_context(asin=amazon['id'], categoria=None, pagina=None)
            if not dry_run and (amazon["store"], amazon["id"]) in done:
                emit_event('BARRIDO_DESCARTE', asin=amazon['id'], motivo='ya_conocido', valor='lookup_confirmado')
                continue
            if len(processed) >= (limit if limit is not None else (5 if dry_run else float("inf"))):
                limited = not dry_run
                break
            if now_art().date().isoformat() != date:
                raise SourceError("Cambió el día ART: consulta sin confirmar")
            row = dict(store=amazon["store"], asin=amazon["id"], amazon_title=amazon.get("title"),
                       amazon_price_usd=amazon["price_usd"], shipping_class=amazon["shipping_class"],
                       queries_used=[], candidates=[], lookup_status="sin_resultados", error=None)
            seen = set()
            try:
                queries = build_queries(amazon.get("title"), (amazon.get("raw") or {}).get("brand") or "")
                if not queries:
                    emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='sin_consulta', valor=amazon.get('title'))
                for query in queries:
                    row["queries_used"].append(query)
                    started = time.monotonic()
                    results = client.search(query)
                    emit_event("BARRIDO_ML_BUSQUEDA", asin=row["asin"], consulta=query,
                               candidatos=len(results), segundos=time.monotonic() - started, dry_run=dry_run)
                    for product in results:
                        identity = product.get("id") if isinstance(product, dict) else None
                        if not identity or identity in seen:
                            emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='duplicado' if identity else 'sin_identidad', valor=identity)
                            continue
                        if len(seen) >= 5:
                            emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='limite_candidatos', valor=identity)
                            continue
                        seen.add(identity)
                        best = client.cheapest(identity)
                        if best is not None:
                            price, item_id = best
                            row["candidates"].append(dict(catalogId=identity, name=product.get("name"),
                                price_ars=price, price_usd=price * rate["value"], itemId=item_id, condition="new"))
                        else:
                            emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='sin_oferta_local_nueva', valor=identity)
                    if row["candidates"] or len(seen) >= 5:
                        break
                row["lookup_status"] = "ok" if row["candidates"] else "sin_resultados"
            except Exception as exc:
                row.update(lookup_status="error", error=str(exc), candidates=[])
                http = getattr(exc, "http", None)
                blocked = http in (403, 429) or getattr(exc, "blocked", False)
                emit_event("BARRIDO_ML_ERROR", asin=row["asin"], motivo=str(exc), http=http)
                if blocked:
                    emit_event("BARRIDO_ML_BLOQUEADO", asin=row["asin"], motivo=str(exc), http=http)
            if now_art().date().isoformat() != date:
                raise SourceError("Cambió el día ART durante la consulta: registro sin confirmar")
            processed.append(row)
            emit_event('BARRIDO_ML_PRODUCTO', asin=row['asin'], candidatos=len(row['candidates']),
                       eligible=amazon.get('eligible', False), estado=row['lookup_status'])
            if state:
                with action('persistiendo candidatos ML'):
                    state.commit_lookup(row)
                    state.materialize_jsonl()
                emit_event('BARRIDO_PERSISTIDO', asin=row['asin'])
            if blocked:
                break
        records = state.materialize_jsonl() if state else processed
        summary = dict(total=len(records), con_candidatos=sum(row["lookup_status"] == "ok" for row in records),
                       sin_resultados=sum(row["lookup_status"] == "sin_resultados" for row in records),
                       errores=sum(row["lookup_status"] == "error" for row in records))
        if limited:
            emit_event("BARRIDO_ML_LIMITE", limite=limit)
        emit_event("BARRIDO_ML_OK", **summary)
        if not dry_run:
            write_summary(output, date, {'ML': summary})
        return dict(status="blocked" if blocked else "partial" if summary["errores"] or limited else "complete", **summary)
