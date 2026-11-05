#!/usr/bin/env python3
"""Publicador de Instagram + Facebook de FRANQUICIA 400 (copia adaptada del de Blackseam) por la Meta Graph API (v21.0).

Corre por cron en el docker (cada 5 min): lee cola_meta.json de este
directorio, publica lo que toca (cuando <= ahora, hasta 3 intentos por
destino) y deja el estado en estado_meta.json. Las piezas más de 6 h pasadas
sin publicar quedan "vencido" y avisam por WhatsApp (WAHA) una sola vez.
Logs sin tokens ni URLs con access_token: META_OK / META_FAIL / META_NADA.
Vive en docker:/home/claude/franquicia400-meta/ (.env con META_*; WAHA se lee del .env de Blackseam).
"""
import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

try:
    import fcntl
except ImportError:
    fcntl = None  # Windows (tests offline): sin lock

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://graph.facebook.com/v21.0"
POLL_INTERVAL = 10  # s entre chequeos de status_code
POLL_MAX = 360      # s máximo de espera (6 min)
MAX_INTENTOS = 3
VENCIDO_TRAS = datetime.timedelta(hours=6)

ENV = {}


class MetaError(Exception):
    """Error saneado: sólo código HTTP + código/mensaje de Graph, nunca tokens ni URLs."""


WAHA_ENV = "/opt/docker/blackseam/soporte/.env"  # mismo WAHA que el resto de los avisos


def _leer(path):
    with open(path, encoding="utf-8") as f:
        return dict(l.strip().split("=", 1) for l in f if "=" in l and not l.startswith("#"))


def cargar_env(here):
    env = _leer(os.path.join(here, ".env"))
    if "WAHA_URL" not in env and os.path.exists(WAHA_ENV):
        env.update({k: v for k, v in _leer(WAHA_ENV).items() if k.startswith(("WAHA_", "WA_"))})
    return env


def clave(entry_id, destino):
    return entry_id + "|" + destino


def _sanear(e):
    code = getattr(e, "code", None)
    if code is None:
        return MetaError(type(e).__name__)
    try:
        body = e.read().decode("utf-8", "replace")
        err = json.loads(body).get("error", {})
        return MetaError("http %s graph %s: %s" % (code, err.get("code", "?"), str(err.get("message", ""))[:200]))
    except Exception:
        return MetaError("http %s" % code)


def graph_get(path, params, token, timeout=30):
    params = dict(params)
    params["access_token"] = token
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _sanear(e)
    except urllib.error.URLError as e:
        raise MetaError(type(e).__name__)


