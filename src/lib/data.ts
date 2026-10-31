import fs from "node:fs";
import path from "node:path";
import type { Store } from "../config";
import { buildQuotes, estimateArs, estimateFromAmazon } from "./estimate";

export interface CatalogEntry {
  asin: string;
  store: Store;
  slug: string;
  name: string;
  brand: string;
  category: string;
  ncm?: string;
  weightKg?: number;
  voltage?: string;
  summary: string;
  verified: boolean;
  /** Foto oficial del fabricante, guardada en public/products. Nunca una imagen de Amazon. */
  image?: string;
  imageSource?: string;
  /** Precio oficial del fabricante, con su fuente. Nunca un precio de Amazon. */
  listPrice?: ListPrice;
  /** Verificado en Amazon con dirección en Argentina: se puede comprar y enviar. */
  shipsToAr?: { freeShipping: boolean; checked: string };
  /** Publicación más barata en Mercado Libre del mismo modelo, con link de afiliado. */
  ml?: { price: number; url: string; checked: string };
  /**
   * Dónde conviene comprarlo, comparando el total real de Amazon (no publicado) con Mercado Libre.
   * Traerlo sólo conviene si ahorra 10% o más: a igual precio gana Mercado Libre (entrega en días,
   * sin aduana, garantía local, cuotas y sin gastar uno de los 5 envíos anuales con franquicia).
   */
  verdict?: "amazon" | "ml";
  /** Por qué ganó Mercado Libre: por precio, o porque Amazon no lo envía a Argentina (sin ASIN comparable). */
  verdictReason?: "precio" | "sinAmazon";
  /** Fecha (AAAA-MM-DD) en que entró a "Lo más vendido" de Mercado Libre. */
  hot?: string;
  /** Total estimado puesto en casa en pesos al MEP, redondeado a 10.000 ARS. */
  amazonArs?: number | null;
  /** Fuente del estimado de Amazon: precio diario scrapeado ("amazon") o precio oficial del fabricante ("oficial"). */
  amazonSource?: "amazon" | "oficial" | null;
  /** Fecha (AAAA-MM-DD) del precio usado para el estimado de Amazon. */
  amazonChecked?: string | null;
}

export interface ListPrice {
  amount: number;
  /** Precio de oferta en la tienda oficial, si lo hay. */
  sale?: number;
  currency: "USD" | "EUR";
  source: string;
  /** Fecha de consulta, AAAA-MM-DD. */
  checked: string;
  /** Si no es de la marca: tienda de EE.UU. de referencia (nunca Amazon). */
  retailer?: string;
}

export interface OfferItem {
  asin: string;
  store: Store;
  title: string | null;
  priceUsd: number | null;
  priceFetchedAt: string | null;
  imageUrl: string | null;
  availability: string | null;
}

export interface Offers {
  generatedAt: string | null;
  mode: "api" | "offline";
  rates: {
    mep: number;
    tarjeta: number;
    oficial: number;
    fetchedAt: string;
    source: string;
  } | null;
  items: OfferItem[];
}

export const PRICE_MAX_AGE_MS = 24 * 60 * 60 * 1000;

const root = process.cwd();

function readJson<T>(rel: string): T | null {
  try {
    return JSON.parse(fs.readFileSync(path.join(root, rel), "utf-8")) as T;
  } catch {
    return null;
  }
}

/** Precio diario de Mercado Libre por slug (data/ml-prices.json). Lo escribe el proceso del worker. */
export interface MlPriceItem {
  price: number;
  /** Link de afiliado a la publicación de ese precio (la más barata del día). */
  url?: string;
  checked: string;
  verdict: "amazon" | "ml";
  verdictReason: "precio" | "sinAmazon";
}

export interface MlPrices {
  generatedAt: string;
  /** Fecha (AAAA-MM-DD) de la corrida. */
  date: string;
  items: Record<string, MlPriceItem>;
}

/** Precio diario de Amazon por slug (data/amazon-prices.json). Lo escribe el worker; nunca se publica en USD/EUR. */
export interface AmazonPriceItem {
  amount: number;
  currency: "USD" | "EUR";
  checked: string;
}

export interface AmazonPrices {
  generatedAt: string;
  date: string;
  items: Record<string, AmazonPriceItem>;
}

const VERDICTS: readonly string[] = ["amazon", "ml"];
const VERDICT_REASONS: readonly string[] = ["precio", "sinAmazon"];

/** Sólo links https de mercadolibre.com.ar: el archivo viene del worker, no se confía a ciegas. */
function isMlUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const u = new URL(value);
    return u.protocol === "https:" && (u.hostname === "mercadolibre.com.ar" || u.hostname.endsWith(".mercadolibre.com.ar"));
  } catch {
    return false;
  }
}

/** Redondea un monto en pesos al múltiplo de 10.000 ARS más cercano. */
export const roundArs10k = (n: number) => Math.round(n / 10000) * 10000;

