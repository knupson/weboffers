import { describe, expect, it } from 'vitest';
import { mergeMlPrices, type CatalogEntry, type MlPrices } from './data';

const base = (over: Partial<CatalogEntry>): CatalogEntry => ({
  asin: 'B000000000', store: 'US', slug: 'producto', name: 'Producto', brand: 'Marca',
  category: 'Monitores', summary: 'Resumen', verified: true, ...over,
});

const catalog: CatalogEntry[] = [
  base({ slug: 'con-ml', ml: { price: 100000, url: 'https://meli.la/abc', checked: '2026-10-01' }, verdict: 'amazon', verdictReason: 'precio' }),
  base({ slug: 'sin-ml', asin: 'B111111111' }),
];

const prices: MlPrices = {
  generatedAt: '2026-10-30T06:00:00-03:00',
  date: '2026-10-30',
  items: {
    'con-ml': { price: 123456, checked: '2026-10-30', verdict: 'ml', verdictReason: 'sinAmazon' },
    'sin-ml': { price: 999, checked: '2026-10-30', verdict: 'ml', verdictReason: 'precio' },
    'no-existe': { price: 5, checked: '2026-10-30', verdict: 'ml', verdictReason: 'precio' },
  },
};

describe('mergeMlPrices', () => {
  it('devuelve el catálogo tal cual si no hay archivo de precios', () => {
    expect(mergeMlPrices(catalog, null)).toBe(catalog);
  });

  it('pisa precio, fecha, veredicto y motivo sólo en entradas que ya tienen ml', () => {
    const [merged] = mergeMlPrices(catalog, prices);
    expect(merged.ml).toEqual({ price: 123456, url: 'https://meli.la/abc', checked: '2026-10-30' });
    expect(merged.verdict).toBe('ml');
    expect(merged.verdictReason).toBe('sinAmazon');
  });

  it('no agrega ml a entradas que no lo tenían, aunque el archivo traiga el slug', () => {
    const [, sinMl] = mergeMlPrices(catalog, prices);
    expect(sinMl).toEqual(catalog[1]);
    expect(sinMl.ml).toBeUndefined();
  });

  it('ignora slugs que no están en el catálogo y no rompe con claves de prototipo', () => {
    const weird: MlPrices = { ...prices, items: { ...prices.items } };
    const out = mergeMlPrices(catalog, { ...weird, items: JSON.parse('{"constructor": {"price": 1}}') });
    expect(out).toEqual(catalog);
  });

  it('no muta el catálogo original', () => {
    const snapshot = JSON.parse(JSON.stringify(catalog));
    mergeMlPrices(catalog, prices);
    expect(catalog).toEqual(snapshot);
  });

  it('descarta valores inválidos y deja el veredicto anterior', () => {
    const bad: MlPrices = {
      ...prices,
      items: { 'con-ml': { price: Number.NaN, checked: '2026-10-30', verdict: 'ml', verdictReason: 'precio' } },
    };
    expect(mergeMlPrices(catalog, bad)[0]).toEqual(catalog[0]);
    const badVerdict = {
      ...prices,
      items: { 'con-ml': { price: 200, checked: '2026-10-30', verdict: 'otra' as 'ml', verdictReason: 'x' as 'precio' } },
    };
    const [m] = mergeMlPrices(catalog, badVerdict);
    expect(m.ml?.price).toBe(200);
    expect(m.verdict).toBe('amazon');
    expect(m.verdictReason).toBe('precio');
  });
});
