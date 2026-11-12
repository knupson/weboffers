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
