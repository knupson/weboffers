#!/usr/bin/env python3
"""Recordatorios y controles de Franquicia 400 por WhatsApp (WAHA del pi4).

Reusa la configuración de WAHA del servicio de avisos de soporte (su .env), igual que
recordatorio_redes.py de Blackseam.

Dos modos:
- Sin argumentos (10:00): tareas del día según el calendario de publicaciones (Reel mar-jue,
  carrusel los lunes, rutina de los lunes, fechas especiales) y avisos puntuales.
- --control <sitio|telegram12|telegram20>: control automático; sólo escribe si algo falló.
  sitio = la portada tiene la fecha de hoy (deploy de las 7:00); telegramNN = el canal tiene
  la publicación de ese turno.
- --prueba: manda un mensaje de prueba.
Cron (dockerhost, hora ART):
  0 10 * * *  recordatorio_franquicia.py
  30 7 * * *  recordatorio_franquicia.py --control sitio
  20 12 * * * recordatorio_franquicia.py --control telegram12
  20 20 * * * recordatorio_franquicia.py --control telegram20
Logs sin números ni claves: FRANQUICIA_RECORDATORIO_OK / _NADA / _FAIL, FRANQUICIA_CONTROL_OK.
"""
import datetime
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ART = datetime.timezone(datetime.timedelta(hours=-3))

CLAUDE = r"Abrí Claude Code en E:\Repositorios\Personal\weboffers, con tu Chrome personal abierto, y decile:"
REEL = f"🎬 Franquicia 400: hoy toca Reel (sale 12:00 en YouTube y 19:00 en Instagram y Facebook, con los precios de hoy).\n{CLAUDE} «armá el Reel del día»."
CARRUSEL = f"🗂️ Franquicia 400: hoy toca el carrusel de la semana y dejar programadas las historias.\n{CLAUDE} «armá el carrusel y las historias de la semana»."

# Avisos de una sola vez (AAAA-MM-DD → texto). Calendario: claude.ai/artifact/MaxRa2pv8JYqNEeeykpQpr
PUNTUALES = {
    "2026-10-31": "🔎 Franquicia 400: 1) Abrí ofertas.knunet.com: el Sony WF-1000XM5 tiene que decir $400.000 (si no, falló la publicación automática de las 7:30; avisame). 2) Mirá si entran clicks en mercadolibre.com.ar/afiliados → Métricas.",
    "2026-11-02": f"⚡ Franquicia 400: arranca el CyberMonday (2 al 4/11).\n{CLAUDE} «revisá que el sitio tenga los precios del Cyber».",
    "2026-11-03": "✅ Franquicia 400: hoy no tenés que armar nada, el Reel 1 ya está programado. A las 19:05 abrí Instagram y fijate que se haya publicado; si no está, avisame.",
    "2026-11-07": f"📣 Franquicia 400: ya hay una semana de datos. Decidí si probamos publicidad (USD 30–50).\n{CLAUDE} «informe de la semana y propuesta de publicidad».",
    "2026-11-23": "🇦🇷 Franquicia 400: feriado. El carrusel de esta semana pasa a mañana.",
    "2026-11-24": CARRUSEL,
    "2026-11-27": f"🖤 Franquicia 400: Black Friday. Hoy hay Reel especial con los precios de hoy (12:00 y 19:00).\n{CLAUDE} «armá el Reel especial de Black Friday».",
    "2026-11-30": f"💻 Franquicia 400: Cyber Monday de EE.UU., Reel especial de cierre del mes.\n{CLAUDE} «armá el Reel especial de Cyber Monday».",
    "2026-12-01": f"🗓️ Franquicia 400: terminó el calendario de noviembre.\n{CLAUDE} «informe del mes y armá el calendario de diciembre».",
}
SIN_REEL = {"2026-11-03"}  # el Reel 1 ya está programado
SIN_CARRUSEL = {"2026-11-23"}  # feriado: pasa al 24
CALENDARIO_HASTA = datetime.date(2026, 11, 30)


def leer_env():
    return dict(l.strip().split("=", 1) for l in open(os.path.join(HERE, ".env"), encoding="utf-8") if "=" in l and not l.startswith("#"))


