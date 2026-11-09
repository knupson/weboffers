"""Precios de Mercado Libre y veredicto diario frente a Amazon."""

from refresh_lock import locked_refresh
import diario
from article_log import ml_line
from requisitos import motivo_total, modo_actual, resumen_etapa
import publicacion

from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import time

import requests

import publish
from variants import variant_conflicts


API_BASE_URL = "https://api.mercadolibre.com"
SITE_ID = "MLA"
ART = timezone(timedelta(hours=-3))
START_HOUR = 6
# Días de oferta especial (ej. CyberMonday): a la 13:00 ART se refrescan los precios de ML una vez más.
# Amazon no se vuelve a releer: se reutiliza el amazon-prices.json del día tal cual.
EXTRA_REFRESH_DATES = {"2026-11-02", "2026-11-03", "2026-11-04", "2026-11-27", "2026-11-30"}
EXTRA_REFRESH_HOUR = 13
RETRY_WAIT_SECONDS = 60.0  # espera antes del único reintento de las consultas fallidas dentro del mismo paso
MIN_SAVING = 0.10
AMAZON_EXTRA = 0.04
# Pausa entre llamadas para no castigar la API de Mercado Libre.
PAUSE_SECONDS = 0.3
# Afiliados de Mercado Libre (públicos, van en cada link compartido). Igual que src/config.ts.
AFFILIATE = {"matt_word": "ale_benzoni", "matt_tool": "58527537"}
_token_cache = {"value": None, "expires_at": 0.0}


def is_configured():
    return all(os.environ.get(key, "").strip() for key in ("ML_CLIENT_ID", "ML_CLIENT_SECRET"))


def pause():
    time.sleep(PAUSE_SECONDS)


