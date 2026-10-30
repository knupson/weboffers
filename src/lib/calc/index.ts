import type { CalcInput, CalcResult, Rates } from './types';

export type { CalcInput, CalcResult, Rates } from './types';

const nonNegative = (value: number): number =>
  Number.isNaN(value) || value < 0 ? 0 : value;
const cents = (value: number): number => Math.round(value * 100) / 100;

function convert(total: number, rate: number | undefined): number | null {
  return typeof rate === 'number' && Number.isFinite(rate) && rate > 0
    ? cents(total * rate)
    : null;
}

export function calculate(input: CalcInput, rates: Rates | null): CalcResult {
  const fobUsd = nonNegative(input.fobUsd);
  const shippingUsd = nonNegative(input.shippingUsd);
  const ivaRate = nonNegative(input.ivaRate ?? 0.21);
  const dutyRate = nonNegative(input.dutyRate ?? 0.35);
  const weightKg = nonNegative(input.weightKg ?? 0);
  const excessUsd = Math.max(0, fobUsd - 400);
  const dutyUsd = excessUsd * dutyRate;
  const statFeeUsd = excessUsd * 0.03;
  const ivaBaseUsd = fobUsd + shippingUsd + dutyUsd + statFeeUsd;
  const ivaUsd = ivaBaseUsd * ivaRate;
  const totalUsd = ivaBaseUsd + ivaUsd;
  const warnings = ['El régimen permite hasta 5 envíos por año.'];

  if (fobUsd > 3000) warnings.push('El FOB supera USD 3000 y queda fuera del régimen courier.');
  if (weightKg > 50) warnings.push('El peso supera el límite de 50 kg por envío.');

  return {
    fobUsd: cents(fobUsd),
    shippingUsd: cents(shippingUsd),
    excessUsd: cents(excessUsd),
    dutyUsd: cents(dutyUsd),
    statFeeUsd: cents(statFeeUsd),
    ivaBaseUsd: cents(ivaBaseUsd),
    ivaUsd: cents(ivaUsd),
    totalUsd: cents(totalUsd),
    totalArsMep: convert(totalUsd, rates?.mep),
    totalArsTarjeta: convert(totalUsd, rates?.tarjeta),
    warnings,
  };
}
