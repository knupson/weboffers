import { describe, expect, it } from "vitest";
import type { CatalogEntry } from "./data";
import { masVendidos } from "./mas-vendidos";

const p = (slug: string, hot?: string) => ({ slug, hot }) as unknown as CatalogEntry;

describe("masVendidos", () => {
  it("12/11: dos marcas del 02/11 no muestran la sección (vieja e incompleta)", () => {
    expect(masVendidos([p("toshiba", "2026-11-02"), p("redmi", "2026-11-02"), p("x")], "2026-11-12")).toEqual([]);
  });
  it("tres marcas de la semana muestran la fila completa", () => {
    const hot = [p("a", "2026-11-12"), p("b", "2026-11-08"), p("c", "2026-11-05")];
    expect(masVendidos([...hot, p("d")], "2026-11-12").map((x) => x.slug)).toEqual(["a", "b", "c"]);
  });
  it("con menos de 3 frescas no se muestra aunque haya viejas", () => {
    expect(masVendidos([p("a", "2026-11-12"), p("b", "2026-11-11"), p("c", "2026-11-02")], "2026-11-12")).toEqual([]);
  });
  it("una marca con fecha futura no cuenta", () => {
    expect(masVendidos([p("a", "2026-11-13"), p("b", "2026-11-12"), p("c", "2026-11-12")], "2026-11-12")).toEqual([]);
  });
});

describe("applyMasVendidos", () => {
  it("pone la fecha de hoy en los slugs destacados y deja el resto", async () => {
    const { applyMasVendidos } = await import("./data");
    const cat = [p("toshiba", "2026-11-02"), p("jbl"), p("otro", "2026-11-02")];
    const out = applyMasVendidos(cat, { fecha: "2026-11-12", slugs: ["toshiba", "jbl"] });
    expect(out.map((x) => [x.slug, x.hot])).toEqual([["toshiba", "2026-11-12"], ["jbl", "2026-11-12"], ["otro", "2026-11-02"]]);
  });
  it("un archivo ausente o inválido no cambia nada", async () => {
    const { applyMasVendidos } = await import("./data");
    const cat = [p("a", "2026-11-02")];
    expect(applyMasVendidos(cat, null)).toBe(cat);
    expect(applyMasVendidos(cat, { fecha: "ayer", slugs: ["a"] })).toBe(cat);
    expect(applyMasVendidos(cat, { fecha: "2026-11-12", slugs: "a" } as never)).toBe(cat);
  });
});
