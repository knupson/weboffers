import { calculate, type CalcInput, type Rates } from "./calc";
import { fetchEurUsd, fetchRates } from "./dolar";
import type { ListPrice } from "./data";

/** Precio oficial vigente: el de oferta del fabricante si lo hay, si no el de lista. */
export const officialPrice = (lp: ListPrice) => lp.sale ?? lp.amount;

/**
 * Cargos de importación que Amazon cobra por encima del IVA. Medido el 30/10/2026 en
 * 15 productos con envío gratis a Argentina: el total cobrado fue 23% a 27% del precio.
 */
export const AMAZON_EXTRA = 0.04;

/** Medido el 30/10/2026: desde USD 100 el envío a Argentina es gratis en productos elegibles; debajo ronda USD 45. */
export const shippingFor = (usd: number) => (usd >= 100 ? 0 : 45);

/** Costo total en USD puesto en casa (impuestos + envío + 4% de Amazon), igual que amazon_total_usd en worker/ml_prices.py. */
export function calculateAmazon(input: CalcInput, rates: Rates | null) {
  const result = calculate(input, rates);
  const gross = result.totalUsd + input.fobUsd * AMAZON_EXTRA;
  const totalUsd = Math.round(gross * 100) / 100;
  return { ...result, totalUsd, amazonExtraUsd: input.fobUsd * AMAZON_EXTRA,
    totalArsMep: rates && rates.mep > 0 ? Math.round(gross * rates.mep) : null,
    totalArsTarjeta: rates && rates.tarjeta > 0 ? Math.round(gross * rates.tarjeta) : null };
}

export function amazonTotalUsd(usd: number): number {
  return calculateAmazon({ fobUsd: usd, shippingUsd: shippingFor(usd) }, null).totalUsd;
}

export function estimateFromAmazon(usd: number, mep: number): number {
  return calculateAmazon({ fobUsd: usd, shippingUsd: shippingFor(usd) }, { mep, tarjeta: 0 }).totalArsMep!;
}

/**
 * Costo estimado puesto en casa, en pesos al MEP, con el precio oficial del fabricante.
 */
export function estimateArs(lp: ListPrice, mep: number, eurUsd: number | null): number | null {
  const toUsd = lp.currency === "EUR" ? eurUsd : 1;
  if (!toUsd || !(mep > 0)) return null;
  const fobUsd = officialPrice(lp) * toUsd;
  return estimateFromAmazon(fobUsd, mep);
}

let cached: Promise<{ mep: number | null; eurUsd: number | null }> | null = null;

/** Cotizaciones del momento del build, pedidas una sola vez por build. */
export function buildQuotes() {
  cached ??= Promise.all([fetchRates(), fetchEurUsd()]).then(([r, eurUsd]) => ({ mep: r?.mep ?? null, eurUsd }));
  return cached;
}
