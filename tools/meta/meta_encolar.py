#!/usr/bin/env python3
"""Encola una pieza de redes en la cola de Meta del docker (cola_meta.json).

Corre en la PC Windows bajo Git Bash (python3). Copia el media con scp a
docker:/opt/docker/blackseam/lista/descargas/redes/<ID>/ (servido por
https://lista.blackseam.knunet.com), arma las URLs públicas y hace upsert de
la entrada (por id) en /home/claude/franquicia400-meta/cola_meta.json vía
`ssh docker python3 -` con el script en stdin. Nunca usa shell=True.

Ejemplos:
  python3 tools/redes/meta_encolar.py --id pieza-2026-11-10 \\
      --cuando "2026-11-10 19:00" --tipo reel \\
      --texto-ig ig.txt --texto-fb fb.txt clip.mp4
  python3 tools/redes/meta_encolar.py --listar
"""
import argparse
import datetime
import json
import os
import subprocess
import sys

HOST = "docker"
DIR_LISTA = "/opt/docker/blackseam/lista/descargas/redes"  # lo sirve la lista de Blackseam; sólo UN nivel de carpeta (05/11: con subcarpeta daba 404)
PREFIJO = "f400-"
DIR_SOPORTE = "/home/claude/franquicia400-meta"
URL_BASE = "https://lista.blackseam.knunet.com/descargas/redes"
TZ_AR = datetime.timezone(datetime.timedelta(hours=-3))

SCRIPT_UPSERT = r'''import json, os
entry = json.loads(__ENTRY__)
path = "/home/claude/franquicia400-meta/cola_meta.json"
cola = []
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        cola = json.load(f)
cola = [e for e in cola if e.get("id") != entry["id"]]
cola.append(entry)
cola.sort(key=lambda e: e.get("cuando", ""))
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(cola, f, ensure_ascii=False, indent=1)
os.replace(tmp, path)
print("ENCOLADO " + entry["id"] + " (piezas en cola: " + str(len(cola)) + ")")
'''

SCRIPT_LISTAR = r'''import json, os
base = "/home/claude/franquicia400-meta/"
cola = []
if os.path.exists(base + "cola_meta.json"):
    with open(base + "cola_meta.json", encoding="utf-8") as f:
        cola = json.load(f)
estado = {}
if os.path.exists(base + "estado_meta.json"):
    with open(base + "estado_meta.json", encoding="utf-8") as f:
        estado = json.load(f)
print("%-26s %-25s %-9s %-7s %s" % ("id", "cuando", "tipo", "destinos", "estado"))
for e in sorted(cola, key=lambda x: x.get("cuando", "")):
    est = []
    for d in e.get("destinos", []):
        s = estado.get(e["id"] + "|" + d) or {}
        est.append(d + ":" + s.get("estado", "pendiente"))
    print("%-26s %-25s %-9s %-7s %s" % (e["id"], e.get("cuando", ""), e.get("tipo", ""), ",".join(e.get("destinos", [])), " ".join(est)))
'''


def ssh_stdin(script):
    r = subprocess.run(["ssh", HOST, "python3", "-"], input=script.encode("utf-8"), capture_output=True)
    if r.returncode != 0:
        sys.exit("falló el script remoto: " + r.stderr.decode("utf-8", "replace"))
    return r.stdout.decode("utf-8", "replace")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Encola una pieza en la cola de Meta del docker")
    ap.add_argument("--listar", action="store_true", help="muestra la cola remota con su estado")
    ap.add_argument("--id", help="id único de la pieza, ej. pieza-2026-11-10")
    ap.add_argument("--cuando", help='horario de publicación, ej. "2026-11-10 19:00" (hora de Argentina, -03:00)')
    ap.add_argument("--tipo", choices=["reel", "carrusel"])
    ap.add_argument("--texto-ig", help="archivo con el caption de Instagram")
    ap.add_argument("--texto-fb", help="archivo con el texto de Facebook")
    ap.add_argument("--destinos", default="ig,fb", help="separados por coma: ig,fb (default: ig,fb)")
    ap.add_argument("media", nargs="*", help="archivos de media (mp4 o imágenes)")
    args = ap.parse_args(argv)

    if args.listar:
        print(ssh_stdin(SCRIPT_LISTAR), end="")
        return 0

    faltan = [n for n, v in [("--id", args.id), ("--cuando", args.cuando), ("--tipo", args.tipo),
                             ("--texto-ig", args.texto_ig), ("--texto-fb", args.texto_fb)] if not v]
    if faltan or not args.media:
        ap.error("faltan argumentos: %s" % ", ".join(faltan + (["MEDIA..."] if not args.media else [])))

    cuando = datetime.datetime.strptime(args.cuando, "%Y-%m-%d %H:%M").replace(tzinfo=TZ_AR).isoformat()
    destinos = [d.strip() for d in args.destinos.split(",") if d.strip()]
    with open(args.texto_ig, encoding="utf-8") as f:
        texto_ig = f.read()
    with open(args.texto_fb, encoding="utf-8") as f:
        texto_fb = f.read()

    remoto_dir = "%s/%s%s" % (DIR_LISTA, PREFIJO, args.id)
    subprocess.run(["ssh", HOST, "mkdir", "-p", remoto_dir], check=True, capture_output=True)

    urls = []
    for m in args.media:
        base = os.path.basename(m)
        subprocess.run(["scp", m, "%s:%s/%s" % (HOST, remoto_dir, base)], check=True, capture_output=True)
        urls.append("%s/%s%s/%s" % (URL_BASE, PREFIJO, args.id, base))
        # Meta descarga desde esta URL: si no responde 200, la pieza fallaría a la hora de publicar (05/11).
        try:
            import urllib.request
            code = urllib.request.urlopen(urllib.request.Request(urls[-1], method="HEAD"), timeout=30).status
        except Exception as e:
            code = getattr(e, "code", type(e).__name__)
        if code != 200:
            sys.exit("la URL pública no responde 200 (%s): %s — no se encola" % (code, urls[-1]))
        print("subido y verificado %s" % urls[-1])

    entry = {"id": args.id, "cuando": cuando, "tipo": args.tipo, "destinos": destinos,
             "media": urls, "texto_ig": texto_ig, "texto_fb": texto_fb}
    script = SCRIPT_UPSERT.replace("__ENTRY__", repr(json.dumps(entry, ensure_ascii=False)))
    print(ssh_stdin(script).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
