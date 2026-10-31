import fs from "node:fs";
import path from "node:path";
import type { Store } from "../config";
import { buildQuotes, estimateFromAmazon } from "./estimate";

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
  /** Precio oficial del fabricante, con su fuente (conservado en el catálogo, no se muestra). */
  listPrice?: ListPrice;
  /** Verificado en Amazon con dirección en Argentina: se puede comprar y enviar. */
  shipsToAr?: { freeShipping: boolean; checked: string };
  /** Envío a Argentina relevado hoy (ART) por el worker: false = Amazon no lo envía, no se muestra. */
  shipsToArToday?: boolean;
  /** Publicación más barata en Mercado Libre del mismo modelo, con link de afiliado. */
  ml?: { price: number; url: string; checked: string; catalogId?: string };
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
  /** Fuente del estimado de Amazon: únicamente precio diario scrapeado ("amazon") o null. */
  amazonSource?: "amazon" | null;
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
  verdict?: "amazon" | "ml";
  verdictReason?: "precio" | "sinAmazon";
}

export interface MlPrices {
  generatedAt: string;
  /** Fecha (AAAA-MM-DD) de la corrida. */
  date: string;
  items: Record<string, MlPriceItem>;
}

/** Relevamiento de envío a Argentina (servicio amazon-ar): vigente sólo si `checked` es hoy ART. */
export interface AmazonArShipping {
  ships: boolean;
  /** Envío gratis a Argentina; null si no se pudo determinar. */
  free: boolean | null;
  checked: string;
}

/** Precio diario de Amazon por slug (data/amazon-prices.json). Lo escribe el worker; nunca se publica en USD/EUR. */
export interface AmazonPriceItem {
  amount?: number;
  currency?: "USD" | "EUR";
  checked?: string;
  shipsToAr?: AmazonArShipping;
}

export interface AmazonPrices {
  generatedAt: string;
  date: string;
  items: Record<string, AmazonPriceItem>;
}

const VERDICTS: readonly string[] = ["amazon", "ml"];
const VERDICT_REASONS: readonly string[] = ["precio", "sinAmazon"];
export const MIN_AMAZON_SAVING = 0.10;
export const MIN_COMPARABLE_PRODUCTS = 100;
const ART_OFFSET_MS = -3 * 60 * 60 * 1000;

/** Devuelve la fecha AAAA-MM-DD en hora argentina (UTC-3). */
export function artDate(now = Date.now()): string {
  return new Date(now + ART_OFFSET_MS).toISOString().slice(0, 10);
}

/** Un relevamiento es vigente sólo si su fecha `checked` (AAAA-MM-DD) coincide con el día de hoy en ART. */
export function isFreshAmazonDate(checked: unknown, now = Date.now()): checked is string {
  if (typeof checked !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(checked)) return false;
  const checkedMs = Date.parse(`${checked}T00:00:00Z`);
  if (!Number.isFinite(checkedMs) || new Date(checkedMs).toISOString().slice(0, 10) !== checked) return false;
  return checked === artDate(now);
}

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
 * Cruza el catálogo con `data/ml-prices.json`. Sólo conserva el precio de Mercado Libre
 * si fue relevado hoy (fecha ART); nunca muestra el `ml.price` del catálogo ni precios de días anteriores.
 */
export function mergeMlPrices(
  catalog: CatalogEntry[],
  prices: MlPrices | null,
  now = Date.now(),
): CatalogEntry[] {
  const items = prices?.items ?? {};
  const today = artDate(now);
  return catalog.map((entry) => {
    if (!entry.ml) return entry;
    if (!prices || !Object.prototype.hasOwnProperty.call(items, entry.slug)) {
      return { ...entry, ml: undefined };
    }
    const item = items[entry.slug];
    if (
      !item ||
      !Number.isFinite(item.price) ||
      !(item.price > 0) ||
      item.checked !== today
    ) {
      return { ...entry, ml: undefined };
    }
    return {
      ...entry,
      ml: {
        ...entry.ml,
        price: item.price,
        url: isMlUrl(item.url) ? item.url : entry.ml.url,
        checked: item.checked,
      },
      verdict: item.verdict && VERDICTS.includes(item.verdict) ? (item.verdict as CatalogEntry["verdict"]) : entry.verdict,
      verdictReason:
        item.verdictReason && VERDICT_REASONS.includes(item.verdictReason)
          ? (item.verdictReason as CatalogEntry["verdictReason"])
          : entry.verdictReason,
    };
  });
}

