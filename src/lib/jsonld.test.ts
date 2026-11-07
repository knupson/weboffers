import { describe, expect, it } from "vitest";
import { productJsonLd } from "./jsonld";
import type { CatalogEntry } from "./data";

const now = Date.parse("2026-12-31T15:00:00Z");
const product: CatalogEntry = {
  slug: "ssd", name: "SSD 1 TB", brand: "SanDisk", category: "Almacenamiento", summary: "SSD",
  asin: "B123", store: "US", verified: true, image: "/products/ssd.webp",
  shipsToAr: { checked: "2026-12-31", freeShipping: true },
  ml: { price: 300000, checked: "2026-12-31", url: "https://mercadolibre.com.ar/p/MLA1" },
  amazonArs: 200000, amazonUsd: 150, amazonSource: "amazon", amazonChecked: "2026-12-31",
};
describe("Product JSON-LD", () => {
  it("declara sólo el precio real de Mercado Libre, válido el día del relevamiento", () => {
    expect(productJsonLd(product, "https://ofertas.knunet.com", now).offers).toEqual({
      "@type": "Offer", priceCurrency: "ARS", price: 300000,
      priceValidUntil: "2026-12-31", url: "https://mercadolibre.com.ar/p/MLA1",
    });
  });
  it.each([{ ml: undefined }, { amazonArs: null }, { amazonArs: NaN }, { amazonChecked: "2026-12-30" },
    { shipsToArToday: false }, { verified: false }])("omite toda oferta si no es comparable: %o", (change) => {
    expect(productJsonLd({ ...product, ...change }, "https://ofertas.knunet.com", now)).not.toHaveProperty("offers");
  });
});
