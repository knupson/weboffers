import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { CATEGORY_ART } from "../config";

describe("ilustraciones de categoría", () => {
  it("cada ruta de CATEGORY_ART existe en public/ con su .json de procedencia", () => {
    for (const [cat, src] of Object.entries(CATEGORY_ART)) {
      const file = path.join(process.cwd(), "public", src);
      expect(fs.existsSync(file), `${cat}: ${src}`).toBe(true);
      expect(fs.existsSync(`${file}.json`), `${cat}: ${src}.json`).toBe(true);
    }
  });
  it("12/11: las categorías publicadas ya no usan la ilustración de Hogar", () => {
    for (const cat of ["Juguetes", "Auto", "Anteojos", "Herramientas", "Mochilas", "Celulares", "Deportes", "Salud", "Mascotas"]) {
      expect(CATEGORY_ART[cat], cat).not.toBe("/art/cat-hogar.webp");
    }
  });
});
