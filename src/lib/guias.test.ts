import { describe, expect, it } from "vitest";
import { ahorroGuia, guiasPublicables, productosDeGuia, validarGuias, type Guia } from "./guias";

const prod = (slug: string, category: string, ml: number, amazonArs: number, freeShipping = true) => ({
  slug, category, ml: { price: ml, url: "", checked: "2026-11-21" }, amazonArs,
  shipsToAr: { freeShipping, checked: "2026-11-21" },
});

const base: Guia = {
  slug: "g", title: "t", description: "d", h1: "h", intro: "i", sections: [], faq: [],
};

const comparables = [
  prod("reloj-a", "Relojes", 1_000_000, 400_000), // ahorra 600.000 (60 %)
  prod("reloj-b", "Relojes", 2_000_000, 1_200_000), // ahorra 800.000 (40 %)
  prod("reloj-c", "Relojes", 300_000, 90_000), // ahorra 210.000 (70 %)
  prod("reloj-d", "Relojes", 500_000, 600_000), // conviene ML: -100.000
  prod("taladro", "Herramientas", 900_000, 300_000),
];

describe("ahorroGuia", () => {
  it("calcula la diferencia en pesos y en porcentaje sobre el precio de Mercado Libre", () => {
    expect(ahorroGuia(comparables[0])).toEqual({ ars: 600_000, pct: 0.6 });
  });
});

describe("productosDeGuia", () => {
  it("filtra por categorías y ordena por ahorro en pesos", () => {
    const g = { ...base, filtro: { categorias: ["Relojes"], ordenarPor: "ahorro_ars" as const, limite: 3, minimo: 2 } };
    expect(productosDeGuia(g, comparables).map((p) => p.slug)).toEqual(["reloj-b", "reloj-a", "reloj-c"]);
  });

  it("ordena por porcentaje y acepta varias categorías", () => {
    const g = { ...base, filtro: { categorias: ["Relojes", "Herramientas"], ordenarPor: "ahorro_pct" as const, limite: 2, minimo: 1 } };
    expect(productosDeGuia(g, comparables).map((p) => p.slug)).toEqual(["reloj-c", "taladro"]);
  });

  it("pone primero los related publicados y completa con el filtro sin repetir", () => {
    const g = { ...base, related: ["reloj-d", "no-publicado"], filtro: { categorias: ["Relojes"], ordenarPor: "ahorro_ars" as const, limite: 3, minimo: 1 } };
    expect(productosDeGuia(g, comparables).map((p) => p.slug)).toEqual(["reloj-d", "reloj-b", "reloj-a"]);
  });

  it("sin filtro mantiene el comportamiento anterior: sólo los related publicados", () => {
    expect(productosDeGuia({ ...base, related: ["taladro", "otro"] }, comparables).map((p) => p.slug)).toEqual(["taladro"]);
    expect(productosDeGuia(base, comparables)).toEqual([]);
  });
});

describe("guiasPublicables", () => {
  it("no publica una guía dinámica con menos productos que el mínimo", () => {
    const g = { ...base, filtro: { categorias: ["Relojes"], ordenarPor: "ahorro_ars" as const, limite: 8, minimo: 5 } };
    expect(guiasPublicables([g], comparables)).toEqual([]);
    expect(guiasPublicables([{ ...g, filtro: { ...g.filtro, minimo: 4 } }], comparables)).toHaveLength(1);
  });

  it("las guías sin filtro se publican aunque no tengan productos", () => {
    expect(guiasPublicables([base], comparables)).toHaveLength(1);
  });

  it("la insignia del primero sólo va si ese producto ahorra trayéndolo", () => {
    const g = { ...base, badgePrimero: "Mayor ahorro real", filtro: { categorias: ["Relojes"], ordenarPor: "ahorro_ars" as const, limite: 3, minimo: 1 } };
    const [r] = guiasPublicables([g], comparables);
    expect(r.notas["reloj-b"]).toEqual({ badge: "Mayor ahorro real" });
    const soloMl = { ...g, related: ["reloj-d"] };
    expect(guiasPublicables([soloMl], comparables)[0].notas["reloj-d"]).toBeUndefined();
  });

  it("la insignia exige el mismo veredicto que la tarjeta: ahorro de al menos 10 % y envío gratis", () => {
    const g = { ...base, badgePrimero: "Mayor ahorro real", filtro: { categorias: ["X"], ordenarPor: "ahorro_ars" as const, limite: 3, minimo: 1 } };
    // Ahorra 5 %: la tarjeta dice que conviene Mercado Libre, así que no va la insignia.
    expect(guiasPublicables([g], [prod("chico", "X", 1_000_000, 950_000)])[0].notas).toEqual({});
    // Ahorra 50 % pero sin envío gratis confirmado: la tarjeta dice «sin envío», tampoco.
    expect(guiasPublicables([g], [prod("sin-envio", "X", 1_000_000, 500_000, false)])[0].notas).toEqual({});
    expect(guiasPublicables([g], [prod("ok", "X", 1_000_000, 900_000)])[0].notas).toEqual({ ok: { badge: "Mayor ahorro real" } });
  });

  it("combina la nota editorial del JSON con la insignia automática", () => {
    const g = { ...base, badgePrimero: "Mayor ahorro real", notas: { "reloj-b": { texto: "Automático suizo" }, "reloj-a": { badge: "Conviene acá" } },
      filtro: { categorias: ["Relojes"], ordenarPor: "ahorro_ars" as const, limite: 2, minimo: 1 } };
    const [r] = guiasPublicables([g], comparables);
    expect(r.notas["reloj-b"]).toEqual({ badge: "Mayor ahorro real", texto: "Automático suizo" });
    expect(r.notas["reloj-a"]).toEqual({ badge: "Conviene acá" });
  });
});

describe("validarGuias", () => {
  it("rechaza filtros mal escritos en vez de publicar una guía vacía en silencio", () => {
    const mal = (filtro: unknown) => () => validarGuias([{ ...base, filtro } as Guia]);
    expect(mal({ categorias: [], ordenarPor: "ahorro_ars", limite: 8, minimo: 4 })).toThrow(/categorias/);
    expect(mal({ categorias: ["Relojes"], ordenarPor: "precio", limite: 8, minimo: 4 })).toThrow(/ordenarPor/);
    expect(mal({ categorias: ["Relojes"], ordenarPor: "ahorro_ars", limite: 3, minimo: 4 })).toThrow(/minimo/);
    expect(() => validarGuias([base, base])).toThrow(/repetido/);
  });
});
