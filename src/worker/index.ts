// Worker de Cloudflare: sirve el sitio estático y, en /api/*, la búsqueda viva de Mercado Libre.
// Va en TypeScript plano, sin Astro: no importar ../config (usa import.meta.env de Astro).
import { edgeCache, type Env, type EdgeCache } from "./types";

export type { Env } from "./types";

const ML_API = "https://api.mercadolibre.com";
// Mismos valores que ML_AFFILIATE en src/config.ts. Duplicados a propósito (ese archivo es de Astro).
const ML_AFFILIATE = { word: "ale_benzoni", tool: "58527537" } as const;
const MAX_PRODUCTS = 6;
const CACHE_SECONDS = 3600;
const TIMEOUT_MS = 8000;
const TOKEN_MARGIN_S = 300;
const Q_MIN = 2;
const Q_MAX = 80;

export interface MlResult {
  id: string;
  name: string;
  price: number;
  url: string;
}

// Error controlado hacia Mercado Libre. El mensaje nunca incluye secretos ni el token.
export class MlError extends Error {
  readonly status: number;
  constructor(message: string, status = 502) {
    super(message);
    this.name = "MlError";
    this.status = status;
  }
}

// Token de aplicación en memoria del isolate: se reutiliza hasta vencer (menos un margen).
let tokenCache: { token: string; expiresAt: number } | null = null;
let tokenPending: Promise<string> | null = null;

async function getToken(env: Env): Promise<string> {
  if (tokenCache && Date.now() < tokenCache.expiresAt) return tokenCache.token;
  // Si llegan varias búsquedas juntas, comparten la misma petición de token.
  if (!tokenPending) {
    tokenPending = requestToken(env).finally(() => {
      tokenPending = null;
    });
  }
  return tokenPending;
}

