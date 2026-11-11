"""Alta de productos al revés (05/11): de lo que ML vende en Argentina hacia Amazon.

Medido el 05/11: partiendo de los más vendidos de Amazon, 153 candidatos dieron 2 altas (63 sin vendedor local en ML,
p. ej. Canon PowerShot V10 sólo con publicaciones internacionales). Partiendo de ML: 1.871 más vendidos en 468
categorías de tecnología, 1.861 con vendedor nuevo en Argentina, 327 entre USD 100 y 1.000 que no estaban.

Flujo: más vendidos de ML (/highlights, API oficial) con vendedor local nuevo -> nombre del producto (/products/{id})
-> búsqueda en Amazon US con el scraper (/search, sin patrocinados) -> mismo formato que discover_products para que
match_candidates valide el par (marca, modelo, variante, capacidad, precio) con las mismas reglas de siempre.
"""
import time

import requests

import ml_prices
from tools import discover_products as discovery
from buscar_log import BuscarLog, line, check_stop

RAICES = ("MLA1648", "MLA1000", "MLA1051", "MLA1144", "MLA1039")  # Computación, Electrónica, Celulares, Consolas, Cámaras
PROFUNDIDAD = 2
# 05/11: el rango USD 100-400 es sobre el precio de AMAZON (franquicia) y se exige en should_keep_amazon_item.
# Sobre ML sólo un margen coherente con el validador (ML entre 0,6 y 6 veces Amazon): 100/1,67 ~ 60 y 400*6 = 2.400.
# Antes 100-1.000 (inventado): descartaba sin buscar productos con ML a 3,5x Amazon, como el Logitech G733.
ML_MIN_USD, ML_MAX_USD = 60, 2400
RESULTADOS_AMAZON = 8

from tools.categorias_ml import DOMINIOS, categoria_ml  # noqa: E402,F401  (movido 11/11)


def _get(path, **params):
    for intento in range(3):
        check_stop()
        r = requests.get(ml_prices.API_BASE_URL + path, params=params,
                         headers={"Authorization": f"Bearer {ml_prices.get_token()}"}, timeout=30)
        if r.status_code == 429 and intento < 2:
            time.sleep(2 * (intento + 1))
            continue
        return r
    return r


def categorias(raiz, profundidad=PROFUNDIDAD, journal=None, failures=None):
    check_stop()
    key = f"arbol:{raiz}"
    saved = journal.resolved("categoria").get(key) if journal else None
    if saved:
        hijos = saved["children"]
    else:
        try:
            r = _get(f"/categories/{raiz}")
            r.raise_for_status()
            hijos = r.json().get("children_categories") or []
            if not isinstance(hijos, list) or any(not isinstance(h, dict) or not isinstance(h.get("id"), str) for h in hijos):
                raise ValueError("Categorías hijas inválidas")
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            line("BUSCAR_CATEGORIA", id=raiz, estado="error", motivo=str(exc))
            if journal:
                journal.append("categoria_error", key, "error", str(exc))
            if failures is not None:
                failures.append({"categoria": raiz, "motivo": str(exc)})
            return [raiz]
        line("BUSCAR_CATEGORIA", id=raiz, estado="ok", n=len(hijos))
        if journal:
            journal.append("categoria", key, "ok", children=hijos)
    out = [raiz]
    if profundidad > 0:
        for h in hijos:
            out += categorias(h["id"], profundidad - 1, journal=journal, failures=failures)
    return out


def mas_vendidos_ml(catalog_ids_existentes, journal=None, failures=None):
    """No esconder categorías fallidas como si fueran listas vacías."""
    vistos = {}
    for raiz in RAICES:
        for cat in categorias(raiz, journal=journal, failures=failures):
            check_stop()
            saved = journal.resolved("destacados").get(cat) if journal else None
            if saved:
                content = saved["content"]
            else:
                try:
                    r = _get(f"/highlights/MLA/category/{cat}")
                    r.raise_for_status()
                    content = r.json().get("content") or []
                    if not isinstance(content, list) or any(not isinstance(x, dict) for x in content):
                        raise ValueError("Destacados inválidos")
                except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                    line("BUSCAR_CATEGORIA", id=cat, estado="error", motivo=str(exc))
                    if journal:
                        journal.append("categoria_error", cat, "error", str(exc))
                    if failures is not None:
                        failures.append({"categoria": cat, "motivo": str(exc)})
                    continue
                line("BUSCAR_CATEGORIA", id=cat, estado="ok", n=len(content))
                if journal:
                    journal.append("destacados", cat, "ok", content=content)
            for x in content:
                if x.get("type") == "PRODUCT" and x.get("id") not in catalog_ids_existentes:
                    vistos.setdefault(x["id"], cat)
    return vistos


