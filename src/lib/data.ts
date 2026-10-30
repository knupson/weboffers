import fs from "node:fs";
import path from "node:path";
import type { Store } from "../config";

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

const VERDICTS: readonly string[] = ["amazon", "ml"];
const VERDICT_REASONS: readonly string[] = ["precio", "sinAmazon"];

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
      ml: { ...entry.ml, price: item.price, checked: item.checked ?? entry.ml.checked },
      verdict: VERDICTS.includes(item.verdict) ? (item.verdict as CatalogEntry["verdict"]) : entry.verdict,
      verdictReason: VERDICT_REASONS.includes(item.verdictReason)
        ? (item.verdictReason as CatalogEntry["verdictReason"])
        : entry.verdictReason,
    };
  });
}

export function loadCatalog(): CatalogEntry[] {
  const catalog = readJson<CatalogEntry[]>("data/catalog.json") ?? [];
  return mergeMlPrices(catalog, readJson<MlPrices>("data/ml-prices.json"));
}

/** El build puede traer offers.json desde una URL (R2) o desde el archivo local. */
export async function loadOffers(): Promise<Offers> {
  const empty: Offers = { generatedAt: null, mode: "offline", rates: null, items: [] };
  const url = import.meta.env.OFFERS_URL;
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
  const [catalog, offers] = await Promise.all([Promise.resolve(loadCatalog()), loadOffers()]);
  const byKey = new Map(offers.items.map((i) => [`${i.store}:${i.asin}`, i]));
  const products = catalog.map((entry) => {
    const offer = byKey.get(`${entry.store}:${entry.asin}`);
    return { ...entry, offer, price: freshPrice(offer) };
  });
  return { products, offers };
}
