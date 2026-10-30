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

export const STORE_LABEL: Record<Store, string> = { US: "Amazon.com", ES: "Amazon.es" };

export function amazonUrl(asin: string, store: Store): string {
  const host = store === "ES" ? "www.amazon.es" : "www.amazon.com";
  const tag = store === "ES" ? ES_TAG : US_TAG;
  const qs = tag ? `?tag=${encodeURIComponent(tag)}` : "";
  return `https://${host}/dp/${encodeURIComponent(asin)}${qs}`;
}

export const CATEGORY_ICON: Record<string, string> = {
  Monitores: "monitor",
  "Mini PCs": "cpu",
  Almacenamiento: "hard-drives",
  Periféricos: "keyboard",
  Audio: "headphones",
};

// Búsquedas curadas: llevan a Amazon con el tag aunque el producto no esté en el catálogo.
export const SEARCHES: Array<{ label: string; query: string; store: Store; icon: string }> = [
  { label: "Monitores 1440p de 165 Hz o más", query: "1440p 165hz gaming monitor", store: "US", icon: "monitor" },
  { label: "SSD NVMe de 2 TB", query: "nvme ssd 2tb pcie 4.0", store: "US", icon: "hard-drives" },
  { label: "Mini PC con Ryzen", query: "mini pc ryzen 7", store: "US", icon: "cpu" },
  { label: "Teclados mecánicos inalámbricos", query: "wireless mechanical keyboard", store: "US", icon: "keyboard" },
  { label: "Auriculares con cancelación de ruido", query: "noise cancelling headphones", store: "US", icon: "headphones" },
  { label: "Joysticks para PC", query: "pc controller bluetooth", store: "US", icon: "game-controller" },
  { label: "Cafeteras espresso de 220 V", query: "cafetera espresso", store: "ES", icon: "plug" },
  { label: "Robots aspiradores de 220 V", query: "robot aspirador", store: "ES", icon: "plug" },
];

export function amazonDealsUrl(store: Store): string {
  const host = store === "ES" ? "www.amazon.es" : "www.amazon.com";
  const tag = store === "ES" ? ES_TAG : US_TAG;
  return `https://${host}/gp/goldbox${tag ? `?tag=${encodeURIComponent(tag)}` : ""}`;
}

export function amazonSearchUrl(query: string, store: Store): string {
  const host = store === "ES" ? "www.amazon.es" : "www.amazon.com";
  const tag = store === "ES" ? ES_TAG : US_TAG;
  const params = new URLSearchParams({ k: query });
  if (tag) params.set("tag", tag);
  return `https://${host}/s?${params.toString()}`;
}
