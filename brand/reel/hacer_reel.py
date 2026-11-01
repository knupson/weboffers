"""Generá el Duelo de hoy: python hacer_reel.py (Python 3.13, sin paquetes extra)."""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import wave

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
PIPER = Path(r'E:\Repositorios\Personal\_datos\blackseam\voces\descargas\piper\piper\piper.exe')
MODELO = Path(r'E:\Repositorios\Personal\_datos\blackseam\voces\descargas\modelos\es_AR-daniela-high.onnx')
ART = timezone(timedelta(hours=-3))


def leer(path: Path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def escribir(path: Path, datos):
    path.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def redondear(n: float) -> int:
    """Math.round de JS para montos positivos; Python round usa empate al par."""
    return math.floor(n + 0.5)


def estimate_from_amazon(usd: float, mep: float) -> int:
    """Port de src/lib/estimate.ts:estimateFromAmazon y calc/index.ts:calculate.

    calculate devuelve totalUsd redondeado a centavos ANTES del adicional del 4%.
    La franquicia sólo exime derechos/tasa: IVA sobre toda la base más envío.
    """
    fob = max(0, usd)
    shipping = 0 if usd >= 100 else 45
    excess = max(0, fob - 400)
    duty = excess * 0.35
    stat = excess * 0.03
    iva_base = fob + shipping + duty + stat
    total = redondear((iva_base + iva_base * 0.21) * 100) / 100
    return redondear((total + usd * 0.04) * mep)


def precio_sitio(usd: float, mep: float) -> int:
    """src/lib/data.ts:mergeAmazonPrices aplica roundArs10k al estimado."""
    return redondear(estimate_from_amazon(usd, mep) / 10000) * 10000


def pedir_json(url: str):
    # DolarAPI rechaza el User-Agent por defecto de urllib con HTTP 403.
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def cotizaciones(necesita_euro: bool) -> tuple[float, float | None]:
    """Misma fuente y validación que src/lib/dolar.ts, sin cotización de respaldo."""
    rates = pedir_json('https://dolarapi.com/v1/dolares')
    values = {}
    for casa in ('bolsa', 'tarjeta', 'oficial'):
        value = next((r.get('venta') for r in rates if r.get('casa') == casa), None)
        if not positivo(value):
            raise ValueError(f'DolarAPI no devolvió una cotización válida para {casa}.')
        values[casa] = value
    eur_usd = None
    if necesita_euro:
        eur = pedir_json('https://dolarapi.com/v1/cotizaciones/eur').get('venta')
        usd = pedir_json('https://dolarapi.com/v1/dolares/oficial').get('venta')
        if not positivo(eur) or not positivo(usd):
            raise ValueError('No se pudo obtener el cruce EUR/USD de DolarAPI.')
        eur_usd = eur / usd
    return values['bolsa'], eur_usd


def positivo(value) -> bool:
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def datos_hoy(hoy: str):
    ml = leer(REPO / 'data/ml-prices.json')
    amazon = leer(REPO / 'data/amazon-prices.json')
    catalogo = leer(REPO / 'data/catalog.json')
    viejos = [f'{nombre}: {data.get("date", "sin fecha")}' for nombre, data in
              [('ml-prices.json', ml), ('amazon-prices.json', amazon)] if data.get('date') != hoy]
    if viejos:
        raise ValueError(f'No se genera el Reel: hoy es {hoy} (Argentina), pero ' + '; '.join(viejos)
                         + '. Actualizá ambos relevamientos: nunca se usan precios viejos.')
    return ml['items'], amazon['items'], catalogo


def comparables(ml, amazon, catalogo, hoy, mep, eur_usd):
    productos = []
    for item in catalogo:
        slug = item['slug']
        m, a = ml.get(slug, {}), amazon.get(slug, {})
        if not item.get('verified') or not item.get('asin') or not item.get('image'):
            continue
        if m.get('checked') != hoy or a.get('checked') != hoy:
            continue
        if not positivo(m.get('price')) or not positivo(a.get('amount')):
            continue
        currency = a.get('currency')
        if currency not in ('USD', 'EUR') or (currency == 'EUR' and not eur_usd):
            continue
        shipping = a.get('shipsToAr', {})
        if shipping.get('checked') == hoy and shipping.get('ships') is False:
            continue
        free = (shipping.get('free') is True if shipping.get('checked') == hoy
                else item.get('shipsToAr', {}).get('freeShipping') is True)
        usd = a['amount'] * (eur_usd if currency == 'EUR' else 1)
        az = precio_sitio(usd, mep)
        if az <= 0:
            continue
        ratio = redondear((1 - az / m['price']) * 1e6) / 1e6
        # Igual que comparePrices: Amazon sólo gana con >=10% y envío gratis.
        winner = 'amazon' if ratio >= .10 and free else 'ml' if ratio < .10 else None
        productos.append(dict(item, ml=m['price'], az=az, usd=usd, free=free, gana=winner))
    return productos


def elegir(productos, historial):
    usados = {slug for reel in historial[-6:] for slug in reel['productos']}
    disponibles = [p for p in productos if p['slug'] not in usados
                   and (REPO / 'public/products' / (p['slug'] + '.webp')).is_file()]
    az = [p for p in disponibles if p['gana'] == 'amazon' and p['az'] < p['ml']]
    ml = [p for p in disponibles if p['gana'] == 'ml' and p['ml'] < p['az']]
    if not az or not ml:
        raise ValueError('Faltan dos productos nuevos con foto: uno con ahorro en Amazon y otro con ahorro en ML, fuera de los últimos seis Reels.')
    # Ahorro respecto de la alternativa más cara, igual denominador para ambos lados.
    return [max(az, key=lambda p: (p['ml'] - p['az']) / p['ml']),
            max(ml, key=lambda p: (p['az'] - p['ml']) / p['az'])]


UNIDADES = ('cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis diecisiete dieciocho diecinueve veinte veintiuno veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete veintiocho veintinueve').split()
DECENAS = ['', '', '', 'treinta', 'cuarenta', 'cincuenta', 'sesenta', 'setenta', 'ochenta', 'noventa']
CIENTOS = ['', 'ciento', 'doscientos', 'trescientos', 'cuatrocientos', 'quinientos', 'seiscientos', 'setecientos', 'ochocientos', 'novecientos']


def apocopar(texto):
    if texto.endswith('veintiuno'):
        return texto[:-9] + 'veintiún'
    if texto.endswith('uno'):
        return texto[:-3] + 'un'
    return texto


def palabras(n: int) -> str:
    if n < 30:
        return UNIDADES[n]
    if n < 100:
        return DECENAS[n // 10] + (' y ' + palabras(n % 10) if n % 10 else '')
    if n == 100:
        return 'cien'
    if n < 1000:
        return CIENTOS[n // 100] + (' ' + palabras(n % 100) if n % 100 else '')
    if n < 1000000:
        return ('mil' if n // 1000 == 1 else apocopar(palabras(n // 1000)) + ' mil') + (' ' + palabras(n % 1000) if n % 1000 else '')
    return ('un millón' if n // 1000000 == 1 else apocopar(palabras(n // 1000000)) + ' millones') + (' ' + palabras(n % 1000000) if n % 1000000 else '')


def hablado(monto):
    n = max(1000, redondear(monto / 1000) * 1000)
    return palabras(n) + (' de pesos' if n % 1000000 == 0 else ' pesos')


def ars(n):
    return f'{redondear(n):,}'.replace(',', '.')


def guiones(a, b, cantidad):
    doble = a['ml'] > 2 * a['az']
    hook = ('Podés pagar más del doble si comprás este producto en Mercado Libre.' if doble else
            'Este producto sale menos traído de Amazon. Mirá la diferencia.')
    motivo = 'El envío se come la diferencia.' if b['usd'] < 100 else 'Incluso con envío gratis, conviene comprarlo acá.'
    return [hook,
            f"{a['name']}. {hablado(a['ml'])} en Mercado Libre. Traído de Amazon, unos {hablado(a['az'])}. Gana Amazon.",
            'Pero ojo, no siempre gana Amazon.',
            f"{b['name']}. {hablado(b['ml'])} en Mercado Libre. De Amazon, unos {hablado(b['az'])}. Gana Mercado Libre. {motivo}",
            'La regla: debajo de cien dólares, el envío puede matar el ahorro. Desde cien, compará el total con envío e impuestos.',
            f'Comparamos {palabras(cantidad)} productos con los precios de hoy. Link en la bio.']


def subtitulos(texto, duracion):
    words = texto.split()
    chunks = []
    while words:
        size = 2 if len(words) == 5 else min(4, len(words))
        chunks.append(' '.join(words[:size]))
        words = words[size:]
    total = sum(len(c) + 1 for c in chunks)
    offset = 0
    partes = []
    for chunk in chunks:
        partes.append([round(duracion * offset / total, 3), chunk])
        offset += len(chunk) + 1
    return partes


def ejecutar(args, *, entrada=None, timeout=3600):
    subprocess.run([str(a) for a in args], cwd=BASE, input=entrada,
                   check=True, timeout=timeout)


def sintetizar(textos):
    duraciones = []
    for i, texto in enumerate(textos):
        print(f'Locución {i + 1}/6: {texto}', flush=True)
        wav = BASE / f'public/d{i}.wav'
        ejecutar([PIPER, '--model', MODELO, '--output_file', wav, '--length_scale', '0.95'],
                 entrada=(texto + '\n').encode('utf-8'), timeout=180)
        with wave.open(str(wav), 'rb') as audio:
            duraciones.append(audio.getnframes() / audio.getframerate())
    return duraciones


def emoji(p):
    categoria = p.get('category', '').lower()
    for fragmento, icono in [('auricular', '🎧'), ('audio', '🔊'), ('joystick', '🎮'), ('gaming', '🎮'),
                            ('almacenamiento', '💾'), ('monitor', '🖥️'), ('teclado', '⌨️'),
                            ('mouse', '🖱️'), ('cámara', '📷'), ('reloj', '⌚')]:
        if fragmento in categoria:
            return icono
    return '💻'


def caption(a, b, cantidad, fecha):
    motivo = 'el envío se come la diferencia.' if b['usd'] < 100 else 'incluso con envío gratis, conviene comprar acá.'
    return f'''¿Amazon o Mercado Libre? Depende del producto 👇

{emoji(a)} {a['name']}: ${ars(a['ml'])} en Mercado Libre vs ~${ars(a['az'])} traídos de Amazon. Gana Amazon.
{emoji(b)} {b['name']}: ${ars(b['ml'])} en Mercado Libre vs ~${ars(b['az'])} de Amazon. Gana Mercado Libre: {motivo}

Comparamos {cantidad} productos con los precios de hoy: link en la bio.

Precios del {fecha}. Amazon: estimado puesto en casa, con envío e impuestos (franquicia de USD 400).

Voz: Piper «es_AR-daniela-high» (CC BY-SA 4.0). Música: «Hip Hop 02», Mixkit.

#amazonargentina #mercadolibre #comprasalexterior #franquicia400 #tecnologia
'''


def main():
    hoy = datetime.now(ART).date().isoformat()
    ml, amazon, catalogo = datos_hoy(hoy)  # Antes de red, audio, props o historial.
    historial_path = BASE / 'historial.json'
    historial = leer(historial_path) if historial_path.exists() else []
    mep, eur_usd = cotizaciones(any(a.get('currency') == 'EUR' and a.get('checked') == hoy for a in amazon.values()))
    productos = comparables(ml, amazon, catalogo, hoy, mep, eur_usd)
    a, b = elegir(productos, historial)
    print(f"Ejemplo Amazon: {a['name']} | FOB USD {a['usd']:.2f} | MEP ${mep} (dolarapi.com) | estimado ARS ${ars(estimate_from_amazon(a['usd'], mep))} | sitio ${ars(a['az'])}", flush=True)
    npx = shutil.which('npx.cmd') or shutil.which('npx')
    ffmpeg = shutil.which('ffmpeg')
    if not npx or not ffmpeg or not PIPER.is_file() or not MODELO.is_file():
        raise ValueError('Falta npx, ffmpeg, Piper o el modelo es_AR-daniela-high en las rutas configuradas.')
    props = copy.deepcopy(leer(BASE / 'src/duelo.json'))
    textos = guiones(a, b, len(productos))
    duraciones = sintetizar(textos)
    props.update(voz=duraciones, audio=[f'd{i}.wav' for i in range(6)],
                 subs=[subtitulos(t, d) for t, d in zip(textos, duraciones)],
                 cantidad=len(productos), hookImage=a['slug'] + '.webp')
    props['duelos'] = []
    for i, producto in enumerate((a, b)):
        escena = 1 if i == 0 else 3
        dur = duraciones[escena]
        nota = (f"Te ahorrás ~$ {ars(producto['ml'] - producto['az'])}" if i == 0 else
                'El envío se come la diferencia' if b['usd'] < 100 else 'Conviene comprarlo acá')
        props['duelos'].append(dict(img=producto['slug'] + '.webp', nombre=producto['name'],
                                    ml=producto['ml'], az=producto['az'], gana=producto['gana'],
                                    mlAt=[dur * .16, dur * .36], azAt=[dur * .53, dur * .73],
                                    ganaAt=dur * .83, nota=nota))
        shutil.copyfile(REPO / 'public/products' / (producto['slug'] + '.webp'), BASE / 'public' / (producto['slug'] + '.webp'))
    fecha = datetime.fromisoformat(hoy).strftime('%d/%m/%Y')
    t = props['textos']
    t['gancho'] = ['PAGÁS', 'MÁS DEL', 'DOBLE'] if a['ml'] > 2 * a['az'] else ['AMAZON', 'SALE', 'MENOS']
    t['ganchoSub'] = 'si lo comprás en Mercado Libre' if a['ml'] > 2 * a['az'] else 'Mirá la diferencia con Mercado Libre'
    t['tarjetas'] = [dict(titulo='MENOS DE USD 100', sub='El envío puede comerse el ahorro. Compará el total.'),
                     dict(titulo='DESDE USD 100', sub='En productos elegibles, el envío es gratis. Compará.')]
    t['pie'] = f'Precios del {fecha} · Amazon: estimado con envío e impuestos'
    escribir(BASE / 'src/duelo.json', props)
    out = BASE / 'out'
    out.mkdir(exist_ok=True)
    raw = out / f'duelo-{hoy}.mp4'
    final = out / f'duelo-{hoy}-final.mp4'
    ejecutar([npx, 'remotion', 'render', 'Duelo', raw], timeout=3600)
    ejecutar([ffmpeg, '-y', '-i', raw, '-c:v', 'copy', '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11',
              '-c:a', 'aac', '-b:a', '192k', final], timeout=600)
    (out / f'duelo-{hoy}.txt').write_text(caption(a, b, len(productos), fecha), encoding='utf-8')
    historial.append(dict(fecha=hoy, reel=final.name, productos=[a['slug'], b['slug']]))
    escribir(historial_path, historial)  # Sólo consumir los productos si terminó el render.
    print(f'Reel listo: {final}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        sys.exit(1)
