import fs from "node:fs";
import path from "node:path";
import { artDate } from "./data";

export interface MlSheet {
  fetched: string;
  name: string;
  attributes: [string, string][];
  mainFeatures: string[];
  // Conservamos los ids originales para volver a comprobar la capacidad al renderizar.
  rawAttributes: { id: string; value_name?: string | null }[];
}

function quantities(text: string): Set<string> {
  return new Set([...text.matchAll(/(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(GB|TB)\b(?!\s*\/)/gi)]
    .map((m) => `${Number(m[1].replace(",", "."))}${m[2].toUpperCase()}`));
}

export function validMlSheet(productName: string, input: unknown, now = Date.now()): MlSheet | null {
  if (!input || typeof input !== "object") return null;
  const sheet = input as MlSheet;
  if (typeof sheet.name !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(sheet.fetched)) return null;
  const stamp = Date.parse(`${sheet.fetched}T00:00:00Z`);
  const age = (Date.parse(`${artDate(now)}T00:00:00Z`) - stamp) / 86400e3;
  if (!Number.isFinite(age) || age < 0 || age > 7 || new Date(stamp).toISOString().slice(0, 10) !== sheet.fetched) return null;
  if (!Array.isArray(sheet.rawAttributes) || !Array.isArray(sheet.attributes) || !Array.isArray(sheet.mainFeatures)) return null;
  if (!sheet.attributes.every((a) => Array.isArray(a) && a.length === 2 && a.every((v) => typeof v === "string")) ||
      !sheet.mainFeatures.every((text) => typeof text === "string")) return null;
  const names = new Set([...quantities(productName), ...quantities(sheet.name)]);
  for (const attribute of sheet.rawAttributes) {
    if (!attribute || typeof attribute.id !== "string" || (attribute.value_name != null && typeof attribute.value_name !== "string")) return null;
    // Mismo criterio que worker/ml_fichas.py: sin máximos ni velocidades; RAM sólo si el nombre trae dos cantidades.
    const id = attribute.id.toUpperCase();
    const kind = /MAX_|SPEED/.test(id) ? null : id.includes("RAM") ? "ram" : /CAPACITY|INTERNAL_MEMORY|STORAGE/.test(id) ? "storage" : null;
    if (!kind || !names.size || (kind === "ram" && names.size < 2)) continue;
    if ([...quantities(attribute.value_name ?? "")].some((q) => !names.has(q))) return null;
  }
  return sheet;
}

export function loadMlSheet(catalogId: string | undefined, productName: string, now = Date.now()): MlSheet | null {
  if (!catalogId) return null;
  try {
    // Igual que readJson de data.ts: relativo a la raíz del proyecto. Con import.meta.url, en el build
    // la ruta apuntaba a la carpeta del bundle y ninguna ficha se mostraba (07/11).
    const data = JSON.parse(fs.readFileSync(path.join(process.cwd(), "data", "ml-fichas.json"), "utf8"));
    return validMlSheet(productName, data.items?.[catalogId], now);
  } catch { return null; }
}