def mensaje(hoy):
    partes = []
    iso = hoy.isoformat()
    if hoy.weekday() == 0:
        lunes = f"🛒 Franquicia 400: rutina de los lunes (≈15 min).\n{CLAUDE} «rutina de los lunes» y «informe de la semana» (Umami → decisiones de la semana)."
        if hoy.day <= 7:
            lunes += "\n📊 Primer lunes del mes: pedile también «informe del mes» (Umami y comisiones)."
        partes.append(lunes)
    if hoy <= CALENDARIO_HASTA:
        if hoy.weekday() == 0 and iso not in SIN_CARRUSEL:
            partes.append(CARRUSEL)
        if hoy.weekday() in (1, 2, 3) and iso not in SIN_REEL:
            partes.append(REEL)
    if iso in PUNTUALES:
        partes.append(PUNTUALES[iso])
    return "\n\n".join(partes)


def bajar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (control Franquicia 400)"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def control(que, ahora, bajar=bajar):
    """Texto de alerta si algo falló; "" si está todo bien."""
    hoy = ahora.date().isoformat()
    if que == "sitio":
        try:
            html = bajar("https://ofertas.knunet.com/")
        except Exception as e:
            return f"🚨 Franquicia 400: ofertas.knunet.com no responde ({getattr(e, 'code', type(e).__name__)}).\n{CLAUDE} «el sitio no responde, revisalo»."
        if f'"{hoy}' not in html:
            return f"⚠️ Franquicia 400: el sitio no tiene los precios de hoy (no salió el deploy de las 7:00).\n{CLAUDE} «el sitio no se actualizó hoy, revisá la pi4»."
        return ""
    if que in ("telegram12", "telegram20"):
        hora = int(que[-2:])
        try:
            html = bajar("https://t.me/s/franquicia400")
        except Exception:
            return ""  # si t.me no responde no es un problema nuestro
        desde = datetime.datetime.fromisoformat(f"{hoy}T{hora:02d}:00:00-03:00")
        fechas = [datetime.datetime.fromisoformat(f) for f in re.findall(r'<time[^>]*datetime="([^"]+)"', html)]
        if any(f >= desde for f in fechas):
            return ""
        return f"⚠️ Franquicia 400: no salió la publicación de Telegram de las {hora}.\n{CLAUDE} «no salió el Telegram de las {hora}, revisá la pi4»."
    raise SystemExit(f"control desconocido: {que}")


def enviar(texto, etiqueta):
    env = leer_env()
    payload = {"session": env.get("WAHA_SESSION") or "default", "chatId": env["WA_NOTIFY_CHAT_ID"], "text": texto}
    req = urllib.request.Request(env["WAHA_URL"].rstrip("/") + "/api/sendText", data=json.dumps(payload).encode(), method="POST")
    req.add_header("X-Api-Key", env.get("WAHA_API_KEY", ""))
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=15).read()
        print("FRANQUICIA_RECORDATORIO_OK", etiqueta)
    except Exception as e:
        print("FRANQUICIA_RECORDATORIO_FAIL", getattr(e, "code", type(e).__name__))
        sys.exit(1)


def main():
    ahora = datetime.datetime.now(ART)
    hoy = ahora.date()
    if len(sys.argv) > 2 and sys.argv[1] == "--control":
        texto = control(sys.argv[2], ahora)
        if texto:
            enviar(texto, f"control-{sys.argv[2]} {hoy.isoformat()}")
        else:
            print("FRANQUICIA_CONTROL_OK", sys.argv[2], hoy.isoformat())
        return
    texto = mensaje(hoy)
    if len(sys.argv) > 1 and sys.argv[1] == "--prueba":
        texto = "🧪 Prueba de avisos de Franquicia 400. A las 10 llegan las tareas del día; los controles de las 7:30, 12:20 y 20:20 sólo escriben si algo falló.\n\n" + (
            texto or mensaje(hoy + datetime.timedelta(days=1)))
    if not texto:
        print("FRANQUICIA_RECORDATORIO_NADA", hoy.isoformat())
        return
    enviar(texto, hoy.isoformat())


if __name__ == "__main__":
    main()