export interface PriceComparison {
  /** "sinEnvio": Amazon sale >=10% menos pero no está confirmado el envío a Argentina: no se resalta a ninguno. */
  verdict: "amazon" | "ml" | "sinEnvio";
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
  const verdict: PriceComparison["verdict"] =
    savingRatio >= MIN_AMAZON_SAVING ? (entry.shipsToAr?.freeShipping === true ? "amazon" : "sinEnvio") : "ml";
  const rawDiff = verdict === "ml" ? amazonArs - mlPrice : mlPrice - amazonArs;
  const saving = rawDiff >= 5000 ? roundArs10k(rawDiff) : 0;
  return { verdict, saving };
}

/**
 * Calcula el estimado en ARS puesto en casa únicamente desde el precio diario de Amazon relevado hoy (ART),
 * redondeado a 10.000 ARS, junto con la fuente ("amazon" | null), la fecha y el veredicto recalculado.
 * Nunca usa `listPrice` del fabricante ni precios de días anteriores.
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
    let amazonSource: "amazon" | null = null;
    let amazonChecked: string | null = null;
    let shipsToAr = entry.shipsToAr;
    let shipsToArToday: boolean | undefined;
    const scraped = Object.prototype.hasOwnProperty.call(items, entry.slug) ? items[entry.slug] : undefined;
    if (mep && mep > 0) {
      if (
        scraped &&
        typeof scraped.amount === "number" &&
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
    }
    // El relevamiento de envío de hoy (ART) pisa el shipsToAr del catálogo.
    const ar = scraped?.shipsToAr;
    if (ar && isFreshAmazonDate(ar.checked, now)) {
      shipsToAr = { freeShipping: ar.free === true, checked: ar.checked };
      shipsToArToday = ar.ships === true;
    }
    const { verdict: compared } = comparePrices({ ml: entry.ml, amazonArs, shipsToAr });
    // Sin envío confirmado no hay ganador: el catálogo no guarda veredicto.
    const verdict = compared === "sinEnvio" ? undefined : compared;
    const verdictReason: CatalogEntry["verdictReason"] = entry.asin ? "precio" : "sinAmazon";
    return {
      ...entry,
      amazonArs,
      amazonSource,
      amazonChecked,
      shipsToAr,
      shipsToArToday,
      verdict,
      verdictReason,
    };
  });
}

/**
 * Un producto es comparable (y por lo tanto se muestra) únicamente si:
 *   - está verificado y tiene ASIN en Amazon,
 *   - Amazon lo envía a Argentina según el relevamiento de hoy (shipsToArToday !== false),
 *   - tiene precio en Mercado Libre relevado hoy (fecha ART == hoy ART), y
 *   - tiene precio en Amazon relevado hoy (fecha ART == hoy ART) convertido a ARS.
 */
