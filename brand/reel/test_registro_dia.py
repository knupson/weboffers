"""Registro compartido de productos por día (19/11). Sin red: python -m unittest test_registro_dia."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hacer_reel as r
import lote_historias as lote
import registro_dia as reg


def prod(slug, ml, az, gana):
    return dict(slug=slug, name=slug, ml=ml, az=az, gana=gana)


class RegistroTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / 'productos-del-dia.json'

    def test_reserva_y_lee_por_turno(self):
        reg.reservar('2026-11-23', 'historia12', ['a'], path=self.path)
        reg.reservar('2026-11-23', 'historia20', ['b'], path=self.path)
        self.assertEqual(reg.reservados('2026-11-23', excepto='reel19', path=self.path), {'a', 'b'})
        self.assertEqual(reg.reservados('2026-11-24', path=self.path), set())

    def test_no_deja_repetir_producto_el_mismo_dia(self):
        reg.reservar('2026-11-23', 'historia12', ['a'], path=self.path)
        with self.assertRaises(ValueError):
            reg.reservar('2026-11-23', 'reel19', ['a', 'c'], path=self.path)
        with self.assertRaises(ValueError):
            reg.reservar('2026-11-23', 'reel19', ['c', 'c'], path=self.path)
        reg.reservar('2026-11-24', 'reel19', ['a', 'c'], path=self.path)  # otro día sí

    def test_rehacer_el_mismo_turno_lo_pisa(self):
        reg.reservar('2026-11-23', 'reel19', ['a', 'b'], path=self.path)
        reg.reservar('2026-11-23', 'reel19', ['c', 'd'], path=self.path)
        self.assertEqual(reg.leer(self.path)['2026-11-23']['reel19'], ['c', 'd'])

    def test_turno_desconocido(self):
        with self.assertRaises(ValueError):
            reg.reservar('2026-11-23', 'historia18', ['a'], path=self.path)

    def test_borra_dias_viejos(self):
        reg.reservar('2026-08-01', 'reel19', ['a', 'b'], path=self.path)
        reg.reservar('2026-11-23', 'reel19', ['c', 'd'], path=self.path)
        self.assertNotIn('2026-08-01', reg.leer(self.path))


class ReelExcluyeHistoriasTest(unittest.TestCase):
    def setUp(self):
        p = patch.object(Path, 'is_file', return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_reel_no_usa_productos_de_las_historias_de_hoy(self):
        productos = [prod('az1', 1000, 400, 'amazon'), prod('az2', 900, 500, 'amazon'),
                     prod('ml1', 300, 600, 'ml'), prod('ml2', 300, 500, 'ml')]
        a, b = r.elegir(productos, [], foto_ok=lambda s: True, excluir={'az1', 'ml1'})
        self.assertEqual((a['slug'], b['slug']), ('az2', 'ml2'))


class LoteTest(unittest.TestCase):
    def setUp(self):
        p = patch.object(Path, 'is_file', return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def test_diez_productos_distintos_en_la_semana(self):
        productos = [prod(f'p{i}', 1000, 1000 - i * 10 - 10, 'amazon') for i in range(14)]
        fechas = lote.fechas_lote('2026-11-23', 5)
        elegido = lote.elegir_lote(productos, fechas, [], {}, foto_ok=lambda s: True)
        slugs = [p['slug'] for dia in elegido.values() for p in dia.values()]
        self.assertEqual(len(slugs), 10)
        self.assertEqual(len(set(slugs)), 10)
        self.assertEqual(fechas[-1], '2026-11-27')

    def test_respeta_historial_reel_ya_hecho_y_fotos(self):
        productos = [prod(f'p{i}', 1000, 1000 - i * 10 - 10, 'amazon') for i in range(6)]
        historial = [dict(fecha='2026-11-20', slug='p5')]  # el de más ahorro ya salió hace poco
        reservado = {'2026-11-23': {'p4'}}  # el Reel de ese día ya lo usó
        elegido = lote.elegir_lote(productos, ['2026-11-23'], historial, reservado, foto_ok=lambda s: s != 'p3')
        self.assertEqual({p['slug'] for p in elegido['2026-11-23'].values()}, {'p2', 'p1'})

    def test_sin_productos_suficientes_corta(self):
        productos = [prod('p1', 1000, 500, 'amazon')]
        with self.assertRaises(ValueError):
            lote.elegir_lote(productos, ['2026-11-23'], [], {}, foto_ok=lambda s: True)

    def test_enlaces_con_utm_y_telegram(self):
        self.assertEqual(lote.enlace_ficha('x', '2026-11-23', 'instagram'),
                         'https://ofertas.knunet.com/productos/x/?utm_source=instagram&utm_medium=social'
                         '&utm_campaign=historia&utm_content=historia-23-11')
        self.assertEqual(lote.TELEGRAM, 'https://t.me/franquicia400')


if __name__ == '__main__':
    unittest.main()
