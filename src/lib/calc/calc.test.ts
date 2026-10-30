import { describe, expect, it } from 'vitest';
import { calculate, type Rates } from './index';

const rates: Rates = { mep: 1200, tarjeta: 1500, oficial: 1000 };

describe('calculate', () => {
  it('applies default IVA below the allowance', () => {
    expect(calculate({ fobUsd: 279, shippingUsd: 54 }, null)).toMatchObject({
      fobUsd: 279, shippingUsd: 54, excessUsd: 0, dutyUsd: 0,
      statFeeUsd: 0, ivaBaseUsd: 333, ivaUsd: 69.93, totalUsd: 402.93,
    });
  });

  it('exempts exactly USD 400 FOB', () => {
    expect(calculate({ fobUsd: 400, shippingUsd: 0 }, null)).toMatchObject({
      excessUsd: 0, dutyUsd: 0, statFeeUsd: 0,
    });
  });

  it('taxes only the excess and includes duties in the IVA base', () => {
    expect(calculate({ fobUsd: 450, shippingUsd: 0 }, null)).toMatchObject({
      excessUsd: 50, dutyUsd: 17.5, statFeeUsd: 1.5,
      ivaBaseUsd: 469, ivaUsd: 98.49, totalUsd: 567.49,
    });
  });

  it('warns about courier limits and the yearly shipment allowance', () => {
    const result = calculate({ fobUsd: 3001, shippingUsd: 0, weightKg: 51 }, null);
    expect(result.warnings).toEqual(expect.arrayContaining([
      expect.stringContaining('3000'), expect.stringContaining('5 envíos'),
      expect.stringContaining('50 kg'),
    ]));
    const boundary = calculate({ fobUsd: 3000, shippingUsd: 0, weightKg: 50 }, null);
    expect(boundary.warnings).toHaveLength(1);
    expect(calculate({ fobUsd: 0, shippingUsd: 0 }, null).warnings)
      .toEqual([expect.stringContaining('5 envíos')]);
  });

  it('uses 21 percent IVA by default', () => {
    const standard = calculate({ fobUsd: 100, shippingUsd: 0 }, null);
    expect(standard.ivaUsd).toBe(21);
    expect(standard.warnings).toHaveLength(1);
  });

  it('converts using each supplied rate', () => {
    expect(calculate({ fobUsd: 279, shippingUsd: 54 }, rates)).toMatchObject({
      totalArsMep: 483516, totalArsTarjeta: 604395,
    });
  });

  it('returns null ARS values when rates are absent', () => {
    expect(calculate({ fobUsd: 100, shippingUsd: 0 }, null)).toMatchObject({
      totalArsMep: null, totalArsTarjeta: null,
    });
  });

  it.each([-1, NaN, 0, Infinity, -Infinity])('rejects invalid exchange rate %s independently', (rate) => {
    expect(calculate({ fobUsd: 100, shippingUsd: 0 }, { mep: rate, tarjeta: 2 }))
      .toMatchObject({ totalArsMep: null, totalArsTarjeta: 242 });
    expect(calculate({ fobUsd: 100, shippingUsd: 0 }, { mep: 2, tarjeta: rate }))
      .toMatchObject({ totalArsMep: 242, totalArsTarjeta: null });
  });

  it.each([-10, NaN])('clamps invalid input %s to zero', (value) => {
    expect(calculate({ fobUsd: value, shippingUsd: value, weightKg: value }, null))
      .toMatchObject({ fobUsd: 0, shippingUsd: 0, totalUsd: 0 });
    expect(calculate({ fobUsd: 450, shippingUsd: 0, ivaRate: value, dutyRate: value }, null))
      .toMatchObject({ dutyUsd: 0, ivaUsd: 0, totalUsd: 451.5 });
  });

  it('accepts zero and custom tax rates', () => {
    expect(calculate({ fobUsd: 450, shippingUsd: 0, ivaRate: 0, dutyRate: 0 }, null))
      .toMatchObject({ dutyUsd: 0, ivaUsd: 0, totalUsd: 451.5 });
    expect(calculate({ fobUsd: 450, shippingUsd: 0, dutyRate: 0.1 }, null).dutyUsd).toBe(5);
  });

  it('rounds outputs without rounding intermediate tax or conversion amounts', () => {
    const input = Object.freeze({ fobUsd: 400.014, shippingUsd: 0.014 });
    const fixedRates = Object.freeze({ mep: 3, tarjeta: 4 });
    const result = calculate(input, fixedRates);
    const base = 400.014 + 0.014 + 0.014 * 0.35 + 0.014 * 0.03;
    const total = base * 1.21;
    expect(result.fobUsd).toBe(400.01);
    expect(result.totalUsd).toBe(Math.round(total * 100) / 100);
    expect(result.totalArsMep).toBe(Math.round(total * 3 * 100) / 100);
    expect(result.totalArsTarjeta).toBe(Math.round(total * 4 * 100) / 100);
  });
});
