// Estado del build para los controles automáticos (03/11): cuántos productos se publicaron y por qué faltaron
// precios de Amazon. Lo lee `tools/recordatorio_franquicia.py --control sitio` a las 7:30.
import fs from "node:fs";
import path from "node:path";
import { isComparable, loadAmazonPrices, loadMlPrices, loadProducts } from "../lib/data";
import { publicationBreakdown } from "../lib/desglose";

// Búsqueda semanal de productos (worker/catalog_auto.py); el deployer copia el estado a data/.
function readCatalogState() {
  try {
    return JSON.parse(fs.readFileSync(path.join(process.cwd(), "data", "catalog-auto-state.json"), "utf-8"));
  } catch {
    return null;
  }
}

export async function GET() {
  const now = Date.now();
  const { products } = await loadProducts(now);
  const amazon = loadAmazonPrices();
  const body = {
    publicados: products.filter((p) => isComparable(p, null, now)).length,
    slot: loadMlPrices()?.slot ?? null,
    preciosDe: amazon?.date ?? null,
    amazon: amazon?.run ?? null,
    ritmo: amazon?.pace ?? null,
    catalogo: readCatalogState(),
  };
  // Archivo privado del build: el deployer lo conserva fuera del sitio público.
  if (process.env.CADENA_DESGLOSE_PATH) {
    // Sin catalog-origins.json (build a mano, sin overlay del deployer) el origen queda vacío: el build no se cae.
    let origins: Record<string, string> = {};
    try {
      origins = JSON.parse(fs.readFileSync(path.join(process.cwd(), 'data', 'catalog-origins.json'), 'utf8'));
    } catch (error: any) {
      if (error?.code !== 'ENOENT') throw error;
    }
    fs.writeFileSync(process.env.CADENA_DESGLOSE_PATH, JSON.stringify(publicationBreakdown(products, origins, now)));
  }
  return new Response(JSON.stringify(body, null, 1), { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
