import { artDate, comparePrices, isComparable, type CatalogEntry } from "./data";

export function rankToday(products: CatalogEntry[], pricesDate: string, now = Date.now()) {
  const comparable = pricesDate === artDate(now) ? products.filter((p) => isComparable(p, null, now)) : [];
  const rows = comparable.map((product) => ({ product, ...comparePrices(product) }));
  const ranked = (verdict: "amazon" | "ml") => rows.filter((r) => r.verdict === verdict)
    .sort((a, b) => b.saving - a.saving || a.product.slug.localeCompare(b.product.slug)).slice(0, 10);
  return { count: comparable.length, amazon: ranked("amazon"), ml: ranked("ml") };
}