def get_token():
    """Token client_credentials, cacheado en memoria hasta casi su vencimiento."""
    if _token_cache["value"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["value"]
    response = requests.post(
        API_BASE_URL + "/oauth/token",
        data={"grant_type": "client_credentials",
              "client_id": os.environ["ML_CLIENT_ID"],
              "client_secret": os.environ["ML_CLIENT_SECRET"]},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    expires_in = float(body.get("expires_in", 3600))
    _token_cache.update(value=body["access_token"],
                        expires_at=time.time() + max(60.0, expires_in - 120))
    return _token_cache["value"]


def get_json(path, params=None):
    response = requests.get(
        API_BASE_URL + path,
        params=params,
        headers={"Authorization": f"Bearer {get_token()}"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def search_products(query):
    """Catálogo de Mercado Libre por texto. Devuelve la lista de resultados con id y name."""
    return get_json("/products/search", {"status": "active", "site_id": SITE_ID, "q": query}).get("results", [])


def is_no_winners(response):
    if response is None or response.status_code != 404:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and body.get("error") == "not_found" \
        and "no winners" in str(body.get("message", "")).lower()


def fetch_items(catalog_id):
    if not re.fullmatch(r"[A-Za-z0-9]+", str(catalog_id)):
        raise ValueError("catalogId inválido")
    try:
        payload = get_json(f"/products/{catalog_id}/items")
    except requests.HTTPError as exc:
        # 404 "No winners found": el producto de catálogo existe pero hoy no tiene vendedores activos.
        # Es ausencia confirmada, no una falla de la consulta.
        if is_no_winners(exc.response):
            return []
        raise
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Respuesta de ML sin resultados válidos")
    return payload["results"]


def is_international(item):
    """Compra internacional (CBT): vendedor de afuera, llega con aduana. No cuenta como precio en Argentina."""
    tags = list(item.get("tags") or []) + list((item.get("shipping") or {}).get("tags") or [])
    return any(isinstance(t, str) and t.startswith("cbt") for t in tags) \
        or item.get("international_delivery_mode") not in (None, "none")


def cheapest_new(results):
    """(precio, item_id) de la publicación nueva más barata vendida desde Argentina. Sin campo condition se acepta."""
    best = None
    for item in results:
        if not isinstance(item, dict) or item.get("condition") not in (None, "new"):
            continue
        if ("currency_id" in item and item["currency_id"] != "ARS") or is_international(item):
            continue
        price = item.get("price")
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            continue
        if math.isfinite(price) and price > 0 and (best is None or price < best[0]):
            item_id = item.get("item_id") or item.get("id")
            best = (price, item_id if isinstance(item_id, str) and re.fullmatch(r"MLA\d+", item_id) else None)
    return best


def min_new_price(results):
    best = cheapest_new(results)
    return best[0] if best else None


def item_url(catalog_id, item_id):
    """Ficha del producto con esa publicación elegida y el código de afiliado."""
    params = f"matt_word={AFFILIATE['matt_word']}&matt_tool={AFFILIATE['matt_tool']}"
    if item_id:
        params = f"pdp_filters=item_id%3A{item_id}&" + params
    return f"https://www.mercadolibre.com.ar/p/{catalog_id}?{params}"


def _js_round(value):
    return math.floor(value + 0.5)


def shipping_for(usd):
    return 0 if usd >= 100 else 45


def amazon_total_usd(usd, shipping_usd=None):
    """Costo total en USD puesto en casa (impuestos + envío + 4% de Amazon), igual que el sitio."""
    if shipping_usd is None:
        shipping_usd = shipping_for(usd)
    excess = max(0.0, usd - 400.0)
    iva_base = usd + shipping_usd + excess * 0.35 + excess * 0.03
    iva = iva_base * 0.21
    calc_total = _js_round((iva_base + iva) * 100) / 100
    return _js_round((calc_total + usd * AMAZON_EXTRA) * 100) / 100


def estimate_from_amazon(usd, mep):
    """Total en ARS al MEP con la misma fórmula que estimateFromAmazon en src/lib/estimate.ts."""
    shipping_usd = shipping_for(usd)
    excess = max(0.0, usd - 400.0)
    iva_base = usd + shipping_usd + excess * 0.35 + excess * 0.03
    iva = iva_base * 0.21
    calc_total = _js_round((iva_base + iva) * 100) / 100
    return int(_js_round((calc_total + usd * AMAZON_EXTRA) * mep))


def round_ars_10k(value):
    """Redondea al múltiplo de 10.000 ARS más cercano, igual que roundArs10k en src/lib/data.ts."""
    return int(_js_round(value / 10000.0) * 10000)


def verdict_for(total_usd, mep, ml_price, free_shipping):
    """Amazon sólo gana si ahorra al menos 10% y el envío a Argentina es gratis."""
    # round evita que 0.9 se vea como 0.0999... en el borde del 10%.
    saving = round(1 - total_usd * mep / ml_price, 6)
    return "amazon" if free_shipping is True and saving >= MIN_SAVING else "ml"


def verdict_from_ars(ml_price, amazon_ars, free_shipping):
    """Misma regla que comparePrices en src/lib/data.ts sobre el precio ML y el estimado ARS redondeado."""
    if not _is_valid_amount(ml_price) or not _is_valid_amount(amazon_ars):
        return "ml"
    saving = round(1 - amazon_ars / ml_price, 6)
    if saving < MIN_SAVING:
        return "ml"
    # Amazon sale menos pero sin envío confirmado a Argentina: no hay ganador.
    return "amazon" if free_shipping is True else "sin_envio"


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _is_valid_amount(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) and value > 0


def _today_art(now=None):
    if isinstance(now, datetime):
        return now.astimezone(ART).date()
    if isinstance(now, date):
        return now
    return datetime.now(ART).date()


def _is_fresh_checked(checked, today_date):
    return isinstance(checked, str) and checked == today_date.isoformat()


def _slot_id(date_str, hour):
    return f"{date_str}T{hour:02d}"


def _done_slot(previous):
    """Slot ya ejecutado según el archivo guardado. Sin clave "slot" vale el slot de la mañana de su "date"."""
    if not isinstance(previous, dict):
        return None
    slot = previous.get("slot")
    if isinstance(slot, str):
        return slot
    date_value = previous.get("date")
    if isinstance(date_value, str):
        return _slot_id(date_value, START_HOUR)
    return None


def load_amazon_prices(path, now=None):
    data = load_json(path, {})
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    today_date = _today_art(now)
    return {
        slug: entry
        for slug, entry in items.items()
        if isinstance(entry, dict)
        and entry.get("currency") in ("USD", "EUR")
        and _is_valid_amount(entry.get("amount"))
        and _is_fresh_checked(entry.get("checked"), today_date)
    }


def _resolve_amazon_usd(product, amazon_items, eur_usd=None):
    """Devuelve (usd, source, checked) sólo desde amazon-prices.json del día."""
    slug = product.get("slug")
    scraped = amazon_items.get(slug) if isinstance(amazon_items, dict) else None
    if isinstance(scraped, dict) and ("asin" not in scraped or scraped["asin"] == product.get("asin")) and _is_valid_amount(scraped.get("amount")):
        currency = scraped.get("currency")
        if currency == "USD":
            return float(scraped["amount"]), "amazon", scraped.get("checked")
        if currency == "EUR" and _is_valid_amount(eur_usd):
            return float(scraped["amount"]) * float(eur_usd), "amazon", scraped.get("checked")
    return None, None, None


def resolve_amazon_total(product, amazon_items, eur_usd=None):
    """Devuelve (total_usd, source) desde amazon-prices.json del día."""
    usd, source, _ = _resolve_amazon_usd(product, amazon_items, eur_usd)
    if usd is None:
        return None, None
    return amazon_total_usd(usd), source


def estimate_amazon_ars(product, amazon_items, mep, eur_usd=None):
    """Devuelve (amazon_ars, source, checked) redondeado a 10.000 ARS, igual que mergeAmazonPrices en TS."""
    if not _is_valid_amount(mep):
        return None, None, None
    usd, source, checked = _resolve_amazon_usd(product, amazon_items, eur_usd)
    if usd is None:
        return None, None, None
    return round_ars_10k(estimate_from_amazon(usd, mep)), source, checked


def functional_conflicts(product, amazon_items):
    """Diferencias de variante funcionales entre el título de Amazon (de hoy o del catálogo) y el nombre de ML.

    El color no frena la publicación (mismo modelo); switch, capacidad, tamaño, layout o conexión sí.
    """
    ml_name = (product.get("ml") or {}).get("name")
    amazon_title = (amazon_items.get(product.get("slug")) or {}).get("title") or product.get("amazonTitle")
    if not ml_name or not amazon_title:
        return []
    return [c for c in variant_conflicts(amazon_title, ml_name) if c != "color"]


def motivo_salteo_ml(product, sin_gratis, amazon_items, estado, today, modo, eur_usd=None):
    """Por qué ML no consulta este producto (08/11), o None: lo vio fallar una etapa anterior.

    Orden: requisitos del catálogo, envío visto por Chrome hoy, precio de Amazon de hoy en rango.
    """
    from amazon_prices import RANGE_MIN, RANGE_MAX
    motivo = motivo_total(product, estado, today, modo)
    if motivo:
        return motivo
    if product.get("store") == "US" and product.get("asin") in sin_gratis:
        return sin_gratis[product["asin"]]
    scraped = amazon_items.get(product["slug"])
    if not isinstance(scraped, dict) or scraped.get("asin", product.get("asin")) != product.get("asin"):
        return "sin_precio_amazon_hoy"
    usd, _, _ = _resolve_amazon_usd(product, amazon_items, eur_usd)
    # Sin cotización del euro no se puede medir el rango de España: no se saltea por eso.
    if usd is not None and not RANGE_MIN <= usd <= RANGE_MAX:
        return "amazon_fuera_de_rango"
    return None


@locked_refresh
def maybe_refresh(catalog, prices_path, amazon_prices_path, mep, now, eur_usd=None, *, force=False):
    """Recalcula al encadenar (force) o desde las 06:00 ART y, en los días de
    EXTRA_REFRESH_DATES, una vez más desde las 13:00 ART. Devuelve True si corrió."""
    local = now.astimezone(ART)
    today = local.date().isoformat()
    if not force and local.hour < START_HOUR:
        return False
    extra_slot = _slot_id(today, EXTRA_REFRESH_HOUR) if today in EXTRA_REFRESH_DATES else None
    previous = load_json(prices_path, None)
    # Un archivo de hoy marcado «completo: false» lo dejó el alta sin que la verificación corriera (F-15): para la
    # verificación no cuenta como pasada hecha (consulta todo). El alta sí lo retoma: sólo maneja sus productos.
    modo = modo_actual()
    done_slot = (_done_slot(previous) if isinstance(previous, dict) and previous.get("date") == today
                 and (previous.get("completo") is not False or modo == "alta") else None)
    # 08/11 (Alejandro: «cada elemento que no cumpla se tiene que filtrar en el mismo momento que vemos que no
    # cumple»): ML sólo consulta lo que pasó las etapas anteriores. Se saltea lo que no cumple el catálogo
    # (requisitos.py), lo que el Chrome de hoy vio sin envío gratis y lo que no tiene precio de Amazon de hoy
    # en rango. Lo salteado queda en «skipped» con su motivo; si más tarde en el día pasa (p. ej. un reintento
    # de Amazon lo recupera), cuenta como nuevo en la pasada siguiente y se consulta.
    from amazon_prices import chrome_sin_envio_gratis
    sin_gratis = chrome_sin_envio_gratis(amazon_prices_path, today)
    amazon_items = load_amazon_prices(amazon_prices_path, local.date())

    estado = publicacion.cargar(Path(prices_path).parent)
    if modo == "alta":
        # Todo el resto del flujo opera sólo sobre este bloque; los diagnósticos previos quedan intactos.
        catalog = [p for p in catalog if publicacion.motivo_estado(p, estado, today, modo) is None]
    fusionar = modo == "alta" and isinstance(previous, dict) and previous.get("date") == today
    salteos = {p["slug"]: m for p in catalog
               if p.get("slug") and (m := motivo_salteo_ml(p, sin_gratis, amazon_items, estado, today, modo, eur_usd))}
    nuevos = set()
    if extra_slot is not None and local.hour >= EXTRA_REFRESH_HOUR and done_slot != extra_slot:
        slot = extra_slot
    elif done_slot is not None:
        # 07/11: un alta confirmada de día entra al catálogo después del slot; con force se consulta igual.
        # 08/11: lo que se salteó antes y ahora cumple (p. ej. un reintento de Amazon le trajo precio) se
        # consulta en cualquier pasada, con o sin force.
        vistos = (set(previous.get("items") or {}) | set(previous.get("absent") or [])
                  | set(previous.get("failed") or []) | set(previous.get("variantConflict") or []))
        antes_salteados = set(previous.get("skipped") or {})
        nuevos = {p["slug"] for p in catalog if p.get("slug") and p["slug"] not in vistos and p["slug"] not in salteos
                  and (force or p["slug"] in antes_salteados)}
        if nuevos:
            print(f"Mercado Libre: {len(nuevos)} productos nuevos o que ahora cumplen desde el slot {done_slot}; se consultan: "
                  f"{', '.join(sorted(nuevos))}.", flush=True)
        elif not previous.get("failed") or previous.get("attempts", 1) >= 3 or previous.get("attemptHour") == local.hour:
            # Pasada horaria sin consulta: una sola línea (06/11: 275 líneas por hora tapaban lo importante).
            print(f"Mercado Libre: sin consulta en esta pasada (slot {done_slot} ya ejecutado).", flush=True)
            return False
        slot = done_slot
    else:
        slot = _slot_id(today, START_HOUR)
    if not is_configured():
        print("Mercado Libre: faltan ML_CLIENT_ID o ML_CLIENT_SECRET; se omite.", flush=True)
        for p in catalog:
            print(ml_line(p, "omitido", reason="credenciales_ml_ausentes"), flush=True)
        return False
    retry = done_slot == slot
    items = dict(previous.get("items") or {}) if retry or fusionar else {}
    absent = list(previous.get("absent") or []) if retry or fusionar else []
    propios = {p["slug"] for p in catalog}
    failed = [s for s in (previous.get("failed") or []) if s not in propios] if fusionar else []
    variant_conflict = [s for s in (previous.get("variantConflict") or []) if s not in propios] if fusionar else []
    if fusionar:
        salteos = {**{s: m for s, m in (previous.get("skipped") or {}).items() if s not in propios}, **salteos}
    attempts = previous.get("attempts", 1) + 1 if retry else 1
    consultados = 0
    # F-23: cada consulta queda en el diario al obtenerla; si el paso se corta, la corrida siguiente del mismo slot
    # retoma lo ya consultado en vez de repetir todo.
    journal = diario.ruta(prices_path, today)
    diario.purgar(prices_path, today)
    # También al reintentar o ampliar un slot ya hecho: si esa pasada se cortó antes de guardar el archivo, lo que ya
    # consultó está en el diario (mismo día y mismo slot). Las fallas nunca se anotan, así que no se congelan.
    resumidos = {r.get("slug"): r for r in diario.leer(journal)
                 if r.get("t") == "consulta" and r.get("slot") == slot and r.get("date") == today}
    fallaron = []

    def consultar(product, catalog_id):
        """Una consulta a ML: devuelve ('ok', entry), ('absent', None) o ('failed', excepción)."""
        try:
            best = cheapest_new(fetch_items(catalog_id))
            if best is None:
                return "absent", None
            price, item_id = best
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            return "failed", exc
        price = int(round(price))
        amazon_ars, source, _ = estimate_amazon_ars(product, amazon_items, mep, eur_usd)
        if amazon_ars is None:
            # Sin estimado de Amazon del día o sin cotización no hay cálculo: queda el veredicto del catálogo.
            verdict, reason = product.get("verdict") or "ml", "existing"
        else:
            free_shipping = (product.get("shipsToAr") or {}).get("freeShipping")
            verdict, reason = verdict_from_ars(price, amazon_ars, free_shipping), "precio"
        entry = {"catalogId": catalog_id, "price": price, "url": item_url(catalog_id, item_id), "checked": today,
                 "verdict": verdict, "verdictReason": reason}
        if source:
            entry["amazonSource"] = source
        return "ok", entry

    def anotar(slug, estado, entry=None):
        diario.anotar(journal, {"t": "consulta", "date": today, "slot": slot,
                                "at": datetime.now(ART).isoformat(timespec="seconds"),
                                "slug": slug, "estado": estado, "entry": entry})

    for product in catalog:
        slug = product["slug"]
        catalog_id = (product.get("ml") or {}).get("catalogId")
        if retry and slug not in previous.get("failed", []) and slug not in nuevos:
            status = "ok" if slug in items else "absent" if slug in absent else "omitido"
            print(ml_line(product, status, items.get(slug), salteos.get(slug) or "sin_reconsulta_en_este_reintento"), flush=True)
            continue
        if slug in salteos:
            print(ml_line(product, "omitido", reason=salteos[slug]), flush=True)
            continue
        consultados += 1
        conflicto = functional_conflicts(product, amazon_items)
        if conflicto:
            # Par mal emparejado (p. ej. G915 X Clicky vs Tactile, 05/11): no se publica y queda registrado.
            variant_conflict.append(slug)
            print(ml_line(product, "variantConflict", reason=", ".join(conflicto)), flush=True)
            print(f"VARIANTE_DISTINTA {slug}: {', '.join(conflicto)} (Amazon vs ML); no se publica.", flush=True)
            continue
        registro = resumidos.get(slug)
        if registro is not None and registro.get("estado") in ("ok", "absent") and (
                registro.get("estado") == "absent" or (registro.get("entry") or {}).get("catalogId") == catalog_id):
            if registro["estado"] == "ok":
                items[slug] = registro["entry"]
            else:
                absent.append(slug)
            print(ml_line(product, registro["estado"], registro.get("entry"), "ya_consultado_hoy"), flush=True)
            continue
        estado, resultado = consultar(product, catalog_id)
        if estado == "absent":
            absent.append(slug)
            anotar(slug, "absent")
            print(ml_line(product, "absent", reason="sin_oferta_local_nueva"), flush=True)
        elif estado == "failed":
            failed.append(slug)
            fallaron.append(product)
            print(ml_line(product, "failed", reason=f"consulta_{type(resultado).__name__}"), flush=True)
            print(f"Mercado Libre: no se pudo consultar {slug} ({type(resultado).__name__}); se omite.", flush=True)
        else:
            items[slug] = resultado
            anotar(slug, "ok", resultado)
            print(ml_line(product, "ok", resultado), flush=True)
        pause()
    if fallaron and not retry:
        # F-21: una vez, en este mismo paso, se reintentan las consultas que fallaron; la cadena corre ML una sola vez
        # por bloque y lo que quedaba en «failed» seguía sin precio de hoy (y fuera del sitio) hasta mañana.
        print(f"Mercado Libre: {len(fallaron)} consultas fallidas; espero {RETRY_WAIT_SECONDS:.0f} s y las reintento "
              f"una vez en este paso.", flush=True)
        time.sleep(RETRY_WAIT_SECONDS)
        for product in fallaron:
            slug = product["slug"]
            estado, resultado = consultar(product, (product.get("ml") or {}).get("catalogId"))
            if estado == "failed":
                print(ml_line(product, "failed", reason=f"reintento_{type(resultado).__name__}"), flush=True)
            else:
                failed.remove(slug)
                if estado == "ok":
                    items[slug] = resultado
                    anotar(slug, "ok", resultado)
                else:
                    absent.append(slug)
                    anotar(slug, "absent")
                print(ml_line(product, estado, resultado if estado == "ok" else None, "recuperado_en_reintento"), flush=True)
            pause()
    # F-15: el alta sin archivo de hoy de la verificación escribe sólo sus productos; se marca para que el deploy
    # no lo tome como corrida entera (y la verificación del día no lo dé por hecho).
    parcial = (modo == "alta" and not fusionar) or (fusionar and previous.get("completo") is False)
    publish.write_atomic(prices_path, {"generatedAt": now.isoformat(), "date": today, "slot": slot, "items": items,
                                       "absent": absent, "failed": failed, "variantConflict": variant_conflict,
                                       "skipped": salteos, "attempts": attempts, "attemptHour": local.hour,
                                       **({"completo": False} if parcial else {})})
    print(f"Mercado Libre: precios actualizados, productos={len(items)}.", flush=True)
    print(resumen_etapa("ml", len(catalog), salteos, consultados=consultados, con_precio=len(items),
                        sin_oferta_local=len(absent), fallas=len(failed), variante_distinta=len(variant_conflict)), flush=True)
    return True


def merge(catalog, prices_path, amazon_prices_path=None, mep=None, eur_usd=None, now=None):
    """Catálogo con el precio de ML, estimado ARS de Amazon y veredicto recalculado (igual que el sitio)."""
    data = load_json(prices_path, None)
    items = data.get("items") if isinstance(data, dict) else None
    amazon_items = load_amazon_prices(amazon_prices_path, now) if amazon_prices_path else {}
    compute_estimates = mep is not None or amazon_prices_path is not None
    if not isinstance(items, dict) and not amazon_items and not compute_estimates:
        return catalog
    items = items if isinstance(items, dict) else {}
    today_date = _today_art(now) if now is not None else None
    merged = []
    for product in catalog:
        slug = product.get("slug")
        item = items.get(slug)
        price = item.get("price") if isinstance(item, dict) else None
        checked = item.get("checked") if isinstance(item, dict) else None
        if checked is None and isinstance(data, dict):
            checked = data.get("date")
        fresh_ml = True if today_date is None else _is_fresh_checked(checked, today_date)
        has_ml = (
            bool(product.get("ml"))
            and fresh_ml
            and isinstance(item, dict)
            and ("catalogId" not in item or item["catalogId"] == product["ml"].get("catalogId"))
            and not isinstance(price, bool)
            and isinstance(price, (int, float))
            and math.isfinite(price)
        )
        if not has_ml and not compute_estimates:
            merged.append(product)
            continue
        out = {**product}
        if has_ml:
            out["ml"] = {**product["ml"], "price": price}
            if isinstance(checked, str):
                out["ml"]["checked"] = checked
            if item.get("verdict") in ("amazon", "ml"):
                out["verdict"] = item["verdict"]
            if not compute_estimates and item.get("amazonSource") == "amazon":
                out["amazonSource"] = item["amazonSource"]
        elif compute_estimates:
            out["ml"] = None
        if compute_estimates:
            amazon_ars, source, amz_checked = estimate_amazon_ars(out, amazon_items, mep, eur_usd)
            out["amazonArs"] = amazon_ars
            out["amazonSource"] = source
            out["amazonChecked"] = amz_checked
            out["amazonUsd"] = _resolve_amazon_usd(out, amazon_items, eur_usd)[0]
            ml_price = (out.get("ml") or {}).get("price")
            if _is_valid_amount(ml_price) and amazon_ars is not None:
                free_shipping = (out.get("shipsToAr") or {}).get("freeShipping")
                out["verdict"] = verdict_from_ars(ml_price, amazon_ars, free_shipping)
            elif amazon_ars is None and mep is not None:
                out["verdict"] = "ml"
        merged.append(out)
    return merged
