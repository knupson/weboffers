"""Busca contrapartes locales de los productos Amazon del día, sin emparejar ni publicar."""
import json
from collections import Counter
from email.utils import parsedate_to_datetime
import math
from pathlib import Path
import time
from uuid import uuid4

import requests

from .amazon_source import AmazonSource, SourceError
from .config import Config
from .currency import MEP_MAX_DIAS, load_daily_rates, validate_rate
from .events import now_art, emit_event, http_call, wait, observed, set_context, set_action, action, response_excerpt
from .models import positive
from .ml_matching import amazon_identity, build_queries, candidate_score, starts_without_brand
from .state import State, LookupState, acquire_run_lock, write_summary


class MLClient:
    def __init__(self, config, *, get=None, sleep=time.sleep, clock=time.monotonic):
        import ml_prices
        self.ml, self.get = ml_prices, get or ml_prices.get_json
        self.config, self.sleep = config, sleep
        self.clock, self.last_request_started = clock, None
        self.requests_ml, self.items_404, self.consecutive_429 = 0, 0, 0
        self.requests_by_kind = Counter()
        self.session_id = uuid4().hex
        self.transport = requests.Session() if get is None else None

    def _http(self, method, url, **kwargs):
        def perform():
            response = http_call(self.transport.request, method, url, store='ML',
                                 session_id=self.session_id, located=None,
                                 attempt=self.consecutive_429 + 1, **kwargs)
            response.raise_for_status()
            return response
        return self._retry(perform, url)

    def _retry(self, perform, path):
        """Pausa por intento real, también para OAuth; 429 no termina el producto."""
        while True:
            if self.last_request_started is not None:
                remaining = self.config.ml_pause - (self.clock() - self.last_request_started)
                if remaining > 0:
                    wait(remaining, 'pausa_ml', sleep=self.sleep)
            self.last_request_started = self.clock()
            self.requests_ml += 1
            kind = 'ml_search' if path.endswith('/products/search') else 'ml_price' if path.endswith('/items') else 'other'
            self.requests_by_kind[kind] += 1
            emit_event('BARRIDO_ML_PEDIDO', path=path, numero=self.requests_ml,
                       consecutivos_429=self.consecutive_429)
            try:
                result = perform()
            except requests.HTTPError as exc:
                response = exc.response
                status = response.status_code if response is not None else None
                if status == 404 and path.endswith('/items'):
                    self.items_404 += 1
                if status != 429:
                    self.consecutive_429 = 0
                    raise
                self.consecutive_429 += 1
                emit_event('BARRIDO_ML_429', path=path, consecutivos=self.consecutive_429,
                           limite=self.config.ml_consecutive_429,
                           retry_after=response.headers.get('Retry-After'))
                if self.consecutive_429 >= self.config.ml_consecutive_429:
                    emit_event('BARRIDO_ML_REINTENTOS_AGOTADOS', motivo='limite_429_consecutivos_ml',
                               path=path, consecutivos=self.consecutive_429)
                    raise
                delay = None
                header = response.headers.get('Retry-After')
                if header is not None:
                    try:
                        delay = float(header)
                    except (ValueError, TypeError):
                        try:
                            delay = max(0, (parsedate_to_datetime(header) - now_art()).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
                    if delay is not None and (not math.isfinite(delay) or delay < 0):
                        delay = None
                    if delay is None:
                        emit_event('BARRIDO_ML_RETRY_AFTER_INVALIDO', valor=header)
                if delay is None:
                    delay = min(self.config.ml_backoff_cap,
                                self.config.ml_backoff * 2 ** (self.consecutive_429 - 1))
                wait(delay, 'backoff_429_ml', sleep=self.sleep)
                continue
            except Exception:
                self.consecutive_429 = 0
                raise
            self.consecutive_429 = 0
            return result

    def request(self, path, params=None):
        try:
            if self.transport is not None:
                token = self.ml.get_token(request=lambda url, **kw: self._http('POST', url, **kw))
                response = self._http('GET', self.ml.API_BASE_URL + path, params=params,
                                      headers={'Authorization': f'Bearer {token}'}, timeout=30)
                response.raise_for_status()
                return response.json()
            return self._retry(lambda: self.get(path, params=params), path)
        except requests.HTTPError as exc:
            response = exc.response
            http = response.status_code if response is not None else None
            # 08/11: el cuerpo se guarda siempre (antes se descartaba la página HTML y no se supo qué dijo ML).
            literal = response_excerpt(response, 500) if response is not None else ''
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
                if exc.http == 404:
                    emit_event('BARRIDO_DESCARTE', motivo='catalogo_sin_ofertas_404', valor=identity)
                    return None
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
                  client=None, rate_loader=load_daily_rates, catalog_path='/app/data/catalog.json',
                  catalog_auto_path=None, source_factory=None):
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
        validate_rate(rate, date, MEP_MAX_DIAS)
        if state:
            state.freeze({"rate": rate, "min_usd": config.min_usd, "max_usd": config.max_usd})
        client = client or MLClient(config)
        known_ml = {}
        for path in dict.fromkeys((Path(catalog_path), Path(catalog_auto_path) if catalog_auto_path else Path(output).parent / 'catalog-auto.json')):
            if path.exists():
                for product in json.loads(path.read_text(encoding='utf-8')):
                    identity = (product.get('ml') or {}).get('catalogId')
                    if product.get('asin') and isinstance(identity, str) and identity.startswith('MLA') and identity[3:].isdigit():
                        known_ml.setdefault(product['asin'], identity)
        kinds_before = dict(getattr(client, 'requests_by_kind', {}))
        requests_before = getattr(client, 'requests_ml', 0)
        items_404_before = getattr(client, 'items_404', 0)
        records = state.materialize_jsonl() if state else []
        done = {(row["store"], row["asin"]) for row in records if row["lookup_status"] != "error"}
        processed, blocked, limited = [], False, False
        rejected_in_a_row = 0
        eligible_processed = 0
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
            seen, checked = set(), 0
            try:
                identity_amazon = amazon_identity(amazon)
                known_id = known_ml.get(amazon['id'])
                if known_id:
                    emit_event('BARRIDO_ML_ATAJO_CONOCIDO', asin=amazon['id'], catalogo=known_id)
                    best = client.cheapest(known_id)
                    seen.add(known_id)
                    if best is not None:
                        price, item_id = best
                        row['candidates'].append(dict(catalogId=known_id, name=amazon.get('title'),
                            price_ars=price, price_usd=price * rate['value'], itemId=item_id, condition='new'))
                    else:
                        emit_event('BARRIDO_ML_ATAJO_FALLBACK', asin=amazon['id'], catalogo=known_id,
                                   motivo='sin_oferta_local_nueva')
                sin_marca = not row['candidates'] and starts_without_brand(amazon.get('title'))
                if sin_marca:
                    emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='sin_marca', valor=amazon.get('title'))
                queries = [] if row['candidates'] or sin_marca else build_queries(amazon.get("title"), row=amazon)
                emit_event('BARRIDO_ML_IDENTIDAD', marca=identity_amazon['brand'],
                           modelos=identity_amazon['models'], linea=identity_amazon['line'], consultas=queries)
                if not queries and not row['candidates'] and not sin_marca:
                    emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='sin_consulta', valor=amazon.get('title'))
                fallback_reason = None
                for query_index, query in enumerate(queries[:2]):
                    if query_index:
                        emit_event('BARRIDO_ML_SEGUNDA_CONSULTA', asin=row['asin'],
                                   consulta_anterior=row['queries_used'][-1], consulta=query,
                                   motivo=fallback_reason)
                    row["queries_used"].append(query)
                    started = time.monotonic()
                    results = client.search(query)
                    emit_event("BARRIDO_ML_BUSQUEDA", asin=row["asin"], consulta=query,
                               candidatos=len(results), segundos=time.monotonic() - started, dry_run=dry_run)
                    ranked = []
                    for product in results:
                        identity = product.get("id") if isinstance(product, dict) else None
                        if not identity or identity in seen:
                            emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='duplicado' if identity else 'sin_identidad', valor=identity)
                            continue
                        seen.add(identity)
                        score, reason = candidate_score(identity_amazon, product)
                        if score is None:
                            emit_event('BARRIDO_DESCARTE', asin=row['asin'], catalogo=identity,
                                       nombre=product.get('name'), motivo='candidato_no_coincide', valor=reason)
                            continue
                        ranked.append((score, product))
                        emit_event('BARRIDO_ML_CANDIDATO_VALIDADO', catalogo=identity,
                                   nombre=product.get('name'), puntaje=score, motivo=reason)
                    # El límite se aplica a consultas de ofertas, no a descartes locales.
                    ranked.sort(key=lambda entry: entry[0], reverse=True)
                    fallback_reason = ('sin_resultados' if not results else
                                       'sin_candidato_valido' if not ranked else 'sin_oferta_local_nueva')
                    for index, (score, product) in enumerate(ranked):
                        identity = product['id']
                        if checked >= 5:
                            emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='limite_candidatos', valor=identity)
                            continue
                        checked += 1
                        emit_event('BARRIDO_ML_CANDIDATO', catalogo=identity, nombre=product.get('name'),
                                   puntaje=score, orden=checked)
                        best = client.cheapest(identity)
                        if best is not None:
                            price, item_id = best
                            row["candidates"].append(dict(catalogId=identity, name=product.get("name"),
                                price_ars=price, price_usd=price * rate["value"], itemId=item_id, condition="new"))
                            emit_event('BARRIDO_ML_SELECCION', catalogo=identity,
                                       motivo='primera_oferta_local_nueva_valida', consultas_items=checked)
                            for _, skipped in ranked[index + 1:]:
                                emit_event('BARRIDO_DESCARTE', catalogo=skipped['id'],
                                           motivo='oferta_ya_encontrada', valor=identity)
                            break
                        else:
                            emit_event('BARRIDO_DESCARTE', asin=row['asin'], motivo='sin_oferta_local_nueva', valor=identity)
                    if row["candidates"] or checked >= 5:
                        break
                row["lookup_status"] = "ok" if row["candidates"] else "sin_resultados"
            except Exception as exc:
                row.update(lookup_status="error", error=str(exc), candidates=[])
                http = getattr(exc, "http", None)
                rejected = http in (403, 429) or getattr(exc, "blocked", False)
                emit_event("BARRIDO_ML_ERROR", asin=row["asin"], motivo=str(exc), http=http)
                # 08/11: UN 403 cortó la etapa con 2202 productos sin buscar; era esa consulta
                # («Montblanc Sartorial 131200 …» da 403 siempre, las demás 200). Se corta recién con
                # consecutive_blocks productos seguidos rechazados; si no, ese producto queda en error y sigue.
                rejected_in_a_row = rejected_in_a_row + 1 if rejected else 0
                blocked = rejected_in_a_row >= config.consecutive_blocks
                if blocked:
                    emit_event("BARRIDO_ML_BLOQUEADO", asin=row["asin"], motivo=str(exc), http=http,
                               seguidos=rejected_in_a_row)
                elif rejected:
                    emit_event("BARRIDO_ML_CONSULTA_RECHAZADA", asin=row["asin"], motivo=str(exc), http=http,
                               seguidos=rejected_in_a_row, limite=config.consecutive_blocks, sigue=True)
            else:
                rejected_in_a_row = 0
            if now_art().date().isoformat() != date:
                raise SourceError("Cambió el día ART durante la consulta: registro sin confirmar")
            processed.append(row)
            eligible_processed += int(bool(amazon.get('eligible')))
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
        variation_failures = 0
        if not dry_run and not blocked:
            variation_failures = enrich_ml_variations(config, output, date, records,
                                                      source_factory=source_factory, rate_loader=rate_loader)
            set_context(tienda='ML', asin=None, pagina=None)
        summary = dict(total=len(records), con_candidatos=sum(row["lookup_status"] == "ok" for row in records),
                       sin_resultados=sum(row["lookup_status"] == "sin_resultados" for row in records),
                       errores=sum(row["lookup_status"] == "error" for row in records))
        # Numerador y denominador de ESTA ejecución; total/con_candidatos incluyen el checkpoint.
        requests_ml = getattr(client, 'requests_ml', 0) - requests_before
        summary.update(requests_ml=requests_ml,
                       requests_ml_por_producto=requests_ml / len(processed) if processed else None,
                       items_404=getattr(client, 'items_404', 0) - items_404_before,
                       productos_procesados=len(processed),
                       productos_con_candidato=sum(bool(row['candidates']) for row in processed),
                       alcance_metricas='ejecucion_actual')
        from .events import stage_metrics
        summary.update(stage_metrics())
        for kind in ('ml_search', 'ml_price'):
            summary['requests_por_tipo'][kind] = getattr(client, 'requests_by_kind', {}).get(kind, 0) - kinds_before.get(kind, 0)
        if getattr(client, 'transport', None) is None:
            summary['requests_por_tipo']['other'] += getattr(client, 'requests_by_kind', {}).get('other', 0) - kinds_before.get('other', 0)
        summary.update(productos_unicos=len(processed), variation_failures=variation_failures,
                       requests_por_producto_elegible=sum(summary['requests_por_tipo'].values()) / eligible_processed if eligible_processed else None)
        if limited:
            emit_event("BARRIDO_ML_LIMITE", limite=limit)
        from . import ml_matching
        # 08/11: palabras de las búsquedas que no están en glosario_es.json (para ampliarlo; quedan en inglés).
        emit_event("BARRIDO_ML_SIN_TRADUCCION", cantidad=len(ml_matching._untranslated),
                   palabras=sorted(ml_matching._untranslated)[:500])
        emit_event("BARRIDO_ML_OK", **summary)
        if not dry_run:
            write_summary(output, date, {'ML': summary})
        return dict(status="blocked" if blocked else "partial" if summary["errores"] or limited or variation_failures else "complete", **summary)


