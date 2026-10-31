export const UMAMI = { src: "https://analytics.knunet.com/k.js", id: "a0176c95-f04a-4452-95d1-d60ae943a76e" };

// Afiliados de Mercado Libre: etiqueta y herramienta de la cuenta (públicas, van en cada link compartido).
// Los links de producto salen del generador oficial (meli.la); estos parámetros se usan en búsquedas.
export const ML_AFFILIATE = { word: "ale_benzoni", tool: "58527537" } as const;

export const SOCIAL = [
  { name: "YouTube", handle: "@Franquicia400", url: "https://www.youtube.com/@Franquicia400" },
  { name: "Telegram", handle: "@franquicia400", url: "https://t.me/franquicia400" },
  { name: "Instagram", handle: "franquicia.400", url: "https://www.instagram.com/franquicia.400/" },
] as const;

export const SITE = {
  name: "Franquicia 400",
  url: "https://ofertas.knunet.com",
  parent: { name: "KnuNet", url: "https://knunet.com" },
  description:
    "¿Amazon o Mercado Libre? Comparamos lo que te sale traer cada producto puesto en tu casa con lo que sale acá, y te decimos dónde te conviene comprarlo.",
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
  "Audio y video": "/art/cat-audio.webp",
  Cocina: "/art/cat-cocina.webp",
  Hogar: "/art/cat-hogar.webp",
  Gaming: "/art/cat-joystick.webp",
  "Tablets y lectores": "/art/cat-lectores.webp",
  "Carga y energía": "/art/cat-carga.webp",
  Redes: "/art/cat-redes.webp",
  "Cuidado personal": "/art/cat-cuidado.webp",
  Componentes: "/art/cat-componentes.webp",
  Cámaras: "/art/cat-camaras.webp",
  Relojes: "/art/cat-relojes.webp",
  Herramientas: "/art/cat-hogar.webp", // TODO: ilustración propia
  Deportes: "/art/cat-hogar.webp", // TODO: ilustración propia
  Juguetes: "/art/cat-hogar.webp", // TODO: ilustración propia
  Instrumentos: "/art/cat-hogar.webp", // TODO: ilustración propia
  Oficina: "/art/cat-hogar.webp", // TODO: ilustración propia
  Celulares: "/art/cat-hogar.webp", // TODO: ilustración propia
  Bebés: "/art/cat-hogar.webp", // TODO: ilustración propia
  Mascotas: "/art/cat-hogar.webp", // TODO: ilustración propia
  Belleza: "/art/cat-hogar.webp", // TODO: ilustración propia
  Auto: "/art/cat-hogar.webp", // TODO: ilustración propia
  Jardín: "/art/cat-hogar.webp", // TODO: ilustración propia
  Salud: "/art/cat-hogar.webp", // TODO: ilustración propia
};

// Productos cuya categoría no los representa bien llevan su propia ilustración genérica.
export const PRODUCT_ART: Record<string, string> = {
  "8bitdo-ultimate-bluetooth-negro": "/art/cat-joystick.webp",
  "logitech-mx-master-3s": "/art/cat-mouse.webp",
};

export const artFor = (p: { slug: string; category: string }) => PRODUCT_ART[p.slug] ?? CATEGORY_ART[p.category] ?? "/art/cat-perifericos.webp";

// Búsquedas curadas: llevan a Amazon con el tag aunque el producto no esté en el catálogo.
// term: lo que se busca en nuestro catálogo. ml: link de afiliado oficial (generador de Mercado Libre) a esa búsqueda.
export const SEARCHES: Array<{ label: string; query: string; store: Store; category: string; art?: string; ml?: string; term: string }> = [
  { term: "ssd", label: "SSD NVMe de 2 TB", query: "nvme ssd 2tb pcie 4.0", store: "US", category: "Almacenamiento", ml: "https://meli.la/1YNptPJ" },
  { term: "ryzen", label: "Procesadores AMD Ryzen", query: "amd ryzen processor", store: "US", category: "Componentes", ml: "https://meli.la/1ZnvKXh" },
  { term: "auriculares", label: "Auriculares con cancelación de ruido", query: "noise cancelling headphones", store: "US", category: "Audio y video", ml: "https://meli.la/1UsPwMm" },
  { term: "garmin", label: "Relojes Garmin", query: "garmin smartwatch", store: "US", category: "Relojes", ml: "https://meli.la/2cxStP1" },
  { term: "cámara", label: "Cámaras de acción", query: "action camera 4k", store: "US", category: "Cámaras", ml: "https://meli.la/1Q632PA" },
  { term: "kobo", label: "Lectores de libros Kobo", query: "kobo ereader", store: "US", category: "Tablets y lectores", ml: "https://meli.la/1b92rDR" },
  { term: "mouse", label: "Mouse inalámbricos premium", query: "logitech mx master", store: "US", category: "Periféricos", art: "/art/cat-mouse.webp", ml: "https://meli.la/2MgDFB5" },
  { term: "router", label: "Routers Wi-Fi 7", query: "wifi 7 router", store: "US", category: "Redes", ml: "https://meli.la/1uK1xhZ" },
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
