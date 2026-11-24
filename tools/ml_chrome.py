"""Ofertas de Mercado Libre leídas de la página pública con el Chrome de la VM, por CDP (24/11).

Motivo (medido el 24/11 10:00-10:30 desde el worker): la API de ML responde 403 «PolicyAgent»
(PA_UNAUTHORIZED_RESULT_FROM_POLICIES) en /products/{id}/items y 403 access_denied en /items/{id}, con el token de la
app, con token de usuario, sin token y saliendo por WARP. La última consulta buena fue el 23/11 06:35:06
(worker-2026-11-23.log); la primera fallida, el 24/11 04:02:00. /products/{id} sigue dando 200, pero no trae precios.
La página «Otras opciones de compra» (/p/{catálogo}/s) trae las mismas ofertas: ítem, precio, moneda y condición en el
evento de melidata, y las internacionales (CBT) marcadas con el componente «cbt_summary». Verificado en
MLA17332828: sin la internacional, la nueva más barata es MLA1848139213 a 700.000, igual que la API el 23/11.

Corre DENTRO del contenedor chrome-claude (CDP en 127.0.0.1:9222):
  docker exec chrome-claude python3 /tmp/ml_chrome.py MLA123 [MLA456 ...]
Salida (stdout): {"generado": ..., "items": {catalogId: {"results": [...] | None, "motivo", "leido", "paginas"}}}.
«results» tiene la forma de /products/{id}/items (item_id, price, currency_id, condition, tags) para que
ml_prices.cheapest_new decida igual que con la API. results None = no se pudo leer (cuenta como falla, nunca como
«sin oferta»). Una línea ML_CHROME_PRODUCTO por catálogo va a stderr.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import random
import re
import sys
import time
import urllib.request

CDP = "http://127.0.0.1:9222"
ART = timezone(timedelta(hours=-3))
TIMEOUT_PAGINA = 40
ESPERA_CARGA = 3
INTENTOS_LECTURA = 4  # hasta ~12 s para que la página tenga su estado inicial
# Ritmo: una página cada 4 a 7 s, como una persona mirando; ML pide verificación de cuenta a clientes automáticos
# (curl desde la VM el 24/11 terminó en /gz/account-verification).
PAUSA_MIN, PAUSA_MAX = 4.0, 7.0
MAX_PAGINAS = 12  # 24/11: MLA37106988 (Logitech MX Brio) tenía 9 páginas de 10 ofertas; con 5 cinco catálogos quedaron en falla
RECONEXIONES = 3
ESPERA_RECONEXION = 20
RECICLAR_CADA = 15
# Si ML pide verificación en varias páginas seguidas, se corta: seguir sólo empeora el bloqueo.
VERIFICACIONES_SEGUIDAS_MAX = 3
# Tope propio (s): se deja de pedir catálogos antes del KILL externo, así lo leído siempre llega a stdout.
TOPE = float(os.environ.get("ML_CHROME_TOPE") or 3000)
INICIO = time.monotonic()
BLOQUEADOS = ["*.jpg", "*.jpeg", "*.png", "*.gif", "*.webp", "*.avif", "*.svg", "*.mp4", "*.webm",
              "*.woff", "*.woff2", "*.ttf", "*http2.mlstatic.com/D_*"]

LEER = r"""(() => {
const out={url:location.href, verificacion:/account-verification|\/gz\/|\/login\/|captcha|suspicious/i.test(location.href)};
try {
  const st=_n.ctx.r.appProps.pageProps.initialState;
  const comp=st.components||{};
  const ev=(((comp.track||{}).melidata_event||{}).event_data)||{};
  out.catalogo=ev.catalog_product_id||null;
  out.items=(ev.items||[]).map(i=>({item_id:i.item_id||null, price:i.price, currency_id:i.currency_id||null,
                                     condition:i.item_condition||null}));
  const res=((comp.results||{}).items)||[];
  out.ofertas=res.map(r=>{const s=JSON.stringify(r); return {ids:(s.match(/MLA\d{6,}/g)||[]), cbt:s.includes('"cbt_summary"')};});
  out.hayResultados=!!comp.results;
} catch(e) { out.error=String(e).slice(0,200); }
const pag=document.querySelector('.andes-pagination');
out.siguiente=!!(pag && pag.querySelector('.andes-pagination__button--next:not(.andes-pagination__button--disabled) a'));
out.sinOfertas=/no hay (otras )?opciones de compra|no hay publicaciones|sin stock/i.test((document.body||{}).innerText||'');
return JSON.stringify(out);})()"""


def resultados(d):
    """Une el evento de melidata (precio, condición) con las ofertas visibles (marca internacional) de una página.

    Devuelve (lista, motivo_de_falla). Revisión de Codex del 24/11: una oferta sin fila visible o sin condición no se
    adivina (antes se tomaba como internacional o se aceptaba sin condición): el catálogo entero queda en falla."""
    cbt = {}
    for oferta in d.get("ofertas") or []:
        for item_id in oferta.get("ids") or []:
            cbt[item_id] = cbt.get(item_id, False) or bool(oferta.get("cbt"))
    salida = []
    for item in d.get("items") or []:
        item_id = item.get("item_id")
        if not isinstance(item_id, str) or not re.fullmatch(r"MLA\d+", item_id):
            return None, "oferta_sin_id"
        if item_id not in cbt:
            return None, "oferta_sin_fila_visible"
        if item.get("condition") not in ("new", "used", "refurbished", "not_specified"):
            return None, f"condicion_desconocida:{item.get('condition')}"
        salida.append({"item_id": item_id, "price": item.get("price"), "currency_id": item.get("currency_id"),
                       "condition": item.get("condition"), "tags": ["cbt_item"] if cbt[item_id] else []})
    return salida, None


def interpretar(paginas, cid=None):
    """paginas: lo leído de cada página de /s. Devuelve (results o None, motivo).

    Toda duda es falla (results None), nunca «sin ofertas»: una página que no es del catálogo pedido, una página sin
    ofertas legibles o con filas que no se pudieron unir deja el producto sin precio de hoy."""
    if not paginas:
        return None, "sin_lectura"
    if paginas[0].get("verificacion"):
        return None, "verificacion_ml"
    todos, vistos = [], set()
    for n, d in enumerate(paginas, 1):
        if d.get("verificacion"):
            return None, "verificacion_ml" if n == 1 else "pagina_siguiente_sin_leer"
        if d.get("error"):
            return None, f"pagina_sin_datos:{str(d['error'])[:80]}"
        if cid is not None and d.get("catalogo") != cid:
            return None, f"pagina_de_otro_catalogo:{d.get('catalogo')}"
        if not d.get("items"):
            # 1.ª página sin ofertas: no hay forma probada de distinguir «sin vendedores» de una página mal leída.
            return None, "sin_items" if n == 1 else "pagina_siguiente_vacia"
        lista, falla = resultados(d)
        if falla:
            return None, falla
        ids = {r["item_id"] for r in lista}
        if ids & vistos:
            return None, "pagina_repetida"
        vistos |= ids
        todos.extend(lista)
    return todos, "ok"


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
    params = {"url": "about:blank", "background": True}
    if ctx:
        params["browserContextId"] = ctx
    tid = (await c.call("Target.createTarget", params))["targetId"]
    s = (await c.call("Target.attachToTarget", {"targetId": tid, "flatten": True}))["sessionId"]
    await c.call("Page.enable", {}, s)
    await c.call("Network.enable", {}, s)
    await c.call("Network.setBlockedURLs", {"urls": BLOQUEADOS}, s)
    return tid, s


async def leer_pagina(c, s, url):
    # about:blank primero: si la navegación falla o tarda, nunca se lee el documento anterior (revisión de Codex 24/11).
    await c.call("Page.navigate", {"url": "about:blank"}, s)
    await c.call("Page.navigate", {"url": url}, s)
    d = {}
    for _ in range(INTENTOS_LECTURA):
        await asyncio.sleep(ESPERA_CARGA)
        r = await c.call("Runtime.evaluate", {"expression": LEER, "returnByValue": True}, s, timeout=TIMEOUT_PAGINA)
        if r.get("exceptionDetails"):
            det = r["exceptionDetails"]
            raise RuntimeError(f"js: {(det.get('exception') or {}).get('description') or det.get('text')}"[:200])
        d = json.loads((r.get("result") or {}).get("value") or "{}")
        if d.get("verificacion") or (not d.get("error") and d.get("items")):
            break
    return d


async def leer_catalogo(c, s, cid):
    paginas = []
    for n in range(1, MAX_PAGINAS + 1):
        if time.monotonic() - INICIO > TOPE:
            raise TopeML()
        url = f"https://www.mercadolibre.com.ar/p/{cid}/s" + (f"?page={n}" if n > 1 else "")
        d = await leer_pagina(c, s, url)
        paginas.append(d)
        if not d.get("siguiente") or d.get("verificacion") or d.get("error"):
            break
        await asyncio.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))
    else:
        # Más de MAX_PAGINAS: la lista queda incompleta.
        return None, "demasiadas_paginas", len(paginas)
    results, motivo = interpretar(paginas, cid)
    return results, motivo, len(paginas)


def linea(cid, item):
    precios = [r["price"] for r in item.get("results") or []
               if not r["tags"] and r.get("condition") == "new" and isinstance(r.get("price"), (int, float))]
    return (f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} ML_CHROME_PRODUCTO catalogo={cid} "
            f"ofertas={len(item['results']) if item.get('results') is not None else 'ausente'} "
            f"menor_local_nueva={min(precios) if precios else 'ausente'} paginas={item.get('paginas')} "
            f"motivo={item.get('motivo')}")


async def recorrer(c, ctx, tid, s, cids, items):
    seguidas = 0
    for n, cid in enumerate(cids):
        if time.monotonic() - INICIO > TOPE:
            print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} ML_CHROME_TOPE {TOPE:.0f} s; quedan {len(cids) - n} sin leer",
                  file=sys.stderr, flush=True)
            raise TopeML()
        if n and n % RECICLAR_CADA == 0:
            try:
                await c.call("Target.closeTarget", {"targetId": tid}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            tid, s = await nueva_pestana(c, ctx)
        empezado = datetime.now(ART).isoformat(timespec="seconds")
        try:
            results, motivo, paginas = await asyncio.wait_for(
                leer_catalogo(c, s, cid), (TIMEOUT_PAGINA + ESPERA_CARGA + PAUSA_MAX) * MAX_PAGINAS + 5)
            items[cid] = {"results": results, "motivo": motivo, "paginas": paginas}
        except TopeML:
            print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} ML_CHROME_TOPE {TOPE:.0f} s; quedan {len(cids) - n} sin leer",
                  file=sys.stderr, flush=True)
            raise
        except Exception as e:  # noqa: BLE001 — página colgada: se anota y se sigue con otra pestaña
            items[cid] = {"results": None, "motivo": f"error:{type(e).__name__}", "paginas": 0}
            try:
                await c.call("Target.closeTarget", {"targetId": tid}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            tid, s = await nueva_pestana(c, ctx)
        # «leido» es cuándo EMPEZÓ el catálogo: si cruza medianoche, guardar lo descarta (revisión de Codex 24/11).
        items[cid]["leido"] = empezado
        print(linea(cid, items[cid]), file=sys.stderr, flush=True)
        seguidas = seguidas + 1 if items[cid]["motivo"] == "verificacion_ml" else 0
        if seguidas >= VERIFICACIONES_SEGUIDAS_MAX:
            print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} ML_CHROME_CORTE verificacion_ml en {seguidas} páginas seguidas; "
                  f"quedan {len(cids) - n - 1} sin leer", file=sys.stderr, flush=True)
            raise VerificacionML()
        await asyncio.sleep(random.uniform(PAUSA_MIN, PAUSA_MAX))
    return tid


class VerificacionML(Exception):
    pass


class TopeML(Exception):
    pass


async def sesion(cids, items):
    import websockets  # sólo existe en el contenedor chrome-claude; los tests del worker no lo necesitan
    ver = json.load(urllib.request.urlopen(CDP + "/json/version", timeout=10))
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=2**24) as ws:
        c = Cdp(ws)
        lector = asyncio.create_task(c.run())
        ctx, tid = None, None
        try:
            # Perfil del Chrome de la VM (sesión de ML de Alejandro), no contexto anónimo: el 24/11 10:26 el contexto
            # anónimo terminó en /login/identification en vez de la página del producto; con el perfil carga.
            tid, s = await nueva_pestana(c, ctx)
            tid = await recorrer(c, ctx, tid, s, cids, items)
        finally:
            try:
                if tid:
                    await c.call("Target.closeTarget", {"targetId": tid}, timeout=10)
                if ctx:
                    await c.call("Target.disposeBrowserContext", {"browserContextId": ctx}, timeout=10)
            except Exception:  # noqa: BLE001
                pass
            lector.cancel()


async def main(cids):
    cids = list(dict.fromkeys(c for c in cids if re.fullmatch(r"MLA\d+", c)))
    items, inicio = {}, time.time()
    codigo = 0
    for reconexion in range(RECONEXIONES + 1):
        pendientes = [c for c in cids if c not in items]
        if not pendientes:
            break
        try:
            await sesion(pendientes, items)
            break
        except VerificacionML:
            codigo = 2
            break
        except TopeML:
            codigo = 3
            break
        except Exception as exc:  # noqa: BLE001
            if reconexion == RECONEXIONES:
                codigo = 1
                print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} ML_CHROME_FALLA {type(exc).__name__}: {str(exc)[:160]}",
                      file=sys.stderr, flush=True)
                break
            print(f"{datetime.now(ART):%Y-%m-%d %H:%M:%S} ML_CHROME_RECONEXION intento={reconexion + 1}/{RECONEXIONES} "
                  f"pendientes={len(pendientes)} motivo={type(exc).__name__}: {str(exc)[:120]}", file=sys.stderr, flush=True)
            await asyncio.sleep(ESPERA_RECONEXION)
    print(json.dumps({"generado": datetime.now(ART).isoformat(timespec="seconds"), "segundos": round(time.time() - inicio),
                      "items": items}, ensure_ascii=False))
    return codigo


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
