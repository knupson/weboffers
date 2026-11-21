import fs from "node:fs";
import path from "node:path";
import { comparePrices, type CatalogEntry } from "./data";

/** Selección dinámica: los productos publicados hoy de esas categorías, ordenados por ahorro trayéndolos por Amazon. */
export interface FiltroGuia {
  categorias: string[];
  ordenarPor: "ahorro_ars" | "ahorro_pct";
  /** Cuántas tarjetas muestra como máximo (contando las de `related`). */
  limite: number;
  /** Con menos productos publicados que esto, la guía no se genera (404) ni se lista. */
  minimo: number;
}

/** Insignia y nota editorial opcionales sobre la tarjeta de un producto. */
export interface NotaProducto {
  badge?: string;
  texto?: string;
}

export interface Guia {
  slug: string;
  title: string;
  description: string;
  h1: string;
  intro: string;
  sections: Array<{ heading: string; paragraphs: string[]; bullets?: string[] }>;
  faq: Array<{ q: string; a: string }>;
  /** Productos fijos: van primero si están publicados hoy. */
  related?: string[];
  filtro?: FiltroGuia;
  /** Notas por slug. Si el producto no está en la guía ese día, la nota no aparece. */
  notas?: Record<string, NotaProducto>;
  /** Insignia automática para el primer producto, sólo si la tarjeta también da ganador a Amazon. */
  badgePrimero?: string;
}

/** Lo mínimo que la guía necesita de un producto ya filtrado por `isComparable`. */
export type ProductoGuia = Pick<CatalogEntry, "slug" | "category" | "ml" | "amazonArs" | "shipsToAr">;

export interface GuiaPublicable<T extends ProductoGuia> {
  g: Guia;
  productos: T[];
  notas: Record<string, NotaProducto>;
}

const ORDENES = ["ahorro_ars", "ahorro_pct"] as const;

export function validarGuias(guias: Guia[]): Guia[] {
  const slugs = new Set<string>();
  for (const g of guias) {
    if (slugs.has(g.slug)) throw new Error(`guias.json: slug repetido ${g.slug}`);
    slugs.add(g.slug);
    const f = g.filtro;
    if (!f) continue;
    const donde = `guias.json ${g.slug}: filtro`;
    if (!Array.isArray(f.categorias) || f.categorias.length === 0 || f.categorias.some((c) => typeof c !== "string" || !c.trim())) {
      throw new Error(`${donde}.categorias tiene que ser una lista de categorías`);
    }
    if (!ORDENES.includes(f.ordenarPor)) throw new Error(`${donde}.ordenarPor tiene que ser ${ORDENES.join(" o ")}`);
    if (!Number.isInteger(f.limite) || f.limite < 1) throw new Error(`${donde}.limite tiene que ser un entero mayor que 0`);
    if (!Number.isInteger(f.minimo) || f.minimo < 1 || f.minimo > f.limite) {
      throw new Error(`${donde}.minimo tiene que ser un entero entre 1 y limite`);
    }
  }
  return guias;
}

export function loadGuias(): Guia[] {
  let raw: string;
  try {
    raw = fs.readFileSync(path.join(process.cwd(), "data/guias.json"), "utf-8");
  } catch {
    return [];
  }
  // Un JSON roto o un filtro mal escrito corta el build: mejor eso que guías vacías publicadas en silencio.
  return validarGuias(JSON.parse(raw) as Guia[]);
}

/** Ahorro trayéndolo por Amazon con los dos montos que muestra la tarjeta (negativo si conviene Mercado Libre). */
export function ahorroGuia(p: ProductoGuia): { ars: number; pct: number } {
  const ml = p.ml?.price ?? 0;
  const amazon = p.amazonArs ?? 0;
  if (!(ml > 0) || !(amazon > 0)) return { ars: 0, pct: 0 };
  const ars = ml - amazon;
  return { ars, pct: Math.round((ars / ml) * 1e6) / 1e6 };
}

/** `comparables` ya tiene que venir filtrado con `isComparable`: acá no se vuelve a mirar la fecha de los precios. */
export function productosDeGuia<T extends ProductoGuia>(g: Guia, comparables: T[]): T[] {
  const bySlug = new Map(comparables.map((p) => [p.slug, p]));
  const fijos = (g.related ?? []).map((s) => bySlug.get(s)).filter((p): p is T => p != null);
  if (!g.filtro) return fijos;
  const { categorias, ordenarPor, limite } = g.filtro;
  const usados = new Set(fijos.map((p) => p.slug));
  const clave = (p: T) => (ordenarPor === "ahorro_pct" ? ahorroGuia(p).pct : ahorroGuia(p).ars);
  const dinamicos = comparables
    .filter((p) => categorias.includes(p.category) && !usados.has(p.slug))
    .sort((a, b) => clave(b) - clave(a) || a.slug.localeCompare(b.slug));
  return [...fijos, ...dinamicos].slice(0, Math.max(limite, fijos.length));
}

export function guiasPublicables<T extends ProductoGuia>(guias: Guia[], comparables: T[]): GuiaPublicable<T>[] {
  const out: GuiaPublicable<T>[] = [];
  for (const g of guias) {
    const productos = productosDeGuia(g, comparables);
    if (g.filtro && productos.length < g.filtro.minimo) continue;
    const enGuia = new Set(productos.map((p) => p.slug));
    const notas: Record<string, NotaProducto> = Object.fromEntries(
      Object.entries(g.notas ?? {}).filter(([slug]) => enGuia.has(slug)).map(([slug, n]) => [slug, { ...n }]),
    );
    const primero = productos[0];
    // Mismo criterio que la tarjeta (comparePrices): sólo si ahí también gana Amazon (>= 10 % y envío gratis).
    if (g.badgePrimero && primero && comparePrices(primero).verdict === "amazon") {
      notas[primero.slug] = { ...notas[primero.slug], badge: g.badgePrimero };
    }
    out.push({ g, productos, notas });
  }
  return out;
}

/** La guía dinámica publicada que cubre esa categoría (la primera de guias.json), para ofrecerla desde la ficha. */
export function guiaDeCategoria<T extends ProductoGuia>(publicables: GuiaPublicable<T>[], categoria: string): Guia | null {
  return publicables.find((r) => r.g.filtro?.categorias.includes(categoria))?.g ?? null;
}

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Escapa el texto y convierte las rutas internas escritas entre paréntesis en links. */
export function linkify(text: string): string {
  return escape(text).replace(/\s?\((\/(?:calculadora|productos|guias|guia)\/[a-z0-9-]*\/?)\)/g, (_, href: string) => {
    const label = href.startsWith("/calculadora") ? "abrirla" : href.startsWith("/productos") ? "ver producto" : "leer guía";
    return ` (<a href="${href}">${label}</a>)`;
  });
}
