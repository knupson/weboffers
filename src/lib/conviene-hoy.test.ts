import { expect, it } from "vitest";
import { rankToday } from "./conviene-hoy";
import type { CatalogEntry } from "./data";

const now = Date.parse("2026-11-07T15:00:00Z");
const product: CatalogEntry = { slug: "ssd", name: "SSD", brand: "SanDisk", category: "SSD", summary: "SSD", asin: "B1", store: "US",
  verified: true, image: "/ssd.webp", shipsToAr: { checked: "2026-11-07", freeShipping: true },
  ml: { price: 300000, checked: "2026-11-07", url: "https://mercadolibre.com.ar" },
  amazonArs: 200000, amazonUsd: 150, amazonSource: "amazon", amazonChecked: "2026-11-07" };
it("ordena por ahorro y limita cada lista a diez sin alterar los productos", () => {
  const products = Array.from({ length: 12 }, (_, i) => ({ ...product, slug: `ssd-${i}`, amazonArs: 100000 + i * 10000 }));
  const result = rankToday([...products, { ...product, slug: "local", amazonArs: 400000 }], "2026-11-07", now);
  expect(result.count).toBe(13);
  expect(result.amazon).toHaveLength(10);
  expect(result.amazon[0].product.slug).toBe("ssd-0");
  expect(result.amazon[0].saving).toBe(200000);
  expect(result.ml[0].saving).toBe(100000);
});
it("excluye precios viejos, faltantes y envíos no confirmados", () => {
  expect(rankToday([product], "2026-11-06", now)).toEqual({ count: 0, amazon: [], ml: [] });
  for (const changes of [{ amazonChecked: "2026-11-06" }, { ml: undefined }, { shipsToArToday: false }]) {
    expect(rankToday([{ ...product, ...changes }], "2026-11-07", now).count).toBe(0);
  }
});
