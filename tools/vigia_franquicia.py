#!/usr/bin/env python3
"""Vigía de Franquicia 400: corre cada 15 min en la VM docker y avisa por WhatsApp SÓLO si algo falla (05/11).

Nació porque las fallas aparecían de casualidad: la VM sin internet, errores en el log del worker
que nadie leía, contenedores caídos, precios que no se actualizaban. Cada problema se avisa una vez
por día; si el aviso no sale (p. ej. sin internet) queda pendiente y se reintenta en la pasada siguiente.

Cron (VM docker, hora ART):
  */15 * * * * /usr/bin/python3 /opt/docker/blackseam/soporte/vigia_franquicia.py >> /home/claude/logs/vigia_franquicia.log 2>&1
Logs: VIGIA_OK / VIGIA_AVISO <claves> / VIGIA_PENDIENTE (no se pudo mandar).
"""
import datetime
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import recordatorio_franquicia as rf  # noqa: E402  (enviar, pedir, ART, MINIMO_PRODUCTOS)

ESTADO = os.path.join(HERE, "estado_vigia.json")
WORKER = "franquicia400-weboffers-worker-1"
DEPLOYER = "franquicia400-weboffers-deployer-1"
CONTENEDORES = [WORKER, DEPLOYER, "franquicia400-weboffers-amazon-ar-1", "franquicia400-weboffers-amazon-scraper-1"]
LOGS_WORKER = "/opt/docker/franquicia400/worker/output/logs"
# Líneas del log del worker que son fallas reales (no ruido esperado).
MARCAS_FALLA = re.compile(r"Falló|DEPLOY_FAIL|AMAZON_SCRAPER_FAIL|Traceback|corrida incompleta|MENOS_DE_100|VARIANTE_DISTINTA")
ML_FALLAS_TOLERADAS = 3  # "no se pudo consultar" sueltas por día antes de avisar
SIN_LATIDO_MIN = 75      # el worker imprime al menos una vez por hora


def sh(*cmd, timeout=30):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout


def hay_internet():
    for url in ("https://api.mercadolibre.com/sites/MLA", "https://www.google.com/generate_204"):
        try:
            urllib.request.urlopen(url, timeout=10)
            return True
        except urllib.error.HTTPError:
            return True  # respondió (aunque sea 403): hay salida
        except Exception:
            continue
    return False


def leer_json_contenedor(contenedor, ruta):
    code, out = sh("docker", "exec", contenedor, "cat", ruta)
    return json.loads(out) if code == 0 and out.strip() else None


def chequeos(ahora, **kw):
    """Devuelve {clave: texto} con cada problema; si un chequeo explota, eso también es un problema (no tumba al resto)."""
    try:
        return _chequeos(ahora, **kw)
    except Exception as e:  # noqa: BLE001
        return {"vigia-error": f"el vigía falló al revisar ({type(e).__name__}: {str(e)[:80]})"}


