#!/usr/bin/env python3
"""Descubre candidatos de Amazon US (best sellers y búsquedas) y los cruza con Mercado Libre.

Corre dentro del contenedor weboffers-worker. Es de sólo lectura contra el scraper
y la API de Mercado Libre; escribe los candidatos en --output con publish.write_atomic.

Contenedor:
  docker exec -i franquicia400-weboffers-worker-1 python /app/tools/discover_products.py
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import time

import requests

ROOT = Path(__file__).resolve().parent.parent
if (ROOT / "worker").is_dir():
    sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT))

import ml_prices  # noqa: E402
import publish  # noqa: E402

DEFAULT_SCRAPER_URL = "http://weboffers-amazon-scraper:8000"
DEFAULT_OUTPUT_PATH = "/app/output/discovery-candidates.json"
HTTP_TIMEOUT_SECONDS = 60
SCRAPER_PAUSE_SECONDS = 1.0
TOP_PER_CATEGORY = 50
CANDIDATES_PER_PRODUCT = 5
PROGRESS_EVERY = 20
CHECKPOINT_EVERY = 50
MIN_PRICE_USD = 30.0
MAX_PRICE_USD = 2000.0

SEED_DEPARTMENTS = ("electronics", "pc", "photo", "videogames", "wireless")

TARGET_CATEGORY_KEYWORDS = (
    # computers & components
    "computer",
    "component",
    "processor",
    "cpu",
    "graphics card",
    "gpu",
    "motherboard",
    "memory",
    "ram",
    "cooling",
    "power suppl",
    "desktop",
    "laptop",
    "mini pc",
    # storage
    "storage",
    "solid state",
    "ssd",
    "hard drive",
    "flash drive",
    "memory card",
    "microsd",
    "nas",
    # monitors
    "monitor",
    # keyboards/mice
    "keyboard",
    "mice",
    "mouse",
    "peripher",
    "input device",
    "webcam",
    # headphones/audio
    "headphone",
    "earbud",
    "in-ear",
    "over-ear",
    "audio",
    "speaker",
    "microphone",
    "soundbar",
    # smartwatches
    "smartwatch",
    "smart watch",
    "wearable",
    # cameras/action cams
    "camera",
    "action cam",
    "camcorder",
    "lens",
    "digital camera",
    # gaming controllers/headsets
    "controller",
    "gamepad",
    "gaming headset",
    "gaming",
    "playstation",
    "xbox",
    "nintendo",
    # networking/routers
    "networking",
    "router",
    "wi-fi",
    "wifi",
    "mesh",
    "wireless access",
    "modem",
    "switch",
    # tablets/e-readers
    "tablet",
    "ereader",
    "e-reader",
    "ebook reader",
    "kindle",
    # power banks
    "power bank",
    "portable power",
    "portable charger",
    "battery pack",
    # smart home
    "smart home",
    "home automation",
    "smart plug",
    "smart light",
    "robot vacuum",
)

FALLBACK_CATEGORIES = (
    {"id": "pc/193870011", "name": "Computer Components"},
    {"id": "pc/1292110011", "name": "Data Storage"},
    {"id": "pc/1292115011", "name": "Monitors"},
    {"id": "pc/12879431", "name": "Keyboards, Mice & Input Devices"},
    {"id": "electronics/172541", "name": "Headphones & Earbuds"},
    {"id": "electronics/10048700011", "name": "Smartwatches"},
    {"id": "photo/502394", "name": "Digital Cameras"},
    {"id": "videogames/402052011", "name": "Video Game Accessories"},
    {"id": "pc/172504", "name": "Networking Products"},
    {"id": "pc/13896617011", "name": "Computers & Tablets"},
    {"id": "wireless/7073960011", "name": "Portable Power Banks"},
    {"id": "electronics/6563140011", "name": "Smart Home"},
)

KNOWN_MULTIWORD_BRANDS = (
    "Western Digital",
    "WD_BLACK",
    "WD Black",
    "Logitech G",
    "Turtle Beach",
    "Cooler Master",
    "be quiet!",
    "Audio-Technica",
    "Harman Kardon",
    "Bang & Olufsen",
    "Bowers & Wilkins",
    "SCUF Gaming",
    "Raspberry Pi",
)

EXCLUDED_TITLE_RE = re.compile(
    r"\b("
    r"cases|covers|cables|screen\s+protectors?|tempered\s+glass|lens\s+protectors?"
    r"|replacement\s+parts?|replacements?|spare\s+parts?"
    r"|refurbished|renewed|reconditioned|pre-owned|open[\s-]+box"
    r"|compatible\s+with|compatible\s+con"
    r"|protective\s+case|silicone\s+case|hard\s+case|carrying\s+case|folio\s+case|wallet\s+case|phone\s+case|ipad\s+case|tablet\s+case"
    r"|keyboard\s+cover|dust\s+cover|protective\s+cover|webcam\s+cover"
    r"|charging\s+cable|extension\s+cable|adapter\s+cable|hdmi\s+cable|usb(?:-c)?\s+cable|ethernet\s+cable|patch\s+cable|power\s+cord|extension\s+cord"
    r"|ear\s*pads?|ear\s*tips?|watch\s+bands?|watch\s+straps?|keycaps?|mouse\s+skates?|mouse\s+feet"
    r"|ink\s+cartridges?|toner\s+cartridges?"
    r")\b",
    re.IGNORECASE,
)

STANDALONE_ACCESSORY_RE = re.compile(
    r"(?<!with\s)(?<!with\sa\s)(?<!with\scharging\s)(?<!with\scarrying\s)\b(case|cover|cable)\b",
    re.IGNORECASE,
)

WITH_CASE_ALLOW_RE = re.compile(
    r"\bwith\s+(?:a\s+)?(?:magsafe\s+|wireless\s+|usb-c\s+)?(?:charging|carrying)\s+case\b",
    re.IGNORECASE,
)

MARKETING_WORDS_RE = re.compile(
    r"\b("
    r"all-new|newest|latest\s+model|new\s+model|new\s+version|official|authentic|original"
    r"|the\s+best|best-in-class|ultimate|premium|professional|pro-grade"
    r"|ultra-fast|superfast|high-speed|high\s+performance|next-gen"
    r"|crystal\s+clear|hands-free\s+calling|hands-free|voice\s+control|works\s+with\s+alexa"
    r"|auto\s+noise\s+canceling\s+optimizer|built-in\s+microphone|with\s+mic"
    r"|for\s+pc|for\s+mac|for\s+windows|for\s+laptop|for\s+desktop|for\s+iphone|for\s+android"
    r"|amazon\s+exclusive|frustration-free\s+packaging"
    r")\b",
    re.IGNORECASE,
)

CAPACITY_TOKEN_RE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:TB|GB|MB|W|mAh|Hz|K|mm|inch|\"|'')\b", re.IGNORECASE)


def scraper_url(url=None):
    return (url or os.getenv("AMAZON_SCRAPER_URL") or DEFAULT_SCRAPER_URL).rstrip("/")


def scraper_pause():
    time.sleep(SCRAPER_PAUSE_SECONDS)


def default_catalog_path():
    repo_catalog = ROOT / "data" / "catalog.json"
    if repo_catalog.exists():
        return str(repo_catalog)
    env_catalog = os.getenv("CATALOG_PATH")
    if env_catalog and Path(env_catalog).exists():
        return env_catalog
    if Path("/data/catalog.json").exists():
        return "/data/catalog.json"
    return str(repo_catalog)


def load_existing_asins(catalog_path):
    entries = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    return {
        entry["asin"].strip()
        for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("asin"), str) and entry["asin"].strip()
    }


def is_relevant_category(name, path_or_id=""):
    haystack = f"{name or ''} {path_or_id or ''}".lower()
    return any(keyword in haystack for keyword in TARGET_CATEGORY_KEYWORDS)


def fetch_bestseller_categories(parent_category="", base_url=None):
    params = {"country": "US"}
    if parent_category:
        params["category"] = parent_category
    response = requests.get(
        f"{scraper_url(base_url)}/best-sellers/categories",
        params=params,
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json() or {}
    return payload.get("categories") or []


def discover_categories(base_url=None):
    """Descubre los IDs/paths de categorías tecnológicas relevantes en Amazon US."""
    discovered = []
    seen = set()

    def add_cat(cat_id, cat_name):
        if not cat_id or cat_id in seen:
            return
        seen.add(cat_id)
        discovered.append({"id": cat_id, "name": cat_name or cat_id})

    root_cats = fetch_bestseller_categories("", base_url=base_url)
    scraper_pause()

    seed_to_expand = []
    for item in root_cats:
        if not isinstance(item, dict):
            continue
        cat_id = (item.get("path") or item.get("id") or "").strip()
        cat_name = (item.get("name") or "").strip()
        if not cat_id:
            continue
        if cat_id in SEED_DEPARTMENTS:
            seed_to_expand.append((cat_id, cat_name))
        elif is_relevant_category(cat_name, cat_id):
            add_cat(cat_id, cat_name)

    for dept_id, dept_name in seed_to_expand:
        try:
            sub_cats = fetch_bestseller_categories(dept_id, base_url=base_url)
        except requests.RequestException as exc:
            print(f"Categoría raíz {dept_id} falló ({type(exc).__name__})", flush=True)
            sub_cats = []
        scraper_pause()
        matched_in_dept = 0
        for sub in sub_cats:
            if not isinstance(sub, dict):
                continue
            sub_id = (sub.get("path") or sub.get("id") or "").strip()
            sub_name = (sub.get("name") or "").strip()
            if not sub_id or sub_id == dept_id:
                continue
            if is_relevant_category(sub_name, sub_id):
                add_cat(sub_id, sub_name)
                matched_in_dept += 1
        if matched_in_dept == 0 and is_relevant_category(dept_name, dept_id):
            add_cat(dept_id, dept_name)

    if not discovered:
        return list(FALLBACK_CATEGORIES)
    return discovered


def fetch_bestsellers_for_category(category_id, category_name="", base_url=None, limit=TOP_PER_CATEGORY):
    response = requests.get(
        f"{scraper_url(base_url)}/best-sellers",
        params={"category": category_id, "country": "US", "page": 1},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json() or {}
    raw_items = payload.get("items") or payload.get("results") or []
    resolved_cat = category_name or payload.get("title") or category_id
    out = []
    for item in raw_items[:limit]:
        if isinstance(item, dict):
            enriched = dict(item)
            enriched.setdefault("amazonCategory", resolved_cat)
            out.append(enriched)
    return out


def fetch_search_results(query, base_url=None, limit=TOP_PER_CATEGORY):
    response = requests.get(
        f"{scraper_url(base_url)}/search",
        params={"query": query, "country": "US", "page": 1},
        timeout=HTTP_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json() or {}
    raw_items = payload.get("results") or payload.get("items") or []
    out = []
    for item in raw_items[:limit]:
        if isinstance(item, dict):
            enriched = dict(item)
            enriched.setdefault("amazonCategory", f"search:{query}")
            out.append(enriched)
    return out


def extract_price_usd(item):
    if not isinstance(item, dict):
        return None
    price = item.get("price")
    if isinstance(price, dict):
        currency = price.get("currency")
        if currency and currency != "USD":
            return None
        amount = price.get("amount")
    elif isinstance(price, (int, float)) and not isinstance(price, bool):
        amount = price
    else:
        amount = item.get("priceUsd") or item.get("amazonPriceUsd")
    if isinstance(amount, (int, float)) and not isinstance(amount, bool) and math.isfinite(amount) and amount > 0:
        return float(amount)
    return None


def is_in_stock(item):
    if not isinstance(item, dict):
        return False
    if item.get("in_stock") is False or item.get("is_in_stock") is False:
        return False
    availability = item.get("availability")
    if isinstance(availability, bool):
        return availability
    if isinstance(availability, dict):
        if availability.get("is_in_stock") is False:
            return False
        status = str(availability.get("status") or "").lower()
        if "unavailable" in status or "out of stock" in status:
            return False
    elif isinstance(availability, str):
        low = availability.lower()
        if "unavailable" in low or "out of stock" in low or "sin stock" in low:
            return False
    return True


def is_excluded_title(title):
    if not isinstance(title, str) or not title.strip():
        return True
    if EXCLUDED_TITLE_RE.search(title):
        return True
    stripped_Allowed = WITH_CASE_ALLOW_RE.sub("", title)
    if STANDALONE_ACCESSORY_RE.search(stripped_Allowed):
        return True
    return False


def infer_brand(item):
    raw_brand = (item.get("brand") or "").strip() if isinstance(item, dict) else ""
    if raw_brand:
        raw_brand = re.sub(r"^Visit the\s+(.+?)\s+Store$", r"\1", raw_brand, flags=re.IGNORECASE)
        raw_brand = re.sub(r"^Brand:\s*", "", raw_brand, flags=re.IGNORECASE)
        if raw_brand:
            return raw_brand
    title = (item.get("title") or item.get("amazonTitle") or "").strip() if isinstance(item, dict) else ""
    if not title:
        return ""
    for known in KNOWN_MULTIWORD_BRANDS:
        if title.lower().startswith(known.lower()):
            return known
    first_token = re.split(r"[\s,|/–—-]+", title)[0].strip()
    return first_token


def should_keep_amazon_item(item, existing_asins, seen_asins=None):
    if not isinstance(item, dict):
        return False
    asin = (item.get("asin") or "").strip()
    if not asin or asin in existing_asins or (seen_asins is not None and asin in seen_asins):
        return False
    title = (item.get("title") or item.get("amazonTitle") or "").strip()
    if is_excluded_title(title):
        return False
    if not is_in_stock(item):
        return False
    price_usd = extract_price_usd(item)
    if price_usd is None or price_usd < MIN_PRICE_USD or price_usd > MAX_PRICE_USD:
        return False
    return True


def clean_title_for_ml(title, brand=""):
    """Limpia el título de Amazon dejando marca y tokens principales del modelo para buscar en ML."""
    if not isinstance(title, str):
        return (brand or "").strip()
    cleaned = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", title)
    cleaned = MARKETING_WORDS_RE.sub(" ", cleaned)

    segments = [seg.strip() for seg in re.split(r"\s*[|;–—]\s*|\s+-\s+|,\s*", cleaned) if seg.strip()]
    if not segments:
        return (brand or "").strip()

    primary = segments[0]
    extra_tokens = []
    for seg in segments[1:3]:
        for match in CAPACITY_TOKEN_RE.findall(seg):
            if match.lower() not in primary.lower():
                extra_tokens.append(match)

    combined = " ".join([primary, *extra_tokens])
    combined = MARKETING_WORDS_RE.sub(" ", combined)
    tokens = [tok.strip(",.:;/") for tok in combined.split() if tok.strip(",.:;/")]
    tokens = tokens[:8]
    query = " ".join(tokens).strip()
    brand_clean = (brand or "").strip()
    if brand_clean and brand_clean.lower() not in query.lower():
        query = f"{brand_clean} {query}".strip()
    return re.sub(r"\s+", " ", query).strip()


def find_ml_candidates(query):
    """Busca en el catálogo de ML los top 5 productos y obtiene el menor precio nuevo e itemId."""
    found = []
    results = ml_prices.search_products(query)[:CANDIDATES_PER_PRODUCT]
    ml_prices.pause()
    for result in results:
        if not isinstance(result, dict) or not result.get("id"):
            continue
        catalog_id = result["id"]
        try:
            items = ml_prices.fetch_items(catalog_id)
            best = ml_prices.cheapest_new(items)
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            print(f"  candidato {catalog_id} sin precio ({type(exc).__name__})", flush=True)
            best = None
        ml_prices.pause()
        if best is None:
            continue
        min_price, item_id = best
        if min_price is None or not item_id:
            continue
        found.append({
            "catalogId": catalog_id,
            "name": result.get("name") or "",
            "minPrice": min_price,
            "itemId": item_id,
        })
    return found


def collect_amazon_candidates(existing_asins, queries=None, categories=None, base_url=None):
    """Reúne y filtra productos de best-sellers y búsquedas adicionales."""
    cats = categories if categories is not None else discover_categories(base_url=base_url)
    raw_items = []
    for cat in cats:
        cat_id = cat["id"] if isinstance(cat, dict) else str(cat)
        cat_name = cat.get("name", cat_id) if isinstance(cat, dict) else str(cat)
        try:
            items = fetch_bestsellers_for_category(cat_id, cat_name, base_url=base_url)
            raw_items.extend(items)
        except requests.RequestException as exc:
            print(f"Best sellers {cat_id} falló ({type(exc).__name__})", flush=True)
        scraper_pause()

    for query in queries or []:
        q = query.strip()
        if not q:
            continue
        try:
            items = fetch_search_results(q, base_url=base_url)
            raw_items.extend(items)
        except requests.RequestException as exc:
            print(f"Búsqueda '{q}' falló ({type(exc).__name__})", flush=True)
        scraper_pause()

    filtered = []
    seen_asins = set()
    for item in raw_items:
        if not should_keep_amazon_item(item, existing_asins, seen_asins):
            continue
        asin = item["asin"].strip()
        seen_asins.add(asin)
        title = (item.get("title") or item.get("amazonTitle") or "").strip()
        brand = infer_brand(item)
        filtered.append({
            "asin": asin,
            "store": "US",
            "amazonTitle": title,
            "brand": brand,
            "amazonCategory": item.get("amazonCategory") or "",
            "amazonPriceUsd": extract_price_usd(item),
        })
    return filtered


def discover_products(
    catalog_path,
    output_path=DEFAULT_OUTPUT_PATH,
    queries=None,
    categories=None,
    base_url=None,
):
    existing_asins = load_existing_asins(catalog_path)
    amazon_candidates = collect_amazon_candidates(
        existing_asins=existing_asins,
        queries=queries,
        categories=categories,
        base_url=base_url,
    )
    total = len(amazon_candidates)
    results = []
    for idx, candidate in enumerate(amazon_candidates, start=1):
        query = clean_title_for_ml(candidate["amazonTitle"], candidate["brand"])
        try:
            ml_list = find_ml_candidates(query)
        except requests.RequestException as exc:
            print(f"  búsqueda ML fallida para {candidate['asin']} ({type(exc).__name__})", flush=True)
            ml_list = []
        results.append({
            "asin": candidate["asin"],
            "store": "US",
            "amazonTitle": candidate["amazonTitle"],
            "brand": candidate["brand"],
            "amazonCategory": candidate["amazonCategory"],
            "amazonPriceUsd": candidate["amazonPriceUsd"],
            "ml": ml_list,
        })
        if idx % PROGRESS_EVERY == 0:
            print(f"Progreso: {idx}/{total} productos procesados.", flush=True)
        if idx % CHECKPOINT_EVERY == 0:
            publish.write_atomic(output_path, results)
            print(f"Checkpoint guardado en {output_path} ({len(results)} productos).", flush=True)

    publish.write_atomic(output_path, results)
    print(f"Descubrimiento finalizado en {output_path}: productos={len(results)}.", flush=True)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", default=default_catalog_path())
    parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--queries", nargs="*", default=[], help="Búsquedas extra en Amazon (/search)")
    parser.add_argument("--scraper-url", default=None)
    args = parser.parse_args(argv)

    if not ml_prices.is_configured():
        print("Faltan ML_CLIENT_ID o ML_CLIENT_SECRET en el entorno.", flush=True)
        return 1
    ml_prices.get_token()
    discover_products(
        catalog_path=args.catalog,
        output_path=args.output,
        queries=args.queries,
        base_url=args.scraper_url,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