def enrich_ml_variations(config, output, date, records, *, source_factory=None, rate_loader=load_daily_rates):
    """Reanuda variantes con el State Amazon original y un transporte compartido por tienda."""
    from .runner import enrich_variations
    candidates = {(row['store'], row['asin']) for row in records if row['candidates']}
    sources, touched, failures = {}, set(), 0
    blocked_in_a_row = 0
    for amazon in amazon_rows(output, date, config):
        if not amazon.get('eligible') or not amazon.get('has_variations'):
            continue
        store, identity = amazon['store'], amazon['id']
        set_context(tienda=store, asin=identity, categoria=None, pagina=None)
        if (store, identity) not in candidates:
            emit_event('BARRIDO_DESCARTE', motivo='variantes_sin_ml', valor=identity)
            continue
        state = State(output, date, store)
        touched.add(store)
        if state.variation(identity) is not None:
            continue
        # No abrir sesión ni cargar cotización si ya se agotó el cupo.
        path = state.root / 'variations.json'
        saved = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if identity not in saved and len(saved) >= config.variation_limit:
            continue
        if now_art().date().isoformat() != date:
            raise SourceError('Cambió el día ART antes de adquirir variantes')
        if store not in sources:
            context = state.root / 'context.json'
            rate = json.loads(context.read_text(encoding='utf-8'))['rate'] if context.exists() else rate_loader(store, date)
            validate_rate(rate, date)
            sources[store] = (source_factory(store, date, rate) if source_factory else
                              AmazonSource(store, date, rate, config, Path(output) / 'refinements'))
        try:
            failures += enrich_variations([amazon], sources[store], state, config, expected_date=date)
            blocked_in_a_row = 0
        except SourceError as exc:
            # 08/11: un bloqueo de UN producto cortaba todas las variantes; se corta con N seguidos.
            failures += 1
            blocked_in_a_row += 1
            if blocked_in_a_row >= config.consecutive_blocks:
                emit_event('BARRIDO_VARIANTES_CORTADAS', motivo=str(exc), seguidos=blocked_in_a_row)
                break
            emit_event('BARRIDO_VARIANTE_RECHAZADA', id=identity, motivo=str(exc), seguidos=blocked_in_a_row,
                       limite=config.consecutive_blocks, sigue=True)
    for store in touched:
        state = State(output, date, store)
        if state.pages():
            state.materialize_jsonl()
    return failures