def _chequeos(ahora, internet=hay_internet, sh=sh, leer=leer_json_contenedor, bajar=rf.bajar, logs_dir=LOGS_WORKER):
    """Devuelve {clave: texto} con cada problema encontrado ahora."""
    hoy = ahora.date().isoformat()
    problemas = {}
    if not internet():
        problemas["internet"] = "la VM docker no tiene salida a internet, revisá la ruta por defecto"
        return problemas  # sin internet el resto da falsos positivos

    try:
        code, out = sh("docker", "ps", "--format", "{{.Names}}")
    except Exception as e:  # noqa: BLE001
        code, out = 1, ""
        problemas["docker"] = f"docker no responde ({type(e).__name__})"
    vivos = set(out.split()) if code == 0 else set()
    caidos = [c for c in CONTENEDORES if c not in vivos]
    if caidos:
        problemas["contenedores:" + ",".join(caidos)] = f"contenedores caídos: {', '.join(caidos)}"

    log = os.path.join(logs_dir, f"worker-{hoy}.log")
    lineas = open(log, encoding="utf-8", errors="replace").read().splitlines() if os.path.exists(log) else []
    for linea in lineas:
        if MARCAS_FALLA.search(linea):
            texto = linea.split(" ", 1)[-1][:160]
            problemas["log:" + texto[:80]] = f"el worker registró: {texto}"
    ml_fallas = [l for l in lineas if "Mercado Libre: no se pudo consultar" in l]
    if len(ml_fallas) > ML_FALLAS_TOLERADAS:
        problemas["ml-fallas"] = f"Mercado Libre: {len(ml_fallas)} consultas fallidas hoy (ver log del worker)"
    if WORKER in vivos:
        ultima = next((l for l in reversed(lineas) if re.match(r"\d\d:\d\d:\d\d ", l)), None)
        if ultima is None and ahora.hour >= 2:
            problemas["latido"] = "el worker no escribió nada en el log de hoy"
        elif ultima is not None:
            h = datetime.datetime.combine(ahora.date(), datetime.time.fromisoformat(ultima[:8]), rf.ART)
            if (ahora - h).total_seconds() > SIN_LATIDO_MIN * 60:
                problemas["latido"] = f"el worker no da señales desde las {ultima[:5]}"

    try:
        code, out = sh("docker", "exec", DEPLOYER, "cat", f"/state/logs/deployer-{hoy}.log")
    except Exception:  # noqa: BLE001
        code, out = 1, ""
    for linea in (out.splitlines() if code == 0 else []):
        if "DEPLOY_FAIL" in linea:
            problemas["deploy:" + linea[25:90]] = f"el despliegue falló: {linea[25:180]}"

    if (ahora.hour, ahora.minute) >= (7, 30):
        for nombre in ("ml-prices.json", "amazon-prices.json"):
            try:
                data = leer(WORKER, f"/app/output/{nombre}")
            except Exception:  # noqa: BLE001
                data = None
            if not data or data.get("date") != hoy:
                problemas["fresco:" + nombre] = f"{nombre} no tiene la fecha de hoy"
        try:
            estado = json.loads(bajar("https://ofertas.knunet.com/estado.json"))
            if estado.get("preciosDe") != hoy:
                problemas["sitio-fecha"] = "el sitio no tiene los precios de hoy"
            elif (estado.get("publicados") or 0) < rf.MINIMO_PRODUCTOS:
                problemas["sitio-minimo"] = f"el sitio tiene {estado.get('publicados')} productos (mínimo {rf.MINIMO_PRODUCTOS})"
        except Exception:
            problemas["sitio-caido"] = "el sitio no responde"
    return problemas


def cargar_estado(hoy):
    try:
        estado = json.load(open(ESTADO, encoding="utf-8"))
    except Exception:
        estado = {}
    if estado.get("fecha") != hoy:
        # Lo pendiente de ayer (no enviado) se conserva; lo ya avisado se olvida.
        estado = {"fecha": hoy, "avisados": [], "pendientes": estado.get("pendientes", {}),
                  "sin_internet_desde": estado.get("sin_internet_desde")}
    return estado


def main(ahora=None, enviar=rf.enviar):
    ahora = ahora or datetime.datetime.now(rf.ART)
    hoy = ahora.date().isoformat()
    estado = cargar_estado(hoy)
    problemas = chequeos(ahora)

    if "internet" in problemas:
        estado.setdefault("sin_internet_desde", None)
        estado["sin_internet_desde"] = estado["sin_internet_desde"] or ahora.strftime("%d/%m %H:%M")
    elif estado.get("sin_internet_desde"):
        problemas["internet-volvio"] = (f"la VM docker estuvo sin internet desde {estado['sin_internet_desde']} "
                                        f"hasta las {ahora.strftime('%H:%M')}; revisá qué no corrió")
        estado["sin_internet_desde"] = None

    nuevos = {k: v for k, v in problemas.items() if k not in estado["avisados"]}
    estado["pendientes"].update(nuevos)
    if estado["pendientes"] and "internet" not in problemas:
        # Hasta 6 por mensaje; sólo se marcan como avisados los que salieron (el resto va en la pasada siguiente).
        lote = list(estado["pendientes"])[:6]
        texto = rf.pedir([estado["pendientes"][k] for k in lote])
        try:
            enviar(texto, f"vigia {hoy}")
            estado["avisados"] += lote
            for k in lote:
                estado["pendientes"].pop(k)
            print("VIGIA_AVISO", ",".join(lote))
        except SystemExit:
            print("VIGIA_PENDIENTE", len(estado["pendientes"]))
    elif "internet" in problemas:
        print("VIGIA_PENDIENTE sin internet")
    else:
        print("VIGIA_OK", hoy, ahora.strftime("%H:%M"))
    json.dump(estado, open(ESTADO, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
