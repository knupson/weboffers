// Analítica de Franquicia 400 en Umami (13/11): atribución de sesión, clicks salientes y micro-conversiones.
//
// - UTMs first-touch: las de la primera página de la sesión con utm_* quedan en sessionStorage y viajan en cada
//   evento (Umami ya registra las UTMs de la landing, pero no las asocia a los eventos de las páginas siguientes).
// - Clicks salientes: `click_amazon` / `click_ml` con slug, categoria, precio_usd, ahorro_pct, ubicacion y boton.
//   Los enlaces llevan los datos en atributos data-salida-* (ver `salidaAttrs`) y un único listener los envía.
// - Micro-conversiones: `filtrar_categoria`, `buscar_producto`, `usar_calculadora`.
// - Higiene: sin Umami para navigator.webdriver (Chrome automatizado) ni para sesiones abiertas con ?notrack=1.
//
// Todo pasa por window.umami?.track: si Umami no cargó (bloqueador, notrack), nada falla.

export const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content"] as const;
export type Utms = Partial<Record<(typeof UTM_KEYS)[number], string>>;
export type Tienda = "amazon" | "ml";
export type Ubicacion =
  | "ficha"
  | "ficha_relacionados"
  | "portada"
  | "mas_vendidos"
  | "catalogo"
  | "busqueda"
  | "busqueda_vivo"
  | "guia"
  | "calculadora"
  | "conviene_hoy";

const UTM_STORAGE = "f400_utm";
const NOTRACK_STORAGE = "f400_notrack";
const UTM_MAX = 100; // un valor más largo es basura o un intento de inyectar texto: se recorta

type Store = Pick<Storage, "getItem" | "setItem">;
type Props = Record<string, string | number>;
type UmamiWindow = { umami?: { track: (event: string, data?: Props) => unknown } };

function sessionStore(): Store | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null; // modo privado estricto o storage bloqueado
  }
}

function leerUtms(store: Store | null): Utms {
  try {
    const raw = store?.getItem(UTM_STORAGE);
    const data = raw ? JSON.parse(raw) : null;
    if (!data || typeof data !== "object") return {};
    const out: Utms = {};
    for (const k of UTM_KEYS) if (typeof data[k] === "string" && data[k]) out[k] = data[k];
    return out;
  } catch {
    return {};
  }
}

/** Guarda las UTMs de la URL si la sesión todavía no tiene (first-touch) y devuelve las de la sesión. */
export function captureUtms(search: string, store: Store | null = sessionStore()): Utms {
  const previas = leerUtms(store);
  if (Object.keys(previas).length) return previas;
  const params = new URLSearchParams(search);
  const nuevas: Utms = {};
  for (const k of UTM_KEYS) {
    const v = params.get(k)?.trim();
    if (v) nuevas[k] = v.slice(0, UTM_MAX);
  }
  if (Object.keys(nuevas).length) {
    try {
      store?.setItem(UTM_STORAGE, JSON.stringify(nuevas));
    } catch {
      // sin storage la atribución vale sólo para esta página
    }
  }
  return nuevas;
}

export function sessionUtms(store: Store | null = sessionStore()): Utms {
  return leerUtms(store);
}

/** false para Chrome automatizado o sesiones con ?notrack=1 (la marca dura toda la sesión). */
export function shouldTrack(search: string, webdriver: boolean | undefined, store: Store | null = sessionStore()): boolean {
  if (webdriver === true) return false;
  if (new URLSearchParams(search).get("notrack") === "1") {
    try {
      store?.setItem(NOTRACK_STORAGE, "1");
    } catch {
      // sin storage, al menos esta página no se registra
    }
    return false;
  }
  try {
    return store?.getItem(NOTRACK_STORAGE) !== "1";
  } catch {
    return true;
  }
}

function limpiar(data: Record<string, string | number | null | undefined>): Props {
  const out: Props = {};
  for (const [k, v] of Object.entries(data)) {
    if (typeof v === "number" ? Number.isFinite(v) : typeof v === "string" && v !== "") out[k] = v as string | number;
  }
  return out;
}

// Umami se carga después del HTML: lo que pase antes (p. ej. buscar_producto al abrir /buscar/, cuyo script corre
// antes que el cargador de Base.astro) espera en la cola. Si el cargador decide no medir, la cola se vacía y no crece.
let umamiDescartado = false;
const cola: Array<[string, Props]> = [];
const COLA_MAX = 20;
export function umamiNoSeCarga(): void {
  umamiDescartado = true;
  cola.splice(0);
}
export function umamiListo(win: UmamiWindow | undefined = typeof window === "undefined" ? undefined : (window as unknown as UmamiWindow)): void {
  for (const [event, data] of cola.splice(0)) {
    try {
      win?.umami?.track(event, data);
    } catch {
      // la analítica nunca rompe la página
    }
  }
}

