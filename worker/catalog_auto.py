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
from article_log import alta_line

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import discover_products as discovery, match_candidates as matching
from tools.apply_candidates import validate_and_build_entries
from tools.fetch_photos import to_webp, ALLOWED_HOSTS
from tools import crecer_desde_ml
from tools.identifier_gate import strong_identifier_match

ART = timezone(timedelta(hours=-3))


class PacedScraper:
    """Cuenta también reintentos y categorías; corta antes de agotar el presupuesto."""
    def __init__(self, limit, budget=None):
        self.limit = max(0, limit)
        self.pages = 0
        self.valid = 0
        self.failures = 0
        self.budget = budget

    def pause(self, seconds):
        if self.budget:
            seconds = min(seconds, max(0, self.budget.deadline - time.monotonic()))
        time.sleep(seconds)
        if self.budget and self.budget.expired():
            raise discovery.PageBudgetExhausted()

    def get(self, url, **kwargs):
        for attempt in range(2):
            if self.budget and self.budget.expired():
                raise discovery.PageBudgetExhausted()
            if self.pages >= self.limit:
                raise discovery.PageBudgetExhausted()
            if self.pages:
                self.pause(300 if self.pages % 100 == 0 else amazon_prices.PAUSE_SECONDS)
            amazon_prices.charge_pages(1)
            self.pages += 1
            try:
                response = requests.get(url, **kwargs)
                response.raise_for_status()
                payload = response.json() or {}
                if payload.get("items") or payload.get("results") or payload.get("categories"):
                    self.valid += 1
                    return response
            except (requests.RequestException, ValueError):
                if attempt:
                    self.failures += 1
                    raise
            if attempt == 0:
                self.pause(amazon_prices.BACKOFF_SECONDS)
        self.failures += 1
        return response


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


def add_accepted(catalog, matches, output, today):
    """Valida, obtiene la foto y persiste pendientes; nunca escribe catalog-auto."""
    output = Path(output)
    return update_state(catalog, output / "altas.json",
                        lambda: _add_accepted(catalog, matches, output, today))


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


def _add_accepted(catalog, matches, output, today):
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
    for row in matches["accepted"]:
        usd = row.get("amazonPriceUsd")
        reason = pending_rejection(row, catalog + added, rejected)
        if reason:
            print(alta_line(row, "descartado", reason, {"precio": usd}), flush=True)
            continue
        key = (row["asin"], row["catalogId"])
        if key in review or not strong_identifier_match(row):
            review[key] = {**row, "amazonIds": row.get("amazonIds") or {},
                           "mlIds": row.get("mlIds") or {},
                           "motivoRevision": "sin_identificador_fuerte",
                           "revisionDesde": review.get(key, {}).get("revisionDesde", today)}
            print(alta_line(row, "revision", "sin_identificador_fuerte", {"precio": usd}), flush=True)
            continue
        try:
            entry = build_pending(row, catalog + added, output, today)
            if entry is None:
                failures.append({"slug": row["slug"], "motivo": "sin_foto"})
                print(alta_line(row, "descartado", "sin_foto", {"precio": usd}), flush=True)
                continue
            added.append(entry)
            print(alta_line(row, "pendiente_envio", item={"precio": usd}), flush=True)
        except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as exc:
            failures.append({"slug": row.get("slug"), "motivo": type(exc).__name__})
            print(alta_line(row, "descartado", type(exc).__name__, {"precio": usd, "text": str(exc)}), flush=True)
    publish.write_atomic(pending_path, pending + added)
    publish.write_atomic(review_path, list(review.values()))
    return added, failures


