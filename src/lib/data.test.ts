import { describe, expect, it } from 'vitest';
import {
  comparePrices,
  getComparableSlugs,
  isComparable,
  mergeAmazonPrices,
  mergeMlPrices,
  roundArs10k,
  type AmazonPrices,
  type CatalogEntry,
  type MlPrices,
} from './data';

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

  it('usa el link del día si es de mercadolibre.com.ar y si no deja el del catálogo', () => {
    const url = 'https://www.mercadolibre.com.ar/p/MLA1?pdp_filters=item_id%3AMLA7&matt_word=ale_benzoni&matt_tool=58527537';
    const item = prices.items['con-ml'];
    const conUrl = mergeMlPrices(catalog, { ...prices, items: { 'con-ml': { ...item, url } } });
    expect(conUrl[0].ml?.url).toBe(url);
    for (const bad of ['https://evil.com/mercadolibre.com.ar', 'http://www.mercadolibre.com.ar/p/MLA1', 'javascript:alert(1)']) {
      const out = mergeMlPrices(catalog, { ...prices, items: { 'con-ml': { ...item, url: bad } } });
      expect(out[0].ml?.url).toBe('https://meli.la/abc');
    }
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

describe('mergeAmazonPrices & isComparable', () => {
  it('redondea a múltiplos de 10.000 ARS', () => {
    expect(roundArs10k(585000)).toBe(590000);
    expect(roundArs10k(584999)).toBe(580000);
  });

  it('usa precio scrapeado en USD o EUR y cae a listPrice oficial cuando falta', () => {
    const entries: CatalogEntry[] = [
      base({
        slug: 'scraped-usd',
        ml: { price: 500000, url: 'https://meli.la/1', checked: '2026-10-30' },
        listPrice: { amount: 400, currency: 'USD', source: 'https://x.test', checked: '2026-10-01' },
      }),
      base({
        slug: 'scraped-eur',
        store: 'ES',
        ml: { price: 500000, url: 'https://meli.la/2', checked: '2026-10-30' },
      }),
      base({
        slug: 'fallback-oficial',
        ml: { price: 500000, url: 'https://meli.la/3', checked: '2026-10-30' },
        listPrice: { amount: 300, sale: 250, currency: 'USD', source: 'https://x.test', checked: '2026-10-15' },
      }),
      base({
        slug: 'sin-fuente',
        ml: { price: 500000, url: 'https://meli.la/4', checked: '2026-10-30' },
      }),
      base({
        slug: 'sin-ml',
        listPrice: { amount: 250, currency: 'USD', source: 'https://x.test', checked: '2026-10-15' },
      }),
      base({
        slug: 'sin-asin',
        asin: '',
        ml: { price: 500000, url: 'https://meli.la/5', checked: '2026-10-30' },
        listPrice: { amount: 250, currency: 'USD', source: 'https://x.test', checked: '2026-10-15' },
      }),
    ];
    const amazonPrices: AmazonPrices = {
      generatedAt: '2026-10-31T10:00:00Z',
      date: '2026-10-31',
      items: {
        'scraped-usd': { amount: 250, currency: 'USD', checked: '2026-10-31' },
        'scraped-eur': { amount: 200, currency: 'EUR', checked: '2026-10-31' },
      },
    };
    const now = Date.parse('2026-10-31T12:00:00-03:00');
    const merged = mergeAmazonPrices(entries, amazonPrices, 1200, 1.25, now);
    // 250 USD @ 1200 MEP -> 375.000 -> redondeado a 10.000 = 380.000
    expect(merged[0]).toMatchObject({ amazonArs: 380000, amazonSource: 'amazon', amazonChecked: '2026-10-31' });
    // 200 EUR * 1.25 = 250 USD @ 1200 MEP -> 380.000
    expect(merged[1]).toMatchObject({ amazonArs: 380000, amazonSource: 'amazon', amazonChecked: '2026-10-31' });
    // listPrice.sale = 250 USD @ 1200 MEP -> 380.000
    expect(merged[2]).toMatchObject({ amazonArs: 380000, amazonSource: 'oficial', amazonChecked: '2026-10-15' });
    expect(merged[3]).toMatchObject({ amazonArs: null, amazonSource: null, amazonChecked: null });

    expect(merged.filter((p) => isComparable(p)).map((p) => p.slug)).toEqual([
      'scraped-usd',
      'scraped-eur',
      'fallback-oficial',
    ]);
  });

  it('descarta precios scrapeados de Amazon con más de 3 días de antigüedad', () => {
    const now = Date.parse('2026-10-31T12:00:00-03:00');
    const entries: CatalogEntry[] = [
      base({
        slug: 'tres-dias',
        ml: { price: 500000, url: 'https://meli.la/1', checked: '2026-10-31' },
      }),
      base({
        slug: 'vencido-con-oficial',
        ml: { price: 500000, url: 'https://meli.la/2', checked: '2026-10-31' },
        listPrice: { amount: 400, currency: 'USD', source: 'https://x.test', checked: '2026-10-01' },
      }),
      base({
        slug: 'vencido-sin-oficial',
        ml: { price: 500000, url: 'https://meli.la/3', checked: '2026-10-31' },
      }),
    ];
    const amazonPrices: AmazonPrices = {
      generatedAt: '2026-10-31T10:00:00Z',
      date: '2026-10-31',
      items: {
        'tres-dias': { amount: 250, currency: 'USD', checked: '2026-10-28' }, // 3 días -> válido
        'vencido-con-oficial': { amount: 250, currency: 'USD', checked: '2026-10-27' }, // 4 días -> cae a oficial
        'vencido-sin-oficial': { amount: 250, currency: 'USD', checked: '2026-10-27' }, // 4 días -> null
      },
    };
    const merged = mergeAmazonPrices(entries, amazonPrices, 1200, 1.25, now);
    expect(merged[0]).toMatchObject({ amazonArs: 380000, amazonSource: 'amazon', amazonChecked: '2026-10-28' });
    // 400 USD @ 1200 MEP -> 600.000 ARS desde listPrice oficial
    expect(merged[1]).toMatchObject({ amazonArs: 600000, amazonSource: 'oficial', amazonChecked: '2026-10-01' });
    expect(merged[2]).toMatchObject({ amazonArs: null, amazonSource: null, amazonChecked: null });
    expect(isComparable(entries[2], amazonPrices, now)).toBe(false);
    expect(isComparable(entries[0], amazonPrices, now)).toBe(true);
  });

  it('recalcula el veredicto y el ahorro desde los mismos montos mostrados (comparePrices)', () => {
    const now = Date.parse('2026-10-31T12:00:00-03:00');
    const entries: CatalogEntry[] = [
      // Caso 1: venía con verdict="amazon" pero el estimado en ARS supera al precio de ML -> debe pasar a "ml"
      base({
        slug: 'amazon-mas-caro',
        verdict: 'amazon',
        shipsToAr: { freeShipping: true, checked: '2026-10-01' },
        ml: { price: 350000, url: 'https://meli.la/1', checked: '2026-10-31' },
        listPrice: { amount: 250, currency: 'USD', source: 'https://x.test', checked: '2026-10-01' }, // -> 380.000 ARS
      }),
      // Caso 2: venía con verdict="ml" pero Amazon ahorra >= 10% con envío gratis -> debe pasar a "amazon"
      base({
        slug: 'amazon-gana',
        verdict: 'ml',
        shipsToAr: { freeShipping: true, checked: '2026-10-01' },
        ml: { price: 500000, url: 'https://meli.la/2', checked: '2026-10-31' },
        listPrice: { amount: 250, currency: 'USD', source: 'https://x.test', checked: '2026-10-01' }, // -> 380.000 ARS (ahorra 24%)
      }),
      // Caso 3: ahorra >= 10% pero sin envío gratis -> gana "ml"
      base({
        slug: 'sin-envio-gratis',
        verdict: 'amazon',
        shipsToAr: { freeShipping: false, checked: '2026-10-01' },
        ml: { price: 500000, url: 'https://meli.la/3', checked: '2026-10-31' },
        listPrice: { amount: 250, currency: 'USD', source: 'https://x.test', checked: '2026-10-01' },
      }),
    ];
    const merged = mergeAmazonPrices(entries, null, 1200, 1.25, now);
    expect(merged[0]).toMatchObject({ amazonArs: 380000, verdict: 'ml', verdictReason: 'precio' });
    expect(comparePrices(merged[0])).toEqual({ verdict: 'ml', saving: 30000 });

    expect(merged[1]).toMatchObject({ amazonArs: 380000, verdict: 'amazon', verdictReason: 'precio' });
    expect(comparePrices(merged[1])).toEqual({ verdict: 'amazon', saving: 120000 });

    expect(merged[2]).toMatchObject({ amazonArs: 380000, verdict: 'ml', verdictReason: 'precio' });
    expect(comparePrices(merged[2])).toEqual({ verdict: 'ml', saving: 0 });
  });

  it('filtra slugs del sitemap con la misma comparación calculada (requiere MEP y EUR/USD)', () => {
    const now = Date.parse('2026-10-31T12:00:00-03:00');
    const entries: CatalogEntry[] = [
      base({
        slug: 'us-ok',
        ml: { price: 500000, url: 'https://meli.la/1', checked: '2026-10-31' },
        listPrice: { amount: 250, currency: 'USD', source: 'https://x.test', checked: '2026-10-01' },
      }),
      base({
        slug: 'es-eur',
        store: 'ES',
        ml: { price: 500000, url: 'https://meli.la/2', checked: '2026-10-31' },
        listPrice: { amount: 200, currency: 'EUR', source: 'https://x.test', checked: '2026-10-01' },
      }),
    ];
    // Sin MEP ninguna ficha tiene amazonArs calculado -> ninguna va al sitemap
    expect([...getComparableSlugs(entries, null, null, null, 1.25, now)]).toEqual([]);
    // Con MEP pero sin EUR/USD, sólo entra la de USD (la de EUR sería noindex)
    expect([...getComparableSlugs(entries, null, null, 1200, null, now)]).toEqual(['us-ok']);
    // Con MEP y EUR/USD entran ambas
    expect([...getComparableSlugs(entries, null, null, 1200, 1.25, now)]).toEqual(['us-ok', 'es-eur']);
  });
});
