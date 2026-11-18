#!/usr/bin/env python3
"""Recordatorios y controles de Franquicia 400 por WhatsApp (WAHA de la VM docker).

Reusa la configuración de WAHA del servicio de avisos de soporte (su .env), igual que
recordatorio_redes.py de Blackseam. Mensajes lo más cortos posible: sólo la frase para Claude.

Modos:
- Sin argumentos (10:00): tareas del día según el calendario de publicaciones y avisos puntuales.
- --control <sitio|sitio13|telegram12|telegram20>: control automático; sólo escribe si algo falló.
  sitio = la portada tiene la fecha de hoy (deploy de las 7:00); telegramNN = el canal tiene
  la publicación de ese turno.
- --prueba: manda el mensaje de hoy (o de mañana) como prueba.
Cron (docker, hora ART):
  0 10 * * *  recordatorio_franquicia.py
  30 7 * * *  recordatorio_franquicia.py --control sitio
  30 15 * * * recordatorio_franquicia.py --control sitio13  (sólo controla días con despliegue extra)
  20 12 * * * recordatorio_franquicia.py --control telegram12
  20 20 * * * recordatorio_franquicia.py --control telegram20
  10 19 * * * recordatorio_franquicia.py --control reel19 (todos los días desde 13/11: el Reel sale solo, cron 18:15 generar_y_encolar_reel.sh)   (API de Meta, token en /home/claude/franquicia400-meta/.env)
Logs sin números ni claves: FRANQUICIA_RECORDATORIO_OK / _NADA / _FAIL, FRANQUICIA_CONTROL_OK.
"""
import datetime
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ART = datetime.timezone(datetime.timedelta(hours=-3))

# 16/11: formato compacto (Alejandro: «sin repetir el texto largo de "Abrí Claude Code..." en cada mensaje»).
CLAUDE = "F400 · decile a Claude en weboffers:"

# Frases extra por fecha (AAAA-MM-DD). Calendario: claude.ai/artifact/MaxRa2pv8JYqNEeeykpQpr
FRASES = {
    "2026-11-02": ["revisá que el sitio tenga los precios del Cyber"],
    "2026-11-07": ["informe de la semana y propuesta de publicidad"],
    "2026-11-24": ["armá el carrusel de la semana por API"],
    "2026-11-27": ["armá el Reel especial de Black Friday"],
    "2026-11-30": ["armá el Reel especial de Cyber Monday"],
    "2026-12-01": ["informe del mes y armá el calendario de diciembre"],
}
# Avisos que no necesitan a Claude (una línea).
NOTAS = {
}
SIN_CARRUSEL = {"2026-11-23"}  # feriado: pasa al 24
MINIMO_PRODUCTOS = 100
MAXIMO_SIN_ENVIO = 3  # tarjetas «no confirmamos el envío» toleradas antes de avisar
EXTRA_DEPLOY_DATES = {"2026-11-02", "2026-11-03", "2026-11-04", "2026-11-27", "2026-11-30"}


def leer_env():
    return dict(l.strip().split("=", 1) for l in open(os.path.join(HERE, ".env"), encoding="utf-8") if "=" in l and not l.startswith("#"))


def pedir(frases):
    citas = [f"«{f}»" for f in frases]
    if len(citas) == 1:
        return f"{CLAUDE} {citas[0]}"
    return CLAUDE + "\n" + "\n".join(f"• {c}" for c in citas)


def mensaje(hoy):
    iso = hoy.isoformat()
    frases = []
    if hoy.weekday() == 0:
        frases += ["rutina de los lunes", "informe de la semana"]
        if hoy.day <= 7:
            frases.append("informe del mes")
    # Esqueleto semanal permanente (skill redes-proyectos): sin fecha de vencimiento (05/11).
    if hoy.weekday() == 0 and iso not in SIN_CARRUSEL:
        frases.append("armá el carrusel de la semana por API")
    # 17/11: sin historias ni Shorts por Chrome (regla redes-proyectos: sólo API oficial); el carrusel va por la cola de Meta.
    # 13/11: el Reel del día ya no se pide: lo genera y encola el cron de la VM (18:15, generar_y_encolar_reel.sh).
    frases += FRASES.get(iso, [])
    partes = [pedir(frases)] if frases else []
    if iso in NOTAS:
        partes.append(NOTAS[iso])
    return "\n".join(partes)


