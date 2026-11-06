import { expect, it } from "vitest";
import { artDate, isFreshAmazonDate, isComparable, comparableChecks, type CatalogEntry, type AmazonPrices } from "./data";
const ARSHIPPING_MAX_DAYS = 14;
function isFreshArShippingDate(checked: unknown, now: number): checked is string {
  if (typeof checked !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(checked)) return false;
  const checkedMs = Date.parse(`${checked}T00:00:00Z`);
  if (!Number.isFinite(checkedMs) || new Date(checkedMs).toISOString().slice(0, 10) !== checked) return false;
  const age = (Date.parse(`${artDate(now)}T00:00:00Z`) - checkedMs) / (24 * 60 * 60 * 1000);
  return age >= 0 && age <= ARSHIPPING_MAX_DAYS;
}
function oldIsComparable(entry: CatalogEntry, amazonPrices?: AmazonPrices | null, now = Date.now(), eurUsd = 1.08): boolean {
  const today = artDate(now);
  // Amazon no envía este producto a Argentina (relevamiento vigente): no hay comparación posible.
  if (entry.shipsToArToday === false) {
    return false;
  }
  // REGLA 0 del user (03/11): un comparador necesita los dos lados completos. El de Amazon es «puesto en tu casa»:
  // sin envío gratis a Argentina confirmado (catálogo o relevamiento de ≤14 días) no hay total, y no se publica.
  if (entry.shipsToAr?.freeShipping !== true || !isFreshArShippingDate(entry.shipsToAr.checked, now)) {
    return false;
  }
  if (
    !entry.verified ||
    !entry.asin ||
    // Regla del user: producto sin foto no se publica.
    !entry.image ||
    !entry.ml ||
    !Number.isFinite(entry.ml.price) ||
    !(entry.ml.price > 0) ||
    entry.ml.checked !== today
  ) {
    return false;
  }
  if ("amazonArs" in entry) {
    return (
      typeof entry.amazonArs === "number" &&
      Number.isFinite(entry.amazonArs) &&
      entry.amazonArs > 0 &&
      typeof entry.amazonUsd === "number" &&
      Number.isFinite(entry.amazonUsd) &&
      entry.amazonUsd >= 100 && entry.amazonUsd <= 400 &&
      entry.amazonSource === "amazon" &&
      entry.amazonChecked === today
    );
  }
  const items = amazonPrices?.items ?? {};
  const raw = Object.prototype.hasOwnProperty.call(items, entry.slug) ? items[entry.slug] : undefined;
  const scraped = raw && (raw.asin === undefined || raw.asin === entry.asin) ? raw : undefined;
  const usd = scraped?.amount != null ? scraped.amount * (scraped.currency === "EUR" ? eurUsd : 1) : NaN;
  return Boolean(
    scraped &&
      (scraped.currency === "USD" || scraped.currency === "EUR") &&
      usd >= 100 && usd <= 400 &&
      typeof scraped.amount === "number" &&
      Number.isFinite(scraped.amount) &&
      scraped.amount > 0 &&
      isFreshAmazonDate(scraped.checked, now),
  );
}

const now = Date.parse('2026-11-06T15:00:00Z');
const base = {
  slug: 'kindle-paperwhite', asin: 'B0CFPJYX7P', store: 'US', verified: true, image: '/kindle.webp',
  shipsToAr: { freeShipping: true, checked: '2026-11-06' },
  ml: { price: 650000, checked: '2026-11-06', url: 'https://mercadolibre.com.ar/p/MLA123' },
} as CatalogEntry;

it('conserva el resultado anterior en ambas ramas y con fallas simultáneas', () => {
  const patches: Partial<CatalogEntry>[] = [
    {}, { shipsToArToday: false }, { shipsToArToday: true }, { verified: false }, { asin: '' },
    { image: '' }, { image: undefined }, { ml: undefined },
    ...[0, -1, NaN, Infinity, 650000].map(price => ({ ml: { ...base.ml!, price } })),
    ...['2026-11-05', '2026-11-06', '2026-11-07', 'invalida'].map(checked => ({ ml: { ...base.ml!, checked } })),
    { shipsToAr: undefined }, { shipsToAr: { freeShipping: false, checked: '2026-11-06' } },
    ...['2026-10-22', '2026-10-23', '2026-11-07', '2026-02-30', 'invalida'].map(checked => ({ shipsToAr: { freeShipping: true, checked } })),
  ];
  for (const amount of [undefined, -1, 0, 99.99, 100, 200, 400, 400.01, NaN, Infinity, '200']) {
    for (const currency of ['USD', 'EUR', 'ARS', undefined]) {
      for (const checked of ['2026-11-06', '2026-11-05', 'invalida']) {
        for (const asin of [base.asin, 'OTRO', undefined]) {
          const prices = { items: { [base.slug]: { amount, currency, checked, asin } } } as unknown as AmazonPrices;
          const merged = { amazonArs: 300000, amazonUsd: amount, amazonChecked: checked, amazonSource: 'amazon' };
          for (const patch of patches) {
            for (const entry of [{ ...base, ...patch }, { ...base, ...merged, ...patch } as CatalogEntry]) {
              expect(isComparable(entry, prices, now, 1.25)).toBe(oldIsComparable(entry, prices, now, 1.25));
            }
          }
        }
      }
    }
  }
  for (const patch of [{ amazonArs: null }, { amazonArs: 0 }, { amazonArs: Infinity }, { amazonSource: null }]) {
    const entry = { ...base, amazonArs: 300000, amazonUsd: 200, amazonSource: 'amazon', amazonChecked: '2026-11-06', ...patch } as CatalogEntry;
    expect(isComparable(entry, null, now)).toBe(oldIsComparable(entry, null, now));
  }
  expect(isComparable(base, null, now)).toBe(oldIsComparable(base, null, now));
});

it('evalúa todos los filtros en orden aunque fallen los primeros', () => {
  const checks = comparableChecks({ ...base, verified: false, ml: undefined, amazonArs: null }, null, now);
  expect(checks.map(c => c.filtro)).toEqual(['envia_ar', 'envio_gratis', 'verificado', 'asin', 'imagen', 'ml_presente', 'ml_precio', 'ml_hoy', 'amazon_ars', 'amazon_usd', 'amazon_rango', 'amazon_fuente', 'amazon_hoy']);
  expect(checks.filter(c => !c.ok).map(c => c.filtro)).toContain('amazon_hoy');
});
