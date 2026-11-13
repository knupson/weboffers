import { describe, expect, it } from "vitest";
import { bajadaDePrecio, etiquetaBajada, preciosPrevios, type HistorialAmazon } from "./bajas-precio";

const HOY = "2026-11-13";
const hist = (precios: Record<string, number>): HistorialAmazon =>
  Object.fromEntries(Object.entries(precios).map(([fecha, p]) => [fecha, { garmin: p }]));

describe("ventana de 7 días", () => {
  it("toma sólo los 7 días anteriores a hoy, sin hoy ni días más viejos ni precios inválidos", () => {
    const h: HistorialAmazon = {
      "2026-11-05": { garmin: 999 }, // 8 días antes: afuera
      "2026-11-06": { garmin: 150 },
      "2026-11-07": { garmin: 0 },
      "2026-11-09": { otro: 10 },
      "2026-11-12": { garmin: 160 },
      "2026-11-13": { garmin: 1 }, // hoy: lo da el precio actual
      "basura": { garmin: 5 },
    };
    expect(preciosPrevios("garmin", HOY, h)).toEqual([150, 160]);
    expect(preciosPrevios("garmin", "13/11", h)).toEqual([]);
    expect(preciosPrevios("garmin", HOY, null)).toEqual([]);
  });
});

describe("bajadaDePrecio", () => {
  it("bajó contra la mediana y es el mínimo de la semana", () => {
    const h = hist({ "2026-11-08": 200, "2026-11-09": 198, "2026-11-10": 200, "2026-11-12": 199 });
    expect(bajadaDePrecio("garmin", 181, HOY, h)).toEqual({ usd: 19, medianaUsd: 199.5, dias: 4 });
    expect(etiquetaBajada({ usd: 19 })).toBe("Bajó USD 19 esta semana");
  });

  it("exige al menos 3 días de historial (altas recientes no)", () => {
    expect(bajadaDePrecio("garmin", 150, HOY, hist({ "2026-11-11": 200, "2026-11-12": 200 }))).toBeNull();
  });

  it("alcanza con 5 % aunque sean menos de USD 10", () => {
    const h = hist({ "2026-11-09": 120, "2026-11-10": 120, "2026-11-11": 120 });
    expect(bajadaDePrecio("garmin", 113.9, HOY, h)?.usd).toBe(6); // 5,08 %
    expect(bajadaDePrecio("garmin", 114.5, HOY, h)).toBeNull(); // 4,6 % y USD 5,5
  });

  it("alcanza con USD 10 aunque sea menos de 5 %", () => {
    const h = hist({ "2026-11-09": 390, "2026-11-10": 390, "2026-11-11": 390 });
    expect(bajadaDePrecio("garmin", 380, HOY, h)?.usd).toBe(10); // 2,6 %
    expect(bajadaDePrecio("garmin", 381, HOY, h)).toBeNull();
  });

  it("si en la semana hubo un precio más bajo que hoy, no es «bajó» (subida artificial y vuelta)", () => {
    const h = hist({ "2026-11-09": 200, "2026-11-10": 170, "2026-11-11": 200, "2026-11-12": 260 });
    expect(bajadaDePrecio("garmin", 180, HOY, h)).toBeNull();
  });

  it("empatar el mínimo de la semana cuenta como mínimo", () => {
    const h = hist({ "2026-11-09": 200, "2026-11-10": 180, "2026-11-11": 200, "2026-11-12": 200 });
    expect(bajadaDePrecio("garmin", 180, HOY, h)?.usd).toBe(20);
  });

  it("precio igual o más alto, o sin precio actual: nada", () => {
    const h = hist({ "2026-11-09": 200, "2026-11-10": 200, "2026-11-11": 200 });
    expect(bajadaDePrecio("garmin", 200, HOY, h)).toBeNull();
    expect(bajadaDePrecio("garmin", 210, HOY, h)).toBeNull();
    expect(bajadaDePrecio("garmin", null, HOY, h)).toBeNull();
    expect(bajadaDePrecio("garmin", Number.NaN, HOY, h)).toBeNull();
  });
});
