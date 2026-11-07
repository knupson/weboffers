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
  it("usa los montos mostrados y avanza un día incluso al cambiar de año", () => {
    expect(productJsonLd(product, "https://ofertas.knunet.com", now).offers).toEqual({
      "@type": "AggregateOffer", priceCurrency: "ARS", offerCount: 2,
      lowPrice: 200000, highPrice: 300000, priceValidUntil: "2027-01-01", availability: "https://schema.org/InStock",
    });
    expect(productJsonLd({ ...product, amazonArs: 400000 }, "https://ofertas.knunet.com", now).offers)
      .toMatchObject({ lowPrice: 300000, highPrice: 400000 });
  });
  it.each([{ ml: undefined }, { amazonArs: null }, { amazonArs: NaN }, { amazonChecked: "2026-12-30" },
    { shipsToArToday: false }, { verified: false }])("omite toda oferta si no es comparable: %o", (change) => {
    expect(productJsonLd({ ...product, ...change }, "https://ofertas.knunet.com", now)).not.toHaveProperty("offers");
  });
});
