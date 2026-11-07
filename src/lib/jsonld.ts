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
  const prices = [product.ml!.price, product.amazonArs!];
  const expires = new Date(`${product.ml!.checked}T00:00:00Z`);
  expires.setUTCDate(expires.getUTCDate() + 1);
  return { ...base, offers: {
    "@type": "AggregateOffer", priceCurrency: "ARS", offerCount: 2,
    lowPrice: Math.min(...prices), highPrice: Math.max(...prices),
    priceValidUntil: expires.toISOString().slice(0, 10),
    availability: "https://schema.org/InStock",
  } };
}
