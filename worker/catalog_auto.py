"""Alta en dos fases: pares validados quedan pendientes del envío gratis a AR.

Sólo tools/confirmar_altas.py los promueve con evidencia de Chrome del día y
precio USD 100–400. No modifica las altas existentes ni publica pendientes.
"""
from datetime import datetime, timedelta, timezone
import json
import io
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit

import requests
from PIL import Image

import amazon_prices
from catalog import load_catalog, read_catalog
import ml_prices
import publish
import publicacion
from alta_state import read_json, rejected_asins, duplicate, update_state
from refresh_lock import locked_refresh
from article_log import alta_line
from buscar_log import BuscarLog, line

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import discover_products as discovery, match_candidates as matching
from tools.apply_candidates import validate_and_build_entries
from tools.fetch_photos import to_webp, ALLOWED_HOSTS
from tools import crecer_desde_ml
from tools.identifier_gate import strong_identifier_match

ART = timezone(timedelta(hours=-3))


class PacedScraper:
    """Cuenta también reintentos y categorías; corta antes de agotar el presupuesto."""
    def __init__(self, limit, journal=None, progress=None):
        self.limit = max(0, limit)
        self.pages = 0
        self.valid = 0
        self.failures = 0
        self.journal, self.progress = journal, progress

    def pause(self, seconds):
        time.sleep(seconds)

    def get(self, url, **kwargs):
        for attempt in range(2):
            if self.pages >= self.limit:
                raise discovery.PageBudgetExhausted()
            if self.pages:
                self.pause(amazon_prices.PAUSE_SECONDS)
            amazon_prices.charge_pages(1)
            self.pages += 1
            try:
                response = requests.get(url, **kwargs)
                response.raise_for_status()
                payload = response.json() or {}
                if isinstance(payload, dict) and any(isinstance(payload.get(k), list) for k in ("items", "results", "categories")):
                    self.valid += 1
                    count = sum(len(payload.get(k) or []) for k in ("items", "results", "categories"))
                    self.page_line(url, kwargs, attempt, "valida" if count else "vacia", count)
                    return response
                raise ValueError("Respuesta sin listas de resultados")
            except (requests.RequestException, ValueError) as exc:
                self.page_line(url, kwargs, attempt, type(exc).__name__, 0, str(exc))
                if attempt:
                    self.failures += 1
                    raise
            if attempt == 0:
                self.pause(amazon_prices.BACKOFF_SECONDS)
        self.failures += 1
        return response

    def page_line(self, url, kwargs, attempt, status, count, reason=""):
        line("AMAZON_PAGINA", n=self.pages, url=url, params=kwargs.get("params"),
             estado=status, motivo=reason or "respuesta_valida", intento=attempt + 1, items=count,
             pausa_s=amazon_prices.BACKOFF_SECONDS if status not in ("valida", "vacia") and not attempt else 0)
        if self.journal:
            self.journal.append("pagina", str(self.pages), status, reason or "respuesta_valida",
                                url=url, params=kwargs.get("params"), items=count, attempt=attempt + 1)
        if self.progress:
            self.progress()


def fetch_photo(entry, output):
    product = ml_prices.get_json(f"/products/{entry['ml']['catalogId']}")
    ml_prices.pause()
    pictures = product.get("pictures") or []
    url = pictures[0].get("url") if pictures else None
    parsed = urlsplit(url or "")
    if parsed.scheme != "https" or parsed.netloc not in ALLOWED_HOSTS:
        return False
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = to_webp(response.content)
    dest = Path(output) / "products" / f"{entry['slug']}.webp"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    with Image.open(io.BytesIO(data)) as image:
        image.convert("RGB").save(dest.with_suffix(".jpg"), "JPEG", quality=90)
    entry.update(image=f"/products/{entry['slug']}.webp", imageSource=url)
    return True


def mismo_producto(row, existente):
    """Misma marca, algún código de modelo en común y misma capacidad (o ninguna informada)."""
    nombre_a = " ".join(filter(None, [row.get("name"), row.get("amazonTitle")]))
    nombre_b = " ".join(filter(None, [existente.get("name"), existente.get("amazonTitle")]))
    if not nombre_a or not nombre_b:
        return False
    if matching.brand_key(row.get("brand") or "") != matching.brand_key(existente.get("brand") or ""):
        return False
    if not (matching.model_tokens(nombre_a) & matching.model_tokens(nombre_b)):
        return False
    cap_a, cap_b = matching.quantities(nombre_a).get("gb", set()), matching.quantities(nombre_b).get("gb", set())
    return not cap_a or not cap_b or max(cap_a) == max(cap_b)


def add_accepted(catalog, matches, output, today, journal=None):
    """Valida, obtiene la foto y persiste pendientes; nunca escribe catalog-auto."""
    output = Path(output)
    return update_state(catalog, output / "altas.json",
                        lambda: _add_accepted(catalog, matches, output, today, journal=journal))


