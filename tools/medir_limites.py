"""Medición de límites reales de Mercado Libre y Amazon (05/11). Corre DENTRO del worker:

  docker exec -d -w /app/worker franquicia400-weboffers-worker-1 python /app/tools/medir_limites.py <modo>

Modos: ml | amazon | ar. Cada pedido queda en /app/output/limites/<modo>-AAAAMMDD-HHMM.jsonl con:
hora, servicio, endpoint, paso, código HTTP, latencia, cantidad pedida, ok, vacías, encabezados de límite.
Al final escribe <archivo>.resumen.json. Latido en /app/output/limites/<modo>.latido (paso actual y hora).
Regla de corte en Amazon: 3 tandas seguidas con 0 ok en el conjunto de control -> se para el paso y se mide
la recuperación con 1 tanda de control a los 1, 5, 15, 30 y 60 minutos.
"""
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/app/worker")
import requests  # noqa: E402

import amazon_prices as az  # noqa: E402
import ml_prices as ml  # noqa: E402

ART = timezone(timedelta(hours=-3))
OUT = "/app/output/limites"
os.makedirs(OUT, exist_ok=True)
LOCK = threading.Lock()
HEADERS_LIMITE = ("retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset",
                  "x-request-id", "x-content-type-options")


def hay_red():
    """Control independiente de Amazon y ML: si esto falla, el problema es la red de la VM."""
    for url in ("https://www.google.com/generate_204", "https://1.1.1.1"):
        try:
            requests.get(url, timeout=8)
            return True
        except requests.RequestException:
            continue
    return False


def ahora():
    return datetime.now(ART)


