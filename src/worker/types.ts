// Bindings y secretos del Worker. Los secretos los carga el operador con `wrangler secret put`.
export interface Env {
  // Assets estáticos de ./dist (binding definido en wrangler.jsonc).
  ASSETS: { fetch(request: Request): Promise<Response> };
  ML_CLIENT_ID: string;
  ML_CLIENT_SECRET: string;
  META_CAPI_TOKEN?: string;
  META_PIXEL_ID?: string;
}

export interface WorkerContext {
  waitUntil(promise: Promise<unknown>): void;
}

// Subconjunto de la Cache API de Cloudflare (`caches.default`). Sin tipos externos.
export interface EdgeCache {
  match(key: string): Promise<Response | undefined>;
  put(key: string, response: Response): Promise<void>;
}

export function edgeCache(): EdgeCache {
  return (globalThis as unknown as { caches: { default: EdgeCache } }).caches.default;
}
