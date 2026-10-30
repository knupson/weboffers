export const UMAMI = { src: "https://analytics.knunet.com/k.js", id: "a0176c95-f04a-4452-95d1-d60ae943a76e" };

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

// Ilustraciones propias por categoría (filete pintado con Gemini). Nunca son fotos del producto.
export const CATEGORY_ART: Record<string, string> = {
  Monitores: "/art/cat-monitores.webp",
  "Mini PCs": "/art/cat-minipc.webp",
  Almacenamiento: "/art/cat-almacenamiento.webp",
  Periféricos: "/art/cat-perifericos.webp",
  Audio: "/art/cat-audio.webp",
  Cocina: "/art/cat-cocina.webp",
  Hogar: "/art/cat-hogar.webp",
  Gaming: "/art/cat-joystick.webp",
  "Tablets y lectores": "/art/cat-lectores.webp",
  "Carga y energía": "/art/cat-carga.webp",
  Redes: "/art/cat-redes.webp",
  "Cuidado personal": "/art/cat-cuidado.webp",
};

// Productos cuya categoría no los representa bien llevan su propia ilustración genérica.
export const PRODUCT_ART: Record<string, string> = {
  "8bitdo-ultimate-bluetooth-negro": "/art/cat-joystick.webp",
  "logitech-mx-master-3s": "/art/cat-mouse.webp",
};

export const artFor = (p: { slug: string; category: string }) => PRODUCT_ART[p.slug] ?? CATEGORY_ART[p.category];

// Búsquedas curadas: llevan a Amazon con el tag aunque el producto no esté en el catálogo.
export const SEARCHES: Array<{ label: string; query: string; store: Store; category: string; art?: string }> = [
  { label: "Monitores 1440p de 165 Hz o más", query: "1440p 165hz gaming monitor", store: "US", category: "Monitores" },
  { label: "SSD NVMe de 2 TB", query: "nvme ssd 2tb pcie 4.0", store: "US", category: "Almacenamiento" },
  { label: "Mini PC con Ryzen", query: "mini pc ryzen 7", store: "US", category: "Mini PCs" },
  { label: "Teclados mecánicos inalámbricos", query: "wireless mechanical keyboard", store: "US", category: "Periféricos" },
  { label: "Auriculares con cancelación de ruido", query: "noise cancelling headphones", store: "US", category: "Audio" },
  { label: "Cafeteras espresso de 220 V", query: "cafetera espresso", store: "ES", category: "Cocina" },
  { label: "Robots aspiradores de 220 V", query: "robot aspirador", store: "ES", category: "Hogar" },
  { label: "Freidoras de aire de 220 V", query: "freidora de aire", store: "ES", category: "Cocina", art: "/art/cat-freidora.webp" },
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