/**
 * Pisa el precio de Mercado Libre del día sobre cada entrada del catálogo que ya tiene `ml`.
 * Sin archivo o sin item para el slug, la entrada sigue igual. No muta el catálogo original.
 */
export function mergeMlPrices(catalog: CatalogEntry[], prices: MlPrices | null): CatalogEntry[] {
  if (!prices) return catalog;
  const items = prices.items ?? {};
  return catalog.map((entry) => {
    if (!entry.ml || !Object.prototype.hasOwnProperty.call(items, entry.slug)) return entry;
    const item = items[entry.slug];
    if (!item || !Number.isFinite(item.price)) return entry;
    return {
      ...entry,
      ml: {
        ...entry.ml,
        price: item.price,
        url: isMlUrl(item.url) ? item.url : entry.ml.url,
        checked: item.checked ?? entry.ml.checked,
      },
      verdict: VERDICTS.includes(item.verdict) ? (item.verdict as CatalogEntry["verdict"]) : entry.verdict,
      verdictReason: VERDICT_REASONS.includes(item.verdictReason)
        ? (item.verdictReason as CatalogEntry["verdictReason"])
        : entry.verdictReason,
    };
  });
}

export const AMAZON_PRICE_MAX_AGE_DAYS = 3;
export const MIN_AMAZON_SAVING = 0.10;
const ART_OFFSET_MS = -3 * 60 * 60 * 1000;
const DAY_MS = 24 * 60 * 60 * 1000;

export interface PriceComparison {
  verdict: "amazon" | "ml";
  saving: number;
}

/**
 * Calcula el veredicto ("amazon" | "ml") y el ahorro redondeado a 10.000 ARS a partir de los mismos dos
 * montos mostrados en pantalla (`ml.price` y `amazonArs`). Amazon sólo gana si ahorra >= 10% y tiene envío gratis.
 */
export function comparePrices(
  entry: Pick<CatalogEntry, "ml" | "amazonArs" | "shipsToAr">,
): PriceComparison {
  const mlPrice = entry.ml?.price;
  const amazonArs = entry.amazonArs;
  if (
    typeof mlPrice !== "number" ||
    !Number.isFinite(mlPrice) ||
    mlPrice <= 0 ||
    typeof amazonArs !== "number" ||
    !Number.isFinite(amazonArs) ||
    amazonArs <= 0
  ) {
    return { verdict: "ml", saving: 0 };
  }
  const savingRatio = Math.round((1 - amazonArs / mlPrice) * 1e6) / 1e6;
  const verdict =
    entry.shipsToAr?.freeShipping === true && savingRatio >= MIN_AMAZON_SAVING ? "amazon" : "ml";
  const rawDiff = verdict === "amazon" ? mlPrice - amazonArs : amazonArs - mlPrice;
  const saving = rawDiff >= 5000 ? roundArs10k(rawDiff) : 0;
  return { verdict, saving };
}

/** Un precio diario de Amazon es vigente sólo si `checked` (AAAA-MM-DD) tiene a lo sumo 3 días en ART. */
export function isFreshAmazonDate(checked: unknown, now = Date.now()): checked is string {
  if (typeof checked !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(checked)) return false;
  const checkedMs = Date.parse(`${checked}T00:00:00Z`);
  if (!Number.isFinite(checkedMs) || new Date(checkedMs).toISOString().slice(0, 10) !== checked) return false;
  const todayArtStr = new Date(now + ART_OFFSET_MS).toISOString().slice(0, 10);
  const todayMs = Date.parse(`${todayArtStr}T00:00:00Z`);
  const ageDays = Math.round((todayMs - checkedMs) / DAY_MS);
  return ageDays >= 0 && ageDays <= AMAZON_PRICE_MAX_AGE_DAYS;
}

/**
 * Calcula el estimado en ARS puesto en casa desde el precio diario de Amazon (o el oficial como respaldo),
 * redondeado a 10.000 ARS, junto con la fuente ("amazon" | "oficial"), la fecha y el veredicto recalculado.
 */
export function mergeAmazonPrices(
  catalog: CatalogEntry[],
  prices: AmazonPrices | null,
  mep: number | null,
  eurUsd: number | null,
  now = Date.now(),
): CatalogEntry[] {
  const items = prices?.items ?? {};
  return catalog.map((entry) => {
    let amazonArs: number | null = null;
    let amazonSource: "amazon" | "oficial" | null = null;
    let amazonChecked: string | null = null;
    if (mep && mep > 0) {
      const scraped = Object.prototype.hasOwnProperty.call(items, entry.slug) ? items[entry.slug] : undefined;
      if (
        scraped &&
        Number.isFinite(scraped.amount) &&
        scraped.amount > 0 &&
        (scraped.currency === "USD" || scraped.currency === "EUR") &&
        isFreshAmazonDate(scraped.checked, now)
      ) {
        const toUsd = scraped.currency === "EUR" ? eurUsd : 1;
        if (toUsd && toUsd > 0) {
          amazonArs = roundArs10k(estimateFromAmazon(scraped.amount * toUsd, mep));
          amazonSource = "amazon";
          amazonChecked = scraped.checked;
        }
      }
      if (amazonArs == null && entry.listPrice) {
        const est = estimateArs(entry.listPrice, mep, eurUsd);
        if (est != null && est > 0) {
          amazonArs = roundArs10k(est);
          amazonSource = "oficial";
          amazonChecked = entry.listPrice.checked;
        }
      }
    }
    const { verdict } = comparePrices({ ml: entry.ml, amazonArs, shipsToAr: entry.shipsToAr });
    const verdictReason: CatalogEntry["verdictReason"] = entry.asin ? "precio" : "sinAmazon";
    return {
      ...entry,
      amazonArs,
      amazonSource,
      amazonChecked,
      verdict,
      verdictReason,
    };
  });
}

