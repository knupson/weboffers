"""Envío a Argentina leído con el Chrome de la VM en un contexto ANÓNIMO (sin cuenta), por CDP (05/11).

Motivo (verificado el 05/11): Amazon bloquea al servicio amazon-ar en el cambio de ubicación
(address-change -> HTTP 200 con 0 bytes; modal -> HTTP 503 con la página antibots). Un contexto anónimo
del Chrome real ya entra con «Deliver to Argentina» (ubicación por IP) y muestra «FREE delivery … to Argentina».
Sin cuenta de usuario: el contexto se crea vacío y se destruye al terminar.

Corre DENTRO del contenedor chrome-claude (CDP en 127.0.0.1:9222):
  docker exec chrome-claude python3 /tmp/envio_ar_chrome.py ASIN [ASIN ...]
Salida (stdout): un JSON {"generado": ..., "items": {asin: {"ships", "free", "text", "motivo"}}}.
ships/free: True/False sólo con evidencia en la página; None si no se pudo leer (no cuenta como «no envía»).
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from article_log import chrome_line

import websockets

CDP = "http://127.0.0.1:9222"
ART = timezone(timedelta(hours=-3))
TIMEOUT_PRODUCTO = 30
ESPERA_CARGA = 4
RECICLAR_CADA = 10  # pestaña nueva cada N productos: libera memoria (05/11 el kernel mató un Chrome por OOM con 3 GB)
# Para leer el texto de envío no hacen falta imágenes, videos ni fuentes: se bloquean para bajar memoria y tráfico.
BLOQUEADOS = ["*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.avif", "*.svg", "*.mp4", "*.webm", "*.m3u8",
              "*.woff", "*.woff2", "*.ttf", "*images-amazon.com/images/I/*", "*m.media-amazon.com/images/*"]

# 05/11: el envío se lee SÓLO del bloque de entrega de la oferta destacada (#deliveryBlockContainer dentro del
# recuadro de compra). Leyendo la página entera se tomaban «FREE delivery … to Argentina» de productos PATROCINADOS
# (bloques sp_detail*): el Kingston NV3 decía «FREE» por un patrocinado y su envío real era «$26.14 delivery».
LEER = r"""(() => {const t=document.body.innerText;
const bb=document.getElementById('desktop_qualifiedBuyBox')||document.getElementById('desktop_buybox')||document.getElementById('buybox');
const q=(sel)=>{const e=bb&&bb.querySelector(sel); return e?(e.innerText||'').replace(/\s+/g,' ').trim():'';};
const entrega=q('#deliveryBlockContainer')||q('#mir-layout-DELIVERY_BLOCK')||q('#deliveryBlockMessage');
const b=bb?(bb.innerText||''):'';
return JSON.stringify({deliver:((document.getElementById('glow-ingress-block')||{}).innerText||'').replace(/\s+/g,' '),
 buybox:!!bb,
 envio:entrega||null,
 sinOferta:(b.match(/[^\n]*(See All Buying Options|No featured offers available|cannot be shipped to your selected delivery location|This item cannot be shipped|Currently unavailable)[^\n]*/)||[])[0]||null,
 captcha:/captcha|Enter the characters you see/i.test(t),
 lang:(document.documentElement.lang||'').toLowerCase(),
 intersticial:/Click the button below to continue shopping/i.test(t)&&!document.getElementById('productTitle'),
 precio:(['#corePrice_feature_div .a-offscreen','#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen','#corePriceDisplay_desktop_feature_div .a-offscreen','#apex_desktop .a-offscreen'].map(s=>{const e=document.querySelector(s); return e && (e.innerText||e.textContent||'').trim();}).find(v=>v && /\d/.test(v)))||null,
 titulo:((document.getElementById('productTitle')||{}).innerText||'').trim().slice(0,80)})})()"""


# 07/11: Amazon muestra a veces «Click the button below to continue shopping» en vez del producto (se
# registraba mal como ubicacion_no_ar). Alejandro autorizó apretar el botón; después del clic la página
# salía en castellano, por eso se vuelve a cargar el producto con language=en_US.
CONTINUAR = r"""(() => {const b=document.querySelector('form button, form input[type=submit], button');
if(b){b.click(); return true;} return false;})()"""
INTENTOS_INTERSTICIAL = 2


# 10/11: con «See All Buying Options» el recuadro de compra no tiene oferta destacada, pero el panel de ofertas
# suele tener otro vendedor con envío gratis a Argentina: de 29 ASIN así (envio_ar_chrome.log, 07-09/11) el panel
# dio 8 elegibles. Se elige la oferta MÁS BARATA que cumpla (no la primera).
# En el contexto anónimo el panel lateral no abre ni con ?aod=1 ni con el clic (probado 10/11 en B0BHJF2VRN:
# #aod-offer-list nunca aparece): se pide desde la misma página el HTML que llena ese panel
# (/gp/product/ajax/aodAjaxMain, igual que worker/barrido/vendor/amazon/products.offers), con la ubicación y las
# cookies del contexto, y se lee con los selectores de parsers.offers_page/_offer.
LEER_PANEL = r"""(async () => {const tx=(e)=>e?(e.innerText||e.textContent||'').replace(/\s+/g,' ').trim():'';
const asin=(location.pathname.match(/\/dp\/([A-Z0-9]{10})/)||[])[1];
const q=new URLSearchParams({asin, pc:'dp', experienceId:'aodAjaxMain', filters:JSON.stringify({all:true,new:true})});
const r=await fetch('/gp/product/ajax/aodAjaxMain?'+q, {credentials:'include'});
const html=await r.text(); const doc=new DOMParser().parseFromString(html,'text/html');
const bloques=[...doc.querySelectorAll('#aod-pinned-offer, #aod-offer')];
return JSON.stringify({deliver:tx(document.getElementById('glow-ingress-block')),
 lang:(document.documentElement.lang||'').toLowerCase(), http:r.status,
 captcha:/captcha|Enter the characters you see/i.test(html),
 lista:!!(doc.getElementById('aod-offer-list')||doc.getElementById('aod-pinned-offer')),
 ofertas:bloques.map(b=>{const p=b.querySelector('#aod-offer-price')||b;
  const precio=tx(p.querySelector('.a-price:not([data-a-strike]) .a-offscreen'))||tx(p.querySelector('.aok-offscreen'));
  return {precio:precio||null,
   condicion:tx(b.querySelector('#aod-offer-heading'))||(b.id==='aod-pinned-offer'?'New':null),
   vendedor:tx(b.querySelector('#aod-offer-soldBy a'))||null,
   envio:tx(b.querySelector('[data-csa-c-delivery-price]'))||null,
   noEnvia:/cannot be shipped|does not ship/i.test(tx(b))};})})})()"""


def monto(texto):
    m = re.search(r"\$\s*([\d,]+(?:\.\d+)?)", texto or "")
    return float(m.group(1).replace(",", "")) if m else None


def interpretar_panel(d, previo):
    """Oferta más barata del panel que sea nueva, de USD 100 a 400, con «FREE delivery» y sin aviso de que no envía.
    Sin ninguna, se conserva el resultado del recuadro (sin_oferta_ar). Ante la duda, nada se da por bueno."""
    if not d or d.get("captcha") or not d.get("lista") or (d.get("lang") and not d["lang"].startswith("en")):
        return {**previo, "panel": "no_leido"}
    if "argentina" not in (d.get("deliver") or "").lower():
        return {**previo, "panel": "ubicacion_no_ar"}
    elegibles = []
    for oferta in d.get("ofertas") or []:
        precio = monto(oferta.get("precio"))
        if (precio is not None and 100 <= precio <= 400 and not oferta.get("noEnvia")
                and (oferta.get("condicion") or "").strip().lower().startswith("new")
                and re.match(r"\s*FREE (delivery|shipping)", oferta.get("envio") or "", re.I)):
            elegibles.append((precio, oferta))
    if not elegibles:
        return {**previo, "panel": f"sin_oferta_elegible:{len(d.get('ofertas') or [])}"}
    precio, oferta = min(elegibles, key=lambda e: e[0])
    return {"ships": True, "free": True, "text": oferta["envio"][:160], "motivo": "panel_ofertas",
            # Precio canónico: el texto del panel puede traer ruido («$389.67 with 13 percent savings», 10/11).
            "precio": f"${precio:.2f}", "vendedor": oferta.get("vendedor")}


def interpretar(d):
    """Traduce lo leído a ships/free con evidencia literal; ante la duda, None."""
    if d.get("captcha"):
        return {"ships": None, "free": None, "text": None, "motivo": "captcha"}
    if d.get("intersticial"):
        return {"ships": None, "free": None, "text": None, "motivo": "intersticial"}
    if d.get("lang") and not d["lang"].startswith("en"):
        # Los textos que se interpretan («FREE delivery», «See All Buying Options») están en inglés:
        # en otro idioma no se decide nada (07/11 «Entrega GRATIS» se leyó como envío pago).
        return {"ships": None, "free": None, "text": (d.get("envio") or "")[:160] or None, "motivo": "pagina_no_ingles"}
    if "argentina" not in (d.get("deliver") or "").lower():
        return {"ships": None, "free": None, "text": None, "motivo": "ubicacion_no_ar"}
    if d.get("buybox") is False:
        return {"ships": None, "free": None, "text": None, "motivo": "sin_recuadro_de_compra"}
    envio = d.get("envio")
    if d.get("sinOferta") and not envio:
        return {"ships": False, "free": None, "text": d["sinOferta"][:160], "motivo": "sin_oferta_ar"}
    if envio and d.get("precio"):
        # Envío confirmado sólo con texto de envío Y precio en el recuadro de compra: una oferta real.
        return {"ships": True, "free": bool(re.match(r"\s*FREE (delivery|shipping)", envio, re.I)), "text": envio[:160], "motivo": None,
                "precio": d.get("precio")}
    if envio:
        return {"ships": None, "free": None, "text": envio[:160], "motivo": "envio_sin_precio"}
    if d.get("sinOferta"):
        return {"ships": False, "free": None, "text": d["sinOferta"][:160], "motivo": "sin_oferta_ar"}
    if not d.get("titulo"):
        return {"ships": None, "free": None, "text": None, "motivo": "pagina_sin_producto"}
    return {"ships": None, "free": None, "text": None, "motivo": "sin_texto_de_envio"}


class Cdp:
    def __init__(self, ws):
        self.ws, self.n, self.pend = ws, 0, {}

    async def run(self):
        async for msg in self.ws:
            d = json.loads(msg)
            if "id" in d and d["id"] in self.pend:
                self.pend.pop(d["id"]).set_result(d)

    async def call(self, method, params=None, session=None, timeout=30):
        self.n += 1
        fut = asyncio.get_event_loop().create_future()
        self.pend[self.n] = fut
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        await self.ws.send(json.dumps(msg))
        r = await asyncio.wait_for(fut, timeout)
        if "error" in r:
            raise RuntimeError(f"{method}: {r['error']}")
        return r.get("result", {})


async def nueva_pestana(c, ctx):
    tid = (await c.call("Target.createTarget", {"url": "about:blank", "browserContextId": ctx}))["targetId"]
    s = (await c.call("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
    await c.call("Page.enable", {}, s)
    await c.call("Network.enable", {}, s)
    await c.call("Network.setBlockedURLs", {"urls": BLOQUEADOS}, s)
    # Precios en dólares en la página (preferencia de moneda de Amazon); sin cuenta.
    await c.call("Network.setCookie", {"name": "i18n-prefs", "value": "USD", "domain": ".amazon.com", "path": "/"}, s)
    await fijar_ingles(c, s)
    return tid, s


async def fijar_ingles(c, s):
    # Idioma de la página: la cadena interpreta textos en inglés (07/11, tras «Continue shopping» salía en castellano).
    await c.call("Network.setCookie", {"name": "lc-main", "value": "en_US", "domain": ".amazon.com", "path": "/"}, s)


async def leer_producto(c, s, asin):
    for intento in range(INTENTOS_INTERSTICIAL + 1):
        await c.call("Page.navigate", {"url": f"https://www.amazon.com/dp/{asin}?language=en_US"}, s)
        await asyncio.sleep(ESPERA_CARGA)
        r = await c.call("Runtime.evaluate", {"expression": LEER, "returnByValue": True}, s, timeout=TIMEOUT_PRODUCTO)
        if r.get("exceptionDetails"):
            # Un error del JavaScript de lectura nunca puede pasar como «página vacía» (05/11).
            det = r["exceptionDetails"]
            raise RuntimeError(f"js: {(det.get('exception') or {}).get('description') or det.get('text')}"[:200])
        d = json.loads((r.get("result") or {}).get("value") or "{}")
        if not d.get("intersticial") or intento == INTENTOS_INTERSTICIAL:
            return d
        print(f"{asin} intersticial: aprieto Continue shopping (intento {intento + 1})", file=sys.stderr, flush=True)
        await c.call("Runtime.evaluate", {"expression": CONTINUAR, "returnByValue": True}, s, timeout=TIMEOUT_PRODUCTO)
        await asyncio.sleep(ESPERA_CARGA)
        await fijar_ingles(c, s)
    return d


async def leer_panel(c, s, asin):
    """Se llama con la pestaña todavía en la ficha del producto (la dejó leer_producto): 1 pedido más."""
    r = await c.call("Runtime.evaluate", {"expression": LEER_PANEL, "returnByValue": True, "awaitPromise": True},
                     s, timeout=TIMEOUT_PRODUCTO)
    if r.get("exceptionDetails"):
        det = r["exceptionDetails"]
        raise RuntimeError(f"js panel: {(det.get('exception') or {}).get('description') or det.get('text')}"[:200])
    return json.loads((r.get("result") or {}).get("value") or "{}")


def abre_panel(item):
    return item.get("motivo") == "sin_oferta_ar" and "See All Buying Options" in (item.get("text") or "")


def ruta_parcial():
    """Archivo (dentro del contenedor) donde cada ASIN leído queda anotado al instante (F-06)."""
    return os.environ.get("AR_CHROME_PARCIAL") or f"/tmp/ar-chrome-parcial-{datetime.now(ART).date()}.jsonl"


def anexar_linea(ruta, linea):
    """Agrega una línea al parcial reparando antes una cola truncada por un KILL, bajo flock (como worker/diario.py)."""
    try:
        import fcntl
    except ImportError:  # sólo en Windows (tests): el contenedor de Chrome es Linux
        fcntl = None
    with open(ruta + ".lock", "a+b") as candado:
        if fcntl:
            fcntl.flock(candado, fcntl.LOCK_EX)
        with open(ruta, "a+b") as archivo:
            archivo.seek(0, os.SEEK_END)
            size = archivo.tell()
            if size:
                archivo.seek(size - 1)
                if archivo.read(1) != b"\n":
                    archivo.seek(0)
                    archivo.truncate(archivo.read().rfind(b"\n") + 1)
            archivo.seek(0, os.SEEK_END)
            archivo.write(linea.encode("utf-8") + b"\n")
            archivo.flush()
            os.fsync(archivo.fileno())


def guardar_parcial(ruta, asin, slugs, item):
    """Una línea JSON por ASIN con flush+fsync: un KILL pierde a lo sumo el ASIN en curso.

    Cada registro lleva su hora ART (`t`): un relevamiento que cruza la medianoche no mezcla días.
    La cadena (tools/envio_ar_chrome.sh) lo fusiona en ar-chrome-AAAA-MM-DD.json aunque el proceso muera."""
    anexar_linea(ruta, json.dumps({"t": item.get("leido") or datetime.now(ART).isoformat(timespec="seconds"),
                                   "asin": asin, "slugs": slugs, "item": item}, ensure_ascii=False))


async def recorrer(c, ctx, tid, s, asins, slugs, items, parcial):
    """Lee cada ASIN, lo anota en el parcial y lo imprime apenas lo tiene. Devuelve la pestaña vigente."""
    for n, asin in enumerate(asins):
        if n and n % RECICLAR_CADA == 0:
            try:
                await c.call("Target.closeTarget", {"targetId": tid}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            tid, s = await nueva_pestana(c, ctx)
        try:
            items[asin] = interpretar(await asyncio.wait_for(leer_producto(c, s, asin),
                                                               (TIMEOUT_PRODUCTO + 2 * ESPERA_CARGA) * (INTENTOS_INTERSTICIAL + 1) + 5))
            if abre_panel(items[asin]):
                # Un fallo del pedido del panel no tira la pestaña ni cambia lo leído en el recuadro: queda anotado.
                try:
                    d_panel = await asyncio.wait_for(leer_panel(c, s, asin), TIMEOUT_PRODUCTO + 5)
                    items[asin] = interpretar_panel(d_panel, items[asin])
                except Exception as exc:  # noqa: BLE001
                    items[asin] = {**items[asin], "panel": f"error:{type(exc).__name__}"}
        except Exception as e:  # noqa: BLE001 — página colgada: se anota y se sigue con otra pestaña
            items[asin] = {"ships": None, "free": None, "text": None, "motivo": f"error:{type(e).__name__}"}
            try:
                await c.call("Target.closeTarget", {"targetId": tid}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            tid, s = await nueva_pestana(c, ctx)
        items[asin]["leido"] = datetime.now(ART).isoformat(timespec="seconds")
        guardar_parcial(parcial, asin, slugs[asin], items[asin])
        print(chrome_line(slugs[asin], asin, items[asin]), file=sys.stderr, flush=True)
    return tid


async def main(asins):
    # También acepta ASIN:slug1,slug2 para conservar la relación con el catálogo.
    slugs = {}
    for argument in asins:
        asin, _, names = argument.partition(":")
        slugs.setdefault(asin, []).extend(names.split(",") if names else [])
    asins = list(slugs)
    ver = json.load(urllib.request.urlopen(CDP + "/json/version"))
    items, inicio = {}, time.time()
    parcial = ruta_parcial()
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=2**24) as ws:
        c = Cdp(ws)
        lector = asyncio.create_task(c.run())
        ctx = (await c.call("Target.createBrowserContext", {"disposeOnDetach": True}))["browserContextId"]
        tid, s = await nueva_pestana(c, ctx)
        try:
            tid = await recorrer(c, ctx, tid, s, asins, slugs, items, parcial)
        finally:
            try:
                await c.call("Target.closeTarget", {"targetId": tid}, timeout=10)
                await c.call("Target.disposeBrowserContext", {"browserContextId": ctx}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            lector.cancel()
    print(json.dumps({"generado": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "segundos": round(time.time() - inicio),
                      "items": items}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
