"""Abre los productos del barrido que Amazon lista sin precio y mide qué se recupera.

Dos tipos, detectados en el HTML de la tarjeta guardada en el JSONL del barrido:
- «See options»: producto con variantes; se pide el panel de ofertas nuevas (`products.offers`).
- «Click to see price»: precio escondido en el listado; se pide la ficha (`products.details`).

Uso (dentro del contenedor del barrido, con PYTHONPATH=/src/worker):
    python -m barrido.revisar_ocultos --jsonl /app/output/barrido/US-AAAA-MM-DD.jsonl \
        --opciones 20 --precio-oculto 20 --salida /app/output/ocultos

Escribe en --salida, con la marca de tiempo de la corrida en el nombre:
- ocultos-<marca>.log: un evento por línea (hora ART con milisegundos, evento, JSON), incluido cada
  pedido HTTP que informa el transporte y cada espera con su motivo.
- ocultos-<marca>.jsonl: un resultado por producto con la respuesta cruda.
- ocultos-<marca>-resumen.json: totales y tiempos por tipo.
No publica ni toca colas: sólo mide.
"""
import argparse
import json
import os
import random
import re
import statistics
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ART = timezone(timedelta(hours=-3))
MIN_USD, MAX_USD = 100.0, 400.0
PAUSA_SEGUNDOS = float(os.environ.get("OCULTOS_PAUSA_SEGUNDOS", "5"))


