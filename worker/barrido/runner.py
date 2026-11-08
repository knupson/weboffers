"""Una tienda bloqueada no impide adquirir las otras."""
from dataclasses import asdict
from collections import Counter
import json
from pathlib import Path
import time
import requests

from .amazon_source import AmazonSource, SourceError, next_page
from .config import Config
from .currency import load_daily_rates, validate_rate, StaleRate
from .events import emit_event, now_art, observed, store_stage, set_context, set_action, wait, action, stage_metrics
from .state import State, acquire_run_lock, write_summary


def retry_page(operation, config, *, store, category, page, sleep=time.sleep):
    failures = blocks = transients = 0
    while True:
        try:
            set_context(tienda=store, categoria=category, pagina=page, asin=None, intento=failures + 1)
            result = operation()
            result.update(retry_failures=failures, block_failures=blocks, transient_failures=transients)
            return result
        except Exception as exc:
            failures += 1
            blocked = getattr(exc, "blocked", False)
            transient = (getattr(exc, "transient", False) or
                         isinstance(exc, (TimeoutError, ConnectionError, requests.Timeout, requests.ConnectionError)) or
                         (getattr(exc, "http", None) or 0) >= 500)
            emit_event("BARRIDO_ERROR", tienda=store, categoria=category, pagina=page,
                       tipo=type(exc).__name__, motivo=str(exc), http=getattr(exc, "http", None))
            if blocked:
                blocks += 1
                exhausted = blocks >= config.consecutive_blocks
                attempt = blocks
            elif transient:
                transients += 1
                exhausted = transients >= config.transient_retries
                attempt = transients
            else:
                exhausted = True
            if exhausted:
                exc.attempts = failures
                if blocked:
                    emit_event("BARRIDO_BLOQUEADO", tienda=store, categoria=category, pagina=page,
                               tipo=type(exc).__name__, motivo=str(exc), http=getattr(exc, "http", None))
                raise
            delay = min(config.backoff * 2 ** (attempt - 1), config.backoff_cap)
            emit_event("BARRIDO_REINTENTO", tienda=store, categoria=category, pagina=page,
                       intento=attempt, pausa=delay, motivo=str(exc), clase="bloqueo" if blocked else "transitorio")
            wait(delay, 'backoff_bloqueo' if blocked else 'backoff_transitorio', sleep=sleep)


def enrich_variations(rows, source, state, config, *, expected_date=None):
    failures = 0
    for row in rows:
        if not row["eligible"] or not row["has_variations"]:
            continue
        identity = row["id"]
        if state.reserve_variation(identity, config.variation_limit):
            emit_event("BARRIDO_VARIANTES", tienda=row["store"], id=identity)
            try:
                value = source.variations(identity)
                if expected_date is not None and now_art().date().isoformat() != expected_date:
                    raise SourceError('Cambió el día ART durante la consulta de variantes')
            except Exception as exc:
                state.finish_variation(identity, status="failed", error=str(exc), value=None)
                emit_event("BARRIDO_ERROR", tienda=row["store"], id=identity, tipo=type(exc).__name__,
                           motivo=str(exc), http=getattr(exc, "http", None))
                failures += 1
                if getattr(exc, "blocked", False):
                    emit_event("BARRIDO_BLOQUEADO", tienda=row["store"], motivo=str(exc), http=getattr(exc, "http", None))
                    raise
            else:
                state.finish_variation(identity, status="complete", value=value)
        row["variations"] = state.variation(identity)
    return failures


def category_metrics(state, category):
    pages = state.pages(category)
    rows = [row for page in pages for row in page["products"]]
    return dict(paginas=len(pages), productos=len(rows), en_rango=sum(
        row["price_usd"] is not None and "fuera_de_rango" not in row["rejection_reasons"] for row in rows),
        envio_gratis=sum(row["shipping_class"] == "gratis" for row in rows),
        envio_pago=sum(row["shipping_class"] == "pago" for row in rows),
        envio_desconocido=sum(row["shipping_class"] in ("desconocido", "envia_costo_desconocido") for row in rows),
        no_envia=sum(row["shipping_class"] == "no_envia" for row in rows),
        fallas=sum(page.get("variation_failures", 0) + page.get("retry_failures", 0) for page in pages),
        segundos=sum(page.get("seconds", 0) for page in pages))


