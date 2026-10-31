#!/usr/bin/env python3
"""Baja la foto oficial del catálogo de Mercado Libre para los productos sin imagen.

Regla del sitio: producto sin foto no se publica. Este script deja la foto en
public/products/<slug>.webp y completa `image` e `imageSource` en data/catalog.json.

Uso (desde Windows, Git Bash):
  python tools/fetch_photos.py            # pide las URLs a la Pi4 (API de ML) y baja las fotos
  python tools/fetch_photos.py --urls x.json   # usa un JSON {slug: url} ya armado
"""
import argparse
import io
import json
from pathlib import Path
import subprocess
import sys

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "data" / "catalog.json"
OUT_DIR = ROOT / "public" / "products"
MAX_SIDE = 900
ALLOWED_HOSTS = ("http2.mlstatic.com",)

# Corre adentro del worker de la Pi4 (tiene las claves de ML): imprime {slug: url}.
PI_SNIPPET = r'''
import json, ml_prices as m
c = json.load(open("/app/data/catalog.json", encoding="utf-8"))
out = {}
for p in c:
    cid = (p.get("ml") or {}).get("catalogId")
    if p.get("image") or not cid:
        continue
    try:
        pics = m.get_json(f"/products/{cid}").get("pictures") or []
        out[p["slug"]] = pics[0].get("url") if pics else None
    except Exception:
        out[p["slug"]] = None
    m.pause()
print(json.dumps(out))
'''


def urls_from_pi():
    res = subprocess.run(
        ["ssh", "pi4", "docker exec -i franquicia400-weboffers-worker-1 python -"],
        input=PI_SNIPPET, capture_output=True, text=True, timeout=600, check=True)
    return json.loads(res.stdout.strip().splitlines()[-1])


def to_webp(data):
    img = Image.open(io.BytesIO(data))
    img.load()
    img = img.convert("RGBA") if img.mode in ("P", "LA", "RGBA") else img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=82, method=6)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--urls", help="JSON {slug: url}; si falta, se piden a la Pi4")
    args = ap.parse_args()
    urls = json.loads(Path(args.urls).read_text(encoding="utf-8")) if args.urls else urls_from_pi()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_slug = {p["slug"]: p for p in catalog}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ok, fail = 0, []
    for slug, url in urls.items():
        p = by_slug.get(slug)
        if not p or p.get("image"):
            continue
        if not url or not url.startswith("https://") or url.split("/")[2] not in ALLOWED_HOSTS:
            fail.append(slug)
            continue
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            (OUT_DIR / f"{slug}.webp").write_bytes(to_webp(r.content))
        except (requests.RequestException, OSError) as exc:
            print(f"  {slug}: no se pudo ({type(exc).__name__})", flush=True)
            fail.append(slug)
            continue
        p["image"] = f"/products/{slug}.webp"
        p["imageSource"] = url
        ok += 1
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Fotos nuevas: {ok}. Sin foto (no se publican): {len(fail)} {fail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
