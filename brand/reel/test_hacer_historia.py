"""Elección del producto de la historia diaria (17/11). Sin red ni render: python -m unittest test_hacer_historia."""
from pathlib import Path
import unittest
from unittest.mock import patch

import hacer_historia as h


def prod(slug, ml, az, gana):
    return dict(slug=slug, name=slug, ml=ml, az=az, gana=gana)


class HistoriaTest(unittest.TestCase):
    def setUp(self):
        p = patch.object(Path, 'is_file', return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_elige_el_de_mas_ahorro_publicable(self):
        productos = [prod('a', 100, 90, 'ml'), prod('b', 1000, 400, 'amazon'), prod('c', 500, 500, None)]
        self.assertEqual(h.elegir_historia(productos, [], [], foto_ok=lambda s: True)['slug'], 'b')

    def test_no_repite_historias_ni_el_reel_reciente(self):
        productos = [prod('b', 1000, 400, 'amazon'), prod('r', 900, 400, 'amazon'), prod('x', 300, 250, 'amazon')]
        historial = [dict(fecha='2026-11-17', slug='b')]
        reel = [dict(productos=['r', 'z'])]
        self.assertEqual(h.elegir_historia(productos, historial, reel, foto_ok=lambda s: True)['slug'], 'x')

    def test_saltea_foto_no_recortable(self):
        productos = [prod('b', 1000, 400, 'amazon'), prod('x', 300, 250, 'amazon')]
        self.assertEqual(h.elegir_historia(productos, [], [], foto_ok=lambda s: s != 'b')['slug'], 'x')

    def test_sin_candidatos_corta(self):
        with self.assertRaises(ValueError):
            h.elegir_historia([prod('c', 500, 500, None)], [], [], foto_ok=lambda s: True)

    def test_historia_tiene_el_sitio_escrito(self):
        tsx = (h.r.BASE / 'src/Historia.tsx').read_text(encoding='utf-8')
        self.assertIn('export const SITIO_VISIBLE = "ofertas.knunet.com"', tsx)
        self.assertIn('<SitioArriba />', tsx)
        self.assertNotIn('Tocá el enlace', tsx)  # no hay sticker: no se promete un enlace tocable


if __name__ == '__main__':
    unittest.main()
