/**
 * Configuración central de Afiliados, Atribución y Cumplimiento Legal
 * FRANQUICIA 400 · KnuNet (ofertas.knunet.com)
 */
export const AFFILIATE_CONFIG = {
  brandCode: "F400",
  siteName: "FRANQUICIA 400",
  parentBrand: "KnuNet",
  parentUrl: "https://knunet.com",
  siteUrl: "https://ofertas.knunet.com",
  siteTagline: "Monitor técnico y simulador aduanero Courier Argentina (RG 5617)",
  // ID de seguimiento de Amazon Associates EE.UU.
  amazonUsTag: import.meta.env.VITE_AMAZON_US_TAG || "knunet-20",
  // ID de seguimiento de Amazon Afiliados España
  amazonEsTag: import.meta.env.VITE_AMAZON_ES_TAG || "knunet-21",
  // Canal de Telegram donde el worker de la Raspberry Pi 4 publica alertas
  telegramChannelUrl: import.meta.env.VITE_TELEGRAM_URL || "https://t.me/franquicia400",
  // Divulgación obligatoria exigida por la Sección 5 del Acuerdo Operativo de Amazon Associates
  amazonDisclosureShort:
    "En calidad de Afiliado de Amazon, obtengo ingresos por las compras adscritas que cumplen los requisitos aplicables.",
  priceDisclaimer:
    "Los precios en USD/EUR, costos de envío AmazonGlobal y disponibilidad son referenciales y pueden variar sin previo aviso. Rige el importe final exhibido en el checkout de Amazon.com o Amazon.es al momento de la compra.",
};

/**
 * Genera el enlace de afiliado hacia la ficha del producto en Amazon EE.UU. o España a partir del ASIN.
 */
export function buildAmazonAffiliateUrl(
  asin: string,
  store: "US" | "ES" = "US"
): string {
  if (store === "ES") {
    return `https://www.amazon.es/dp/${asin}?tag=${AFFILIATE_CONFIG.amazonEsTag}&linkCode=ll1`;
  }
  return `https://www.amazon.com/dp/${asin}?tag=${AFFILIATE_CONFIG.amazonUsTag}&linkCode=ll1&language=es_US`;
}

/**
 * Genera un enlace de búsqueda monetizado en Amazon EE.UU. o España.
 */
export function buildAmazonSearchAffiliateUrl(
  query: string,
  store: "US" | "ES" = "US"
): string {
  const encoded = encodeURIComponent(query.trim() || "monitor gaming 27 qhd");
  if (store === "ES") {
    return `https://www.amazon.es/s?k=${encoded}&tag=${AFFILIATE_CONFIG.amazonEsTag}`;
  }
  return `https://www.amazon.com/s?k=${encoded}&tag=${AFFILIATE_CONFIG.amazonUsTag}&language=es_US`;
}
