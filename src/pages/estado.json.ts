// Estado del build para los controles automáticos (03/11): cuántos productos se publicaron y por qué faltaron
// precios de Amazon. Lo lee `tools/recordatorio_franquicia.py --control sitio` a las 7:30.
import { isComparable, loadAmazonPrices, loadProducts } from "../lib/data";

export async function GET() {
  const { products } = await loadProducts();
  const amazon = loadAmazonPrices();
  const body = {
    publicados: products.filter((p) => isComparable(p)).length,
    preciosDe: amazon?.date ?? null,
    amazon: amazon?.run ?? null,
    ritmo: amazon?.pace ?? null,
  };
  return new Response(JSON.stringify(body, null, 1), { headers: { "Content-Type": "application/json; charset=utf-8" } });
}
