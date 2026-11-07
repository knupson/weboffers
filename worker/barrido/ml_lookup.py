"""Busca contrapartes locales de los productos Amazon del día, sin emparejar ni publicar."""
import json
from pathlib import Path
import re
import time

import requests

from .amazon_source import SourceError
from .config import Config
from .currency import load_daily_rates, validate_rate
from .events import now_art
from .models import positive
from .state import LookupState, acquire_run_lock


def emit_event(event, **fields):
    """Campos clave=valor; JSON escapa el literal para mantener una línea por evento."""
    print(f"{now_art().isoformat()} {event} " + " ".join(
        f"{key}={json.dumps(value, ensure_ascii=False, default=str)}" for key, value in fields.items()), flush=True)


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

    def request(self, path, params=None):
        self.sleep(self.config.ml_pause)
        try:
            return self.get(path, params=params)
        except requests.HTTPError as exc:
            response = exc.response
            http = response.status_code if response is not None else None
            raise SourceError(f"{exc}: {response.text if response is not None else ''}",
                              http=http, blocked=http in (403, 429)) from exc

    def search(self, query):
        body = self.request("/products/search", {"status": "active", "site_id": "MLA", "q": query})
        if not isinstance(body.get("results"), list):
            raise SourceError(f"Búsqueda ML sin results: {body}")
        return body["results"]

    def cheapest(self, identity):
        # fetch_items sólo lee la primera página; aquí recorremos todas antes de elegir.
        offers, seen, offset = [], set(), 0
        while True:
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
            offers.extend(batch)
            if len(offers) >= (body.get("paging") or {}).get("total", len(offers)):
                break
            if not batch:
                raise SourceError(f"Ofertas ML incompletas: {identity} offset={offset}")
            offset += len(batch)
        # El helper compartido acepta campos ausentes; este contrato exige ambos explícitos.
        return self.ml.cheapest_new([item for item in offers if isinstance(item, dict)
                                     and item.get("condition") == "new" and item.get("currency_id") == "ARS"])


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
                if (key in seen or row.get("store") != store or row.get("date") != date
                        or not positive(price) or not config.min_usd <= price <= config.max_usd
                        or row.get("shipping_class") not in ("gratis", "desconocido")):
                    continue
                seen.add(key)
                yield row


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
            if not dry_run and (amazon["store"], amazon["id"]) in done:
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
                for query in queries:
                    row["queries_used"].append(query)
                    started = time.monotonic()
                    results = client.search(query)
                    emit_event("BARRIDO_ML_BUSQUEDA", asin=row["asin"], consulta=query,
                               candidatos=len(results), segundos=time.monotonic() - started, dry_run=dry_run)
                    for product in results:
                        identity = product.get("id") if isinstance(product, dict) else None
                        if not identity or identity in seen:
                            continue
                        if len(seen) >= 5:
                            break
                        seen.add(identity)
                        best = client.cheapest(identity)
                        if best is not None:
                            price, item_id = best
                            row["candidates"].append(dict(catalogId=identity, name=product.get("name"),
                                price_ars=price, price_usd=price * rate["value"], itemId=item_id, condition="new"))
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
            if state:
                state.commit_lookup(row)
                state.materialize_jsonl()
            if blocked:
                break
        records = state.materialize_jsonl() if state else processed
        summary = dict(total=len(records), con_candidatos=sum(row["lookup_status"] == "ok" for row in records),
                       sin_resultados=sum(row["lookup_status"] == "sin_resultados" for row in records),
                       errores=sum(row["lookup_status"] == "error" for row in records))
        if limited:
            emit_event("BARRIDO_ML_LIMITE", limite=limit)
        emit_event("BARRIDO_ML_OK", **summary)
        return dict(status="blocked" if blocked else "partial" if summary["errores"] or limited else "complete", **summary)