def bajar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (control Franquicia 400)"})
    return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")


def contar_revision():
    """Pares en altas-revision.json del worker (root 600: se lee con docker exec); None si no se pudo leer."""
    import subprocess
    try:
        r = subprocess.run(["docker", "exec", "franquicia400-weboffers-worker-1", "cat", "/app/output/altas-revision.json"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return None
        cola = json.loads(r.stdout or "[]")
        return len(cola) if isinstance(cola, list) else None
    except Exception:
        return None


def control(que, ahora, bajar=bajar, revision=contar_revision):
    """Texto de alerta si algo falló; "" si está todo bien."""
    hoy = ahora.date().isoformat()
    if que == "sitio13" and hoy not in EXTRA_DEPLOY_DATES:
        return ""
    if que in ("sitio", "sitio13"):
        try:
            html = bajar("https://ofertas.knunet.com/")
        except Exception:
            return pedir(["el sitio no responde, revisalo"])
        problemas = []
        if f'"{hoy}' not in html:
            problemas.append("el sitio no se actualizó hoy, revisá la VM docker")
        # Mínimo acordado: 100 productos con los dos precios de hoy (cada uno es un ListItem del JSON-LD de la portada).
        n = html.count('"@type":"ListItem"')
        try:
            estado = json.loads(bajar("https://ofertas.knunet.com/estado.json")) or {}
        except Exception:
            estado = {}
        if estado.get("preciosDe") != hoy:
            problemas.append("estado.json no tiene los precios de hoy, revisá el despliegue")
        if estado.get("amazon") is None:
            problemas.append("Amazon: sin datos del worker, revisá la VM docker")
        if n < MINIMO_PRODUCTOS:
            problemas.append(f"el sitio salió hoy con {n} productos (mínimo {MINIMO_PRODUCTOS}){causa_amazon(bajar)}, recuperá los que faltan")
        # Lo que ve el visitante: tarjetas donde Amazon gana pero no hay envío confirmado (03/11: 25 tarjetas).
        try:
            sin_envio = bajar("https://ofertas.knunet.com/productos/").count("no confirmamos el envío")
        except Exception:
            sin_envio = 0
        if sin_envio > MAXIMO_SIN_ENVIO:
            problemas.append(f"hay {sin_envio} productos con «no confirmamos el envío», revisá el envío a Argentina")
        # 16/11: se sacó el control de los lunes de la búsqueda semanal del domingo. Esa búsqueda se retiró el 09/11
        # (commit 8a5005a, alta diaria dentro de la cadena) y el control seguía leyendo catalogo.week de estado.json,
        # congelado en 2026-W45 «running»: avisaba en falso todos los lunes. El alta diaria la controla el vigía
        # (bloque alta:* de cadena-<hoy>.json).
        # 07/11: altas sin identificador fuerte esperan revisión en Chrome (decisión de Alejandro); sólo en el control de las 07:30.
        # 16/11: se cuenta la cola real (altas-revision.json del worker), no catalogo.revision de estado.json (quedó en 5 desde el 09/11).
        if que == "sitio":
            pendientes = revision()
            if pendientes is None:
                problemas.append("no pude leer la cola de altas en revisión, revisá la VM docker")
            elif pendientes > 0:
                problemas.append("revisá las altas")
        return pedir(problemas) if problemas else ""
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
        return pedir([f"no salió el Telegram de las {hora}, revisá la VM docker"])
    if que == "reel19":
        # 13/11: Reel todos los días a las 19:00 en IG y FB (cron 18:15 en la VM). Se consulta la API oficial de Meta.
        desde = datetime.datetime.fromisoformat(f"{hoy}T18:50:00-03:00")
        try:
            env = leer_meta_env()
            ig = graph(f"/{env['META_IG_USER_ID']}/media", {"fields": "media_product_type,timestamp", "limit": "10"}, env)
            pagina = graph(f"/{env['META_PAGE_ID']}", {"fields": "access_token"}, env)["access_token"]
            fb = graph(f"/{env['META_PAGE_ID']}/video_reels", {"fields": "created_time,status", "limit": "10"}, env, pagina)
        except Exception as e:
            return pedir([f"no pude comprobar el Reel de las 19 ({type(e).__name__}), revisalo"])
        falta = []
        if not any(m.get("media_product_type") == "REELS" and meta_fecha(m["timestamp"]) >= desde for m in ig.get("data", [])):
            falta.append("Instagram")
        # Un Reel programado se sube antes: vale la hora de publicación, no la de subida (03/11, falsa alarma).
        if not any(meta_fecha(publicado_fb(v)) >= desde for v in fb.get("data", [])):
            falta.append("Facebook")
        return pedir([f"no salió el Reel de las 19 en {' ni en '.join(falta)}, revisalo"]) if falta else ""
    raise SystemExit(f"control desconocido: {que}")


def causa_amazon(bajar):
    """Motivo de los faltantes de Amazon según /estado.json (resumen de la corrida del worker), en pocas palabras."""
    try:
        run = (json.loads(bajar("https://ofertas.knunet.com/estado.json")) or {}).get("amazon") or {}
    except Exception:
        return ""
    if not run.get("fallas"):
        return ""
    def resumen(motivos):
        return ", ".join(f"{v} {k}" for k, v in sorted((motivos or {}).items(), key=lambda kv: -kv[1])[:3])
    faltan = run.get("faltan")
    if isinstance(faltan, dict):
        # 08/11: lo que importa es lo que falta DESPUÉS de los reintentos (decía 39 cuando faltaba 1).
        recuperados = (run.get("reintento") or {}).get("recuperados") or 0
        historia = f"la corrida dejó {run['fallas']} sin precio y los reintentos recuperaron {recuperados}"
        if not faltan.get("total"):
            return f": no faltan precios de Amazon ({historia}); la causa está en otro filtro, mirá el desglose del deployer"
        return f": faltan {faltan['total']} sin precio de Amazon ({resumen(faltan.get('motivos'))}); {historia}"
    motivos = resumen(run.get("motivos"))
    texto = f": Amazon dejó {run['fallas']} sin precio ({motivos})"
    if run.get("rafaga"):
        texto += f", cortó por ráfaga desde la posición {run.get('primeraFallaPos')}; mañana el worker va más lento solo"
    reintento = run.get("reintento") or {}
    if reintento:
        texto += f"; el reintento recuperó {reintento.get('recuperados')} de {reintento.get('pendientes')}"
    return texto


META_ENV = "/home/claude/franquicia400-meta/.env"


def leer_meta_env():
    return dict(l.strip().split("=", 1) for l in open(META_ENV, encoding="utf-8") if "=" in l and not l.startswith("#"))


def publicado_fb(video):
    fase = ((video.get("status") or {}).get("publishing_phase") or {})
    return fase.get("publish_time") if fase.get("publish_status") == "published" and fase.get("publish_time") else video["created_time"]


def meta_fecha(s):
    # Graph devuelve "2026-11-03T22:00:05+0000".
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")


def graph(ruta, params, env, token=None):
    """GET a la Graph API (token del usuario del sistema o de la página); el token nunca se loguea."""
    q = urllib.parse.urlencode({**params, "access_token": token or env["META_SYSTEM_TOKEN"]})
    with urllib.request.urlopen(f"https://graph.facebook.com/v21.0{ruta}?{q}", timeout=30) as r:
        return json.load(r)


SILENCIO_HASTA = 7  # Alejandro, 07/11: ningún WhatsApp antes de las 7 de la mañana.


def enviar(texto, etiqueta, ahora=None):
    ahora = ahora or datetime.datetime.now(ART)
    if ahora.astimezone(ART).hour < SILENCIO_HASTA:
        # Falla a propósito: el vigía lo deja en pendientes y lo manda en la primera pasada desde las 07:00.
        print("FRANQUICIA_RECORDATORIO_ESPERA", etiqueta, f"(silencio hasta las {SILENCIO_HASTA:02d}:00)")
        sys.exit(1)
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
