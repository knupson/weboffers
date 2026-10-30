export interface ExchangeRates {
  mep: number;
  tarjeta: number;
  oficial: number;
  updatedAt: string;
  isLive: boolean;
}

export interface CourierBreakdown {
  fobUsd: number;
  shippingUsd: number;
  cifUsd: number;
  qualifiesForFranchise: boolean;
  excessFobUsd: number;
  importDutyUsd: number;
  statisticalFeeUsd: number;
  vatRate: 0.105 | 0.21;
  vatUsd: number;
  totalTaxesUsd: number;
  finalTotalUsd: number;
  finalTotalArsMep: number;
  finalTotalArsTarjeta: number;
  savingsUsingMepArs: number;
  savingsUsingMepPercent: number;
  estimatedCommissionUsd: number;
}

export const FALLBACK_RATES: ExchangeRates = {
  mep: 1569,
  tarjeta: 1850,
  oficial: 1420,
  updatedAt: "Referencia local",
  isLive: false,
};

/**
 * Consulta en tiempo real la API pública DolarApi.com para obtener Dólar MEP, Tarjeta y Oficial en Argentina.
 */
export async function fetchLiveExchangeRates(): Promise<ExchangeRates> {
  try {
    const response = await fetch("https://dolarapi.com/v1/dolares");
    if (!response.ok) return FALLBACK_RATES;
    const data: Array<{ casa: string; venta: number; fechaActualizacion: string }> =
      await response.json();

    const bolsa = data.find((d) => d.casa === "bolsa")?.venta || FALLBACK_RATES.mep;
    const tarjeta = data.find((d) => d.casa === "tarjeta")?.venta || FALLBACK_RATES.tarjeta;
    const oficial = data.find((d) => d.casa === "oficial")?.venta || FALLBACK_RATES.oficial;
    const fecha = data.find((d) => d.casa === "bolsa")?.fechaActualizacion;

    return {
      mep: Math.round(bolsa),
      tarjeta: Math.round(tarjeta),
      oficial: Math.round(oficial),
      updatedAt: fecha
        ? new Date(fecha).toLocaleTimeString("es-AR", {
            hour: "2-digit",
            minute: "2-digit",
          })
        : "Hoy",
      isLive: true,
    };
  } catch {
    return FALLBACK_RATES;
  }
}

/**
 * Calcula la liquidación aduanera puerta a puerta en Argentina bajo el régimen de Pequeños Envíos Courier
 * (Decreto 1065/2024 y RG ARCA 5617/2024):
 * - Si FOB <= USD 400: Exento de derechos de importación y de tasa estadística (0%). Tributa únicamente IVA
 *   (10,5% para bienes de informática/tecnología alcanzados por alícuota reducida, o 21% régimen general) sobre base CIF.
 * - Si FOB > USD 400: Los primeros USD 400 FOB están exentos. El excedente sobre USD 400 tributa derechos de
 *   importación (~35% promedio) + tasa de estadística (3%) = 38% sobre el excedente, más el IVA correspondiente.
 */
export function calculateCourierArgentina(
  priceUsd: number,
  shippingUsd: number,
  rates: ExchangeRates,
  vatRate: 0.21 | 0.105 = 0.105,
  affiliateCommissionRate = 0.04
): CourierBreakdown {
  const fobUsd = Math.max(0, priceUsd);
  const shipUsd = Math.max(0, shippingUsd);
  const cifUsd = fobUsd + shipUsd;
  const qualifiesForFranchise = fobUsd <= 400;

  let excessFobUsd = 0;
  let importDutyUsd = 0;
  let statisticalFeeUsd = 0;
  let vatUsd = 0;

  if (qualifiesForFranchise) {
    importDutyUsd = 0;
    statisticalFeeUsd = 0;
    vatUsd = cifUsd * vatRate;
  } else {
    excessFobUsd = fobUsd - 400;
    importDutyUsd = excessFobUsd * 0.35;
    statisticalFeeUsd = excessFobUsd * 0.03;
    const taxableBase = cifUsd + importDutyUsd + statisticalFeeUsd;
    vatUsd = taxableBase * vatRate;
  }

  const totalTaxesUsd = importDutyUsd + statisticalFeeUsd + vatUsd;
  const finalTotalUsd = cifUsd + totalTaxesUsd;

  const finalTotalArsMep = Math.round(finalTotalUsd * rates.mep);
  const finalTotalArsTarjeta = Math.round(finalTotalUsd * rates.tarjeta);
  const savingsUsingMepArs = Math.max(0, finalTotalArsTarjeta - finalTotalArsMep);
  const savingsUsingMepPercent =
    finalTotalArsTarjeta > 0
      ? Math.round((savingsUsingMepArs / finalTotalArsTarjeta) * 100)
      : 0;

  const estimatedCommissionUsd = Number((fobUsd * affiliateCommissionRate).toFixed(2));

  return {
    fobUsd: Number(fobUsd.toFixed(2)),
    shippingUsd: Number(shipUsd.toFixed(2)),
    cifUsd: Number(cifUsd.toFixed(2)),
    qualifiesForFranchise,
    excessFobUsd: Number(excessFobUsd.toFixed(2)),
    importDutyUsd: Number(importDutyUsd.toFixed(2)),
    statisticalFeeUsd: Number(statisticalFeeUsd.toFixed(2)),
    vatRate,
    vatUsd: Number(vatUsd.toFixed(2)),
    totalTaxesUsd: Number(totalTaxesUsd.toFixed(2)),
    finalTotalUsd: Number(finalTotalUsd.toFixed(2)),
    finalTotalArsMep,
    finalTotalArsTarjeta,
    savingsUsingMepArs,
    savingsUsingMepPercent,
    estimatedCommissionUsd,
  };
}
