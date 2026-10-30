import fs from "node:fs";
import path from "node:path";

export interface Guia {
  slug: string;
  title: string;
  description: string;
  h1: string;
  intro: string;
  sections: Array<{ heading: string; paragraphs: string[]; bullets?: string[] }>;
  faq: Array<{ q: string; a: string }>;
  related: string[];
}

export function loadGuias(): Guia[] {
  try {
    return JSON.parse(fs.readFileSync(path.join(process.cwd(), "data/guias.json"), "utf-8")) as Guia[];
  } catch {
    return [];
  }
}

const escape = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/** Escapa el texto y convierte las rutas internas escritas entre paréntesis en links. */
export function linkify(text: string): string {
  return escape(text).replace(/\s?\((\/(?:calculadora|productos|guias|guia)\/[a-z0-9-]*\/?)\)/g, (_, href: string) => {
    const label = href.startsWith("/calculadora") ? "abrirla" : href.startsWith("/productos") ? "ver producto" : "leer guía";
    return ` (<a href="${href}">${label}</a>)`;
  });
}
