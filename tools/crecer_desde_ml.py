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

RAICES = ("MLA1648", "MLA1000", "MLA1051", "MLA1144", "MLA1039")  # Computación, Electrónica, Celulares, Consolas, Cámaras
PROFUNDIDAD = 2
# 05/11: el rango USD 100-400 es sobre el precio de AMAZON (franquicia) y se exige en should_keep_amazon_item.
# Sobre ML sólo un margen coherente con el validador (ML entre 0,6 y 6 veces Amazon): 100/1,67 ~ 60 y 400*6 = 2.400.
# Antes 100-1.000 (inventado): descartaba sin buscar productos con ML a 3,5x Amazon, como el Logitech G733.
ML_MIN_USD, ML_MAX_USD = 60, 2400
RESULTADOS_AMAZON = 8

# 05/11: categoría del sitio desde el dominio de la ficha de ML (domain_id). Adivinarla por palabras del título de
# Amazon puso un celular en «Cámaras» (por su cámara) y un TV Box en «Almacenamiento» (por sus 32 GB).
DOMINIOS = (
    ("CELLPHONE", "Celulares"), ("SMARTPHONE", "Celulares"),
    ("TABLET", "Tablets y lectores"), ("EBOOK_READER", "Tablets y lectores"), ("E_BOOK", "Tablets y lectores"),
    ("SMARTWATCH", "Relojes"), ("FITNESS_TRACKER", "Relojes"), ("WATCH", "Relojes"),
    ("MONITOR", "Monitores"), ("MINI_PC", "Mini PCs"), ("ROUTER", "Redes"), ("NETWORK", "Redes"), ("MESH", "Redes"),
    ("HARD_DRIVE", "Almacenamiento"), ("SOLID_STATE", "Almacenamiento"), ("SSD", "Almacenamiento"),
    ("MEMORY_CARD", "Almacenamiento"), ("USB_FLASH", "Almacenamiento"), ("PEN_DRIVE", "Almacenamiento"),
    ("KEYBOARD", "Periféricos"), ("MOUSE", "Periféricos"), ("MICE", "Periféricos"), ("WEBCAM", "Periféricos"),
    ("GAME_CONSOLE", "Gaming"), ("VIDEO_GAME", "Gaming"), ("GAMEPAD", "Gaming"), ("JOYSTICK", "Gaming"),
    ("CPU", "Componentes"), ("PROCESSOR", "Componentes"), ("GRAPHICS_CARD", "Componentes"), ("MOTHERBOARD", "Componentes"),
    ("RAM_MEMOR", "Componentes"), ("POWER_SUPPL", "Componentes"), ("COMPUTER_COOLER", "Componentes"),
    ("DRONE", "Cámaras"), ("CAMERA", "Cámaras"), ("LENS", "Cámaras"), ("CAMCORDER", "Cámaras"),
    ("POWER_BANK", "Carga y energía"), ("CHARGER", "Carga y energía"),
    ("PRINTER", "Oficina"),
    ("SPEAKER", "Audio y video"), ("HEADPHONE", "Audio y video"), ("EARPHONE", "Audio y video"), ("SOUNDBAR", "Audio y video"),
    ("STREAMING", "Audio y video"), ("TV_BOX", "Audio y video"), ("TELEVISION", "Audio y video"), ("PROJECTOR", "Audio y video"),
    ("DJ_", "Audio y video"), ("MICROPHONE", "Audio y video"), ("AUDIO_INTERFACE", "Audio y video"), ("SMART_SPEAKER", "Audio y video"),
    ("VOICE_RECORDER", "Audio y video"), ("TURNTABLE", "Audio y video"),
)


def categoria_ml(domain_id):
    dominio = (domain_id or "").upper()
    return next((cat for clave, cat in DOMINIOS if clave in dominio), "")


def _get(path, **params):
    for intento in range(3):
        r = requests.get(ml_prices.API_BASE_URL + path, params=params,
                         headers={"Authorization": f"Bearer {ml_prices.get_token()}"}, timeout=30)
        if r.status_code == 429 and intento < 2:
            time.sleep(2 * (intento + 1))
            continue
        return r
    return r


