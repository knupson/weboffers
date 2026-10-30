import { calculate } from "./calc";
import { fetchEurUsd, fetchRates } from "./dolar";
import type { ListPrice } from "./data";

/** Precio oficial vigente: el de oferta del fabricante si lo hay, si no el de lista. */
export const officialPrice = (lp: ListPrice) => lp.sale ?? lp.amount;

/**
 * Cargos de importación que Amazon cobra por encima del IVA. Medido el 30/10/2026 en
 * 15 productos con envío gratis a Argentina: el total cobrado fue 23% a 27% del precio.
 */
export const AMAZON_EXTRA = 0.04;

/**
 * Costo estimado puesto en casa, en pesos al MEP, con el precio oficial del fabricante.
 * Sólo vale para productos verificados con envío gratis a Argentina (sin envío que sumar).
 */
export function estimateArs(lp: ListPrice, mep: number, eurUsd: number | null): number | null {
  const toUsd = lp.currency === "EUR" ? eurUsd : 1;
  if (!toUsd || !(mep > 0)) return null;
  const fobUsd = officialPrice(lp) * toUsd;
  const r = calculate({ fobUsd, shippingUsd: 0 }, { mep, tarjeta: 0 });
  return Math.round((r.totalUsd + fobUsd * AMAZON_EXTRA) * mep);
}

/** Medido el 30/10/2026: desde USD 100 el envío a Argentina es gratis en productos elegibles; debajo ronda USD 45. */
export const shippingFor = (usd: number) => (usd >= 100 ? 0 : 45);

/** Puesto en casa, en pesos al MEP, a partir del precio que la persona ve hoy en Amazon.com. */
export function estimateFromAmazon(usd: number, mep: number): number {
  const r = calculate({ fobUsd: usd, shippingUsd: shippingFor(usd) }, { mep, tarjeta: 0 });
  return Math.round((r.totalUsd + usd * AMAZON_EXTRA) * mep);
}

let cached: Promise<{ mep: number | null; eurUsd: number | null }> | null = null;

/** Cotizaciones del momento del build, pedidas una sola vez por build. */
export function buildQuotes() {
  cached ??= Promise.all([fetchRates(), fetchEurUsd()]).then(([r, eurUsd]) => ({ mep: r?.mep ?? null, eurUsd }));
  return cached;
}
