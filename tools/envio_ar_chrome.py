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
import json
import re
import sys
import time
import urllib.request

import websockets

CDP = "http://127.0.0.1:9222"
TIMEOUT_PRODUCTO = 30
ESPERA_CARGA = 4

LEER = r"""(() => {const t=document.body.innerText;
return JSON.stringify({deliver:((document.getElementById('glow-ingress-block')||{}).innerText||'').replace(/\s+/g,' '),
 envio:(t.match(/[^\n]*(delivery|Delivery)[^\n]*Argentina[^\n]*/)||[])[0]||null,
 sinOferta:(t.match(/[^\n]*(See All Buying Options|No featured offers available|cannot be shipped to your selected delivery location|This item cannot be shipped|Currently unavailable)[^\n]*/)||[])[0]||null,
 captcha:/captcha|Enter the characters you see/i.test(t), titulo:((document.getElementById('productTitle')||{}).innerText||'').trim().slice(0,80)})})()"""


def interpretar(d):
    """Traduce lo leído a ships/free con evidencia literal; ante la duda, None."""
    if d.get("captcha"):
        return {"ships": None, "free": None, "text": None, "motivo": "captcha"}
    if "argentina" not in (d.get("deliver") or "").lower():
        return {"ships": None, "free": None, "text": None, "motivo": "ubicacion_no_ar"}
    envio = d.get("envio")
    if envio:
        return {"ships": True, "free": bool(re.match(r"\s*FREE delivery", envio, re.I)), "text": envio[:160], "motivo": None}
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
    return tid, s


async def leer_producto(c, s, asin):
    await c.call("Page.navigate", {"url": f"https://www.amazon.com/dp/{asin}?language=en_US"}, s)
    await asyncio.sleep(ESPERA_CARGA)
    r = await c.call("Runtime.evaluate", {"expression": LEER, "returnByValue": True}, s, timeout=TIMEOUT_PRODUCTO)
    return json.loads((r.get("result") or {}).get("value") or "{}")


async def main(asins):
    ver = json.load(urllib.request.urlopen(CDP + "/json/version"))
    items, inicio = {}, time.time()
    async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=2**24) as ws:
        c = Cdp(ws)
        lector = asyncio.create_task(c.run())
        ctx = (await c.call("Target.createBrowserContext", {"disposeOnDetach": True}))["browserContextId"]
        tid, s = await nueva_pestana(c, ctx)
        try:
            for asin in asins:
                try:
                    items[asin] = interpretar(await asyncio.wait_for(leer_producto(c, s, asin), TIMEOUT_PRODUCTO + ESPERA_CARGA + 5))
                except Exception as e:  # noqa: BLE001 — página colgada: se anota y se sigue con otra pestaña
                    items[asin] = {"ships": None, "free": None, "text": None, "motivo": f"error:{type(e).__name__}"}
                    try:
                        await c.call("Target.closeTarget", {"targetId": tid}, timeout=10)
                    except Exception:  # noqa: BLE001
                        pass
                    tid, s = await nueva_pestana(c, ctx)
                print(f"{asin} {items[asin]['ships']} {items[asin]['free']} {items[asin]['motivo']}", file=sys.stderr, flush=True)
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
