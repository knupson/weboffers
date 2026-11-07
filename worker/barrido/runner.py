"""Una tienda bloqueada no impide adquirir las otras."""
from dataclasses import asdict
import json
from pathlib import Path
import time

from .amazon_source import AmazonSource, SourceError, next_page
from .currency import load_daily_rates, validate_rate
from .events import emit_event, now_art
from .ml_source import MLSource
from .state import State, acquire_run_lock, write_summary


def retry_page(operation, config, *, store, category, page, sleep=time.sleep):
    failures = 0
    for attempt in range(config.consecutive_blocks):
        try:
            result = operation()
            result["retry_failures"] = failures
            return result
        except Exception as exc:
            failures += 1
            emit_event("BARRIDO_ERROR", tienda=store, categoria=category, pagina=page,
                       tipo=type(exc).__name__, motivo=str(exc), http=getattr(exc, "http", None))
            if not getattr(exc, "blocked", False):
                exc.attempts = failures
                raise
            if attempt + 1 == config.consecutive_blocks:
                emit_event("BARRIDO_BLOQUEADO", tienda=store, categoria=category, pagina=page,
                           tipo=type(exc).__name__, motivo=str(exc), http=getattr(exc, "http", None))
                exc.attempts = failures
                raise
            delay = min(config.backoff * 2 ** attempt, config.backoff_cap)
            emit_event("BARRIDO_REINTENTO", tienda=store, categoria=category, pagina=page,
                       intento=attempt + 1, pausa=delay)
            sleep(delay)


def enrich_variations(rows, source, state, config):
    failures = 0
    for row in rows:
        if not row["eligible"] or not row["has_variations"]:
            continue
        identity = row["id"]
        if state.reserve_variation(identity, config.variation_limit):
            emit_event("BARRIDO_VARIANTES", tienda=row["store"], id=identity)
            try:
                value = source.variations(identity)
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
        con_envio=sum(row["shipping_class"] in ("gratis", "pago", "envia_costo_desconocido") for row in rows),
        fallas=sum(page.get("variation_failures", 0) + page.get("retry_failures", 0) for page in pages),
        segundos=sum(page.get("seconds", 0) for page in pages))


def run_store(store, definition, config, output, date, *, dry_run=False, refresh=False,
              max_pages=None, source_factory=None, rate_loader=load_daily_rates, known=(), sleep=time.sleep):
    state = None if dry_run else State(output, date, store)
    result = dict(status="complete", categories={}, products=0, dry_run=dry_run)
    category_id = None
    try:
        context = {"config": asdict(config), "definition": definition, "known": sorted(known)}
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
        elif store == "ML":
            source = MLSource(date, rate, config, known=known, sleep=sleep)
        else:
            source = AmazonSource(store, date, rate, config, Path(output) / "refinements", refresh=refresh, known=known)
        categories = source.walk_categories(definition) if store == "ML" else [
            node for node in definition["nodes"] if node["id"] not in definition.get("exclude", [])]
        emit_event("BARRIDO_CATEGORIAS", tienda=store, cantidad=len(categories), dry_run=dry_run)
        for category in categories:
            category_id = category["id"]
            page = 1 if dry_run else state.load_checkpoint(category_id)
            signatures = {tuple(row["id"] for row in p["products"]) for p in state.pages(category_id)} if state else set()
            fetched = 0
            while page is not None:
                if now_art().date().isoformat() != date:
                    raise SourceError("Cambió el día ART: se detiene para no mezclar fechas")
                started = time.monotonic()
                data = retry_page(lambda: source.fetch_search_page(category, page, now_art().isoformat()),
                                  config, store=store, category=category_id, page=page, sleep=sleep)
                if now_art().date().isoformat() != date:
                    raise SourceError("Cambió el día ART durante la consulta: página sin confirmar")
                rows = data["products"]
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
                variation_failures = enrich_variations(rows, source, state, config)
                payload = dict(page=page, complete=following is None, products=rows,
                               seconds=time.monotonic() - started, variation_failures=variation_failures,
                               retry_failures=data.get("retry_failures", 0),
                               http=data.get("http"), total_pages=data.get("total_pages"), count=data.get("count"))
                state.commit_page(category_id, page, payload)
                state.materialize_jsonl()
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
                    sleep(config.ml_pause if store == "ML" else config.pause)
            if state:
                result["categories"][category_id] = category_metrics(state, category_id)
    except Exception as exc:
        result.update(status="blocked" if getattr(exc, "blocked", False) else "failed", error=str(exc))
        emit_event("BARRIDO_ERROR", tienda=store, categoria=category_id, tipo=type(exc).__name__,
                   motivo=str(exc), http=getattr(exc, "http", None))
        if state and category_id:
            result["categories"][category_id] = category_metrics(state, category_id)
            result["categories"][category_id]["fallas"] += getattr(exc, "attempts", 1)
    finally:
        if state:
            result["products"] = len(state.materialize_jsonl())
    if result["status"] == "failed" and result["products"]:
        result["status"] = "partial"
    if state and any(page.get("variation_failures", 0) for page in state.pages()) and result["status"] == "complete":
        result["status"] = "partial"
    emit_event("BARRIDO_OK" if result["status"] == "complete" else "BARRIDO_FALLA", tienda=store, **result)
    return result


def run_all(categories, config, output, *, stores=None, date=None, dry_run=False, **options):
    date = date or now_art().date().isoformat()
    if date != now_art().date().isoformat():
        raise ValueError("Sólo se adquiere evidencia del día ART actual")
    results = {}
    with acquire_run_lock(output):
        for store in stores or categories["stores"]:
            results[store] = run_store(store, categories["stores"][store], config, output, date,
                                       dry_run=dry_run, **options)
            if not dry_run:
                write_summary(output, date, results)
    return results
