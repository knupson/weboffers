import { calculate } from "./calc";
import { fetchEurUsd, fetchRates } from "./dolar";
import type { ListPrice } from "./data";

/** Precio oficial vigente: el de oferta del fabricante si lo hay, si no el de lista. */
export const officialPrice = (lp: ListPrice) => lp.sale ?? lp.amount;

/**
 * Costo estimado puesto en casa, en pesos al MEP, con el precio oficial del fabricante.
 * No suma envío: Amazon suele enviar gratis a Argentina los productos elegibles.
 */
export function estimateArs(lp: ListPrice, mep: number, eurUsd: number | null): number | null {
  const toUsd = lp.currency === "EUR" ? eurUsd : 1;
  if (!toUsd || !(mep > 0)) return null;
  return calculate({ fobUsd: officialPrice(lp) * toUsd, shippingUsd: 0 }, { mep, tarjeta: 0 }).totalArsMep;
}

let cached: Promise<{ mep: number | null; eurUsd: number | null }> | null = null;

/** Cotizaciones del momento del build, pedidas una sola vez por build. */
export function buildQuotes() {
  cached ??= Promise.all([fetchRates(), fetchEurUsd()]).then(([r, eurUsd]) => ({ mep: r?.mep ?? null, eurUsd }));
  return cached;
}
