// 13/11: resumen del historial de Amazon para «Bajó de precio» (nunca precios viejos ni de otra moneda).
import { promises as fs } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { resumirHistorialAmazon } from './deploy.mjs';

let dir: string;
beforeEach(async () => {
  dir = await fs.mkdtemp(path.join(os.tmpdir(), 'historial-test-'));
  await fs.mkdir(path.join(dir, 'output', 'historial'), { recursive: true });
  await fs.mkdir(path.join(dir, 'work', 'data'), { recursive: true });
  vi.spyOn(process.stdout, 'write').mockImplementation(() => true);
});
afterEach(async () => {
  vi.restoreAllMocks();
  await fs.rm(dir, { recursive: true, force: true });
});

const escribir = (fecha: string, data: unknown) =>
  fs.writeFile(path.join(dir, 'output', 'historial', `${fecha}-amazon-prices.json`), JSON.stringify(data));
const leer = async () => JSON.parse(await fs.readFile(path.join(dir, 'work', 'data', 'historial-amazon.json'), 'utf8'));

it('sólo precios en USD relevados ese día, de los últimos 8 archivos', async () => {
  for (let d = 1; d <= 10; d++) {
    const fecha = `2026-11-${String(d).padStart(2, '0')}`;
    await escribir(fecha, { date: fecha, items: {
      a: { amount: 100 + d, currency: 'USD', checked: fecha },
      viejo: { amount: 50, currency: 'USD', checked: '2026-10-01' },
      euro: { amount: 90, currency: 'EUR', checked: fecha },
      roto: { amount: 'x', currency: 'USD', checked: fecha },
    } });
  }
  await fs.writeFile(path.join(dir, 'output', 'historial', '2026-11-10-ml-prices.json'), '{}');
  await escribir('2026-11-11', { date: '2026-11-09', items: { a: { amount: 1, currency: 'USD', checked: '2026-11-09' } } }); // fecha cruzada
  await resumirHistorialAmazon(path.join(dir, 'output'), path.join(dir, 'work'));
  const h = await leer();
  expect(Object.keys(h)).toEqual(['2026-11-04', '2026-11-05', '2026-11-06', '2026-11-07', '2026-11-08', '2026-11-09', '2026-11-10']);
  expect(h['2026-11-10']).toEqual({ a: 110 });
});

it('sin historial no deja archivo (ni uno anterior) y no rompe', async () => {
  await fs.rm(path.join(dir, 'output', 'historial'), { recursive: true });
  await fs.writeFile(path.join(dir, 'work', 'data', 'historial-amazon.json'), '{"viejo":{}}');
  await expect(resumirHistorialAmazon(path.join(dir, 'output'), path.join(dir, 'work'))).resolves.toBeUndefined();
  await expect(fs.access(path.join(dir, 'work', 'data', 'historial-amazon.json'))).rejects.toThrow();
});
