#!/usr/bin/env python3
"""Lote semanal de historias con sticker (19/11, opción 1 de Alejandro): lo arma el agente cada lunes.

Corre dentro de la imagen franquicia400-reel (hacer_reel_vm.sh --lote [--desde AAAA-MM-DD] [--dias 5]).
Por cada día elige dos productos publicables hoy (precio del día de los dos lados, envío gratis, USD 100-400):
- historia12: sticker «Ver precios de hoy» a la ficha (con UTM), 12:30.
- historia20: sticker «Ofertas en Telegram» a https://t.me/franquicia400, 20:00.
Los diez productos de la semana son distintos entre sí, no repiten las últimas 10 historias y se anotan en
productos-del-dia.json (registro_dia): el Reel de las 19:00 de cada día no los usa.

Salida en out/lote-AAAA-MM-DD/: por historia un video (para Facebook, con enlace) y el último cuadro como foto
(para Instagram, donde va el sticker de enlace), más lote.json con fecha, hora, producto, archivos y enlace.
La programación en Business Suite la hace el agente en el Chrome de la VM (skill redes-proyectos) y verifica en la
vista previa que cada una tenga el sticker antes de confirmar; si no lo tiene, no la programa.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import shutil
import sys

import hacer_reel as r
import registro_dia

HISTORIAL = r.BASE / 'historial-historias.json'
SIN_REPETIR = 10
TELEGRAM = 'https://t.me/franquicia400'


def fechas_lote(desde: str, dias: int) -> list[str]:
    inicio = date.fromisoformat(desde)
    return [(inicio + timedelta(days=i)).isoformat() for i in range(dias)]


def enlace_ficha(slug: str, fecha: str, red: str) -> str:
    dd_mm = date.fromisoformat(fecha).strftime('%d-%m')
    return (f'https://ofertas.knunet.com/productos/{slug}/?utm_source={red}&utm_medium=social'
            f'&utm_campaign=historia&utm_content=historia-{dd_mm}')


def elegir_lote(productos, fechas, historial, reservado_por_fecha, foto_ok=None):
    """{fecha: {'historia12': producto, 'historia20': producto}} con productos distintos en toda la semana."""
    foto_ok = foto_ok or r.foto_usable
    recientes = {h['slug'] for h in historial[-SIN_REPETIR:]}
    candidatos = [p for p in productos if p.get('gana') and p['slug'] not in recientes
                  and (r.REPO / 'public/products' / (p['slug'] + '.webp')).is_file()]
    # Más ahorro primero, del lado que gane (igual denominador que el Reel y la historia diaria).
    candidatos.sort(key=lambda p: abs(p['ml'] - p['az']) / max(p['ml'], p['az']), reverse=True)
    usados_semana: set[str] = set()
    lote = {}
    for fecha in fechas:
        ocupados = usados_semana | reservado_por_fecha.get(fecha, set())
        dia = {}
        for turno in ('historia12', 'historia20'):
            p = next((c for c in candidatos if c['slug'] not in ocupados and foto_ok(c['slug'])), None)
            if p is None:
                raise ValueError(f'No alcanzan los productos con foto para {fecha} {turno} '
                                 f'(candidatos: {len(candidatos)}, ya usados en el lote: {len(usados_semana)}).')
            dia[turno] = p
            ocupados.add(p['slug'])
            usados_semana.add(p['slug'])
        lote[fecha] = dia
    return lote


def render(p, destino, base):
    npx = shutil.which('npx.cmd') or shutil.which('npx')
    ffmpeg = shutil.which('ffmpeg')
    if not npx or not ffmpeg:
        raise ValueError('Falta npx o ffmpeg en la imagen.')
    raw = destino / f'{base}-raw.mp4'
    video = destino / f'{base}.mp4'
    foto = destino / f'{base}.png'
    props = json.dumps({'img': p['slug'] + '.png', 'nombre': r.nombre_corto(p)}, ensure_ascii=False)
    r.ejecutar([npx, 'remotion', 'render', 'Historia', raw, f'--props={props}'], timeout=1800)
    r.ejecutar([ffmpeg, '-y', '-i', raw, '-c:v', 'libx264', '-crf', '24', '-preset', 'medium', '-pix_fmt', 'yuv420p',
                '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', video],
               timeout=600)
    r.ejecutar([ffmpeg, '-y', '-sseof', '-0.2', '-i', video, '-frames:v', '1', '-update', '1', foto], timeout=120)
    raw.unlink(missing_ok=True)
    return video, foto


def main(argv=None):
    ap = argparse.ArgumentParser()
    hoy = datetime.now(r.ART).date()
    ap.add_argument('--desde', default=hoy.isoformat(), help='primer día del lote (por defecto hoy)')
    ap.add_argument('--dias', type=int, default=5, help='cantidad de días (por defecto 5: lunes a viernes)')
    args = ap.parse_args(argv)
    hoy_iso = hoy.isoformat()
    ml, amazon, catalogo = r.datos_hoy(hoy_iso)  # corta si los precios no son de hoy
    historial = r.leer(HISTORIAL) if HISTORIAL.exists() else []
    mep, eur_usd = r.cotizaciones(any(a.get('currency') == 'EUR' and a.get('checked') == hoy_iso
                                      for a in amazon.values()))
    productos = r.comparables(ml, amazon, catalogo, hoy_iso, mep, eur_usd)
    fechas = fechas_lote(args.desde, args.dias)
    # Lo que ya tomaron otros turnos de esos días (p. ej. el Reel de hoy si el lote se arma tarde).
    # Rearmar el lote pisa sus propias historias; sólo hay que respetar el Reel ya hecho de esos días.
    registro = registro_dia.leer()
    reservado = {f: set(registro.get(f, {}).get('reel19', [])) for f in fechas}
    lote = elegir_lote(productos, fechas, historial, reservado)
    destino = r.BASE / 'out' / f'lote-{args.desde}'
    destino.mkdir(parents=True, exist_ok=True)
    filas = []
    for fecha, dia in lote.items():
        for turno, p in dia.items():
            base = f'{fecha}-{turno}'
            video, foto = render(p, destino, base)
            filas.append(dict(
                fecha=fecha, turno=turno, hora='12:30' if turno == 'historia12' else '20:00', slug=p['slug'],
                nombre=r.nombre_corto(p), video=video.name, foto=foto.name,
                sticker='Ver precios de hoy' if turno == 'historia12' else 'Ofertas en Telegram',
                enlace_instagram=enlace_ficha(p['slug'], fecha, 'instagram') if turno == 'historia12' else TELEGRAM,
                enlace_facebook=enlace_ficha(p['slug'], fecha, 'facebook') if turno == 'historia12' else TELEGRAM))
            print(f'LOTE_HISTORIA {fecha} {turno} {p["slug"]}', flush=True)
        # Se reserva recién con los dos videos del día hechos.
        registro_dia.reservar(fecha, 'historia12', [dia['historia12']['slug']])
        registro_dia.reservar(fecha, 'historia20', [dia['historia20']['slug']])
        historial.extend(dict(fecha=fecha, slug=p['slug'], video=f'lote-{args.desde}/{fecha}-{t}.mp4')
                         for t, p in dia.items())
        r.escribir(HISTORIAL, historial)
    r.escribir(destino / 'lote.json', filas)
    print(f'LOTE_LISTO {destino} historias={len(filas)}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError) as exc:
        print(f'LOTE_FALLA {exc}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # subprocess.CalledProcessError y otros
        print(f'LOTE_FALLA {type(exc).__name__}: {exc}', file=sys.stderr)
        sys.exit(1)
