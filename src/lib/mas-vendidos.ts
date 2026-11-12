import type { CatalogEntry } from "./data";

/** Días que vale la marca de «Lo más vendido» de Mercado Libre: la sección dice «esta semana». */
export const MAS_VENDIDOS_DIAS = 7;
/** Una fila de la grilla tiene 3 columnas: con menos, la sección no se muestra (12/11 quedó una fila incompleta). */
export const MAS_VENDIDOS_MINIMO = 3;

function dias(desde: string, hasta: string): number {
  return (Date.parse(`${hasta}T00:00:00Z`) - Date.parse(`${desde}T00:00:00Z`)) / 86_400_000;
}

/**
 * Productos de «Lo más vendido esta semana». 12/11: la marca `hot` era del 02/11 (cargada a mano y nunca
 * renovada) y la portada mostraba 2 tarjetas con el título «esta semana». Regla 2: nada viejo; sólo marcas de
 * los últimos 7 días, y la sección sólo con una fila completa.
 */
export function masVendidos(products: CatalogEntry[], hoy: string): CatalogEntry[] {
  const frescos = products.filter((p) => p.hot && dias(p.hot, hoy) >= 0 && dias(p.hot, hoy) <= MAS_VENDIDOS_DIAS);
  return frescos.length >= MAS_VENDIDOS_MINIMO ? frescos : [];
}
