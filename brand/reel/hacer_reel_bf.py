"""Reel especial de Black Friday (27/11): los productos publicados hoy con mayor ahorro real frente a Mercado Libre.

Uso (en la VM, dentro de la imagen franquicia400-reel): python3 hacer_reel_bf.py --productos slug1,slug2,slug3,slug4
Cada producto tiene que estar entre los comparables de hoy (precios del día de los dos lados, envío gratis a
Argentina confirmado, USD 100-400) y ganar en Amazon. Reutiliza el cálculo, la voz y los guiones de hacer_reel.py.
Salidas: out/blackfriday-AAAA-MM-DD-final.mp4, .txt (Instagram) y -fb.txt (Facebook, link con UTM).
No toca historial.json; anota los productos en el registro del día (clave reelbf) para que el Reel de las 19 no los repita.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import math
import shutil
import subprocess
import sys

import hacer_reel as h
import recorte
import registro_dia


def pct(p) -> int:
    # Hacia abajo: nunca se muestra más ahorro del que hay.
    return math.floor(100 * (p['ml'] - p['az']) / p['ml'])


def usd(p) -> str:
    return f"USD {p['usd']:.2f}".replace('.', ',')


def ahorro(p) -> str:
    # Mismo redondeo que el «Ahorrás» de la ficha (roundArs10k).
    return h.ars(h.redondear((p['ml'] - p['az']) / 10000) * 10000)


def elegir(productos, slugs):
    por_slug = {p['slug']: p for p in productos}
    elegidos = []
    for slug in slugs:
        p = por_slug.get(slug)
        if p is None:
            raise ValueError(f'«{slug}» no está entre los comparables de hoy: no se usa.')
        if p['gana'] != 'amazon' or p['az'] >= p['ml']:
            raise ValueError(f'«{slug}» no gana en Amazon hoy.')
        elegidos.append(p)
    return sorted(elegidos, key=pct, reverse=True)


def guiones(ps, cantidad):
    textos = [f'Black Friday de verdad. Estos productos salen hasta un {h.palabras(pct(ps[0]))} por ciento menos '
              'traídos de Amazon que en Mercado Libre.']
    for p in ps:
        textos.append(f"{h.nombre_corto(p)}. {h.hablado(p['ml'])} en Mercado Libre. Traído de Amazon, con envío e "
                      f"impuestos, unos {h.hablado(p['az'])}. {h.palabras(pct(p)).capitalize()} por ciento menos.")
    textos.append(f'Comparamos {h.palabras(cantidad)} productos con los precios de hoy. Link en la bio.')
    return textos


def caption(ps, cantidad, fecha, red):
    lineas = '\n'.join(f"{h.nombre_corto(p)}: ${h.ars(p['ml'])} en Mercado Libre vs ~${h.ars(p['az'])} traído de "
                       f"Amazon ({usd(p)}). {pct(p)}% menos." for p in ps)
    if red == 'ig':
        link, tags = 'link en la bio.', '#blackfriday #amazonargentina #mercadolibre #comprasalexterior #franquicia400'
    else:
        link = ('https://ofertas.knunet.com/?utm_source=facebook&utm_medium=social&utm_campaign=reel-blackfriday'
                f"&utm_content=reel-bf-{fecha[:5].replace('/', '-')}")
        tags = '#blackfriday #amazonargentina #franquicia400'
    return f'''Black Friday con ahorro real: el precio de hoy en Mercado Libre contra lo que sale traerlo de Amazon, con envío e impuestos.

{lineas}

Comparamos {cantidad} productos con los precios de hoy: {link}
La mejor oferta del día, todos los días a las 12 y a las 20, en Telegram: t.me/franquicia400

Precios del {fecha}. Amazon: estimado puesto en casa, con envío e impuestos (franquicia de USD 400). El sitio usa links de afiliado.

Voz: Piper «es_AR-daniela-high» (CC BY-SA 4.0). Música: «Hip Hop 02», Mixkit.

{tags}
'''


def main(slugs):
    hoy = datetime.now(h.ART).date().isoformat()
    ml, amazon, catalogo = h.datos_hoy(hoy)  # corta si los precios no son de hoy
    mep, eur_usd = h.cotizaciones(any(a.get('currency') == 'EUR' and a.get('checked') == hoy for a in amazon.values()))
    productos = h.comparables(ml, amazon, catalogo, hoy, mep, eur_usd)
    ps = elegir(productos, slugs)
    for p in ps:
        print(f"BF_PRODUCTO {p['slug']} ml={p['ml']} az={p['az']} usd={p['usd']:.2f} pct={pct(p)}", flush=True)
        recorte.asegurar_transparente(h.REPO / 'public/products' / (p['slug'] + '.webp'), h.BASE / 'public' / (p['slug'] + '.png'))
    npx = shutil.which('npx.cmd') or shutil.which('npx')
    ffmpeg = shutil.which('ffmpeg')
    if not npx or not ffmpeg or not h.PIPER.is_file() or not h.MODELO.is_file():
        raise ValueError('Falta npx, ffmpeg, Piper o el modelo de voz.')
    textos = guiones(ps, len(productos))
    duraciones = h.sintetizar(textos)
    props = copy.deepcopy(h.leer(h.BASE / 'src/duelo.json'))
    props.update(voz=duraciones, audio=[f'd{i}.wav' for i in range(6)],
                 subs=[h.subtitulos(t, d) for t, d in zip(textos, duraciones)],
                 cantidad=len(productos), hookImage=ps[0]['slug'] + '.png', hookSize=300)
    props['duelos'] = []
    for i, p in enumerate(ps):
        dur = duraciones[i + 1]
        props['duelos'].append(dict(img=p['slug'] + '.png', nombre=h.nombre_corto(p), ml=p['ml'], az=p['az'],
                                    gana='amazon', mlAt=[dur * .16, dur * .36], azAt=[dur * .50, dur * .70],
                                    ganaAt=dur * .80, sello=f'-{pct(p)}%',
                                    nota=f"Ahorrás ~$ {ahorro(p)}\nEn Amazon: {usd(p)}"))
    fecha = datetime.fromisoformat(hoy).strftime('%d/%m/%Y')
    t = props['textos']
    t['marca'] = 'Franquicia 400 · Black Friday'
    t['gancho'] = ['BLACK', 'FRIDAY', f'-{pct(ps[0])}%']
    t['ganchoSub'] = 'Ahorro real frente a Mercado Libre'
    t['cierre'][4] = 'LINK EN LA BIO'
    t['pie'] = f'Precios del {fecha} · Amazon: estimado con envío e impuestos'
    h.escribir(h.BASE / 'src/blackfriday.json', props)
    out = h.BASE / 'out'
    out.mkdir(exist_ok=True)
    raw, final = out / f'blackfriday-{hoy}.mp4', out / f'blackfriday-{hoy}-final.mp4'
    h.ejecutar([npx, 'remotion', 'render', 'BlackFriday', raw], timeout=3600)
    h.ejecutar([ffmpeg, '-y', '-i', raw, '-c:v', 'copy', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',
                '-c:a', 'aac', '-b:a', '192k', final], timeout=600)
    (out / f'blackfriday-{hoy}.txt').write_text(caption(ps, len(productos), fecha, 'ig'), encoding='utf-8')
    (out / f'blackfriday-{hoy}-fb.txt').write_text(caption(ps, len(productos), fecha, 'fb'), encoding='utf-8')
    registro_dia.reservar(hoy, 'reelbf', [p['slug'] for p in ps])
    print(f'BF_LISTO {final}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--productos', required=True, help='3 o 4 slugs separados por coma.')
    args = parser.parse_args()
    slugs = [s.strip() for s in args.productos.split(',') if s.strip()]
    if len(slugs) != 4:
        parser.error('La plantilla BlackFriday lleva 4 productos.')
    try:
        main(slugs)
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