export function isComparable(entry: CatalogEntry, amazonPrices?: AmazonPrices | null, now = Date.now()): boolean {
  const today = artDate(now);
  // Amazon no envía este producto a Argentina (relevado hoy): no hay comparación posible.
  if (entry.shipsToArToday === false) {
    return false;
  }
  if (
    !entry.verified ||
    !entry.asin ||
    // Regla del user: producto sin foto no se publica.
    !entry.image ||
    !entry.ml ||
    !Number.isFinite(entry.ml.price) ||
    !(entry.ml.price > 0) ||
    entry.ml.checked !== today
  ) {
    return false;
  }
  if ("amazonArs" in entry) {
    return (
      typeof entry.amazonArs === "number" &&
      Number.isFinite(entry.amazonArs) &&
      entry.amazonArs > 0 &&
      entry.amazonSource === "amazon" &&
      entry.amazonChecked === today
    );
  }
  const items = amazonPrices?.items ?? {};
  const scraped = Object.prototype.hasOwnProperty.call(items, entry.slug) ? items[entry.slug] : undefined;
  return Boolean(
    scraped &&
      typeof scraped.amount === "number" &&
      Number.isFinite(scraped.amount) &&
      scraped.amount > 0 &&
      isFreshAmazonDate(scraped.checked, now),
  );
}

export function loadMlPrices(): MlPrices | null {
  return readJson<MlPrices>("data/ml-prices.json");
}

export function loadCatalog(now = Date.now()): CatalogEntry[] {
  const catalog = readJson<CatalogEntry[]>("data/catalog.json") ?? [];
  return mergeMlPrices(catalog, loadMlPrices(), now);
}

export function loadAmazonPrices(): AmazonPrices | null {
  return readJson<AmazonPrices>("data/amazon-prices.json");
}

/** Determina la fecha común de los archivos de precios del build para `<body data-prices-date>`. */
export function resolvePricesDate(
  mlPrices: MlPrices | null,
  amazonPrices: AmazonPrices | null,
): string {
  const mlDate = mlPrices?.date ?? "";
  const amzDate = amazonPrices?.date ?? "";
  if (mlDate && amzDate && mlDate === amzDate) return mlDate;
  return "";
}

export function loadPricesDate(): string {
  return resolvePricesDate(loadMlPrices(), loadAmazonPrices());
}

/** Emite la alerta MENOS_DE_100 en stderr cuando hay menos de 100 productos comparables, sin fallar el build. */
export function logIfFewProducts(
  comparableCount: number,
  logger: (msg: string) => void = console.error,
): boolean {
  if (comparableCount < MIN_COMPARABLE_PRODUCTS) {
    logger(`MENOS_DE_100: ${comparableCount} productos comparables`);
    return true;
  }
  return false;
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
  const merged = mergeAmazonPrices(mergeMlPrices(catalog, mlPrices, now), amazonPrices, mep, eurUsd, now);
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

/** Acepta datos de `offers.json` únicamente si fueron relevados en la misma fecha ART de hoy (sin ventana de 24h). */
export function freshPrice(item: OfferItem | undefined, now = Date.now()): OfferItem | null {
  if (!item || item.priceUsd == null || !item.priceFetchedAt) return null;
  const fetchedMs = Date.parse(item.priceFetchedAt);
  return Number.isFinite(fetchedMs) && artDate(fetchedMs) === artDate(now) ? item : null;
}

let loggedComparableAlert = false;

export async function loadProducts(now = Date.now()) {
  const [catalog, offers, quotes] = await Promise.all([
    Promise.resolve(loadCatalog(now)),
    loadOffers(),
    buildQuotes(),
  ]);
  const mep = quotes.mep ?? offers.rates?.mep ?? null;
  const withAmazon = mergeAmazonPrices(catalog, loadAmazonPrices(), mep, quotes.eurUsd, now);
  const byKey = new Map(offers.items.map((i) => [`${i.store}:${i.asin}`, i]));
  const products = withAmazon.map((entry) => {
    const offer = byKey.get(`${entry.store}:${entry.asin}`);
    return { ...entry, offer, price: freshPrice(offer, now) };
  });

  if (!loggedComparableAlert) {
    loggedComparableAlert = true;
    const comparableCount = products.filter((p) => isComparable(p, null, now)).length;
    logIfFewProducts(comparableCount);
  }

  return { products, offers };
}
