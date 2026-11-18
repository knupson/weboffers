#!/usr/bin/env python3
"""Historia diaria de Franquicia 400 (17/11, opción A de Alejandro): video 9:16 de la composición Historia con el
link escrito en pantalla, para publicar por la API de Meta (que no pone sticker de enlace).

Corre dentro de la imagen franquicia400-reel (hacer_reel_vm.sh --historia). Reglas:
- Sólo productos publicables hoy: precio del día de los dos lados, envío gratis confirmado y USD 100-400
  (mismas funciones que el Reel: datos_hoy + comparables). Si los relevamientos no son de hoy, no se genera nada.
- No repite un producto de las últimas 10 historias ni uno de los dos del Reel de ayer/hoy.
- Foto con fondo transparente (recorte.py); la que no se puede recortar se saltea.
Salida: out/historia-AAAA-MM-DD-final.mp4 y out/historia-AAAA-MM-DD.json ({slug, nombre, url_producto}).
"""
from __future__ import annotations

from datetime import datetime
import json
import shutil
import sys

import hacer_reel as r

HISTORIAL = r.BASE / 'historial-historias.json'
SIN_REPETIR = 10


def elegir_historia(productos, historial, historial_reel, foto_ok=None):
    foto_ok = foto_ok or r.foto_usable
    usados = {h['slug'] for h in historial[-SIN_REPETIR:]}
    usados |= {slug for reel in historial_reel[-2:] for slug in reel.get('productos', [])}
    candidatos = [p for p in productos if p.get('gana') and p['slug'] not in usados
                  and (r.REPO / 'public/products' / (p['slug'] + '.webp')).is_file()]
    # Más ahorro primero, del lado que gane (igual denominador que el Reel).
    candidatos.sort(key=lambda p: abs(p['ml'] - p['az']) / max(p['ml'], p['az']), reverse=True)
    elegido = next((p for p in candidatos if foto_ok(p['slug'])), None)
    if not elegido:
        raise ValueError('No hay producto publicable hoy con foto recortable fuera de las últimas historias.')
    return elegido


def main():
    hoy = datetime.now(r.ART).date().isoformat()
    ml, amazon, catalogo = r.datos_hoy(hoy)  # corta si los precios no son de hoy
    historial = r.leer(HISTORIAL) if HISTORIAL.exists() else []
    if any(h.get('fecha') == hoy for h in historial):
        print(f'HISTORIA_YA_HECHA {hoy}', flush=True)
        return
    historial_reel = r.leer(r.BASE / 'historial.json') if (r.BASE / 'historial.json').exists() else []
    mep, eur_usd = r.cotizaciones(any(a.get('currency') == 'EUR' and a.get('checked') == hoy for a in amazon.values()))
    productos = r.comparables(ml, amazon, catalogo, hoy, mep, eur_usd)
    p = elegir_historia(productos, historial, historial_reel)
    npx = shutil.which('npx.cmd') or shutil.which('npx')
    ffmpeg = shutil.which('ffmpeg')
    if not npx or not ffmpeg:
        raise ValueError('Falta npx o ffmpeg en la imagen.')
    out = r.BASE / 'out'
    out.mkdir(exist_ok=True)
    raw = out / f'historia-{hoy}.mp4'
    final = out / f'historia-{hoy}-final.mp4'
    props = json.dumps({'img': p['slug'] + '.png', 'nombre': r.nombre_corto(p)}, ensure_ascii=False)
    r.ejecutar([npx, 'remotion', 'render', 'Historia', raw, f'--props={props}'], timeout=1800)
    r.ejecutar([ffmpeg, '-y', '-i', raw, '-c:v', 'libx264', '-crf', '24', '-preset', 'medium', '-pix_fmt', 'yuv420p',
                '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', final],
               timeout=600)
    datos = dict(slug=p['slug'], nombre=r.nombre_corto(p),
                 url_producto=f"https://ofertas.knunet.com/productos/{p['slug']}/")
    r.escribir(out / f'historia-{hoy}.json', datos)
    historial.append(dict(fecha=hoy, slug=p['slug'], video=final.name))
    r.escribir(HISTORIAL, historial)  # sólo se consume el producto si terminó el render
    print(f'HISTORIA_LISTA {final} slug={p["slug"]}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # subprocess.CalledProcessError y otros
        print(f'Error: {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