@store_stage
def run_store(store, definition, config, output, date, *, dry_run=False, refresh=False,
              max_pages=None, source_factory=None, rate_loader=load_daily_rates, known=(), sleep=time.sleep):
    if store not in ("US", "ES"):
        raise ValueError("El barrido por categorías sólo admite US y ES")
    if not dry_run and (config.min_usd, config.max_usd) != (Config().min_usd, Config().max_usd):
        raise ValueError("El rango real debe ser 100–400 USD; usá --dry-run para otro rango")
    state = None if dry_run else State(output, date, store)
    result = dict(status="complete", categories={}, products=0, dry_run=dry_run)
    observed_locations = []
    category_id = None
    seen_products = set()
    try:
        set_action('preparando tienda y cotizacion')
        context = {"config": {k: v for k, v in asdict(config).items() if k != 'stall_seconds'}, "definition": definition}
        previous = state.root / "context.json" if state else None
        if previous and previous.exists():
            frozen = json.loads(previous.read_text(encoding="utf-8"))
            rate = validate_rate(frozen["rate"], date)
        else:
            rate = rate_loader(store, date)
            validate_rate(rate, date)
        if state:
            state.freeze({**context, "rate": rate})
        if source_factory:
            source = source_factory(store, date, rate)
        else:
            source = AmazonSource(store, date, rate, config, Path(output) / "refinements", refresh=refresh, known=known, sleep=sleep)
        categories = [
            node for node in definition["nodes"] if node["id"] not in definition.get("exclude", [])]
        emit_event("BARRIDO_CATEGORIAS", tienda=store, cantidad=len(categories), dry_run=dry_run)
        for category in categories:
            category_id = category["id"]
            set_context(categoria=category_id, pagina=None, asin=None)
            set_action('leyendo checkpoint de categoria')
            try:
                page = 1 if dry_run else state.load_checkpoint(category_id)
                signatures = {tuple(row["id"] for row in p["products"]) for p in state.pages(category_id)} if state else set()
                fetched = 0
                if page is not None:
                    wait(config.pause, 'pausa_entre_paginas', sleep=sleep)
                while page is not None:
                    if now_art().date().isoformat() != date:
                        raise SourceError("Cambió el día ART: se detiene para no mezclar fechas")
                    started = time.monotonic()
                    set_action('adquiriendo pagina Amazon')
                    data = retry_page(lambda: source.fetch_search_page(category, page, now_art().isoformat()),
                                      config, store=store, category=category_id, page=page, sleep=sleep)
                    if now_art().date().isoformat() != date:
                        raise SourceError("Cambió el día ART durante la consulta: página sin confirmar")
                    rows = data["products"]
                    set_action('evaluando productos de pagina')
                    set_context(asin=None)
                    reasons = Counter()
                    known_count = 0
                    kept = 0
                    unique_count = duplicates = 0
                    for row in rows:
                        asin = row['id']
                        decisions = list(row.get('rejection_reasons', []))
                        if asin in seen_products:
                            decisions.append('duplicado')
                            duplicates += 1
                        else:
                            unique_count += 1
                        seen_products.add(asin)
                        for reason in decisions:
                            reason = {'sin_precio_validado': 'sin_precio'}.get(reason, reason)
                            if row.get('shipping_class') == 'no_envia' and reason == 'envio_no_confirmado':
                                reason = 'no_envia'
                            value = ((row.get('raw') or {}).get('price') if reason == 'sin_precio' else
                                     row.get('price_usd') if reason == 'fuera_de_rango'
                                     else row.get('shipping_text') or row.get('shipping_class') if reason.startswith('envio') or reason == 'no_envia'
                                     else asin if reason == 'duplicado'
                                     else (row.get('raw') or {}).get('non_new_marker') if reason == 'no_nuevo'
                                     else row.get('condition'))
                            emit_event('BARRIDO_DESCARTE', asin=asin, motivo=reason, valor=value)
                            reasons[reason] += 1
                        if not decisions:
                            kept += 1
                            emit_event('BARRIDO_CONSERVADO', asin=asin, valor=row.get('price_usd'))
                        if row.get('known'):
                            known_count += 1
                            emit_event('BARRIDO_DESCARTE', asin=asin, motivo='ya_conocido', valor=True, alcance='novedades')
                        # La elegibilidad de evidencia y la deduplicación no alteran el contrato de salida.
                    emit_event('BARRIDO_PAGINA_CONTADORES', productos=len(rows), conservados=kept,
                               productos_unicos=unique_count, duplicados=duplicates,
                               tarjetas_patrocinadas=sum(bool((row.get('raw') or {}).get('is_sponsored')) for row in rows),
                               descartados=len(rows) - kept, descartes_por_motivo=dict(reasons),
                               descartes_novedades_por_motivo={'ya_conocido': known_count})
                    located = data.get('located_ar', all(row.get('located_ar') is True for row in rows))
                    observed_locations.append(located)
                    if not rows:
                        emit_event("BARRIDO_CATEGORIA_VACIA", tienda=store, categoria=category_id, pagina=page)
                    emit_event("BARRIDO_PAGINA", tienda=store, categoria=category_id, pagina=page,
                               de=data.get("total_pages"), productos=len(rows), count=data.get("count"),
                               segundos=time.monotonic() - started, http=data.get("http"), dry_run=dry_run)
                    if dry_run:
                        result["categories"][category_id] = dict(count=data.get("count"), total_pages=data.get("total_pages"), productos=len(rows))
                        result["products"] += len(rows)
                        break
                    signature = tuple(row["id"] for row in rows)
                    if rows and signature in signatures:
                        raise SourceError(f"Página repetida en {category_id}: {list(signature)}")
                    signatures.add(signature)
                    following = next_page(data, page)
                    # Las variantes se adquieren al terminar ML, sólo con contraparte local.
                    variation_failures = 0
                    payload = dict(page=page, complete=following is None, products=rows,
                                   seconds=time.monotonic() - started, variation_failures=variation_failures,
                                   retry_failures=data.get("retry_failures", 0),
                                   raw=data.get("raw"), located_ar=located,
                                   block_failures=data.get("block_failures", 0), transient_failures=data.get("transient_failures", 0),
                                   http=data.get("http"), total_pages=data.get("total_pages"), count=data.get("count"))
                    with action('persistiendo pagina y checkpoint'):
                        state.commit_page(category_id, page, payload)
                        state.materialize_jsonl()
                    emit_event('BARRIDO_PERSISTIDO', categoria=category_id, pagina=page)
                    set_action('calculando metricas de categoria')
                    result["categories"][category_id] = category_metrics(state, category_id)
                    if variation_failures:
                        result["status"] = "partial"
                    page = following
                    fetched += 1
                    if max_pages is not None and fetched >= max_pages and page is not None:
                        result["status"] = "partial"
                        emit_event("BARRIDO_LIMITE", tienda=store, categoria=category_id, pagina=page)
                        break
                    if page is not None:
                        wait(config.pause, 'pausa_entre_paginas', sleep=sleep)
                if state:
                    result["categories"][category_id] = category_metrics(state, category_id)
            except Exception as exc:
                if str(exc).startswith("Cambió el día ART") or getattr(exc, "stop_store", False):
                    raise
                result.update(status="partial", error=str(exc))
                emit_event("BARRIDO_ERROR", tienda=store, categoria=category_id, tipo=type(exc).__name__,
                           motivo=str(exc), http=getattr(exc, "http", None))
                metrics = category_metrics(state, category_id) if state else {}
                result["categories"][category_id] = {**metrics, "status": "failed", "error": str(exc),
                    "fallas": metrics.get("fallas", 0) + getattr(exc, "attempts", 1)}
    except StaleRate as exc:
        result.update(status="skipped" if store == "ES" else "failed", error=str(exc))
        if store == "ES":
            emit_event("BARRIDO_ES_SIN_COTIZACION", motivo=str(exc))
    except Exception as exc:
        result.update(status="blocked" if getattr(exc, "blocked", False) else "failed", error=str(exc))
        emit_event("BARRIDO_ERROR", tienda=store, categoria=category_id, tipo=type(exc).__name__,
                   motivo=str(exc), http=getattr(exc, "http", None))
        if state and category_id:
            result["categories"][category_id] = category_metrics(state, category_id)
            result["categories"][category_id]["fallas"] += getattr(exc, "attempts", 1)
    finally:
        if 'source' in locals() and callable(getattr(source, 'close', None)):
            source.close()
        if state:
            result["products"] = len(state.materialize_jsonl(known=known))
    if result["status"] == "failed" and result["products"]:
        result["status"] = "partial"
    if state and any(page.get("variation_failures", 0) for page in state.pages()) and result["status"] == "complete":
        result["status"] = "partial"
    if store in ("US", "ES"):
        locations = [page.get('located_ar') for page in state.pages()] if state else observed_locations
        if locations and sum(located is not True for located in locations) / len(locations) > config.unlocated_page_ratio:
            result.update(status="partial", reason="ubicacion_ar_no_confirmada")
    result.update(stage_metrics())
    emit_event("BARRIDO_OK" if result["status"] == "complete" else "BARRIDO_FALLA", tienda=store, **result)
    return result


@observed
def run_all(categories, config, output, *, stores=None, date=None, dry_run=False, **options):
    date = date or now_art().date().isoformat()
    if date != now_art().date().isoformat():
        raise ValueError("Sólo se adquiere evidencia del día ART actual")
    results = {}
    with acquire_run_lock(output, config.max_run_hours):
        for store in stores or categories["stores"]:
            results[store] = run_store(store, categories["stores"][store], config, output, date,
                                       dry_run=dry_run, **options)
            if not dry_run:
                write_summary(output, date, results)
    return results