def agregar_identificadores(filas, consulta_ar=None, lote=5, journal=None):
    """Guarda evidencia por ASIN y no confunde servicio caído con ausencia de identificadores."""
    import amazon_prices
    consulta_ar = consulta_ar or (lambda asins: amazon_prices.fetch_ar_shipping(amazon_prices.ar_url(), asins, "US"))
    asins = list(dict.fromkeys(f["asin"] for f in filas if f.get("store", "US") == "US"))
    saved = journal.resolved("ident") if journal else {}
    ids = {asin: saved[asin]["identifiers"] for asin in asins if asin in saved}
    missing = [asin for asin in asins if asin not in ids]
    for i in range(0, len(missing), lote):
        check_stop()
        batch = missing[i:i + lote]
        batch_error = ""
        try:
            response = consulta_ar(batch) or {}
            if not isinstance(response, dict):
                raise ValueError("Respuesta de identificadores inválida")
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            batch_error = str(exc) or type(exc).__name__
            response = {}
        for asin in batch:
            item = response.get(asin)
            item = item if isinstance(item, dict) else {}
            if item.get("error") or not isinstance(item.get("identifiers"), dict):
                reason = item.get("error") or batch_error or "respuesta_sin_identificadores"
                line("IDENT", asin=asin, estado="error", motivo=reason)
                if journal:
                    journal.append("ident_error", asin, "error", reason)
                continue
            ids[asin] = response[asin].get("identifiers") or {}
            status = "ok" if ids[asin] else "sin_identificadores"
            if journal:
                journal.append("ident", asin, status, identifiers=ids[asin])
            line("IDENT", asin=asin, estado=status)
        if i + lote < len(missing):
            time.sleep(amazon_prices.PAUSE_SECONDS)
    for f in filas:
        f["amazonIds"] = ids.get(f["asin"], {})
    return sum(bool(ids.get(asin)) for asin in asins)


