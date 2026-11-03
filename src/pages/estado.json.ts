// Estado del build para los controles automáticos (03/11): cuántos productos se publicaron y por qué faltaron
// precios de Amazon. Lo lee `tools/recordatorio_franquicia.py --control sitio` a las 7:30.
import fs from "node:fs";
import path from "node:path";
import { isComparable, loadAmazonPrices, loadProducts } from "../lib/data";

// Búsqueda semanal de productos (worker/catalog_auto.py); el deployer copia el estado a data/.
function readCatalogState() {
  try {
    return JSON.parse(fs.readFileSync(path.join(process.cwd(), "data", "catalog-auto-state.json"), "utf-8"));
  } catch {
    return null;
  }
}

export async function GET() {
  const { products } = await loadProducts();
  const amazon = loadAmazonPrices();
  const body = {
    publicados: products.filter((p) => isComparable(p)).length,
    preciosDe: amazon?.date ?? null,
    amazon: amazon?.run ?? null,
    ritmo: amazon?.pace ?? null,
    catalogo: readCatalogState(),
  };
  return new Response(JSON.stringify(body, null, 1), { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