def graph_post(path, data, token):
    data = dict(data)
    data["access_token"] = token
    req = urllib.request.Request(BASE + path, data=urllib.parse.urlencode(data).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise _sanear(e)
    except urllib.error.URLError as e:
        raise MetaError(type(e).__name__)


def esperar_finished(contenedor, token):
    fin = time.time() + POLL_MAX
    while True:
        r = graph_get("/" + contenedor, {"fields": "status_code"}, token)
        estado = r.get("status_code")
        if estado == "FINISHED":
            return
        if estado == "ERROR":
            raise MetaError("status_code=ERROR en contenedor %s" % contenedor)
        if time.time() >= fin:
            raise MetaError("timeout esperando FINISHED en contenedor %s" % contenedor)
        time.sleep(POLL_INTERVAL)


def publicar_ig(entry, token):
    ig = ENV["META_IG_USER_ID"]
    media = entry["media"]
    if entry["tipo"] == "reel":
        r = graph_post("/%s/media" % ig, {"media_type": "REELS", "video_url": media[0], "caption": entry["texto_ig"], "share_to_feed": "true"}, token)
        contenedor = r["id"]
    else:
        hijos = []
        for url in media:
            r = graph_post("/%s/media" % ig, {"image_url": url, "is_carousel_item": "true"}, token)
            hijos.append(r["id"])
        r = graph_post("/%s/media" % ig, {"media_type": "CAROUSEL", "children": ",".join(hijos), "caption": entry["texto_ig"]}, token)
        contenedor = r["id"]
    esperar_finished(contenedor, token)
    r = graph_post("/%s/media_publish" % ig, {"creation_id": contenedor}, token)
    return r["id"]


def esperar_fb_publicado(video_id, token):
    fin = time.monotonic() + POLL_MAX
    estado = {}
    while time.monotonic() < fin:
        try:
            estado = graph_get("/" + video_id, {"fields": "status"}, token,
                               timeout=min(30, max(0.001, fin - time.monotonic()))).get("status") or {}
        except MetaError as exc:
            raise MetaError("Reel %s: status=%s; %s" % (video_id, json.dumps(estado), exc)) from exc
        publicacion = estado.get("publishing_phase") or {}
        fases = [estado.get(k) or {} for k in ("uploading_phase", "processing_phase", "publishing_phase")]
        if estado.get("video_status") in ("error", "expired", "upload_failed") or any(
            f.get("status") == "error" or f.get("publish_status") == "error" for f in fases
        ):
            raise MetaError("Reel %s falló: status=%s" % (video_id, json.dumps(estado)))
        if publicacion.get("publish_status") == "published":
            return
        time.sleep(min(POLL_INTERVAL, max(0, fin - time.monotonic())))
    raise MetaError("timeout Reel %s: status=%s" % (video_id, json.dumps(estado)))


def publicar_fb_reel(pagina, video_url, descripcion, token):
    """Reel de página con la Reels Publishing API (start → rupload con file_url → finish), 05/11.

    Antes iba por /videos y salía como video común: no aparecía en video_reels (control reel19).
    Doc: developers.facebook.com/documentation/video-api/guides/reels-publishing
    """
    r = graph_post("/%s/video_reels" % pagina, {"upload_phase": "start"}, token)
    video_id = r["video_id"]
    req = urllib.request.Request("https://rupload.facebook.com/video-upload/v21.0/%s" % video_id, data=b"", method="POST")
    req.add_header("Authorization", "OAuth " + token)
    req.add_header("file_url", video_url)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            ok = json.loads(resp.read().decode("utf-8")).get("success")
    except urllib.error.HTTPError as e:
        raise _sanear(e)
    except urllib.error.URLError as e:
        raise MetaError(type(e).__name__)
    if not ok:
        raise MetaError("rupload sin success para el reel %s" % video_id)
    graph_post("/%s/video_reels" % pagina, {"upload_phase": "finish", "video_id": video_id,
                                            "video_state": "PUBLISHED", "description": descripcion}, token)
    esperar_fb_publicado(video_id, token)
    return video_id


def publicar_fb(entry, token):
    pagina = ENV["META_PAGE_ID"]
    media = entry["media"]
    if entry["tipo"] == "reel":
        return publicar_fb_reel(pagina, media[0], entry["texto_fb"], token)
    ids = []
    for url in media:
        r = graph_post("/%s/photos" % pagina, {"url": url, "published": "false"}, token)
        ids.append(r["id"])
    data = {"message": entry["texto_fb"]}
    for i, pid in enumerate(ids):
        data["attached_media[%d]" % i] = json.dumps({"media_fbid": pid})
    r = graph_post("/%s/feed" % pagina, data, token)
    return r["id"]


def publicar(entry, destino, token):
    if destino == "ig":
        return publicar_ig(entry, token)
    if destino == "fb":
        return publicar_fb(entry, token)
    raise MetaError("destino desconocido: %s" % destino)


def alertar(texto):
    # Mismo WAHA que recordatorio_redes.py; un aviso fallido nunca corta el lote.
    try:
        payload = {"session": ENV.get("WAHA_SESSION") or "default", "chatId": ENV["WA_NOTIFY_CHAT_ID"], "text": texto}
        req = urllib.request.Request(ENV["WAHA_URL"].rstrip("/") + "/api/sendText", data=json.dumps(payload).encode(), method="POST")
        req.add_header("X-Api-Key", ENV.get("WAHA_API_KEY", ""))
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return True
    except Exception:
        return False


def alerta_fallo(entry_id, destino, motivo):
    red = "Instagram" if destino == "ig" else "Facebook"
    return alertar("⚠️ Franquicia 400: no se pudo publicar %s en %s (%s). Lo reviso en el próximo lote." % (entry_id, red, motivo[:80]))


def cargar_json(path, defecto):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return defecto


def guardar_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main(argv=None, here=None):
    global ENV
    here = here or HERE
    ap = argparse.ArgumentParser(description="Publicador de Meta (IG+FB) de FRANQUICIA 400")
    ap.add_argument("--prueba", action="store_true", help="valida el token e imprime página, usuario de IG y permisos; no publica")
    ap.add_argument("--seco", action="store_true", help="muestra lo que se publicaría ahora, sin publicar")
    ap.add_argument("--ahora", metavar="ID", help="publica esa pieza ahora, sin importar cuándo toca")
    args = ap.parse_args(argv)

    ENV = cargar_env(here)

    lock = open(os.path.join(here, "meta_publicar.lock"), "w")
    if fcntl is not None:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # ya hay otro run en curso: salir en silencio

    cola_path = os.path.join(here, "cola_meta.json")
    estado_path = os.path.join(here, "estado_meta.json")
    cola = cargar_json(cola_path, [])
    estado = cargar_json(estado_path, {})

    sys_token = ENV["META_SYSTEM_TOKEN"]
    tokens = {}

    def token_pagina():
        # Sólo se pide cuando hay algo para publicar: el cron corre cada 5 min.
        if "pagina" not in tokens:
            tokens["pagina"] = graph_get("/" + ENV["META_PAGE_ID"], {"fields": "access_token"}, sys_token)["access_token"]
        return tokens["pagina"]

    if args.prueba:
        page_token = token_pagina()
        pagina = graph_get("/" + ENV["META_PAGE_ID"], {"fields": "name"}, page_token)
        ig = graph_get("/" + ENV["META_IG_USER_ID"], {"fields": "username"}, page_token)
        perms = graph_get("/me/permissions", {}, sys_token)
        print("META_PRUEBA pagina=%s ig=@%s permisos=%s" % (
            pagina.get("name", "?"),
            ig.get("username", "?"),
            ",".join(p.get("permission", "?") for p in perms.get("data", []))))
        return 0

    ahora = datetime.datetime.now(datetime.timezone.utc)
    toco_algo = False
    for entry in cola:
        cuando = datetime.datetime.fromisoformat(entry["cuando"])
        if cuando.tzinfo is None:
            cuando = cuando.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=-3)))
        for destino in entry.get("destinos", []):
            k = clave(entry["id"], destino)
            st = estado.get(k) or {}
            if st.get("estado") == "ok":
                continue
            if cuando + VENCIDO_TRAS <= ahora:
                if st.get("estado") != "vencido":
                    st = {"estado": "vencido", "intentos": st.get("intentos", 0), "ultimo_error": st.get("ultimo_error", ""), "alertado": False}
                    estado[k] = st
                if not st.get("alertado"):
                    st["alertado"] = alerta_fallo(entry["id"], destino, "vencida")
                    estado[k] = st
                continue
            if cuando > ahora and args.ahora != entry["id"]:
                continue
            intentos = st.get("intentos", 0)
            if st.get("estado") == "vencido" or intentos >= MAX_INTENTOS:
                if not st.get("alertado"):
                    st["alertado"] = alerta_fallo(entry["id"], destino, st.get("ultimo_error", "sin confirmar"))
                continue
            if args.seco:
                print("META_SECO %s %s %s %d media" % (entry["id"], destino, entry["tipo"], len(entry["media"])))
                toco_algo = True
                continue
            toco_algo = True
            try:
                media_id = publicar(entry, destino, token_pagina())
                estado[k] = {"estado": "ok", "media_id": media_id}
                print("META_OK %s %s %s" % (entry["id"], destino, media_id))
            except Exception as e:  # MetaError u otra (respuesta sin "id"): cuenta como intento
                if not isinstance(e, MetaError):
                    e = MetaError(type(e).__name__)
                intentos += 1
                estado[k] = {"estado": "fallo", "intentos": intentos, "ultimo_error": str(e)[:300]}
                print("META_FAIL %s %s %s" % (entry["id"], destino, e))
                if intentos >= MAX_INTENTOS and not st.get("alertado"):
                    estado[k]["alertado"] = alerta_fallo(entry["id"], destino, str(e))
            # Guardar después de cada destino: si algo corta la corrida, lo ya publicado no se repite.
            guardar_json(estado_path, estado)
    guardar_json(estado_path, estado)
    if not toco_algo:
        print("META_NADA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