def categorias(raiz, profundidad=PROFUNDIDAD):
    r = _get(f"/categories/{raiz}")
    if not r.ok:
        return []
    hijos = r.json().get("children_categories") or []
    out = [raiz]
    if profundidad > 0:
        for h in hijos:
            out += categorias(h["id"], profundidad - 1)
    return out


def mas_vendidos_ml(catalog_ids_existentes):
    """{catalogId: categoria} de los más vendidos que no están en el catálogo."""
    vistos = {}
    for raiz in RAICES:
        for cat in categorias(raiz):
            r = _get(f"/highlights/MLA/category/{cat}")
            if not r.ok:
                continue
            for x in r.json().get("content") or []:
                if x.get("type") == "PRODUCT" and x.get("id") not in catalog_ids_existentes:
                    vistos.setdefault(x["id"], cat)
    return vistos


def candidatos(existing_asins, catalog_ids_existentes, mep, get=None, failures=None, limite=None):
    """Lista en el formato de discover_products: [{asin, amazonTitle, brand, amazonPriceUsd, ml: [...]}]."""
    out, vistos_asin = [], set()
    productos = mas_vendidos_ml(catalog_ids_existentes)
    print(f"Catálogo desde ML: {len(productos)} más vendidos fuera del catálogo.", flush=True)
    for n, pid in enumerate(productos, start=1):
        if limite and n > limite:
            break
        try:
            best = ml_prices.cheapest_new(ml_prices.fetch_items(pid))
        except (requests.RequestException, ValueError, KeyError, TypeError):
            best = None
        if not best or not best[1]:
            continue
        precio, item_id = best
        if not (ML_MIN_USD <= precio / mep <= ML_MAX_USD):
            continue
        r = _get(f"/products/{pid}")
        ficha = r.json() if r.ok else {}
        nombre = (ficha.get("name") or "").strip()
        if not nombre:
            continue
        attrs = {x.get("id"): (x.get("value_name") or "").strip() for x in ficha.get("attributes") or []}
        marca_modelo = " ".join(filter(None, [attrs.get("BRAND"), attrs.get("MODEL") or attrs.get("ALPHANUMERIC_MODEL")]))
        # 05/11: dos búsquedas (nombre comercial y marca + modelo); la prueba A/B mostró que cada una encuentra
        # productos que la otra no (sobre 219 productos: 0 vs 2 aceptados, y la de nombre encontró otros 5).
        consultas = [nombre] + ([marca_modelo] if marca_modelo and marca_modelo.lower() != nombre.lower() else [])
        resultados, cortar = [], False
        for consulta in consultas:
            try:
                resultados += discovery.fetch_search_results(consulta, limit=RESULTADOS_AMAZON, **({"get": get} if get else {}))
            except discovery.PageBudgetExhausted:
                cortar = True
                break
            except requests.RequestException as exc:
                if failures is not None:
                    failures.append({"catalogId": pid, "motivo": f"busqueda_amazon:{type(exc).__name__}"})
        if cortar:
            break
        for item in resultados:
            if item.get("is_sponsored"):
                continue
            if not discovery.should_keep_amazon_item(item, existing_asins, vistos_asin):
                continue
            asin = item["asin"].strip()
            vistos_asin.add(asin)
            out.append({"asin": asin, "store": "US", "amazonTitle": (item.get("title") or "").strip(),
                        # Categoría: la del dominio de ML; si no se reconoce, el título de Amazon (último recurso).
                        "brand": discovery.infer_brand(item),
                        "amazonCategory": categoria_ml(ficha.get("domain_id")) or (item.get("title") or "").strip(),
                        "amazonPriceUsd": discovery.extract_price_usd(item),
                        "ml": [{"catalogId": pid, "name": nombre, "minPrice": precio, "itemId": item_id}]})
        if n % 25 == 0:
            print(f"Catálogo desde ML: {n}/{len(productos)} revisados, {len(out)} pares para validar.", flush=True)
    return out
