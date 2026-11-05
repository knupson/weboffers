import { describe, expect, it } from 'vitest';
import { mergeMlPrices, mergeAmazonPrices, type CatalogEntry } from './data';
import { calculateAmazon, estimateFromAmazon, shippingFor } from './estimate';
import { bestNewPrice } from '../worker';

const now = Date.parse('2026-11-05T12:00:00Z');
const catalog = [{ slug: 'p', asin: 'NEW', store: 'US', ml: { catalogId: 'MLANEW' } }] as CatalogEntry[];

it('descarta identificadores cruzados y acepta registros anteriores sin identificador', () => {
  for (const catalogId of ['OLD', 'MLANEW', undefined]) {
    const prices = { date: '2026-11-05', generatedAt: '', items: { p: { catalogId, price: 500000, checked: '2026-11-05' } } };
    expect(Boolean(mergeMlPrices(catalog, prices, now)[0].ml)).toBe(catalogId !== 'OLD');
  }
  for (const asin of ['OLD', 'NEW', undefined]) {
    const prices = { date: '2026-11-05', generatedAt: '', items: { p: { asin, amount: 200, currency: 'USD' as const, checked: '2026-11-05' } } };
    expect(Boolean(mergeAmazonPrices(catalog, prices, 1000, 1.1, now)[0].amazonArs)).toBe(asin !== 'OLD');
  }
});

it.each([
  { tags: ['cbt'] }, { tags: ['cbt_fulfillment'] }, { shipping: { tags: ['cbt'] } },
  { international_delivery_mode: 'DDP' }, { currency_id: 'USD' }, { currency_id: null },
])('descarta compras internacionales y monedas incorrectas: %j', fields => {
  expect(bestNewPrice([{ price: 1, ...fields }, { price: 100, currency_id: 'ARS' }])).toBe(100);
});

describe('calculo compartido por tarjetas y calculadora', () => {
  it.each([100, 200, 400, 450, 123.45])('incluye el 4%% para USD y EUR convertido (%s)', usd => {
    const calculation = calculateAmazon({ fobUsd: usd, shippingUsd: shippingFor(usd) }, { mep: 1234, tarjeta: 1500 });
    expect(calculation.totalArsMep).toBe(estimateFromAmazon(usd, 1234));
    expect(calculation.amazonExtraUsd).toBe(usd * 0.04);
  });
  it('permite envio y derechos personalizados', () => {
    const result = calculateAmazon({ fobUsd: 500, shippingUsd: 20, dutyRate: 0.1 }, { mep: 1000, tarjeta: 1500 });
    expect(result.totalUsd).toBe(664.93);
    expect(result.totalArsMep).toBe(664930);
  });
});