class Bitacora:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, evento, **campos):
        hora = datetime.now(ART).isoformat(timespec="milliseconds")
        linea = f"{hora} {evento} {json.dumps(campos, ensure_ascii=False, default=str)}"
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(linea + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        print(linea, flush=True)


def crear_observador(log, contador, prefijo):
    """El transporte del vendor delega en el observador el pedido real y la espera: se registran los dos."""
    def observador(**campos):
        evento = campos.pop("event")
        if evento == "request":
            llamar, metodo, url = campos.pop("call"), campos.pop("method"), campos.pop("url")
            bloqueo = campos.pop("block_reason", None)
            datos = {k: campos.pop(k, None) for k in ("country", "session_id", "located", "attempt")}
            contador["http"] += 1
            log(f"{prefijo}_HTTP_INICIO", metodo=metodo, url=url.split("?")[0], **datos)
            t0 = time.monotonic()
            try:
                resp = llamar(metodo, url, **campos)
            except BaseException as exc:
                log(f"{prefijo}_HTTP_FIN", metodo=metodo, url=url.split("?")[0], ms=round((time.monotonic() - t0) * 1000),
                    error=f"{type(exc).__name__}: {exc}", **datos)
                raise
            try:
                motivo = bloqueo(resp) if bloqueo else None
            except Exception as exc:
                motivo = f"no_evaluado: {exc}"
            log(f"{prefijo}_HTTP_FIN", metodo=metodo, url=url.split("?")[0], status=resp.status_code,
                bytes=len(resp.content or b""), ms=round((time.monotonic() - t0) * 1000), bloqueo=motivo, **datos)
            return resp
        if evento == "wait":
            log(f"{prefijo}_ESPERA", motivo=campos.get("reason"), segundos=campos.get("seconds"))
            time.sleep(campos.get("seconds") or 0)
            return None
        log(f"{prefijo}_TRANSPORTE", tipo_evento=evento, **campos)
    return observador


def texto_tarjeta(row):
    html = (row.get("raw") or {}).get("card_html") or ""
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def tipo_de(row):
    texto = texto_tarjeta(row)
    if "See options" in texto:
        return "opciones"
    if "Click to see price" in texto:
        return "precio_oculto"
    return None


def monto(price):
    if isinstance(price, dict):
        price = price.get("amount")
    try:
        valor = float(price)
    except (TypeError, ValueError):
        return None
    return valor if valor > 0 else None


def elegir(jsonl, cantidades, semilla):
    grupos = {tipo: [] for tipo in cantidades}
    with open(jsonl, encoding="utf-8") as fh:
        for linea in fh:
            row = json.loads(linea)
            if "sin_precio_validado" not in (row.get("rejection_reasons") or []):
                continue
            tipo = tipo_de(row)
            if tipo in grupos:
                grupos[tipo].append(row)
    azar = random.Random(semilla)
    elegidos = {tipo: azar.sample(filas, min(cantidades[tipo], len(filas))) for tipo, filas in grupos.items()}
    return grupos, elegidos


def evaluar(precio, envio, condicion_nueva):
    motivos = []
    if precio is None:
        motivos.append("sin_precio")
    elif not MIN_USD <= precio <= MAX_USD:
        motivos.append("fuera_de_rango")
    if not condicion_nueva:
        motivos.append("no_nuevo")
    if envio != "gratis":
        motivos.append(f"envio_{envio}")
    return not motivos, motivos


def revisar_opciones(asin, products, shipping, log):
    respuesta = products.offers(asin, "US", condition="new", postal_code="AR")
    ofertas = respuesta.get("offers") or []
    log("OCULTO_OFERTAS", asin=asin, cantidad=len(ofertas), titulo=respuesta.get("title"))
    mejor = None
    for i, oferta in enumerate(ofertas):
        precio = monto(oferta.get("price"))
        texto_envio = (oferta.get("delivery") or {}).get("text")
        envio = shipping.delivery_from_card({"price": {"amount": precio}, "delivery": texto_envio}, located=True)
        nueva = (oferta.get("condition") or "").strip().lower().startswith("new")
        ok, motivos = evaluar(precio, envio["shipping_class"], nueva)
        log("OCULTO_OFERTA", asin=asin, orden=i, precio=precio, condicion=oferta.get("condition"),
            envio_texto=texto_envio, envio_clase=envio["shipping_class"], vendedor=(oferta.get("seller") or {}).get("name"),
            despacha=oferta.get("ships_from"), elegible=ok, motivos=motivos)
        if ok and (mejor is None or precio < mejor["precio"]):
            mejor = {"precio": precio, "envio_texto": texto_envio, "vendedor": (oferta.get("seller") or {}).get("name")}
    if mejor:
        return {"elegible": True, "motivos": [], **mejor}, respuesta
    return {"elegible": False, "motivos": ["sin_oferta_elegible" if ofertas else "sin_ofertas_producto_nuevo"]}, respuesta


def revisar_precio_oculto(asin, products, shipping, log):
    ficha = products.details(asin, "US", postal_code="AR")
    precio = monto(ficha.get("price"))
    envio = shipping.parse_delivery(ficha, located=True)
    clase = shipping.classify_shipping(envio)
    condicion = (ficha.get("condition") or "new")
    ok, motivos = evaluar(precio, clase, str(condicion).lower().startswith("new"))
    log("OCULTO_FICHA", asin=asin, precio=precio, envio_texto=envio.get("text"), envio_clase=clase,
        condicion=condicion, ubicacion=(ficha.get("delivery") or {}).get("location"), elegible=ok, motivos=motivos)
    return {"elegible": ok, "motivos": motivos, "precio": precio, "envio_texto": envio.get("text")}, ficha


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jsonl", required=True)
    ap.add_argument("--opciones", type=int, default=20)
    ap.add_argument("--precio-oculto", type=int, default=20)
    ap.add_argument("--salida", default="/app/output/ocultos")
    ap.add_argument("--semilla", type=int, default=20261109)
    args = ap.parse_args(argv)

    marca = datetime.now(ART).strftime("%Y-%m-%d-%H%M%S")
    salida = Path(args.salida)
    log = Bitacora(salida / f"ocultos-{marca}.log")
    inicio = time.monotonic()
    log("OCULTOS_INICIO", jsonl=args.jsonl, opciones=args.opciones, precio_oculto=args.precio_oculto,
        semilla=args.semilla, pausa_segundos=PAUSA_SEGUNDOS, proxy=bool(os.environ.get("BARRIDO_AMAZON_PROXY")))

    grupos, elegidos = elegir(args.jsonl, {"opciones": args.opciones, "precio_oculto": args.precio_oculto}, args.semilla)
    for tipo in grupos:
        log("OCULTOS_MUESTRA", tipo=tipo, disponibles=len(grupos[tipo]), elegidos=[r["id"] for r in elegidos[tipo]])

    from .bootstrap import configure_transport
    contador = {"http": 0}
    configure_transport(observer=crear_observador(log, contador, "OCULTO"))
    from amazon import products
    from . import shipping

    resultados = []
    with (salida / f"ocultos-{marca}.jsonl").open("a", encoding="utf-8") as out:
        primero = True
        for tipo, filas in elegidos.items():
            for row in filas:
                asin = row["id"]
                if not primero:
                    log("OCULTO_ESPERA", motivo="pausa_entre_productos", segundos=PAUSA_SEGUNDOS)
                    time.sleep(PAUSA_SEGUNDOS)
                primero = False
                http_antes = contador["http"]
                t0 = time.monotonic()
                log("OCULTO_INICIO", tipo=tipo, asin=asin, titulo=(row.get("title") or "")[:120])
                try:
                    if tipo == "opciones":
                        resultado, crudo = revisar_opciones(asin, products, shipping, log)
                    else:
                        resultado, crudo = revisar_precio_oculto(asin, products, shipping, log)
                    estado, error = "ok", None
                except Exception as exc:  # se registra y se sigue con el próximo
                    resultado, crudo, estado = {"elegible": False, "motivos": ["error"]}, None, "error"
                    error = f"{type(exc).__name__}: {exc}"
                    log("OCULTO_ERROR", tipo=tipo, asin=asin, error=error, traceback=traceback.format_exc())
                ms = round((time.monotonic() - t0) * 1000)
                fila = {"tipo": tipo, "asin": asin, "titulo": row.get("title"), "estado": estado, "error": error,
                        "ms": ms, "pedidos_http": contador["http"] - http_antes, **resultado, "crudo": crudo}
                out.write(json.dumps(fila, ensure_ascii=False, default=str) + "\n")
                out.flush()
                os.fsync(out.fileno())
                resultados.append(fila)
                log("OCULTO_FIN", tipo=tipo, asin=asin, estado=estado, ms=ms, pedidos_http=fila["pedidos_http"],
                    elegible=resultado["elegible"], precio=resultado.get("precio"), motivos=resultado["motivos"])

    resumen = {"inicio_marca": marca, "segundos_total": round(time.monotonic() - inicio, 1),
               "pedidos_http": contador["http"], "por_tipo": {}}
    for tipo in elegidos:
        filas = [r for r in resultados if r["tipo"] == tipo]
        tiempos = [r["ms"] for r in filas]
        resumen["por_tipo"][tipo] = {
            "disponibles": len(grupos[tipo]), "revisados": len(filas),
            "elegibles": sum(r["elegible"] for r in filas), "errores": sum(r["estado"] == "error" for r in filas),
            "motivos": dict(sorted({m: sum(m in r["motivos"] for r in filas) for r in filas for m in r["motivos"]}.items())),
            "ms_promedio": round(statistics.mean(tiempos)) if tiempos else None,
            "ms_mediana": round(statistics.median(tiempos)) if tiempos else None,
            "ms_max": max(tiempos) if tiempos else None,
        }
    (salida / f"ocultos-{marca}-resumen.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8")
    log("OCULTOS_FIN", **resumen)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