def pending_rejection(row, catalog, rejected):
    """Controles comunes al descubrimiento y a la aprobación manual."""
    usd = row.get("amazonPriceUsd")
    if row.get("asin") in rejected:
        return "rechazado_14_dias"
    if duplicate(row, catalog):
        return "duplicado"
    if any(mismo_producto(row, p) for p in catalog if p.get("verified") is not False):
        return "modelo_duplicado"
    if not matching.positive_number(usd) or not 100 <= usd <= 400:
        return "precio_fuera_de_rango"
    if discovery.is_excluded_title(row.get("amazonTitle")) or discovery.is_excluded_title(row.get("name")):
        return "titulo_excluido"
    return None


def build_pending(row, catalog, output, today):
    """Construye la misma entrada y foto para ambas vías de alta."""
    entry = validate_and_build_entries(catalog, [row], today=today)[0]
    if not fetch_photo(entry, output):
        return None
    entry["pendienteDesde"] = today
    return entry


def _add_accepted(catalog, matches, output, today, journal=None):
    pending_path = output / "altas-pendientes.json"
    pending = read_catalog(pending_path) if pending_path.exists() else []
    review_path = output / "altas-revision.json"
    cutoff = (datetime.fromisoformat(today) - timedelta(days=14)).date().isoformat()
    # Conservar la primera fecha: redescubrir un par no renueva su vencimiento.
    review = {(row["asin"], row["catalogId"]): row
              for row in read_json(review_path, []) if row.get("revisionDesde", "") >= cutoff}
    # Releer el automático bajo el bloqueo: Chrome pudo promover durante el descubrimiento.
    catalog = catalog + read_json(output / "catalog-auto.json", []) + pending
    rejected = rejected_asins(output, today)
    added, failures = [], []
    journal = journal or BuscarLog(output, today)

    def decide(row):
        usd = row.get("amazonPriceUsd")
        reason = pending_rejection(row, catalog + added, rejected)
        if reason:
            print(alta_line(row, "descartado", reason, {"precio": usd}), flush=True)
            return "descartado", reason
        key = (row["asin"], row["catalogId"])
        if key in review or not strong_identifier_match(row):
            review[key] = {**row, "amazonIds": row.get("amazonIds") or {},
                           "mlIds": row.get("mlIds") or {},
                           "motivoRevision": "sin_identificador_fuerte",
                           "revisionDesde": review.get(key, {}).get("revisionDesde", today)}
            publish.write_atomic(review_path, list(review.values()))
            print(alta_line(row, "revision", "sin_identificador_fuerte", {"precio": usd}), flush=True)
            return "revision", "sin_identificador_fuerte"
        entry = build_pending(row, catalog + added, output, today)
        if entry is None:
            failures.append({"slug": row["slug"], "motivo": "sin_foto"})
            print(alta_line(row, "descartado", "sin_foto", {"precio": usd}), flush=True)
            return "descartado", "sin_foto"
        added.append(entry)
        publish.write_atomic(pending_path, pending + added)
        print(alta_line(row, "pendiente_envio", item={"precio": usd}), flush=True)
        return "pendiente_envio", "validado"

    for row in matches["accepted"]:
        try:
            status, reason = decide(row)
        except Exception as exc:
            failures.append({"slug": row.get("slug"), "motivo": type(exc).__name__})
            status, reason = "descartado", type(exc).__name__
            print(alta_line(row, status, reason, {"text": str(exc)}), flush=True)
        journal.append("alta", row.get("asin"), status, reason, row=row)
    publish.write_atomic(pending_path, pending + added)
    publish.write_atomic(review_path, list(review.values()))
    return added, failures


