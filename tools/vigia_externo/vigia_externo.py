#!/usr/bin/env python3
"""Vigía externo de Franquicia 400: corre en la pi3 cada 10 min y avisa por Telegram (05/11).

Existe porque el vigía de la VM no puede avisar si la VM se cae o se queda sin internet:
- Latido: el vigía de la VM escribe /home/claude/vigia-latido.txt por SSH (llave restringida) en cada pasada.
  Si tiene más de 35 min o dice "sin-internet", algo anda mal en la VM.
- Sitio: después de las 7:45 /estado.json tiene que tener los precios de hoy y >=100 productos.
- WAHA (canal de avisos de la VM) tiene que responder en la LAN.
Avisa una vez por problema y por día, y avisa cuando se recupera. Canal: bot de Telegram del proyecto, chat del dueño.

Cron (pi3):  */10 * * * * /usr/bin/python3 /home/claude/vigia_externo.py >> /home/claude/vigia_externo.log 2>&1
Config: /home/claude/.vigia_externo.env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID), modo 600.
"""
import datetime
import json
import os
import socket
import urllib.parse
import urllib.request

HOME = "/home/claude"
LATIDO = os.path.join(HOME, "vigia-latido.txt")
ESTADO = os.path.join(HOME, "vigia_externo_estado.json")
ENV = os.path.join(HOME, ".vigia_externo.env")
ART = datetime.timezone(datetime.timedelta(hours=-3))
MAX_LATIDO_MIN = 35


def leer_env(path=ENV):
    return dict(l.strip().split("=", 1) for l in open(path, encoding="utf-8") if "=" in l and not l.startswith("#"))


def chequeos(ahora, latido=LATIDO, bajar=None, puerto_abierto=None):
    # Cloudflare rechaza el User-Agent por defecto de Python con 403 (05/11): mismo UA que el recordatorio.
    bajar = bajar or (lambda u: urllib.request.urlopen(urllib.request.Request(
        u, headers={"User-Agent": "Mozilla/5.0 (control Franquicia 400)"}), timeout=20).read().decode("utf-8", "replace"))
    puerto_abierto = puerto_abierto or _puerto_abierto
    problemas = {}
    try:
        edad = (ahora.timestamp() - os.path.getmtime(latido)) / 60
        contenido = open(latido, encoding="utf-8").read().strip()
    except OSError:
        edad, contenido = None, ""
    if edad is None or edad > MAX_LATIDO_MIN:
        problemas["latido"] = "la VM docker o su vigía no dan señales" + (f" hace {int(edad)} min" if edad else "")
    elif contenido.startswith("sin-internet"):
        problemas["internet"] = "la VM docker está sin internet (no pueden salir los avisos de WhatsApp)"
    if not puerto_abierto("192.168.3.251", 3010):
        problemas["waha"] = "WAHA (WhatsApp) de la VM no responde: los avisos del vigía no van a llegar"
    if (ahora.hour, ahora.minute) >= (7, 45):
        try:
            estado = json.loads(bajar("https://ofertas.knunet.com/estado.json"))
            if estado.get("preciosDe") != ahora.date().isoformat():
                problemas["sitio-fecha"] = "el sitio no tiene los precios de hoy"
            elif (estado.get("publicados") or 0) < 100:
                problemas["sitio-minimo"] = f"el sitio tiene {estado.get('publicados')} productos (mínimo 100)"
        except Exception:  # noqa: BLE001
            problemas["sitio-caido"] = "ofertas.knunet.com no responde"
    return problemas


def _puerto_abierto(host, port):
    try:
        with socket.create_connection((host, port), timeout=5):
            return True
    except OSError:
        return False


def telegram(texto, env=None):
    env = env or leer_env()
    data = urllib.parse.urlencode({"chat_id": env["TELEGRAM_CHAT_ID"], "text": texto}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}/sendMessage", data=data, timeout=20).read()


def main(ahora=None, enviar=telegram, chequear=chequeos, estado_path=ESTADO):
    ahora = ahora or datetime.datetime.now(ART)
    hoy = ahora.date().isoformat()
    try:
        estado = json.load(open(estado_path, encoding="utf-8"))
    except Exception:  # noqa: BLE001
        estado = {}
    activos = estado.get("activos", {})
    if estado.get("fecha") != hoy:
        estado = {"fecha": hoy, "avisados": []}
    problemas = chequear(ahora)
    mensajes = [f"⚠️ Franquicia 400: {t}" for k, t in problemas.items() if k not in estado["avisados"]]
    resueltos = [k for k in activos if k not in problemas]
    mensajes += [f"✅ Franquicia 400: se resolvió «{activos[k]}»" for k in resueltos]
    if mensajes:
        try:
            enviar("\n".join(mensajes))
            estado["avisados"] = sorted(set(estado["avisados"]) | set(problemas))
            activos = dict(problemas)
            print("VIGIA_EXTERNO_AVISO", ahora.strftime("%H:%M"), ",".join(list(problemas) + resueltos))
        except Exception as e:  # noqa: BLE001
            print("VIGIA_EXTERNO_FAIL", type(e).__name__)  # se reintenta en la pasada siguiente
    else:
        activos = dict(problemas)
        print("VIGIA_EXTERNO_OK", ahora.strftime("%H:%M"))
    estado["activos"] = activos
    json.dump(estado, open(estado_path, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
