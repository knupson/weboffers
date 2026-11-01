"""Pruebas sin red ni cambios en los precios reales: python -m unittest -v."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

import hacer_reel as r


class GeneradorTest(unittest.TestCase):
    def test_paridad_con_typescript_del_sitio(self):
        # Ejecuta las funciones reales del sitio, no una segunda copia de la fórmula.
        casos = [[usd, mep] for usd in (0.01, 79.99, 99.99, 100, 279, 400, 400.014, 450, 3000)
                 for mep in (1000, 1475.5, 1500)]
        js = r"""
const fs = require('fs'), ts = require('typescript');
require.extensions['.ts'] = (module, file) => module._compile(ts.transpileModule(
  fs.readFileSync(file, 'utf8'), {compilerOptions: {module: ts.ModuleKind.CommonJS}}
).outputText, file);
const {estimateFromAmazon} = require('../../src/lib/estimate.ts');
const cases = JSON.parse(process.argv[1]);
process.stdout.write(JSON.stringify(cases.map(([usd, mep]) => {
  const ars = estimateFromAmazon(usd, mep);
  return [ars, Math.round(ars / 10000) * 10000];
})));
"""
        result = subprocess.run(['node', '-e', js, json.dumps(casos)], cwd=r.BASE,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout),
                         [[r.estimate_from_amazon(u, m), r.precio_sitio(u, m)] for u, m in casos])
        print('Ejemplo de prueba: FOB USD 279; MEP $1.500; estimado $523.125; sitio $520.000.')

    def test_subtitulos_y_numeros(self):
        for count in range(2, 35):
            text = ' '.join(['palabra'] * count)
            parts = r.subtitulos(text, 10)
            self.assertEqual(' '.join(p[1] for p in parts), text)
            self.assertTrue(all(2 <= len(p[1].split()) <= 4 for p in parts))
            self.assertEqual(parts[0][0], 0)
            self.assertLess(parts[-1][0], 10)
        self.assertEqual(r.hablado(869099), 'ochocientos sesenta y nueve mil pesos')
        self.assertEqual(r.hablado(21000), 'veintiún mil pesos')
        self.assertEqual(r.hablado(1000000), 'un millón de pesos')

    def test_historial_y_seleccion_por_porcentaje(self):
        productos = [dict(slug=s, gana=w, ml=m, az=a) for s, w, m, a in
                     [('viejo', 'amazon', 100, 10), ('a', 'amazon', 100, 50),
                      ('b', 'amazon', 1000, 600), ('c', 'ml', 50, 100)]]
        with patch.object(Path, 'is_file', return_value=True):
            seleccion = r.elegir(productos, [dict(productos=['viejo'])])
        self.assertEqual([p['slug'] for p in seleccion], ['a', 'c'])

    def test_fechas_viejas_abortan_antes_de_escribir(self):
        with patch.object(r, 'leer', side_effect=[dict(date='2000-01-01'), dict(date='2000-01-01'), []]):
            with self.assertRaisesRegex(ValueError, 'nunca se usan precios viejos'):
                r.datos_hoy('2026-11-01')

    def test_pipeline_con_datos_sinteticos_y_subprocesos_simulados(self):
        defaults = r.leer(r.BASE / 'src/duelo.json')
        with tempfile.TemporaryDirectory(dir=r.BASE / 'out') as tmp:
            repo = Path(tmp)
            base = repo / 'brand/reel'
            for folder in (base / 'src', base / 'public', repo / 'public/products', repo / 'data'):
                folder.mkdir(parents=True, exist_ok=True)
            r.escribir(base / 'src/duelo.json', defaults)
            hoy = r.datetime.now(r.ART).date().isoformat()
            catalogo = [dict(slug=s, name=s, category='Audio', asin=s, verified=True,
                             image=f'/products/{s}.webp', shipsToAr=dict(freeShipping=True))
                        for s in ('prueba-amazon', 'prueba-ml')]
            for p in catalogo:
                (repo / 'public/products' / (p['slug'] + '.webp')).write_bytes(b'imagen-de-prueba')
            r.escribir(repo / 'data/catalog.json', catalogo)
            r.escribir(repo / 'data/ml-prices.json', dict(date=hoy, items={
                'prueba-amazon': dict(price=800000, checked=hoy),
                'prueba-ml': dict(price=50000, checked=hoy)}))
            r.escribir(repo / 'data/amazon-prices.json', dict(date=hoy, items={
                'prueba-amazon': dict(amount=200, currency='USD', checked=hoy),
                'prueba-ml': dict(amount=50, currency='USD', checked=hoy)}))
            comandos = []

            def fake_exec(args, **kwargs):
                comandos.append([str(a) for a in args])
                if '--output_file' in args:
                    with wave.open(str(args[args.index('--output_file') + 1]), 'wb') as wav:
                        wav.setparams((1, 2, 22050, 0, 'NONE', 'not compressed'))
                        wav.writeframes(b'\0\0' * 22050 * 5)
                else:
                    Path(args[-1]).write_bytes(b'video-de-prueba')

            with patch.object(r, 'BASE', base), patch.object(r, 'REPO', repo), \
                 patch.object(r, 'cotizaciones', return_value=(1500, None)), \
                 patch.object(r, 'ejecutar', side_effect=fake_exec), \
                 patch.object(Path, 'is_file', return_value=True), \
                 patch.object(r.shutil, 'which', side_effect=lambda p: p), \
                 contextlib.redirect_stdout(io.StringIO()):
                r.main()
            props = r.leer(base / 'src/duelo.json')
            self.assertEqual(props['voz'], [5] * 6)
            self.assertEqual(props['duelos'][0]['az'], 380000)
            self.assertEqual(len(comandos), 8)
            self.assertIn('loudnorm=I=-14:TP=-1.5:LRA=11', comandos[-1])
            self.assertEqual(len(r.leer(base / 'historial.json')), 1)
            self.assertTrue((base / f'out/duelo-{hoy}.txt').is_file())


if __name__ == '__main__':
    unittest.main()