/**
 * Sólo se muestran productos con comparación completa: verificados, con ASIN en Amazon,
 * precio en Mercado Libre y estimado de Amazon (scrapeado o precio oficial).
 */
export function isComparable(entry: CatalogEntry, amazonPrices?: AmazonPrices | null, now = Date.now()): boolean {
  if (!entry.verified || !entry.asin || !entry.ml || !Number.isFinite(entry.ml.price) || !(entry.ml.price > 0)) {
    return false;
  }
  if ("amazonArs" in entry) {
    return typeof entry.amazonArs === "number" && Number.isFinite(entry.amazonArs) && entry.amazonArs > 0;
  }
  const items = amazonPrices?.items ?? {};
  const scraped = Object.prototype.hasOwnProperty.call(items, entry.slug) ? items[entry.slug] : undefined;
  if (scraped && Number.isFinite(scraped.amount) && scraped.amount > 0 && isFreshAmazonDate(scraped.checked, now)) {
    return true;
  }
  const official = entry.listPrice ? (entry.listPrice.sale ?? entry.listPrice.amount) : 0;
  return Number.isFinite(official) && official > 0;
}

export function loadCatalog(): CatalogEntry[] {
  const catalog = readJson<CatalogEntry[]>("data/catalog.json") ?? [];
  return mergeMlPrices(catalog, readJson<MlPrices>("data/ml-prices.json"));
}

export function loadAmazonPrices(): AmazonPrices | null {
  return readJson<AmazonPrices>("data/amazon-prices.json");
}

/** Calcula los slugs comparables aplicando exactamente la misma fusión y cotizaciones que las páginas. */
export function getComparableSlugs(
  catalog: CatalogEntry[],
  mlPrices: MlPrices | null,
  amazonPrices: AmazonPrices | null,
  mep: number | null,
  eurUsd: number | null,
  now = Date.now(),
): Set<string> {
  const merged = mergeAmazonPrices(mergeMlPrices(catalog, mlPrices), amazonPrices, mep, eurUsd, now);
  return new Set(merged.filter((p) => isComparable(p, null, now)).map((p) => p.slug));
}

/** Slugs comparables para filtrar el sitemap en astro.config.mjs. */
export async function loadComparableSlugs(): Promise<Set<string>> {
  const { products } = await loadProducts();
  return new Set(products.filter((p) => isComparable(p)).map((p) => p.slug));
}

/** El build puede traer offers.json desde una URL (R2) o desde el archivo local. */
export async function loadOffers(): Promise<Offers> {
  const empty: Offers = { generatedAt: null, mode: "offline", rates: null, items: [] };
  const url = import.meta.env?.OFFERS_URL ?? process.env.OFFERS_URL;
  if (url) {
    try {
      const res = await fetch(url);
      if (res.ok) return (await res.json()) as Offers;
      console.warn(`[data] OFFERS_URL respondió ${res.status}, uso archivo local`);
    } catch (err) {
      console.warn("[data] No pude leer OFFERS_URL, uso archivo local", err);
    }
  }
  return readJson<Offers>("data/offers.json") ?? empty;
}

export function freshPrice(item: OfferItem | undefined, now = Date.now()): OfferItem | null {
  if (!item || item.priceUsd == null || !item.priceFetchedAt) return null;
  const age = now - new Date(item.priceFetchedAt).getTime();
  return Number.isFinite(age) && age >= 0 && age <= PRICE_MAX_AGE_MS ? item : null;
}

export async function loadProducts() {
  const [catalog, offers, quotes] = await Promise.all([
    Promise.resolve(loadCatalog()),
    loadOffers(),
    buildQuotes(),
  ]);
  const mep = quotes.mep ?? offers.rates?.mep ?? null;
  const withAmazon = mergeAmazonPrices(catalog, loadAmazonPrices(), mep, quotes.eurUsd);
  const byKey = new Map(offers.items.map((i) => [`${i.store}:${i.asin}`, i]));
  const products = withAmazon.map((entry) => {
    const offer = byKey.get(`${entry.store}:${entry.asin}`);
    return { ...entry, offer, price: freshPrice(offer) };
  });
  return { products, offers };
}
