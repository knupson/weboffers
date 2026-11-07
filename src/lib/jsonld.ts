import { isComparable, type CatalogEntry } from "./data";

export function productJsonLd(product: CatalogEntry, siteUrl: string, now = Date.now()): Record<string, unknown> {
  const base = {
    "@type": "Product", name: product.name,
    brand: { "@type": "Brand", name: product.brand },
    description: product.summary, category: product.category,
    ...(product.asin ? { sku: product.asin } : {}),
    ...(product.image ? { image: new URL(product.image, siteUrl).href } : {}),
  };
  if (!isComparable(product, null, now)) return base;
  // Sólo el precio real de Mercado Libre (el de Amazon es una estimación redondeada «puesto en tu casa»),
  // válido únicamente el día en que se relevó: si mañana no hay deploy, no queda declarado como vigente.
  return { ...base, offers: {
    "@type": "Offer", priceCurrency: "ARS", price: product.ml!.price,
    priceValidUntil: product.ml!.checked, url: product.ml!.url,
  } };
}
