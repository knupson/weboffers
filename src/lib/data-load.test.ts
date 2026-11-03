import fs from "node:fs";
import { afterEach, expect, it, vi } from "vitest";
import { loadProducts } from "./data";
import * as estimate from "./estimate";

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); });

function fallback(mep: unknown) {
  vi.spyOn(estimate, "buildQuotes").mockResolvedValue({ mep: null, eurUsd: 1.08 });
  const data: Record<string, unknown> = {
    "offers.json": { items: [], rates: { mep } },
    "catalog.json": [{ slug: "a", asin: "A", verified: true, image: "/a.webp",
      ml: { price: 500000 }, shipsToAr: { freeShipping: true, checked: "2026-11-03" } }],
    "ml-prices.json": { date: "2026-11-03", items: { a: { price: 500000, checked: "2026-11-03" } } },
    "amazon-prices.json": { date: "2026-11-03", items: { a: { amount: 200, currency: "USD", checked: "2026-11-03" } } },
  };
  vi.spyOn(fs, "readFileSync").mockImplementation(((file: string) =>
    JSON.stringify(data[file.split(/[\\/]/).at(-1)!] ?? null)) as typeof fs.readFileSync);
  vi.stubEnv("OFFERS_URL", "");
}

it("usa la cotización del worker si dolarapi falla", async () => {
  fallback(1200);
  const { products } = await loadProducts(Date.parse("2026-11-03T15:00:00Z"));
  expect(products[0].amazonArs).toBe(300000);
  expect(products[0].amazonSource).toBe("amazon");
});

it.each([null, 0, -1, "1200"])("falla sin MEP válido (%s), impidiendo el build", async (mep) => {
  fallback(mep);
  await expect(loadProducts()).rejects.toThrow("Sin cotización MEP válida");
});
