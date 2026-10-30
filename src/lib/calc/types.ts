export type Rates = { mep: number; tarjeta: number; oficial?: number };

export type CalcInput = {
  fobUsd: number;
  shippingUsd: number;
  ivaRate?: number;
  dutyRate?: number;
  weightKg?: number;
};

export type CalcResult = {
  fobUsd: number;
  shippingUsd: number;
  excessUsd: number;
  dutyUsd: number;
  statFeeUsd: number;
  ivaBaseUsd: number;
  ivaUsd: number;
  totalUsd: number;
  totalArsMep: number | null;
  totalArsTarjeta: number | null;
  warnings: string[];
};
