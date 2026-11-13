// «Bajó de precio» (13/11): bajada real del precio de Amazon en la última semana, con el historial diario que
// guarda worker/publish.py (output/historial/AAAA-MM-DD-amazon-prices.json). El deployer lo resume en
// data/historial-amazon.json: {"AAAA-MM-DD": {"slug": precioUsd}} sólo con precios relevados ESE día (checked == fecha).
//
// Reglas (Alejandro, 13/11), todas obligatorias:
// 1. Al menos MIN_DIAS días con precio en los VENTANA_DIAS anteriores a hoy (sin altas recién llegadas).
// 2. El precio de hoy bajó al menos MIN_PCT o MIN_USD contra la MEDIANA de esos días.
// 3. El precio de hoy es el mínimo de la ventana (si ayer subió de golpe, no cuenta como bajada).
// Nunca se muestra un precio tachado: sólo cuánto bajó contra la mediana de la semana.

export type HistorialAmazon = Record<string, Record<string, number>>;

export interface Bajada {
  /** Cuánto bajó contra la mediana de la semana, en USD enteros. */
  usd: number;
  medianaUsd: number;
  dias: number;
}

export const VENTANA_DIAS = 7;
export const MIN_DIAS = 3;
export const MIN_PCT = 0.05;
export const MIN_USD = 10;

const FECHA = /^\d{4}-\d{2}-\d{2}$/;

function restarDias(fecha: string, dias: number): string {
  const d = new Date(`${fecha}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - dias);
  return d.toISOString().slice(0, 10);
}

function mediana(valores: number[]): number {
  const v = [...valores].sort((a, b) => a - b);
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

const valido = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n) && n > 0;

/**
 * Precios del slug en los VENTANA_DIAS días anteriores a `hoy` (no incluye hoy). `hoy` es la fecha ART del
 * precio actual; el historial de hoy se ignora porque el precio actual ya es el del día.
 */
export function preciosPrevios(slug: string, hoy: string, historial: HistorialAmazon | null | undefined): number[] {
  if (!historial || !FECHA.test(hoy)) return [];
  const desde = restarDias(hoy, VENTANA_DIAS);
  return Object.entries(historial)
    .filter(([fecha]) => FECHA.test(fecha) && fecha >= desde && fecha < hoy)
    .map(([, precios]) => precios?.[slug])
    .filter(valido);
}

export function bajadaDePrecio(slug: string, actualUsd: number | null | undefined, hoy: string,
  historial: HistorialAmazon | null | undefined): Bajada | null {
  if (!valido(actualUsd)) return null;
  const previos = preciosPrevios(slug, hoy, historial);
  if (previos.length < MIN_DIAS) return null;
  if (actualUsd > Math.min(...previos)) return null;
  const med = mediana(previos);
  const baja = med - actualUsd;
  if (!(baja > 0) || (baja < MIN_USD && baja / med < MIN_PCT)) return null;
  const usd = Math.round(baja);
  if (usd < 1) return null;
  return { usd, medianaUsd: Math.round(med * 100) / 100, dias: previos.length };
}

export const etiquetaBajada = (b: Pick<Bajada, "usd">) => `Bajó USD ${b.usd} esta semana`;
