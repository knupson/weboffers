#!/usr/bin/env python3
"""Recordatorios y controles de Franquicia 400 por WhatsApp (WAHA del pi4).

Reusa la configuración de WAHA del servicio de avisos de soporte (su .env), igual que
recordatorio_redes.py de Blackseam. Mensajes lo más cortos posible: sólo la frase para Claude.

Modos:
- Sin argumentos (10:00): tareas del día según el calendario de publicaciones y avisos puntuales.
- --control <sitio|telegram12|telegram20>: control automático; sólo escribe si algo falló.
  sitio = la portada tiene la fecha de hoy (deploy de las 7:00); telegramNN = el canal tiene
  la publicación de ese turno.
- --prueba: manda el mensaje de hoy (o de mañana) como prueba.
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

# Frases extra por fecha (AAAA-MM-DD). Calendario: claude.ai/artifact/MaxRa2pv8JYqNEeeykpQpr
FRASES = {
    "2026-11-02": ["revisá que el sitio tenga los precios del Cyber"],
    "2026-11-07": ["informe de la semana y propuesta de publicidad"],
    "2026-11-24": ["armá el carrusel y las historias de la semana"],
    "2026-11-27": ["armá el Reel especial de Black Friday"],
    "2026-11-30": ["armá el Reel especial de Cyber Monday"],
    "2026-12-01": ["informe del mes y armá el calendario de diciembre"],
}
# Avisos que no necesitan a Claude (una línea).
NOTAS = {
    "2026-11-03": "Franquicia 400: a las 19:05 fijate en Instagram que haya salido el Reel 1.",
}
SIN_REEL = {"2026-11-03"}  # el Reel 1 ya está programado
SIN_CARRUSEL = {"2026-11-23"}  # feriado: pasa al 24
CALENDARIO_HASTA = datetime.date(2026, 11, 30)


def leer_env():
    return dict(l.strip().split("=", 1) for l in open(os.path.join(HERE, ".env"), encoding="utf-8") if "=" in l and not l.startswith("#"))


def pedir(frases):
    citas = [f"«{f}»" for f in frases]
    return f"{CLAUDE} " + (", ".join(citas[:-1]) + " y " + citas[-1] if len(citas) > 1 else citas[0]) + "."


def mensaje(hoy):
    iso = hoy.isoformat()
    frases = []
    if hoy.weekday() == 0:
        frases += ["rutina de los lunes", "informe de la semana"]
        if hoy.day <= 7:
            frases.append("informe del mes")
    if hoy <= CALENDARIO_HASTA:
        if hoy.weekday() == 0 and iso not in SIN_CARRUSEL:
            frases.append("armá el carrusel y las historias de la semana")
        if hoy.weekday() in (1, 2, 3) and iso not in SIN_REEL:
            frases.append("armá el Reel del día")
    frases += FRASES.get(iso, [])
    partes = [pedir(frases)] if frases else []
    if iso in NOTAS:
        partes.append(NOTAS[iso])
    return "\n".join(partes)


def bajar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (control Franquicia 400)"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def control(que, ahora, bajar=bajar):
    """Texto de alerta si algo falló; "" si está todo bien."""
    hoy = ahora.date().isoformat()
    if que == "sitio":
        try:
            html = bajar("https://ofertas.knunet.com/")
        except Exception:
            return pedir(["el sitio no responde, revisalo"])
        if f'"{hoy}' not in html:
            return pedir(["el sitio no se actualizó hoy, revisá la pi4"])
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
        return pedir([f"no salió el Telegram de las {hora}, revisá la pi4"])
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
        texto = "Prueba Franquicia 400.\n" + (texto or mensaje(hoy + datetime.timedelta(days=1)))
    if not texto:
        print("FRANQUICIA_RECORDATORIO_NADA", hoy.isoformat())
        return
    enviar(texto, hoy.isoformat())


if __name__ == "__main__":
    main()
