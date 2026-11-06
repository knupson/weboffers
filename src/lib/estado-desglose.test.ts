import fs from 'node:fs';
import { afterEach, expect, it, vi } from 'vitest';
import { GET } from '../pages/estado.json';
import { loadProducts, mergeAmazonPrices, mergeMlPrices, type CatalogEntry } from './data';

vi.mock('./data', async (original) => ({
  ...await original<typeof import('./data')>(),
  loadProducts: vi.fn(), loadAmazonPrices: vi.fn(() => null), loadMlPrices: vi.fn(() => null),
}));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.useRealTimers(); });

it('el endpoint escribe el desglose privado del mismo merge que cuenta en estado.json', async () => {
  const now = Date.parse('2026-11-06T15:00:00Z');
  const date = '2026-11-06';
  vi.useFakeTimers();
  vi.setSystemTime(now);
  const catalog = [{ slug: 'kindle', asin: 'B0CFPJYX7P', image: '/kindle.webp', verified: true,
    ml: { price: 1, url: 'https://mercadolibre.com.ar' }, shipsToAr: { freeShipping: true, checked: date } }] as CatalogEntry[];
  const products = mergeAmazonPrices(mergeMlPrices(catalog, { date, generatedAt: '', items: {
    kindle: { price: 650000, checked: date },
  } }, now), { date, generatedAt: '', items: {
    kindle: { asin: 'B0CFPJYX7P', amount: 200, currency: 'EUR', checked: date },
  } }, 1200, 1.25, now);
  vi.mocked(loadProducts).mockResolvedValue({ products, offers: { items: [], mode: 'offline', rates: null, generatedAt: null }, buildMep: 1200 });
  vi.stubEnv('CADENA_DESGLOSE_PATH', 'informe-privado.json');
  const read = fs.readFileSync;
  vi.spyOn(fs, 'readFileSync').mockImplementation(((file: string, ...args: any[]) =>
    String(file).endsWith('catalog-origins.json') ? '{"kindle":"auto"}' : (read as any)(file, ...args)) as any);
  const write = vi.spyOn(fs, 'writeFileSync').mockImplementation(() => {});
  const state = await (await GET()).json();
  const report = JSON.parse(write.mock.calls[0][1] as string);
  expect(write.mock.calls[0][0]).toBe('informe-privado.json');
  expect(loadProducts).toHaveBeenCalledWith(now);
  expect(report.publicados).toBe(state.publicados);
  expect(report.publicados).toBe(1);
  expect(report.content).toContain('origen=auto PUBLICADO');
  expect(report.content).toContain('amazon_rango=ok(USD 250)');
});
