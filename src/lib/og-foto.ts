// Foto local de un producto para generar /og/<slug>.jpg en el build (13/11). Sólo rutas /products/ que existan.
import fs from "node:fs";
import path from "node:path";

export function fotoLocal(foto: string | null | undefined, raiz = process.cwd()): string | null {
  if (!foto || !foto.startsWith("/products/") || foto.includes("..")) return null;
  const archivo = path.join(raiz, "public", foto);
  return fs.existsSync(archivo) ? archivo : null;
}
