#!/usr/bin/env python3
"""Recordatorios de Franquicia 400 por WhatsApp (WAHA del pi4).

Reusa la configuración de WAHA del servicio de avisos de soporte (su .env), igual que
recordatorio_redes.py de Blackseam. Corre todos los días a las 10 y decide qué mandar:
la rutina de los lunes y los avisos puntuales con fecha.
Cron (dockerhost): 0 10 * * * python3 /opt/docker/blackseam/soporte/recordatorio_franquicia.py
Logs sin números ni claves: FRANQUICIA_RECORDATORIO_OK / _NADA / _FAIL.
"""
import datetime
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ENV = dict(l.strip().split("=", 1) for l in open(os.path.join(HERE, ".env"), encoding="utf-8") if "=" in l and not l.startswith("#"))

CLAUDE = r"Abrí Claude Code en E:\Repositorios\Personal\weboffers, con tu Chrome personal abierto, y decile:"

# Avisos de una sola vez (AAAA-MM-DD → texto).
PUNTUALES = {
    "2026-10-31": "🔎 Franquicia 400: 1) Abrí ofertas.knunet.com: el Sony WF-1000XM5 tiene que decir $400.000 (si no, falló la publicación automática de las 7:30; avisame). 2) Mirá si entran clicks en mercadolibre.com.ar/afiliados → Métricas.",
    "2026-11-01": f"🎬 Franquicia 400: toca el primer Reel de Instagram (sin publicaciones la cuenta no aparece en búsquedas).\n{CLAUDE} «armá el Reel de Instagram».",
    "2026-11-07": f"📣 Franquicia 400: ya hay una semana de datos. Decidí si probamos publicidad (USD 30–50).\n{CLAUDE} «informe de la semana y propuesta de publicidad».",
}


def mensaje(hoy):
    partes = []
    if hoy.weekday() == 0:
        lunes = f"🛒 Franquicia 400: rutina de los lunes (≈15 min).\n{CLAUDE} «rutina de los lunes»."
        if hoy.day <= 7:
            lunes += "\n📊 Primer lunes del mes: pedile también «informe del mes» (Umami y comisiones)."
        partes.append(lunes)
    if hoy.isoformat() in PUNTUALES:
        partes.append(PUNTUALES[hoy.isoformat()])
    return "\n\n".join(partes)


def main():
    hoy = datetime.date.today()
    texto = mensaje(hoy)
    if len(sys.argv) > 1 and sys.argv[1] == "--prueba":
        texto = "🧪 Prueba de recordatorios de Franquicia 400. Llegan a las 10: los lunes la rutina y en fechas puntuales los avisos.\n\n" + (
            texto or mensaje(hoy + datetime.timedelta(days=(7 - hoy.weekday()) % 7 or 7)))
    if not texto:
        print("FRANQUICIA_RECORDATORIO_NADA", hoy.isoformat())
        return
    payload = {"session": ENV.get("WAHA_SESSION") or "default", "chatId": ENV["WA_NOTIFY_CHAT_ID"], "text": texto}
    req = urllib.request.Request(ENV["WAHA_URL"].rstrip("/") + "/api/sendText", data=json.dumps(payload).encode(), method="POST")
    req.add_header("X-Api-Key", ENV.get("WAHA_API_KEY", ""))
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=15).read()
        print("FRANQUICIA_RECORDATORIO_OK", hoy.isoformat())
    except Exception as e:
        print("FRANQUICIA_RECORDATORIO_FAIL", getattr(e, "code", type(e).__name__))
        sys.exit(1)


if __name__ == "__main__":
    main()
