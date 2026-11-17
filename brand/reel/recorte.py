"""Fondo transparente obligatorio para las fotos de producto que van sobre el fondo oscuro (17/11).

El carrusel del 16/11 salió con 4 de 5 fotos en un rectángulo blanco: las fotos de public/products/ son, en su
mayoría, JPG/WebP del vendedor sin canal alfa (RGB con fondo blanco) y ningún paso las recortaba. Antes de componer
una placa o una escena, cada foto pasa por asegurar_transparente():
  1. si el borde ya es transparente, se convierte a PNG tal cual;
  2. si no, se borra el fondo claro conectado con el borde (relleno desde los bordes, así el blanco DENTRO del
     producto no se toca) y se vuelve a medir;
  3. si aun así el borde no queda transparente, SinFondoTransparente: no se genera nada con ese producto.
Sólo usa ffmpeg (está en la imagen franquicia400-reel y en la PC); sin PIL ni dependencias nuevas.
CLI: python3 recorte.py <foto origen> <png destino>  (sale con código 1 si no se puede dejar transparente)."""
import collections
import json
import shutil
import subprocess
import sys
from pathlib import Path

ALFA_TRANSPARENTE = 16  # alfa <= esto cuenta como transparente
MIN_BORDE = 0.80  # fracción mínima del borde que tiene que quedar transparente (el producto puede tocar el borde)
# 17/11, medido con las 4 fotos del carrusel del 16/11: con 232 el relleno entraba por los brillos metálicos de la
# DeWalt DCF961B y le hacía agujeros; con 250 las 4 quedan con el 100 % del borde transparente y el producto entero.
CLARO = 250  # un píxel de fondo tiene los tres canales >= CLARO ...
CROMA = 12  # ... y poca diferencia entre canales (blanco, no un color pastel)
SUAVE = 128  # en el contorno, los píxeles claros (>= SUAVE en los 3 canales) se separan del blanco (sin halo)
CONTORNO = 2  # píxeles de contorno que se suavizan


class SinFondoTransparente(Exception):
    pass


def _bin(nombre):
    ruta = shutil.which(nombre)
    if not ruta:
        raise SinFondoTransparente(f'Falta {nombre}: no se puede verificar el fondo de las fotos.')
    return ruta


