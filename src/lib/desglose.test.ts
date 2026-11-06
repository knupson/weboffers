import { expect, it } from 'vitest';
import { mergeMlPrices, mergeAmazonPrices, isComparable, type CatalogEntry } from './data';
import { publicationBreakdown } from './desglose';

export const now = Date.parse('2026-11-06T15:00:00Z');
const date = '2026-11-06';
const entries = ['kindle-paperwhite', 'sony-wh-1000xm5', 'logitech-mx-master-3s'].map((slug, i) => ({
  slug, asin: ['B0CFPJYX7P', 'B09XS7JWHH', 'B09HM94VDS'][i], store: 'US', verified: true,
  image: `/products/${slug}.webp`, shipsToAr: { freeShipping: true, checked: date },
  ml: { price: 1, checked: date, url: 'https://mercadolibre.com.ar' },
})) as CatalogEntry[];

it('desglosa el merge real, cuenta todas las fallas y conserva el origen', () => {
  const ml = { generatedAt: '', date, items: Object.fromEntries(entries.map((p, i) => [p.slug, { price: [650000, 890000, 230000][i], checked: i === 2 ? '2026-11-05' : date }])) };
  const amazon = { generatedAt: '', date, items: Object.fromEntries(entries.map((p, i) => [p.slug, { asin: p.asin, amount: [159.99, 451.90, 99.99][i], currency: 'USD' as const, checked: date }])) };
  const products = mergeAmazonPrices(mergeMlPrices(entries, ml, now), amazon, 1200, 1.25, now);
  const report = publicationBreakdown(products, { 'sony-wh-1000xm5': 'auto' }, now);
  expect(report).toMatchObject({ total: 3, publicados: 1, filtrados: 2, fallas: { amazon_rango: 2, ml_presente: 1, ml_precio: 1, ml_hoy: 1 } });
  expect(report.publicados).toBe(products.filter(p => isComparable(p, null, now)).length);
  expect(report.content).toContain('origen=auto FILTRADO');
  expect(report.content).toContain('amazon_rango=FALLA(USD 451.9)');
  expect(report.content).toContain('ml_hoy=ok(2026-11-06 $650000)');
  expect(report.content.split('\n').filter(Boolean).every(line => line.startsWith('2026-11-06 12:00:00 '))).toBe(true);
});

it('admite un catálogo vacío', () => {
  expect(publicationBreakdown([], {}, now)).toMatchObject({ total: 0, publicados: 0, filtrados: 0, fallas: {} });
});