class Registro:
    def __init__(self, modo):
        self.modo = modo
        self.path = os.path.join(OUT, f"{modo}-{ahora():%Y%m%d-%H%M}.jsonl")
        self.latido = os.path.join(OUT, f"{modo}.latido")
        self.filas = []

    def anotar(self, **fila):
        fila["hora"] = ahora().isoformat(timespec="milliseconds")
        with LOCK:
            self.filas.append(fila)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(fila, ensure_ascii=False) + "\n")

    def paso(self, texto):
        with open(self.latido, "w", encoding="utf-8") as fh:
            fh.write(f"{ahora():%H:%M:%S} {texto}\n")
        print(f"{ahora():%H:%M:%S} {texto}", flush=True)

    def resumen(self):
        pasos = {}
        for f in self.filas:
            p = pasos.setdefault(f["paso"], {"pedidos": 0, "items": 0, "ok": 0, "vacias": 0, "errores": {},
                                             "lat": [], "desde": f["hora"], "hasta": f["hora"]})
            p["pedidos"] += 1
            p["items"] += f.get("pedidos_items", 1)
            p["ok"] += f.get("ok", 0)
            p["vacias"] += f.get("vacias", 0)
            if f.get("error"):
                p["errores"][f["error"]] = p["errores"].get(f["error"], 0) + 1
            p["lat"].append(f.get("lat_ms", 0))
            p["hasta"] = f["hora"]
        for p in pasos.values():
            lat = sorted(p.pop("lat"))
            p["lat_mediana_ms"] = int(statistics.median(lat)) if lat else None
            p["lat_p95_ms"] = int(lat[int(0.95 * (len(lat) - 1))]) if lat else None
        json.dump(pasos, open(self.path + ".resumen.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return pasos


# ---------------------------------------------------------------- Mercado Libre
def ml_pedido(reg, paso, endpoint, url, params=None):
    t0 = time.monotonic()
    try:
        r = requests.get(url, params=params, headers={"Authorization": f"Bearer {ml.get_token()}"}, timeout=30)
        lat = int((time.monotonic() - t0) * 1000)
        hdr = {k: v for k, v in r.headers.items() if k.lower() in HEADERS_LIMITE or "ratelimit" in k.lower()}
        ok = int(r.status_code == 200)
        reg.anotar(servicio="ml", endpoint=endpoint, paso=paso, http=r.status_code, lat_ms=lat, ok=ok,
                   vacias=0, error=None if ok or r.status_code == 404 else f"http_{r.status_code}", headers=hdr)
        return r.status_code
    except requests.RequestException as e:
        reg.anotar(servicio="ml", endpoint=endpoint, paso=paso, http=None, lat_ms=int((time.monotonic() - t0) * 1000),
                   ok=0, vacias=0, error=type(e).__name__)
        return None


def correr_ml():
    reg = Registro("ml")
    cat = [p for p in json.load(open("/app/data/catalog.json", encoding="utf-8"))
           if p.get("verified") and (p.get("ml") or {}).get("catalogId")]
    ids = [p["ml"]["catalogId"] for p in cat]
    nombres = [p["name"][:40] for p in cat]
    base = ml.API_BASE_URL

    def objetivo(endpoint, i):
        if endpoint == "products_items":
            return f"{base}/products/{ids[i % len(ids)]}/items", None
        return f"{base}/products/search", {"status": "active", "site_id": "MLA", "q": nombres[i % len(nombres)]}

    ml.get_token()
    for endpoint in ("products_items", "products_search"):
        # Escalones de velocidad: N pedidos por segundo durante 60 s (o hasta 3 respuestas 429).
        for rps in (1, 2, 5, 10, 20, 40):
            paso = f"{endpoint}@{rps}rps"
            reg.paso(paso)
            n429, i, fin = 0, 0, time.monotonic() + 60
            with ThreadPoolExecutor(max_workers=min(40, rps * 2)) as ex:
                futuros = []
                while time.monotonic() < fin and n429 < 3:
                    t = time.monotonic()
                    for _ in range(rps):
                        url, params = objetivo(endpoint, i)
                        i += 1
                        futuros.append(ex.submit(ml_pedido, reg, paso, endpoint, url, params))
                    futuros = [f for f in futuros if not (f.done() and f.result() == 429 and (n429 := n429 + 1))]
                    time.sleep(max(0, 1 - (time.monotonic() - t)))
            if n429 >= 3:
                reg.paso(f"{paso}: 3 respuestas 429, corto el escalón; espero 60 s")
                time.sleep(60)
                break
        # Paralelismo sin pausa: K hilos durante 60 s.
        for k in (1, 2, 4, 8, 16):
            paso = f"{endpoint}@{k}hilos"
            reg.paso(paso)
            fin = time.monotonic() + 60
            contador = {"i": 0, "429": 0}

            def hilo():
                while time.monotonic() < fin and contador["429"] < 3:
                    with LOCK:
                        contador["i"] += 1
                        j = contador["i"]
                    url, params = objetivo(endpoint, j)
                    if ml_pedido(reg, paso, endpoint, url, params) == 429:
                        contador["429"] += 1
            with ThreadPoolExecutor(max_workers=k) as ex:
                for _ in range(k):
                    ex.submit(hilo)
            if contador["429"] >= 3:
                reg.paso(f"{paso}: 3 respuestas 429; espero 60 s")
                time.sleep(60)
                break
    reg.paso("FIN")
    print(json.dumps(reg.resumen(), ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- Amazon (precios y envío AR)
def control_amazon():
    cat = {p["slug"]: p for p in json.load(open("/app/data/catalog.json", encoding="utf-8"))}
    items = json.load(open("/app/output/amazon-prices.json", encoding="utf-8"))["items"]
    ship = json.load(open("/app/output/amazon-prices.json", encoding="utf-8")).get("arShipping") or {}
    ok = [s for s, it in items.items() if s in cat and cat[s].get("store") == "US" and it.get("amount")]
    con_envio = [s for s in ok if (ship.get(s) or {}).get("ships") is True]
    return cat, ok[:40], con_envio[:20]


def amazon_tanda(reg, paso, asins, modo):
    t0 = time.monotonic()
    try:
        if modo == "amazon":
            r = az.fetch_bulk(az.scraper_url(), asins, "US")
            ok = sum(1 for a in asins if az.valid_price(r.get(a), "US") is not None)
        else:
            r = az.fetch_ar_shipping(az.ar_url(), asins, "US")
            ok = sum(1 for a in asins if az.shipping_reason(r.get(a)) is None)
        lat = int((time.monotonic() - t0) * 1000)
        reg.anotar(servicio=modo, endpoint="bulk" if modo == "amazon" else "ar-shipping", paso=paso, http=200,
                   lat_ms=lat, pedidos_items=len(asins), ok=ok, vacias=len(asins) - ok, error=None)
        return ok
    except Exception as e:  # noqa: BLE001
        reg.anotar(servicio=modo, endpoint="bulk" if modo == "amazon" else "ar-shipping", paso=paso,
                   http=getattr(getattr(e, "response", None), "status_code", None),
                   lat_ms=int((time.monotonic() - t0) * 1000), pedidos_items=len(asins), ok=0,
                   vacias=len(asins), error=type(e).__name__)
        return 0


def recuperacion(reg, modo, asins):
    for minutos in (1, 5, 15, 30, 60):
        reg.paso(f"recuperacion: espero {minutos} min")
        time.sleep(minutos * 60)
        ok = amazon_tanda(reg, f"recuperacion@{minutos}min", asins[:5], modo)
        if ok:
            reg.paso(f"recuperado a los {minutos} min ({ok}/5)")
            return minutos
    return None


def correr_amazon(modo):
    reg = Registro(modo)
    cat, ok_slugs, con_envio = control_amazon()
    control = [cat[s]["asin"] for s in (ok_slugs if modo == "amazon" else con_envio)]
    reg.paso(f"conjunto de control: {len(control)} ASIN")

    def ciclo(i, n):
        return [control[(i * n + k) % len(control)] for k in range(n)]

    # 3) Escalones de pausa, 15 min cada uno o hasta la regla de corte.
    for pausa in (30, 15, 5, 0):
        paso = f"pausa@{pausa}s"
        fin, vacias_seguidas, i = time.monotonic() + 15 * 60, 0, 0
        while time.monotonic() < fin:
            reg.paso(f"{paso} tanda {i + 1}")
            ok = amazon_tanda(reg, paso, ciclo(i, 5), modo)
            i += 1
            if not hay_red():
                reg.paso(f"{paso}: la VM no tiene salida a internet -> ABORTO (no se mide nada sin red)")
                reg.anotar(servicio=modo, endpoint="aborto", paso=paso, http=None, lat_ms=0, pedidos_items=0,
                           ok=0, vacias=0, error="sin_red")
                print(json.dumps(reg.resumen(), ensure_ascii=False, indent=1))
                return
            vacias_seguidas = 0 if ok else vacias_seguidas + 1
            if vacias_seguidas >= 3:
                reg.paso(f"{paso}: 3 tandas seguidas con 0 ok -> CORTE")
                rec = recuperacion(reg, modo, control)
                reg.anotar(servicio=modo, endpoint="corte", paso=paso, http=None, lat_ms=0, pedidos_items=0,
                           ok=0, vacias=0, error=f"corte_tras_{i}_tandas_recupera_{rec}min")
                break
            time.sleep(pausa)
        else:
            continue
        break  # hubo corte: no se sigue acelerando
    reg.paso("FIN")
    print(json.dumps(reg.resumen(), ensure_ascii=False, indent=1))


def correr_ml_sostenido(rps=5, minutos=30):
    """rps pedidos por segundo REALES (simultáneos) durante `minutos`; corta si en un segundo hay 3 errores
    (conexión o 429). Anota el ritmo efectivo al final."""
    reg = Registro(f"mlsostenido{rps}")
    ids = [p["ml"]["catalogId"] for p in json.load(open("/app/data/catalog.json", encoding="utf-8"))
           if p.get("verified") and (p.get("ml") or {}).get("catalogId")]
    paso = f"products_items@{rps}rps_sostenido"
    reg.paso(paso)
    inicio = time.monotonic()
    fin, i = inicio + minutos * 60, 0
    with ThreadPoolExecutor(max_workers=rps * 2) as ex:
        while time.monotonic() < fin:
            t = time.monotonic()
            futuros = []
            for _ in range(rps):
                url = f"{ml.API_BASE_URL}/products/{ids[i % len(ids)]}/items"
                futuros.append(ex.submit(ml_pedido, reg, paso, "products_items", url))
                i += 1
            codigos = [f.result() for f in futuros]
            malos = sum(1 for c in codigos if c in (None, 429))
            if malos >= 3:
                reg.paso(f"{paso}: {malos} errores en un segundo ({codigos}) tras {i} pedidos -> CORTE; red={hay_red()}")
                break
            if i % (rps * 60) < rps:
                reg.paso(f"{paso}: {i} pedidos, ritmo real {i / (time.monotonic() - inicio):.2f}/s")
            time.sleep(max(0, 1 - (time.monotonic() - t)))
    reg.paso(f"FIN: {i} pedidos en {time.monotonic() - inicio:.0f} s = {i / (time.monotonic() - inicio):.2f}/s")
    print(json.dumps(reg.resumen(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    modo = sys.argv[1]
    if modo.startswith("mlsostenido"):
        # mlsostenido<rps>x<minutos>, p. ej. mlsostenido20x15
        rps, minutos = (modo[len("mlsostenido"):] or "5x30").split("x")
        correr_ml_sostenido(int(rps), int(minutos))
    elif modo == "ml":
        correr_ml()
    else:
        correr_amazon(modo)
