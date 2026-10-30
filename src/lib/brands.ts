import { siAsus, siDell, siSamsung, siSony, siDelonghi } from "simple-icons";

// Logos oficiales vía Simple Icons. Vienen centrados en 24x24: los logotipos anchos
// se recortan a su franja central para que se lean. Las marcas sin logo salen con su nombre.
type Logo = { path: string; viewBox: string; ratio: number };

const wide = (path: string): Logo => ({ path, viewBox: "0 9 24 6", ratio: 4 });
const square = (path: string): Logo => ({ path, viewBox: "0 0 24 24", ratio: 1 });

const LOGOS: Record<string, Logo> = {
  ASUS: wide(siAsus.path),
  Dell: square(siDell.path),
  Samsung: wide(siSamsung.path),
  Sony: wide(siSony.path),
  "De'Longhi": wide(siDelonghi.path),
};

export function brandLogo(brand: string): Logo | null {
  return LOGOS[brand] ?? null;
}