async function requestToken(env: Env): Promise<string> {
  if (!env.ML_CLIENT_ID || !env.ML_CLIENT_SECRET) throw new MlError("Mercado Libre no está configurado");
  const body = new URLSearchParams({
    grant_type: "client_credentials",
    client_id: env.ML_CLIENT_ID,
    client_secret: env.ML_CLIENT_SECRET,
  });
  const res = await fetch(`${ML_API}/oauth/token`, {
    method: "POST",
    headers: { accept: "application/json", "content-type": "application/x-www-form-urlencoded" },
    body,
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (!res.ok) throw new MlError(`Token de Mercado Libre: HTTP ${res.status}`);
  const data = (await res.json()) as { access_token?: unknown; expires_in?: unknown };
  if (typeof data.access_token !== "string") throw new MlError("Token de Mercado Libre sin access_token");
  const ttl = typeof data.expires_in === "number" ? data.expires_in : 3600;
  tokenCache = { token: data.access_token, expiresAt: Date.now() + (ttl - TOKEN_MARGIN_S) * 1000 };
  return data.access_token;
}

async function mlGet(path: string, token: string): Promise<unknown> {
  const res = await fetch(`${ML_API}${path}`, {
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
    signal: AbortSignal.timeout(TIMEOUT_MS),
  });
  if (res.status === 401) tokenCache = null; // token vencido antes de tiempo: se pide otro en la próxima
  if (!res.ok) throw new MlError(`Mercado Libre respondió HTTP ${res.status}`);
  return res.json();
}

// Acepta la forma {results: [...]} de Mercado Libre o un arreglo plano.
function listOf(raw: unknown): unknown[] {
  if (Array.isArray(raw)) return raw;
  if (raw && typeof raw === "object" && Array.isArray((raw as { results?: unknown }).results)) {
    return (raw as { results: unknown[] }).results;
  }
  return [];
}

// Precio más bajo entre las publicaciones nuevas. Si no trae condición, se acepta.
export function bestNewPrice(items: unknown[]): number | null {
  let best: number | null = null;
  for (const item of items) {
    if (!item || typeof item !== "object") continue;
    const { price, condition } = item as { price?: unknown; condition?: unknown };
    if (typeof condition === "string" && condition !== "new") continue;
    if (typeof price !== "number" || !Number.isFinite(price) || price <= 0) continue;
    if (best === null || price < best) best = price;
  }
  return best;
}

export function productUrl(id: string): string {
  return `https://www.mercadolibre.com.ar/p/${encodeURIComponent(id)}?matt_word=${ML_AFFILIATE.word}&matt_tool=${ML_AFFILIATE.tool}`;
}

interface ProductHit {
  id: string;
  name: string;
}

function parseProduct(raw: unknown): ProductHit | null {
  if (!raw || typeof raw !== "object") return null;
  const { id, name } = raw as { id?: unknown; name?: unknown };
  if (typeof id !== "string" || !/^[A-Za-z0-9]{3,30}$/.test(id)) return null;
  if (typeof name !== "string" || !name.trim()) return null;
  return { id, name: name.trim() };
}

// Busca productos de catálogo en Mercado Libre y devuelve el precio nuevo más bajo de cada uno.
export async function buscar(q: string, env: Env): Promise<MlResult[]> {
  const token = await getToken(env);
  const search = await mlGet(`/products/search?status=active&site_id=MLA&q=${encodeURIComponent(q)}`, token);
  const products = listOf(search)
    .map(parseProduct)
    .filter((p): p is ProductHit => p !== null)
    .slice(0, MAX_PRODUCTS);
  if (products.length === 0) return [];

  const settled = await Promise.allSettled(
    products.map(async (p) => {
      const items = await mlGet(`/products/${encodeURIComponent(p.id)}/items`, token);
      return { ...p, price: bestNewPrice(listOf(items)) };
    }),
  );
  const ok = settled.flatMap((r) => (r.status === "fulfilled" ? [r.value] : []));
  // Si fallaron todas las consultas de precio, no hay nada útil que mostrar: es un error de Mercado Libre.
  if (ok.length === 0) throw new MlError("No pudimos leer los precios de Mercado Libre");

  return ok.flatMap((p) => (p.price === null ? [] : [{ id: p.id, name: p.name, price: p.price, url: productUrl(p.id) }]));
}

// Minúsculas y espacios colapsados. Es la clave de caché y lo que se busca.
export function normalizarQ(raw: string): string {
  return raw.trim().replace(/\s+/g, " ").toLowerCase();
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...headers },
  });
}

export async function handleBuscar(request: Request, env: Env, cache: EdgeCache = edgeCache()): Promise<Response> {
  const url = new URL(request.url);
  const q = normalizarQ(url.searchParams.get("q") ?? "");
  if (q.length < Q_MIN || q.length > Q_MAX) {
    return json({ error: `La búsqueda tiene que tener entre ${Q_MIN} y ${Q_MAX} caracteres.` }, 400);
  }

  const key = new URL(`/api/buscar?q=${encodeURIComponent(q)}`, url.origin).toString();
  const cached = await cache.match(key);
  if (cached) return cached;

  try {
    const results = await buscar(q, env);
    const res = json({ q, results }, 200, { "cache-control": `public, max-age=${CACHE_SECONDS}` });
    await cache.put(key, res.clone());
    return res;
  } catch (err) {
    // Se loguea sólo el mensaje controlado de MlError: nunca credenciales ni cuerpos de respuesta.
    console.warn("[buscar]", err instanceof MlError ? err.message : "error inesperado");
    return json({ error: "No pudimos consultar Mercado Libre ahora. Probá de nuevo en un rato." }, 502);
  }
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/buscar") {
      if (request.method !== "GET") return json({ error: "Método no permitido" }, 405, { allow: "GET" });
      return handleBuscar(request, env);
    }
    if (url.pathname.startsWith("/api/")) return json({ error: "No existe esa ruta" }, 404);
    return env.ASSETS.fetch(request);
  },
};
