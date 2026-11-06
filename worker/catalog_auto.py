"""Alta semanal conservadora, sin credenciales de Git ni generación con IA."""
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import discover_products as discovery, match_candidates as matching
from tools.apply_candidates import validate_and_build_entries
from tools.fetch_photos import to_webp, ALLOWED_HOSTS
from tools import crecer_desde_ml

ART = timezone(timedelta(hours=-3))


class PacedScraper:
    """Cuenta también reintentos y categorías; corta antes de agotar el presupuesto."""
    def __init__(self, limit):
        self.limit = max(0, limit)
        self.pages = 0
        self.valid = 0
        self.failures = 0

    def get(self, url, **kwargs):
        for attempt in range(2):
            if self.pages >= self.limit:
                raise discovery.PageBudgetExhausted()
            if self.pages:
                time.sleep(300 if self.pages % 100 == 0 else amazon_prices.PAUSE_SECONDS)
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
                time.sleep(amazon_prices.BACKOFF_SECONDS)
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
    added, failures = [], []
    for row in matches["accepted"]:
        if any(row.get("asin") == p.get("asin") or row.get("slug") == p.get("slug") for p in catalog + added):
            continue
        # El mismo producto de ML no se da de alta dos veces con ASIN distintos (05/11, flujo desde ML).
        if row.get("catalogId") and any(row["catalogId"] == (p.get("ml") or {}).get("catalogId") for p in catalog + added):
            continue
        # Ni el mismo modelo en otro color (otra ficha y otro ASIN): JBL Flip 7 y Tab A11 se duplicaron el 05/11.
        if any(mismo_producto(row, p) for p in catalog + added if p.get("verified") is not False):
            continue
        usd = row.get("amazonPriceUsd")
        if not matching.positive_number(usd) or not 100 <= usd <= 400:
            continue
        if discovery.is_excluded_title(row.get("amazonTitle")) or discovery.is_excluded_title(row.get("name")):
            continue
        try:
            entry = validate_and_build_entries(catalog + added, [row], today=today)[0]
            if not fetch_photo(entry, output):
                failures.append({"slug": row["slug"], "motivo": "sin_foto"})
                continue
            added.append(entry)
        except (requests.RequestException, OSError, ValueError, KeyError, TypeError) as exc:
            failures.append({"slug": row.get("slug"), "motivo": type(exc).__name__})
    return added, failures


def maybe_grow(catalog_path, output, now=None, mep=None, force=False):
    """Alta automática de productos: TODAS las noches de 20:00 a 03:00 ART (05/11; antes sólo los domingos),
    antes del relevamiento de Chrome de las 03:30 que confirma envío y precio de los nuevos.
    `force=True` corre ahora fuera de la ventana (tools/crecer_ahora.py)."""
    now = (now or datetime.now(timezone.utc)).astimezone(ART)
    if not force and not (now.hour >= 20 or now.hour < 3):
        return False
    output = Path(output)
    state_path = output / "catalog-auto-state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    noche = now - timedelta(days=1) if now.hour < 3 else now
    year, week, _ = noche.isocalendar()
    slot = noche.date().isoformat() + (f"-forzado-{now:%H%M%S}" if force else "")
    try:
        expired = state.get("status") == "running" and now - datetime.fromisoformat(state["at"]) > timedelta(hours=6)
    except (KeyError, ValueError, TypeError):
        expired = state.get("status") == "running"
    if state.get("slot") == slot and not expired and not (state.get("status") == "failed" and state.get("pages") == 0):
        return False
    # Registrar el intento antes de consultar: un reinicio nunca duplica el gasto semanal.
    publish.write_atomic(state_path, {"slot": slot, "week": f"{year}-W{week:02d}", "status": "running", "at": now.isoformat()})
    today = now.date().isoformat()
    added, failures, total = [], [], 0
    fatal = False
    scraper = None
    try:
        if not ml_prices.is_configured() or not matching.positive_number(mep):
            raise ValueError("Faltan credenciales de ML o cotización MEP.")
        auto_path = output / "catalog-auto.json"
        previous = read_catalog(auto_path) if auto_path.exists() else []
        catalog = load_catalog(catalog_path, auto_path)
        run_path = output / f"amazon-run-{today}.json"
        runs = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else {}
        amazon_prices.configure_budget(output / "amazon-prices.json", today)
        # 05/11: sin topes inventados (ni el 650/día ni un 400/corrida): no hay límite medido. El descubrimiento
        # termina solo (categorías x más vendidos + búsquedas). Sólo se limita si se configura la variable.
        tope = os.getenv("CATALOG_AUTO_MAX_PAGES")
        scraper = PacedScraper(int(tope) if tope else 10**9)
        if not scraper.limit:
            raise ValueError("Sin presupuesto diario de páginas de Amazon.")
        existing_asins = {p.get("asin") for p in catalog}
        products = discovery.discover_products(catalog_path, output / "discovery-candidates.json",
            get=scraper.get, existing_asins=existing_asins, failures=failures)
        # 05/11: también al revés, desde lo que ML vende en Argentina (rinde mucho más que partir de Amazon).
        if os.getenv("CATALOG_AUTO_DESDE_ML", "1") == "1":
            desde_ml = crecer_desde_ml.candidatos(existing_asins | {p["asin"] for p in products},
                                                  {(p.get("ml") or {}).get("catalogId") for p in catalog},
                                                  mep, get=scraper.get, failures=failures)
            publish.write_atomic(output / "discovery-desde-ml.json", desde_ml)
            products = products + desde_ml
        if not scraper.valid:
            raise ValueError("El scraper no devolvió páginas válidas.")
        con_ids = crecer_desde_ml.agregar_identificadores(products)
        print(f"Catálogo: identificadores de Amazon para {con_ids} de {len(products)} pares.", flush=True)
        matches = matching.match_products(products, mep, catalog)
        publish.write_atomic(output / "match-results.json", matches)
        total = len(matches["accepted"])
        added, photo_failures = add_accepted(catalog, matches, output, today)
        failures.extend(photo_failures)
        publish.write_atomic(auto_path, previous + added)
        if scraper.failures:
            failures.append({"motivo": "paginas_sin_datos", "total": scraper.failures})
            # Muchas páginas vacías sí es una falla de la corrida (freno o scraper roto), no un caso suelto.
            fatal = fatal or scraper.failures > 0.3 * max(1, scraper.pages)
    except Exception as exc:
        added = []
        failures.append({"motivo": type(exc).__name__})
        fatal = True
    # 05/11: fallas sueltas (una búsqueda HTTPError, una foto) no marcan la corrida como fallida: quedan contadas.
    status = "failed" if fatal else "ok"
    publish.write_atomic(state_path, {"slot": slot, "week": f"{year}-W{week:02d}", "status": status, "at": now.isoformat(),
                                    "added": len(added), "pages": scraper.pages if scraper else 0,
                                    "motivos": sorted({f.get("motivo") for f in failures if f.get("motivo")})})
    amazon_prices.write_run_log(output / "amazon-prices.json", today, "catalogo", len(added), total, log_failures=failures)
    # Mismo canal de fallas que el deployer: marcador persistido en los logs de Docker.
    marker = "DEPLOY_FAIL" if fatal else "CATALOGO_OK"
    print(f"{marker} catálogo semanal: altas={len(added)}, aceptados={total}, páginas={scraper.pages if scraper else 0}, fallas={len(failures)}.", flush=True)
    return True