def candidatos(existing_asins, catalog_ids_existentes, mep, get=None, failures=None, limite=None, state=None, output=None, journal=None, on_product=None, progress=None):
    """Lista en el formato de discover_products: [{asin, amazonTitle, brand, amazonPriceUsd, ml: [...]}]."""
    journal = journal or BuscarLog(output or "/app/output")
    resolved = journal.resolved("ml")
    out = [p for r in journal.records if r["stage"] == "ml" for p in r.get("pairs", [])]
    vistos_asin = {p["asin"] for p in out}
    productos = list(mas_vendidos_ml(catalog_ids_existentes, journal=journal, failures=failures))
    # Guardar el próximo catalogId evita desplazar el cursor si salen productos de la lista.
    cursor = (state or {}).get("cursorMl")
    start = productos.index(cursor) if cursor in productos else 0
    productos = productos[start:] + productos[:start]
    print(f"Catálogo desde ML: {len(productos)} más vendidos fuera del catálogo.", flush=True)

    def finish(pid, status, reason, pairs):
        if status == "error_busqueda":
            for pair in pairs:
                pair["_discoveryError"] = reason
        journal.append("ml", pid, status, reason, pairs=pairs)
        line("BUSCAR_ML", id=pid, estado=status, motivo=reason, pares=len(pairs))
        if state is not None:
            state["cursorMl"] = productos[n % len(productos)]
            state["ultimoCatalogId"] = pid
            state["resolvedMl"] = len(journal.resolved("ml"))
        if progress:
            progress()
        for pair in pairs:
            if on_product:
                on_product(pair)

    for n, pid in enumerate(productos, start=1):
        check_stop()
        if pid in resolved:
            line("BUSCAR_ML", id=pid, estado="salteado", motivo="resuelto_7_dias")
            continue
        if limite and n > limite:
            break
        try:
            best = ml_prices.cheapest_new(ml_prices.fetch_items(pid))
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            finish(pid, "error_precio", str(exc), [])
            if failures is not None:
                failures.append({"catalogId": pid, "motivo": type(exc).__name__})
            continue
        if not best or not best[1]:
            finish(pid, "sin_precio", "sin_vendedor_nuevo_local", [])
            continue
        precio, item_id = best
        if not (ML_MIN_USD <= precio / mep <= ML_MAX_USD):
            finish(pid, "fuera_de_rango", f"precio_usd={precio / mep}", [])
            continue
        try:
            r = _get(f"/products/{pid}")
            r.raise_for_status()
            ficha = r.json()
            if not isinstance(ficha, dict):
                raise ValueError("Ficha ML inválida")
            nombre = (ficha.get("name") or "").strip()
            attrs = {x.get("id"): (x.get("value_name") or "").strip() for x in ficha.get("attributes") or []}
            if not nombre:
                raise ValueError("sin_nombre")
            journal.append("ficha_ml", pid, "ok", product=ficha)
        except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
            finish(pid, "sin_ficha", str(exc), [])
            if failures is not None:
                failures.append({"catalogId": pid, "motivo": type(exc).__name__})
            continue
        marca_modelo = " ".join(filter(None, [attrs.get("BRAND"), attrs.get("MODEL") or attrs.get("ALPHANUMERIC_MODEL")]))
        # 05/11: dos búsquedas (nombre comercial y marca + modelo); la prueba A/B mostró que cada una encuentra
        # productos que la otra no (sobre 219 productos: 0 vs 2 aceptados, y la de nombre encontró otros 5).
        consultas = [nombre] + ([marca_modelo] if marca_modelo and marca_modelo.lower() != nombre.lower() else [])
        # 05/11: tercera búsqueda por el CÓDIGO de modelo de la ficha (Galaxy A17 4G = SM-A175F): el nombre y la
        # marca+modelo traían sólo la versión 5G; el código lleva directo al ASIN correcto (B0FRYP55LB).
        codigo = (attrs.get("ALPHANUMERIC_MODEL") or (attrs.get("MPN") or "").split(",")[0]).strip()
        if codigo and len(codigo) >= 4 and any(ch.isdigit() for ch in codigo):
            consultas.append(f"{attrs.get('BRAND', '')} {codigo}".strip())
        # Cuarta: código de barras de la ficha (GTIN/EAN); el buscador de Amazon también encuentra por UPC/EAN.
        gtin = (attrs.get("GTIN") or "").split(",")[0].strip()
        if gtin.isdigit() and len(gtin) >= 8:
            consultas.append(gtin)
        resultados, errors, descartes = [], [], {"patrocinados": 0, "filtro_amazon": 0}
        first_pair = len(out)
        for consulta in consultas:
            check_stop()
            try:
                saved = journal.resolved("amazon_busqueda").get(consulta)
                items = saved["items"] if saved else discovery.fetch_search_results(consulta, limit=RESULTADOS_AMAZON, **({"get": get} if get else {}))
                if items and not saved:
                    journal.append("amazon_busqueda", consulta, "ok", items=items)
                if saved:
                    line("BUSCAR_ML_CONSULTA", id=pid, consulta=consulta, estado="salteado", motivo="cache_hoy")
                resultados += items
            except discovery.PageBudgetExhausted:
                line("BUSCAR_ML", id=pid, estado="interrumpido", motivo="limite_paginas")
                journal.stop_reason = "limite_paginas"
                return out
            except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError) as exc:
                errors.append(type(exc).__name__)
                line("BUSCAR_ML_CONSULTA", id=pid, consulta=consulta, estado="error", motivo=str(exc))
                if failures is not None:
                    failures.append({"catalogId": pid, "motivo": f"busqueda_amazon:{type(exc).__name__}"})
        for item in resultados:
            if item.get("is_sponsored"):
                descartes["patrocinados"] += 1
                line("BUSCAR_AMAZON", asin=item.get("asin"), estado="salteado", motivo="patrocinado")
                continue
            if not discovery.should_keep_amazon_item(item, existing_asins, vistos_asin):
                descartes["filtro_amazon"] += 1
                line("BUSCAR_AMAZON", asin=item.get("asin"), estado="salteado", motivo="filtro_amazon")
                continue
            asin = item["asin"].strip()
            vistos_asin.add(asin)
            out.append({"asin": asin, "store": "US", "amazonTitle": (item.get("title") or "").strip(),
                        # Categoría: la del dominio de ML; si no se reconoce, el título de Amazon (último recurso).
                        "brand": discovery.infer_brand(item),
                        "amazonCategory": categoria_ml(ficha.get("domain_id")) or (item.get("title") or "").strip(),
                        "amazonPriceUsd": discovery.extract_price_usd(item),
                        "ml": [{"catalogId": pid, "name": nombre, "minPrice": precio, "itemId": item_id}]})
        pairs = out[first_pair:]
        finish(pid, "error_busqueda" if errors else "sin_resultados" if not resultados else "con_pares" if pairs else "sin_pares",
               ",".join(errors) or f"consultas_completas descartes={descartes}", pairs)
        if n % 25 == 0:
            print(f"Catálogo desde ML: {n}/{len(productos)} revisados, {len(out)} pares para validar.", flush=True)
    return out
