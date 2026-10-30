export const SITE = {
  name: "Franquicia 400",
  url: "https://ofertas.knunet.com",
  parent: { name: "KnuNet", url: "https://knunet.com" },
  description:
    "Calculá cuánto te sale realmente traer hardware de Amazon a Argentina por courier: franquicia de USD 400, IVA y dólar del día.",
  disclosure:
    "En calidad de Afiliado de Amazon, obtengo ingresos por las compras adscritas que cumplen los requisitos aplicables.",
  priceNotice:
    "Los precios los consulta un proceso automático a Amazon y se muestran con la hora de la consulta. Rige siempre el precio que ves en Amazon al pagar.",
};

// Tags de Associates confirmados por el titular. Las variables de entorno los pisan si hace falta.
const US_TAG = import.meta.env.PUBLIC_AMAZON_US_TAG ?? "knunet-20";
const ES_TAG = import.meta.env.PUBLIC_AMAZON_ES_TAG ?? "knunet-21";

export type Store = "US" | "ES";

export function amazonUrl(asin: string, store: Store): string {
  const host = store === "ES" ? "www.amazon.es" : "www.amazon.com";
  const tag = store === "ES" ? ES_TAG : US_TAG;
  const qs = tag ? `?tag=${encodeURIComponent(tag)}` : "";
  return `https://${host}/dp/${encodeURIComponent(asin)}${qs}`;
}

export function amazonSearchUrl(query: string, store: Store): string {
  const host = store === "ES" ? "www.amazon.es" : "www.amazon.com";
  const tag = store === "ES" ? ES_TAG : US_TAG;
  const params = new URLSearchParams({ k: query });
  if (tag) params.set("tag", tag);
  return `https://${host}/s?${params.toString()}`;
}