def leer_rgba(ruta):
    """(ancho, alto, bytearray RGBA) de cualquier imagen que lea ffmpeg (webp, jpg, png)."""
    info = subprocess.run([_bin('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                           'stream=width,height', '-of', 'json', str(ruta)], capture_output=True, text=True)
    if info.returncode != 0:
        raise SinFondoTransparente(f'{ruta}: ffprobe no la pudo leer: {info.stderr.strip()}')
    s = json.loads(info.stdout)['streams'][0]
    w, h = int(s['width']), int(s['height'])
    crudo = subprocess.run([_bin('ffmpeg'), '-v', 'error', '-i', str(ruta), '-frames:v', '1',
                            '-f', 'rawvideo', '-pix_fmt', 'rgba', '-'], capture_output=True)
    if crudo.returncode != 0 or len(crudo.stdout) != w * h * 4:
        raise SinFondoTransparente(f'{ruta}: ffmpeg no la pudo decodificar: {crudo.stderr.decode(errors="replace").strip()}')
    return w, h, bytearray(crudo.stdout)


def escribir_png(ruta, w, h, rgba):
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([_bin('ffmpeg'), '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{w}x{h}',
                        '-i', '-', '-frames:v', '1', '-pix_fmt', 'rgba', str(ruta)], input=bytes(rgba), capture_output=True)
    if r.returncode != 0:
        raise SinFondoTransparente(f'{ruta}: ffmpeg no pudo escribir el PNG: {r.stderr.decode(errors="replace").strip()}')


def _borde(w, h):
    vistos = dict.fromkeys([(x, 0) for x in range(w)] + [(x, h - 1) for x in range(w)]
                           + [(0, y) for y in range(h)] + [(w - 1, y) for y in range(h)])
    return [y * w + x for x, y in vistos]


def fraccion_borde_transparente(w, h, rgba):
    borde = _borde(w, h)
    return sum(rgba[i * 4 + 3] <= ALFA_TRANSPARENTE for i in borde) / len(borde)


def _es_fondo(rgba, i):
    r, g, b, a = rgba[i * 4:i * 4 + 4]
    return a <= ALFA_TRANSPARENTE or (min(r, g, b) >= CLARO and max(r, g, b) - min(r, g, b) <= CROMA)


def quitar_fondo(w, h, rgba):
    """Copia de rgba con el fondo claro conectado al borde en alfa 0 y el contorno claro suavizado."""
    out = bytearray(rgba)
    fondo = bytearray(w * h)
    cola = collections.deque()
    for i in _borde(w, h):
        if _es_fondo(rgba, i):
            fondo[i] = 1
            cola.append(i)
    while cola:
        i = cola.popleft()
        x, y = i % w, i // w
        for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1, (i + w) if y < h - 1 else -1):
            if j >= 0 and not fondo[j] and _es_fondo(rgba, j):
                fondo[j] = 1
                cola.append(j)
    for i in range(w * h):
        if fondo[i]:
            out[i * 4 + 3] = 0
    # Contorno: el halo claro del JPEG (2 píxeles hacia adentro) pasa a semitransparente; sólo pegado al fondo
    # borrado, así no se aclara nada del interior del producto.
    for _ in range(CONTORNO):
        anillo = []
        for i in range(w * h):
            if fondo[i]:
                continue
            x, y = i % w, i // w
            if (x and fondo[i - 1]) or (x < w - 1 and fondo[i + 1]) or (y and fondo[i - w]) or (y < h - 1 and fondo[i + w]):
                rgb = rgba[i * 4:i * 4 + 3]
                if min(rgb) >= SUAVE:
                    # «Color a alfa» contra blanco: el píxel es una mezcla del producto con el fondo blanco; se
                    # separa el blanco (alfa) y se recupera el color del producto, sin dejar línea clara.
                    a = max(255 - c for c in rgb) / 255
                    out[i * 4 + 3] = min(out[i * 4 + 3], round(255 * a))
                    if a:
                        out[i * 4:i * 4 + 3] = bytes(max(0, min(255, round(255 - (255 - c) / a))) for c in rgb)
                    anillo.append(i)
        for i in anillo:
            fondo[i] = 1
    return out


def asegurar_transparente(origen, destino):
    """Escribe en destino (PNG) la foto con el borde transparente y devuelve True si hubo que recortarla.
    Si no se puede dejar transparente, SinFondoTransparente: el que llama no tiene que generar la placa."""
    w, h, rgba = leer_rgba(origen)
    recortada = fraccion_borde_transparente(w, h, rgba) < MIN_BORDE
    if recortada:
        rgba = quitar_fondo(w, h, rgba)
        f = fraccion_borde_transparente(w, h, rgba)
        if f < MIN_BORDE:
            raise SinFondoTransparente(f'{origen}: después del recorte sólo el {f:.0%} del borde quedó transparente '
                                       f'(mínimo {MIN_BORDE:.0%}); el fondo no es blanco liso. No se genera la placa: '
                                       'reemplazar la foto por una con fondo transparente o blanco.')
    escribir_png(destino, w, h, rgba)
    w2, h2, final = leer_rgba(destino)  # lo que se va a componer, no lo que creemos haber escrito
    f = fraccion_borde_transparente(w2, h2, final)
    if f < MIN_BORDE:
        raise SinFondoTransparente(f'{destino}: el PNG escrito tiene sólo el {f:.0%} del borde transparente.')
    return recortada


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('Uso: python3 recorte.py <foto origen> <png destino>')
    try:
        hecho = asegurar_transparente(sys.argv[1], sys.argv[2])
    except SinFondoTransparente as e:
        sys.exit(f'RECORTE_FALLA {e}')
    print(f"RECORTE_OK {sys.argv[2]} ({'fondo recortado' if hecho else 'ya era transparente'})")