def maybe_grow(catalog_path, output, now=None, mep=None, force=False):
    """Búsqueda diaria sin ventana horaria; force permite una invocación explícita."""
    started = time.monotonic()
    now = (now or datetime.now(timezone.utc)).astimezone(ART)
    output = Path(output)
    state_path = output / "catalog-auto-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    # El control del lunes espera la semana del domingo. La corrida completa
    # la jornada anterior, incluso si se demora, sin cambiar su slot diario.
    year, week, _ = (now - timedelta(days=1)).isocalendar()
    slot = now.date().isoformat()
    if not force and str(state.get("slot", "")).startswith(slot):
        return False
    # Registrar el intento antes de consultar evita repetirlo automáticamente el mismo día.
    state.update({"slot": slot, "week": f"{year}-W{week:02d}", "status": "running", "at": now.isoformat()})
    publish.write_atomic(state_path, state)
    today = now.date().isoformat()
    added, failures, total = [], [], 0
    fatal = False
    scraper = None
    try:
        seconds = os.getenv("CATALOG_AUTO_MAX_SECONDS")
        budget = discovery.TimeBudget(started + max(0, float(seconds))) if seconds else None
        if not ml_prices.is_configured() or not matching.positive_number(mep):
            raise ValueError("Faltan credenciales de ML o cotización MEP.")
        auto_path = output / "catalog-auto.json"
        catalog = load_catalog(catalog_path, auto_path)
        pending = read_json(output / "altas-pendientes.json", [])
        run_path = output / f"amazon-run-{today}.json"
        runs = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
        amazon_prices.configure_budget(output / "amazon-prices.json", today)
        # 05/11: sin topes inventados (ni el 650/día ni un 400/corrida): no hay límite medido. El descubrimiento
        # termina solo (categorías x más vendidos + búsquedas). Sólo se limita si se configura la variable.
        tope = os.getenv("CATALOG_AUTO_MAX_PAGES")
        scraper = PacedScraper(int(tope) if tope else 10**9, budget=budget)
        if not scraper.limit:
            raise ValueError("Sin presupuesto diario de páginas de Amazon.")
        existing_asins = {p.get("asin") for p in catalog + pending} | rejected_asins(output, today)
        existing_asins.update(item["asin"] for item in publicacion.cargar(output).values()
                              if item["situacion"] == "no_revisar" and item["hasta"] > today)
        products = discovery.discover_products(catalog_path, output / "discovery-candidates.json",
            get=scraper.get, existing_asins=existing_asins, failures=failures,
            **({"budget": budget} if budget else {}))
        # 05/11: también al revés, desde lo que ML vende en Argentina (rinde mucho más que partir de Amazon).
        if os.getenv("CATALOG_AUTO_DESDE_ML", "1") == "1":
            desde_ml = crecer_desde_ml.candidatos(existing_asins | {p["asin"] for p in products},
                                                  {(p.get("ml") or {}).get("catalogId") for p in catalog + pending},
                                                  mep, get=scraper.get, failures=failures, budget=budget, state=state)
            publish.write_atomic(output / "discovery-desde-ml.json", desde_ml)
            products = products + desde_ml
        if not scraper.valid and not (budget and budget.expired()):
            raise ValueError("El scraper no devolvió páginas válidas.")
        con_ids = crecer_desde_ml.agregar_identificadores(products)
        print(f"Catálogo: identificadores de Amazon para {con_ids} de {len(products)} pares.", flush=True)
        matches = matching.match_products(products, mep, catalog + pending)
        publish.write_atomic(output / "match-results.json", matches)
        total = len(matches["accepted"])
        added, photo_failures = add_accepted(catalog, matches, output, today)
        failures.extend(photo_failures)
        if scraper.failures:
            failures.append({"motivo": "paginas_sin_datos", "total": scraper.failures})
            # Muchas páginas vacías sí es una falla de la corrida (freno o scraper roto), no un caso suelto.
            fatal = fatal or scraper.failures > 0.3 * max(1, scraper.pages)
    except Exception as exc:
        added = []
        failures.append({"motivo": type(exc).__name__})
        fatal = True
        # 09/11: sin el mensaje, «ValueError» no decía cuál de las tres validaciones cortó la corrida.
        print(f"CATALOGO_ERROR {type(exc).__name__}: {exc}", flush=True)
    # 05/11: fallas sueltas (una búsqueda HTTPError, una foto) no marcan la corrida como fallida: quedan contadas.
    status = "failed" if fatal else "ok"
    state.update({"slot": slot, "week": f"{year}-W{week:02d}", "status": status, "at": now.isoformat(),
                                    "added": len(added), "pages": scraper.pages if scraper else 0,
                                    # 07/11: pares en altas-revision.json; estado.json lo publica y el control de las 07:30 pide «revisá las altas».
                                    "revision": len(read_json(output / "altas-revision.json", [])),
                                    "motivos": sorted({f.get("motivo") for f in failures if f.get("motivo")})})
    publish.write_atomic(state_path, state)
    amazon_prices.write_run_log(output / "amazon-prices.json", today, "catalogo", len(added), total, log_failures=failures)
    # Mismo canal de fallas que el deployer: marcador persistido en los logs de Docker.
    marker = "DEPLOY_FAIL" if fatal else "CATALOGO_OK"
    revision = len(read_json(output / "altas-revision.json", []))
    print(f"{marker} catálogo: pendientes={len(added)}, revision={revision}, aceptados={total}, páginas={scraper.pages if scraper else 0}, fallas={len(failures)}.", flush=True)
    return True