export function track(event: string, data: Record<string, string | number | null | undefined> = {},
  win: UmamiWindow | undefined = typeof window === "undefined" ? undefined : (window as unknown as UmamiWindow),
  store: Store | null = sessionStore()): void {
  try {
    const props = limpiar({ ...data, ...sessionUtms(store) });
    if (win?.umami) win.umami.track(event, props);
    else if (!umamiDescartado && cola.length < COLA_MAX) cola.push([event, props]);
  } catch {
    // la analítica nunca rompe la página
  }
}

/** Ahorro de Amazon contra Mercado Libre en % (negativo: Mercado Libre sale menos). null si falta un precio. */
export function ahorroPct(mlPrice: number | null | undefined, amazonArs: number | null | undefined): number | null {
  if (typeof mlPrice !== "number" || typeof amazonArs !== "number" || !(mlPrice > 0) || !(amazonArs > 0)) return null;
  return Math.round((1 - amazonArs / mlPrice) * 100);
}

/** Atributos data-salida-* de un enlace saliente (se generan en el build, los lee el listener). */
export function salidaAttrs(tienda: Tienda, ubicacion: Ubicacion, p: {
  slug?: string; category?: string; amazonUsd?: number | null; ml?: { price?: number } | null; amazonArs?: number | null;
} = {}, boton?: string): Record<string, string> {
  const pct = ahorroPct(p.ml?.price, p.amazonArs);
  const attrs: Record<string, string> = { "data-salida": tienda, "data-salida-ubicacion": ubicacion };
  if (p.slug) attrs["data-salida-slug"] = p.slug;
  if (p.category) attrs["data-salida-categoria"] = p.category;
  if (typeof p.amazonUsd === "number" && Number.isFinite(p.amazonUsd)) attrs["data-salida-precio-usd"] = p.amazonUsd.toFixed(2);
  if (pct !== null) attrs["data-salida-ahorro-pct"] = String(pct);
  if (boton) attrs["data-salida-boton"] = boton;
  return attrs;
}

/** Evento de un enlace con data-salida (dataset del DOM: data-salida-precio-usd → salidaPrecioUsd). */
export function salidaEvento(ds: Record<string, string | undefined>): { event: string; data: Props } | null {
  const tienda = ds.salida;
  if (tienda !== "amazon" && tienda !== "ml") return null;
  const num = (v: string | undefined) => (v === undefined || v === "" ? undefined : Number(v));
  return {
    event: tienda === "amazon" ? "click_amazon" : "click_ml",
    data: limpiar({
      slug: ds.salidaSlug,
      categoria: ds.salidaCategoria,
      precio_usd: num(ds.salidaPrecioUsd),
      ahorro_pct: num(ds.salidaAhorroPct),
      ubicacion: ds.salidaUbicacion,
      boton: ds.salidaBoton,
    }),
  };
}

export function trackSalida(ds: Record<string, string | undefined>, win?: UmamiWindow, store?: Store | null): void {
  const ev = salidaEvento(ds);
  if (ev) track(ev.event, ev.data, win, store);
}

export const trackFiltrarCategoria = (categoria: string) => track("filtrar_categoria", { categoria: categoria || "todo" });
export const trackBuscarProducto = (termino: string, resultados: number) =>
  track("buscar_producto", { termino: termino.trim().toLowerCase().slice(0, UTM_MAX), resultados });

// La calculadora se usa tecleando: un solo evento por página, con el monto en el que el usuario se quedó.
let calcTimer: ReturnType<typeof setTimeout> | undefined;
let calcEnviado = false;
export function trackCalculadora(montoUsd: number, esperaMs = 1500): void {
  if (calcEnviado || !(montoUsd > 0) || !Number.isFinite(montoUsd)) return;
  clearTimeout(calcTimer);
  calcTimer = setTimeout(() => {
    calcEnviado = true;
    track("usar_calculadora", { monto_usd: Math.round(montoUsd * 100) / 100 });
  }, esperaMs);
}
/** Sólo para tests. */
export function _resetCalculadora(): void {
  clearTimeout(calcTimer);
  calcEnviado = false;
  umamiDescartado = false;
  cola.splice(0);
}
