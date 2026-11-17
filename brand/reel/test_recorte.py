"""17/11: el carrusel del 16/11 salió con 4 fotos en un rectángulo blanco. Cubre el recorte obligatorio de recorte.py
y la guardia de brand/carrusel/render.cjs. Sin red: las fotos de prueba las genera ffmpeg.
python3 -m unittest -v test_recorte"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import recorte as rc

REPO = Path(__file__).resolve().parents[2]


def ffmpeg_imagen(destino, fuente, filtros, *extra):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', fuente, '-vf', filtros, '-frames:v', '1',
                    *extra, str(destino)], check=True)


def alfa(w, rgba, x, y):
    return rgba[(y * w + x) * 4 + 3]


class RecorteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_foto_rgb_con_fondo_blanco_se_recorta(self):
        # Como la Arzopa, el ASUS, el Guess y la DeWalt del 16/11: WebP RGB sin alfa, producto oscuro sobre blanco,
        # con una zona blanca DENTRO del producto que no se tiene que borrar.
        foto = self.d / 'producto.webp'
        ffmpeg_imagen(foto, 'color=white:s=60x40',
                      'drawbox=x=20:y=10:w=20:h=20:color=black:t=fill,drawbox=x=26:y=16:w=8:h=8:color=white:t=fill',
                      '-lossless', '1')
        w, h, crudo = rc.leer_rgba(foto)
        self.assertEqual(rc.fraccion_borde_transparente(w, h, crudo), 0)  # el caso que salió en el carrusel

        png = self.d / 'producto.png'
        self.assertTrue(rc.asegurar_transparente(foto, png))
        w, h, final = rc.leer_rgba(png)
        self.assertEqual(rc.fraccion_borde_transparente(w, h, final), 1)
        self.assertEqual(alfa(w, final, 5, 5), 0)  # fondo
        self.assertEqual(alfa(w, final, 22, 12), 255)  # producto
        self.assertEqual(alfa(w, final, 30, 20), 255)  # blanco dentro del producto: se queda

    def test_foto_ya_transparente_no_se_toca(self):
        # Como los auriculares Skullcandy del 16/11: PNG con alfa y borde transparente.
        foto = self.d / 'auriculares.png'
        crudo = bytearray(60 * 40 * 4)
        for y in range(10, 30):
            for x in range(20, 40):
                crudo[(y * 60 + x) * 4:(y * 60 + x) * 4 + 4] = b'\xff\x00\x00\xff'
        rc.escribir_png(foto, 60, 40, crudo)
        png = self.d / 'auriculares-out.png'
        self.assertFalse(rc.asegurar_transparente(foto, png))
        w, h, final = rc.leer_rgba(png)
        self.assertEqual(rc.fraccion_borde_transparente(w, h, final), 1)
        self.assertEqual(alfa(w, final, 25, 15), 255)

    def test_fondo_que_no_se_puede_recortar_aborta(self):
        # Fondo gris (foto de estudio, escena): el recorte no lo saca y no se tiene que generar la placa.
        foto = self.d / 'escena.jpg'
        ffmpeg_imagen(foto, 'color=gray:s=60x40', 'drawbox=x=20:y=10:w=20:h=20:color=black:t=fill')
        png = self.d / 'escena.png'
        with self.assertRaisesRegex(rc.SinFondoTransparente, 'No se genera la placa'):
            rc.asegurar_transparente(foto, png)
        self.assertFalse(png.exists())

    def test_cli_sale_con_error(self):
        foto = self.d / 'escena.jpg'
        ffmpeg_imagen(foto, 'color=gray:s=60x40', 'drawbox=x=20:y=10:w=20:h=20:color=black:t=fill')
        r = subprocess.run(['python3' if os.name != 'nt' else 'python', str(Path(rc.__file__)), str(foto),
                            str(self.d / 'x.png')], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('RECORTE_FALLA', r.stderr)


class GuardiaRenderTest(unittest.TestCase):
    """render.cjs no compone ninguna placa si un producto no trae la foto recortada que deja datos.py."""

    def _render(self, productos):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, 'datos.json').write_text(json.dumps(dict(fecha='16/11', total=1, link='x', productos=productos)),
                                               encoding='utf-8')
            env = dict(os.environ, CARRUSEL_OUT=tmp, PLAYWRIGHT_MODULE='/no/se/tiene/que/cargar')
            r = subprocess.run(['node', str(REPO / 'brand/carrusel/render.cjs')], capture_output=True, text=True, env=env)
            return r, sorted(p.name for p in Path(tmp).iterdir())

    def test_sin_foto_recortada_aborta_antes_de_renderizar(self):
        r, archivos = self._render([dict(slug='arzopa-z1fc-16-1in', name='Arzopa', category='Monitores',
                                         ml=1, az=1, gana='ml', ahorro=0)])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('sin foto con fondo transparente', r.stderr)
        self.assertEqual(archivos, ['datos.json'])  # ni una placa

    def test_foto_declarada_pero_inexistente_aborta(self):
        r, archivos = self._render([dict(slug='arzopa-z1fc-16-1in', name='Arzopa', category='Monitores',
                                         ml=1, az=1, gana='ml', ahorro=0, foto='fotos/arzopa-z1fc-16-1in.png')])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('sin foto con fondo transparente', r.stderr)
        self.assertEqual(archivos, ['datos.json'])


if __name__ == '__main__':
    unittest.main()