@locked_refresh
def maybe_grow(catalog_path, output, now=None, mep=None, force=False):
    """Diario durable por ítem; el bloqueo permite reconocer un running abandonado."""
    now = (now or datetime.now(timezone.utc)).astimezone(ART)
    output = Path(output)
    state_path = output / "catalog-auto-state.json"
    state = read_json(state_path, {})
    today = now.date().isoformat()
    journal = BuscarLog(output, today)
    if state.get("status") == "running":
        line("CATALOGO_INTERRUMPIDO", ultimoCatalogId=state.get("ultimoCatalogId"), at=state.get("at"))
        journal.append("corrida", state.get("slot", today), "interrumpida", "running_con_lock_libre", previous=state.copy())
        state.update(status="interrupted", interruptedAt=now.isoformat())
        publish.write_atomic(state_path, state)
    if not force and state.get("slot") == today and state.get("status") == "ok":
        return False
    year, week, _ = (now - timedelta(days=1)).isocalendar()
    state.update(slot=today, week=f"{year}-W{week:02d}", status="running", at=now.isoformat())
    added, failures, scraper = [], [], None
    total = 0
    fatal = False

    def progress():
        state.update(pages=scraper.pages if scraper else len(journal.resolved("pagina")),
                     added=sum(r["result"] == "pendiente_envio" for r in journal.records if r["stage"] == "alta"),
                     resolvedMl=len(journal.resolved("ml")),
                     ultimoCatalogId=state.get("ultimoCatalogId"),
                     revision=len(read_json(output / "altas-revision.json", [])))
        publish.write_atomic(state_path, state)

    progress()
    try:
        if not ml_prices.is_configured() or not matching.positive_number(mep):
            raise ValueError("Faltan credenciales de ML o cotización MEP.")
        catalog = load_catalog(catalog_path, output / "catalog-auto.json")
        pending = read_json(output / "altas-pendientes.json", [])
        amazon_prices.configure_budget(output / "amazon-prices.json", today)
        tope = os.getenv("CATALOG_AUTO_MAX_PAGES")
        scraper = PacedScraper(int(tope) if tope else 10**9, journal=journal, progress=progress)
        pages = [r for r in journal.records if r["stage"] == "pagina"]
        scraper.pages = len(pages)
        scraper.valid = sum(r["result"] in ("valida", "vacia") for r in pages)
        existing_asins = {p.get("asin") for p in catalog + pending} | rejected_asins(output, today)
        existing_asins.update(item["asin"] for item in publicacion.cargar(output).values()
                              if item["situacion"] == "no_revisar" and item["hasta"] > today)
        decided = journal.resolved("match")
        matches = {"accepted": [], "doubtful": [], "rejected": []}
        for record in decided.values():
            matches[record["result"]].append(record["row"])

        def on_result(status, row):
            nonlocal total
            # Primero la cola: si muere entre cola y diario, la repetición es
            # idempotente bajo altas.lock y no vuelve a descargar la foto.
            if status == "accepted":
                new, errors = add_accepted(catalog, {"accepted": [row]}, output, today, journal=journal)
                added.extend(new)
                failures.extend(errors)
                total += 1
            elif status == "doubtful":
                def save_review():
                    path = output / "altas-revision.json"
                    rows = read_json(path, [])
                    key = (row.get("asin"), row.get("catalogId"))
                    if key not in {(r.get("asin"), r.get("catalogId")) for r in rows}:
                        rows.append({**row, "motivoRevision": row.get("reason", "matching_dudoso"), "revisionDesde": today})
                        publish.write_atomic(path, rows)
                update_state(catalog, output / "altas.json", save_review)
            matches[status].append(row)
            publish.write_atomic(output / "match-results.json", matches)
            progress()

        def process(product):
            nonlocal fatal
            asin = product["asin"]
            if asin in decided:
                return
            if product.get("ml"):
                try:
                    crecer_desde_ml.agregar_identificadores([product], journal=journal)
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    # La evidencia de descubrimiento ya está guardada. Seguir
                    # bajando los demás productos, sin inventar identificadores
                    # ni dar por decidido este match: se reintenta desde disco.
                    fatal = True
                    failures.append({"asin": asin, "motivo": "identificadores_no_disponibles", "detalle": str(exc)})
                    return
            # La ficha ML descargada durante el descubrimiento también se reutiliza.
            matching.match_products([product], mep,
                catalog + read_json(output / "altas-pendientes.json", []),
                on_result=on_result, journal=journal)
            decided.update(journal.resolved("match"))

        # Reanudar también el intervalo entre resolver el producto y encolarlo.
        for record in list(journal.records):
            if record["stage"] == "amazon":
                process(record["product"])
            elif record["stage"] == "ml":
                for product in record.get("pairs", []):
                    process(product)
        products = discovery.discover_products(catalog_path, output / "discovery-candidates.json",
            get=scraper.get, existing_asins=existing_asins, failures=failures,
            journal=journal, on_product=process)
        if os.getenv("CATALOG_AUTO_DESDE_ML", "1") == "1":
            review = read_json(output / "altas-revision.json", [])
            desde_ml = crecer_desde_ml.candidatos(existing_asins | {p["asin"] for p in products},
                {(p.get("ml") or {}).get("catalogId") for p in catalog + pending} |
                {r.get("catalogId") for r in review}, mep, get=scraper.get,
                failures=failures, state=state, journal=journal, on_product=process, progress=progress)
            publish.write_atomic(output / "discovery-desde-ml.json", desde_ml)
        # Reanudar desde disco no necesita descargar páginas nuevas.
        if not scraper.valid and not journal.resolved("amazon_lista") and not journal.resolved("ml"):
            raise ValueError("El scraper no devolvió páginas válidas.")
        if scraper.failures:
            failures.append({"motivo": "paginas_sin_datos", "total": scraper.failures})
            fatal = fatal or scraper.failures > 0.3 * max(1, scraper.pages)
    except Exception as exc:
        failures.append({"motivo": type(exc).__name__, "detalle": str(exc)})
        fatal = True
        line("CATALOGO_ERROR", tipo=type(exc).__name__, motivo=str(exc))
    state.update(status="failed" if fatal else "ok", motivos=sorted({f["motivo"] for f in failures}))
    progress()
    amazon_prices.write_run_log(output / "amazon-prices.json", today, "catalogo", len(added), total, log_failures=failures)
    marker = "DEPLOY_FAIL" if fatal else "CATALOGO_OK"
    print(f"{marker} catálogo: pendientes={len(added)}, revision={state['revision']}, aceptados={total}, páginas={scraper.pages if scraper else 0}, fallas={len(failures)}.", flush=True)
    return True
