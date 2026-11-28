import { existsSync } from "node:fs";
import { join } from "node:path";

/** Foto sin fondo generada por tools/recortar-fotos.mjs (prebuild). null si no existe: se usa la original. */
export function recorte(src: string | null | undefined, raiz = process.cwd()): string | null {
  const m = src?.match(/^\/products\/([^/]+\.webp)$/);
  return m && existsSync(join(raiz, "public/products/recorte", m[1])) ? `/products/recorte/${m[1]}` : null;
}
