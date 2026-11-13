// Vista previa al compartir una ficha (WhatsApp, Telegram, X) — 13/11.
// WhatsApp guarda la vista previa un tiempo: por eso la descripción siempre dice de qué día son los precios
// (nunca se presenta un precio como «de hoy» sin fecha).
import { formatArs } from "./format";

export interface OgFicha {
  title: string;
  description: string;
  image: string | null;
}

interface ProductoOg {
  name: string;
  ml?: { price?: number; checked?: string } | null;
  amazonArs?: number | null;
  amazonChecked?: string | null;
}

const fechaCorta = (iso?: string | null) => (iso && /^\d{4}-\d{2}-\d{2}$/.test(iso) ? iso.slice(8, 10) + "/" + iso.slice(5, 7) : null);

/** URL absoluta HTTPS de la foto (las del sitio vienen como /products/x.webp). */
export function imagenAbsoluta(foto: string | null | undefined, siteUrl: string): string | null {
  if (!foto) return null;
  if (/^https:\/\//.test(foto)) return foto;
  if (foto.startsWith("/")) return new URL(foto, siteUrl).toString();
  return null;
}

export function ogFicha(p: ProductoOg, verdict: "ml" | "amazon" | "sinEnvio", saving: number,
  foto: string | null | undefined, siteUrl: string): OgFicha {
  const ml = p.ml?.price;
  const az = p.amazonArs;
  const fecha = fechaCorta(p.ml?.checked && p.ml.checked === p.amazonChecked ? p.ml.checked : p.amazonChecked ?? p.ml?.checked);
  let title = p.name;
  if (verdict === "amazon" && typeof az === "number") {
    title += `: ~${formatArs(az)} traído de Amazon` + (saving > 0 ? `, ahorrás ~${formatArs(saving)} vs Mercado Libre` : "");
  } else if (verdict === "ml" && typeof ml === "number") {
    title += `: ${formatArs(ml)} en Mercado Libre, conviene más que traerlo`;
  }
  const partes: string[] = [];
  if (typeof ml === "number") partes.push(`Mercado Libre ${formatArs(ml)}`);
  if (typeof az === "number") partes.push(`Amazon puesto en tu casa ~${formatArs(az)} (envío e impuestos incluidos)`);
  const description = [
    fecha ? `Precios del ${fecha}.` : "",
    partes.join(" · ") + (partes.length ? "." : ""),
    "Mirá la cuenta completa y el precio de hoy en Franquicia 400.",
  ].filter(Boolean).join(" ");
  return { title, description, image: imagenAbsoluta(foto, siteUrl) };
}
