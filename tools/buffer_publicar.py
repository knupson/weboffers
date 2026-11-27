#!/usr/bin/env python3
"""Programa el Reel diario de Franquicia 400 como Short de YouTube y post de X, por la API oficial de Buffer.

Regla (17/11, skill redes-proyectos): ningún agente maneja el sitio web de una red social; se publica sólo por API
oficial o por herramientas que usan esas APIs. Buffer publica en YouTube y X con sus APIs oficiales.

Corre en la VM docker, lo llama generar_y_encolar_reel.sh después de encolar en Meta:
  python3 buffer_publicar.py --id reel-17-11 --cuando 2026-11-17T19:00:00-03:00 \
      --video https://lista.blackseam.knunet.com/descargas/redes/f400-reel-17-11/reel-17-11.mp4 \
      --texto /home/claude/reel/out/duelo-2026-11-17.txt [--seco]
Clave: BUFFER_API_KEY en /home/claude/franquicia400-meta/buffer.env (chmod 600). Nunca se imprime.
Estado (idempotente): /home/claude/franquicia400-meta/estado_buffer.json, clave "<id>|youtube" / "<id>|x".
Logs: BUFFER_OK <id> <red> <post_id> · BUFFER_YA <id> <red> · BUFFER_FALLA <id> <red> <motivo> · BUFFER_SECO.
Una falla avisa por WhatsApp (WAHA, desde las 07:00) y sale con código 1; no toca la cola de Meta.
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

API = "https://api.buffer.com"
DIR = "/home/claude/franquicia400-meta"
ENV_BUFFER = os.path.join(DIR, "buffer.env")
ENV_WAHA = "/opt/docker/blackseam/soporte/.env"
ESTADO = os.path.join(DIR, "estado_buffer.json")
ART = datetime.timezone(datetime.timedelta(hours=-3))
SILENCIO_HASTA = 7  # ningún WhatsApp antes de las 7 (Alejandro, 07/11)

# Canales de la organización de Buffer de ofertas@knunet.com (leídos por list_channels el 17/11).
CANALES = {
    "youtube": "6afcf26cece6dfde5f0233ae",
    "x": "6afcf543ece6dfde5f0249f2",
}
CATEGORIA_YT = "28"  # Ciencia y tecnología
SITIO = "https://ofertas.knunet.com/"
AVISO_AFILIADOS = "Si comprás por los links del sitio, Amazon o Mercado Libre nos pueden pagar una comisión, sin costo extra para vos."

MUTACION = """mutation($input: CreatePostInput!) {
  createPost(input: $input) {
    __typename
    ... on PostActionSuccess { post { id status dueAt } }
    ... on InvalidInputError { message }
    ... on LimitReachedError { message }
    ... on UnauthorizedError { message }
    ... on NotFoundError { message }
    ... on UnexpectedError { message }
    ... on RestProxyError { message }
  }
}"""


def ts():
    return datetime.datetime.now(ART).strftime("%Y-%m-%d %H:%M:%S")


def leer_env(path):
    env = {}
    if os.path.exists(path):
        for linea in open(path, encoding="utf-8"):
            linea = linea.strip()
            if linea and not linea.startswith("#") and "=" in linea:
                k, v = linea.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def utm(red, pid):
    return f"{SITIO}?utm_source={red}&utm_medium=social&utm_campaign=reel-diario&utm_content={pid}"


def fecha_corta(pid):
    m = re.match(r"reel-(\d\d)-(\d\d)$", pid)
    return f"{m.group(1)}/{m.group(2)}" if m else ""


def cantidad_productos(caption):
    m = re.search(r"Comparamos (\d+) productos", caption)
    return m.group(1) if m else None


def texto_youtube(caption, pid):
    """Descripción del Short: el caption del Reel con el link real (UTM youtube) y el aviso de afiliados."""
    if "link en la bio." not in caption:
        raise ValueError("el caption no trae «link en la bio.»")
    desc = caption.replace("link en la bio.", utm("youtube", pid))
    desc = desc.rstrip() + "\n\n" + AVISO_AFILIADOS + "\n#shorts"
    return desc[:4900]


def titulo_youtube(pid):
    t = "¿Amazon o Mercado Libre? Precios de hoy"
    f = fecha_corta(pid)
    return (t + (f" {f}" if f else "") + " #shorts")[:100]


def texto_x(caption, pid, cuerpo=None):
    """Post de X: corto, sin hashtags de más (0-2), link al final. X cuenta cada URL como 23 caracteres.
    `cuerpo` (27/11, Reel especial): todo menos el link, con aviso de afiliados y hashtags incluidos."""
    if cuerpo is None:
        n = cantidad_productos(caption)
        f = fecha_corta(pid)
        cuerpo = "¿Amazon o Mercado Libre? Depende del producto."
        if n:
            cuerpo += f" Hoy{(' ' + f) if f else ''} comparamos {n} productos con los precios del día, envío e impuestos incluidos."
        cuerpo += "\nEl sitio usa links de afiliado.\n#amazonargentina #mercadolibre"
    texto = cuerpo.rstrip() + "\n" + utm("x", pid)
    largo = len(texto) - len(utm("x", pid)) + 23
    if largo > 280:
        raise ValueError(f"el post de X queda en {largo} caracteres")
    return texto


def armar_inputs(pid, cuando, video, caption, ahora, titulo=None, cuerpo_x=None):
    """Devuelve {red: input de createPost}. Si el horario ya pasó (o faltan menos de 2 min), publica ya."""
    due = datetime.datetime.fromisoformat(cuando)
    if due <= ahora + datetime.timedelta(minutes=2):
        modo = {"mode": "shareNow"}
    else:
        modo = {"mode": "customScheduled", "dueAt": due.isoformat()}
    asset = [{"video": {"url": video}}]
    return {
        "youtube": dict(modo, channelId=CANALES["youtube"], schedulingType="automatic", text=texto_youtube(caption, pid),
                        assets=asset, source="franquicia400-buffer_publicar",
                        metadata={"youtube": {"title": (titulo or titulo_youtube(pid))[:100], "categoryId": CATEGORIA_YT,
                                              "privacy": "public", "madeForKids": False, "isAiGenerated": True,
                                              "license": "youtube", "embeddable": True, "notifySubscribers": True}}),
        "x": dict(modo, channelId=CANALES["x"], schedulingType="automatic", text=texto_x(caption, pid, cuerpo_x),
                  assets=asset, source="franquicia400-buffer_publicar",
                  metadata={"twitter": {"isAiGenerated": True}}),
    }


def crear_post(clave, entrada):
    body = json.dumps({"query": MUTACION, "variables": {"input": entrada}}).encode()
    req = urllib.request.Request(API, data=body, method="POST",
                                 headers={"Authorization": "Bearer " + clave, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}"
    except Exception as e:  # red caída, timeout
        return None, f"{type(e).__name__}: {e}"[:200]
    if resp.get("errors"):
        return None, "; ".join(x.get("message", "") for x in resp["errors"])[:200]
    r = (resp.get("data") or {}).get("createPost") or {}
    if r.get("__typename") == "PostActionSuccess":
        return r["post"], None
    return None, f"{r.get('__typename')}: {r.get('message', '')}"[:200]


def alertar(texto, ahora):
    if ahora.astimezone(ART).hour < SILENCIO_HASTA:
        return False
    env = leer_env(ENV_WAHA)
    try:
        payload = {"session": env.get("WAHA_SESSION") or "default", "chatId": env["WA_NOTIFY_CHAT_ID"], "text": texto}
        req = urllib.request.Request(env["WAHA_URL"].rstrip("/") + "/api/sendText", data=json.dumps(payload).encode(),
                                     method="POST", headers={"X-Api-Key": env.get("WAHA_API_KEY", ""),
                                                             "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except Exception:
        return False


def cargar_estado():
    if os.path.exists(ESTADO):
        with open(ESTADO, encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_estado(estado):
    tmp = ESTADO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(estado, f, ensure_ascii=False, indent=1)
    os.replace(tmp, ESTADO)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--id", required=True)
    ap.add_argument("--cuando", required=True, help="ISO con zona, ej. 2026-11-17T19:00:00-03:00")
    ap.add_argument("--video", required=True, help="URL pública del mp4")
    ap.add_argument("--texto", required=True, help="caption del Reel (duelo-AAAA-MM-DD.txt)")
    ap.add_argument("--redes", default="youtube,x")
    ap.add_argument("--titulo", help="titulo del Short (Reel especial); si falta, el del Reel diario")
    ap.add_argument("--texto-x", help="archivo con el post de X sin el link (Reel especial)")
    ap.add_argument("--seco", action="store_true", help="arma los pedidos y no los manda")
    a = ap.parse_args(argv)

    ahora = datetime.datetime.now(ART)
    caption = open(a.texto, encoding="utf-8").read()
    try:
        cuerpo_x = open(a.texto_x, encoding="utf-8").read() if a.texto_x else None
        inputs = armar_inputs(a.id, a.cuando, a.video, caption, ahora, a.titulo, cuerpo_x)
    except ValueError as e:
        print(f"{ts()} BUFFER_FALLA {a.id} todas {e}", flush=True)
        alertar(f"⚠️ Franquicia 400: no se pudo armar el Short/X de {a.id} ({e}).", ahora)
        return 1
    if a.seco:
        for red, entrada in inputs.items():
            print(f"{ts()} BUFFER_SECO {a.id} {red} " + json.dumps(entrada, ensure_ascii=False), flush=True)
        return 0

    clave = leer_env(ENV_BUFFER).get("BUFFER_API_KEY")
    if not clave:
        print(f"{ts()} BUFFER_FALLA {a.id} todas falta BUFFER_API_KEY en {ENV_BUFFER}", flush=True)
        alertar(f"⚠️ Franquicia 400: falta la clave de Buffer; no salen el Short ni X de {a.id}.", ahora)
        return 1

    estado = cargar_estado()
    fallas = []
    for red in [r.strip() for r in a.redes.split(",") if r.strip()]:
        k = f"{a.id}|{red}"
        if (estado.get(k) or {}).get("post_id"):
            print(f"{ts()} BUFFER_YA {a.id} {red} {estado[k]['post_id']}", flush=True)
            continue
        post, error = crear_post(clave, inputs[red])
        if post:
            estado[k] = {"post_id": post["id"], "status": post.get("status"), "dueAt": post.get("dueAt"), "creado": ts()}
            guardar_estado(estado)
            print(f"{ts()} BUFFER_OK {a.id} {red} {post['id']} status={post.get('status')} dueAt={post.get('dueAt')}", flush=True)
        else:
            fallas.append(red)
            print(f"{ts()} BUFFER_FALLA {a.id} {red} {error}", flush=True)
    if fallas:
        nombres = {"youtube": "YouTube", "x": "X"}
        alertar("⚠️ Franquicia 400: Buffer no aceptó %s de %s. Revisá el log del Reel." % (
            " y ".join(nombres.get(r, r) for r in fallas), a.id), ahora)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
