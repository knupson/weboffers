import { describe, expect, it, vi } from "vitest";
import {
  artDate,
  comparePrices,
  freshPrice,
  getComparableSlugs,
  isComparable,
  isFreshAmazonDate,
  logIfFewProducts,
  mergeAmazonPrices,
  mergeMlPrices,
  resolvePricesDate,
  roundArs10k,
  type AmazonPrices,
  type CatalogEntry,
  type MlPrices,
} from "./data";

const base = (over: Partial<CatalogEntry>): CatalogEntry => ({
  image: "/products/producto.webp",
  asin: "B000000000",
  store: "US",
  slug: "producto",
  name: "Producto",
  brand: "Marca",
  category: "Monitores",
  summary: "Resumen",
  verified: true,
  ...over,
});

const NOW_OCT_31 = Date.parse("2026-10-31T12:00:00-03:00");

const catalog: CatalogEntry[] = [
  base({
    slug: "con-ml",
    ml: { price: 100000, url: "https://meli.la/abc", checked: "2026-10-01" },
    verdict: "amazon",
    verdictReason: "precio",
  }),
  base({ slug: "sin-ml", asin: "B111111111" }),
];

const prices: MlPrices = {
  generatedAt: "2026-10-31T06:00:00-03:00",
  date: "2026-10-31",
  items: {
    "con-ml": { price: 123456, checked: "2026-10-31", verdict: "ml", verdictReason: "sinAmazon" },
    "sin-ml": { price: 999, checked: "2026-10-31", verdict: "ml", verdictReason: "precio" },
    "no-existe": { price: 5, checked: "2026-10-31", verdict: "ml", verdictReason: "precio" },
  },
};

describe("artDate e isFreshAmazonDate", () => {
  it("calcula la fecha en hora argentina (UTC-3) y exige exactamente la misma fecha", () => {
    // 2026-10-31 02:30 UTC es 2026-10-30 23:30 ART
    const lateUtc = Date.parse("2026-10-31T02:30:00Z");
    expect(artDate(lateUtc)).toBe("2026-10-30");
    expect(isFreshAmazonDate("2026-10-30", lateUtc)).toBe(true);
    expect(isFreshAmazonDate("2026-10-29", lateUtc)).toBe(false);
    expect(isFreshAmazonDate("2026-10-31", lateUtc)).toBe(false);
  });
});

describe("mergeMlPrices", () => {
  it("nunca muestra el ml.price del catálogo cuando no hay archivo de precios o falta el slug", () => {
    const sinArchivo = mergeMlPrices(catalog, null, NOW_OCT_31);
    expect(sinArchivo[0].ml).toBeUndefined();
    expect(sinArchivo[1].ml).toBeUndefined();
  });

  it("pisa precio, fecha, veredicto y motivo sólo cuando checked coincide con hoy (ART)", () => {
    const [merged] = mergeMlPrices(catalog, prices, NOW_OCT_31);
    expect(merged.ml).toEqual({ price: 123456, url: "https://meli.la/abc", checked: "2026-10-31" });
    expect(merged.verdict).toBe("ml");
    expect(merged.verdictReason).toBe("sinAmazon");
  });

  it("descarta el precio de ML si checked es del día anterior (sin ventana de 24h ni fallback al catálogo)", () => {
    const deAyer: MlPrices = {
      ...prices,
      date: "2026-10-30",
      items: {
        "con-ml": { price: 123456, checked: "2026-10-30", verdict: "ml", verdictReason: "precio" },
      },
    };
    const [merged] = mergeMlPrices(catalog, deAyer, NOW_OCT_31);
    expect(merged.ml).toBeUndefined();
  });

  it("no agrega ml a entradas que no lo tenían, aunque el archivo traiga el slug", () => {
    const [, sinMl] = mergeMlPrices(catalog, prices, NOW_OCT_31);
    expect(sinMl).toEqual(catalog[1]);
    expect(sinMl.ml).toBeUndefined();
  });

  it("ignora slugs que no están en el catálogo y no rompe con claves de prototipo", () => {
    const out = mergeMlPrices(
      catalog,
      { ...prices, items: JSON.parse('{"constructor": {"price": 1, "checked": "2026-10-31"}}') },
      NOW_OCT_31,
    );
    expect(out[0].ml).toBeUndefined();
  });

  it("usa el link del día si es de mercadolibre.com.ar y si no deja el del catálogo", () => {
    const url = "https://www.mercadolibre.com.ar/p/MLA1?pdp_filters=item_id%3AMLA7&matt_word=ale_benzoni&matt_tool=58527537";
    const item = prices.items["con-ml"];
    const conUrl = mergeMlPrices(catalog, { ...prices, items: { "con-ml": { ...item, url } } }, NOW_OCT_31);
    expect(conUrl[0].ml?.url).toBe(url);
    for (const bad of ["https://evil.com/mercadolibre.com.ar", "http://www.mercadolibre.com.ar/p/MLA1", "javascript:alert(1)"]) {
      const out = mergeMlPrices(catalog, { ...prices, items: { "con-ml": { ...item, url: bad } } }, NOW_OCT_31);
      expect(out[0].ml?.url).toBe("https://meli.la/abc");
    }
  });

  it("no muta el catálogo original y descarta precios inválidos", () => {
    const snapshot = JSON.parse(JSON.stringify(catalog));
    mergeMlPrices(catalog, prices, NOW_OCT_31);
    expect(catalog).toEqual(snapshot);

    const bad: MlPrices = {
      ...prices,
      items: { "con-ml": { price: Number.NaN, checked: "2026-10-31", verdict: "ml", verdictReason: "precio" } },
    };
    expect(mergeMlPrices(catalog, bad, NOW_OCT_31)[0].ml).toBeUndefined();
  });
});

describe("mergeAmazonPrices & isComparable", () => {
  it("redondea a múltiplos de 10.000 ARS", () => {
    expect(roundArs10k(585000)).toBe(590000);
    expect(roundArs10k(584999)).toBe(580000);
  });

  it("usa sólo el precio scrapeado del día (USD o EUR) y NUNCA cae a listPrice ni a días previos", () => {
    const entries: CatalogEntry[] = [
      base({
        slug: "scraped-usd",
        ml: { price: 500000, url: "https://meli.la/1", checked: "2026-10-31" },
        listPrice: { amount: 400, currency: "USD", source: "https://x.test", checked: "2026-10-01" },
      }),
      base({
        slug: "scraped-eur",
        store: "ES",
        ml: { price: 500000, url: "https://meli.la/2", checked: "2026-10-31" },
      }),
      base({
        slug: "solo-oficial",
        ml: { price: 500000, url: "https://meli.la/3", checked: "2026-10-31" },
        listPrice: { amount: 300, sale: 250, currency: "USD", source: "https://x.test", checked: "2026-10-31" },
      }),
      base({
        slug: "scraped-ayer",
        ml: { price: 500000, url: "https://meli.la/4", checked: "2026-10-31" },
        listPrice: { amount: 400, currency: "USD", source: "https://x.test", checked: "2026-10-31" },
      }),
    ];
    const amazonPrices: AmazonPrices = {
      generatedAt: "2026-10-31T10:00:00Z",
      date: "2026-10-31",
      items: {
        "scraped-usd": { amount: 250, currency: "USD", checked: "2026-10-31" },
        "scraped-eur": { amount: 200, currency: "EUR", checked: "2026-10-31" },
        "scraped-ayer": { amount: 250, currency: "USD", checked: "2026-10-30" },
      },
    };
    const merged = mergeAmazonPrices(entries, amazonPrices, 1200, 1.25, NOW_OCT_31);

    expect(merged[0]).toMatchObject({ amazonArs: 380000, amazonSource: "amazon", amazonChecked: "2026-10-31" });
    expect(merged[1]).toMatchObject({ amazonArs: 380000, amazonSource: "amazon", amazonChecked: "2026-10-31" });
    // Sin precio scrapeado de hoy -> null (aunque tenga listPrice)
    expect(merged[2]).toMatchObject({ amazonArs: null, amazonSource: null, amazonChecked: null });
    expect(merged[2].listPrice?.amount).toBe(300); // listPrice conservado en el objeto
    // Precio scrapeado de ayer -> null (sin ventana de 3 días ni fallback a listPrice)
    expect(merged[3]).toMatchObject({ amazonArs: null, amazonSource: null, amazonChecked: null });

    expect(isComparable(merged[0], null, NOW_OCT_31)).toBe(true);
    expect(isComparable(merged[1], null, NOW_OCT_31)).toBe(true);
    expect(isComparable(merged[2], null, NOW_OCT_31)).toBe(false);
    expect(isComparable(merged[3], null, NOW_OCT_31)).toBe(false);
  });

  it("isComparable exige que tanto ML como Amazon tengan checked == hoy ART y ASIN verificado", () => {
    const ok = base({
      slug: "ok",
      ml: { price: 500000, url: "https://meli.la/1", checked: "2026-10-31" },
      amazonArs: 380000,
      amazonSource: "amazon",
      amazonChecked: "2026-10-31",
    });
    expect(isComparable(ok, null, NOW_OCT_31)).toBe(true);
    expect(
      isComparable(
        { ...ok, ml: { price: 500000, url: "https://meli.la/1", checked: "2026-10-30" } },
        null,
        NOW_OCT_31,
      ),
    ).toBe(false);
    expect(isComparable({ ...ok, amazonChecked: "2026-10-30" }, null, NOW_OCT_31)).toBe(false);
    expect(isComparable({ ...ok, asin: "" }, null, NOW_OCT_31)).toBe(false);
    expect(isComparable({ ...ok, verified: false }, null, NOW_OCT_31)).toBe(false);
  });

  it("recalcula el veredicto y el ahorro desde los mismos montos mostrados (comparePrices)", () => {
    const entries: CatalogEntry[] = [
      base({
        slug: "amazon-mas-caro",
        verdict: "amazon",
        shipsToAr: { freeShipping: true, checked: "2026-10-01" },
        ml: { price: 350000, url: "https://meli.la/1", checked: "2026-10-31" },
      }),
      base({
        slug: "amazon-gana",
        verdict: "ml",
        shipsToAr: { freeShipping: true, checked: "2026-10-01" },
        ml: { price: 500000, url: "https://meli.la/2", checked: "2026-10-31" },
      }),
      base({
        slug: "sin-envio-gratis",
        verdict: "amazon",
        shipsToAr: { freeShipping: false, checked: "2026-10-01" },
        ml: { price: 500000, url: "https://meli.la/3", checked: "2026-10-31" },
      }),
    ];
    const amazonPrices: AmazonPrices = {
      generatedAt: "2026-10-31T10:00:00Z",
      date: "2026-10-31",
      items: {
        "amazon-mas-caro": { amount: 250, currency: "USD", checked: "2026-10-31" },
        "amazon-gana": { amount: 250, currency: "USD", checked: "2026-10-31" },
        "sin-envio-gratis": { amount: 250, currency: "USD", checked: "2026-10-31" },
      },
    };
    const merged = mergeAmazonPrices(entries, amazonPrices, 1200, 1.25, NOW_OCT_31);
    expect(merged[0]).toMatchObject({ amazonArs: 380000, verdict: "ml", verdictReason: "precio" });
    expect(comparePrices(merged[0])).toEqual({ verdict: "ml", saving: 30000 });

    expect(merged[1]).toMatchObject({ amazonArs: 380000, verdict: "amazon", verdictReason: "precio" });
    expect(comparePrices(merged[1])).toEqual({ verdict: "amazon", saving: 120000 });

    // Amazon sale menos pero sin envío gratis confirmado: no hay ganador (nunca "conviene" el más caro).
    expect(merged[2]).toMatchObject({ amazonArs: 380000, verdict: undefined, verdictReason: "precio" });
    expect(comparePrices(merged[2])).toEqual({ verdict: "sinEnvio", saving: 120000 });
  });

  it("filtra slugs del sitemap exigiendo ambos precios del día, MEP y EUR/USD", () => {
    const entries: CatalogEntry[] = [
      base({
        slug: "us-ok",
        ml: { price: 500000, url: "https://meli.la/1", checked: "2026-10-01" },
      }),
      base({
        slug: "es-eur",
        store: "ES",
        ml: { price: 500000, url: "https://meli.la/2", checked: "2026-10-01" },
      }),
    ];
    const mlToday: MlPrices = {
      generatedAt: "2026-10-31T10:00:00Z",
      date: "2026-10-31",
      items: {
        "us-ok": { price: 500000, checked: "2026-10-31" },
        "es-eur": { price: 500000, checked: "2026-10-31" },
      },
    };
    const amzToday: AmazonPrices = {
      generatedAt: "2026-10-31T10:00:00Z",
      date: "2026-10-31",
      items: {
        "us-ok": { amount: 250, currency: "USD", checked: "2026-10-31" },
        "es-eur": { amount: 200, currency: "EUR", checked: "2026-10-31" },
      },
    };
    expect([...getComparableSlugs(entries, mlToday, amzToday, null, 1.25, NOW_OCT_31)]).toEqual([]);
    expect([...getComparableSlugs(entries, mlToday, amzToday, 1200, null, NOW_OCT_31)]).toEqual(["us-ok"]);
    expect([...getComparableSlugs(entries, mlToday, amzToday, 1200, 1.25, NOW_OCT_31)]).toEqual(["us-ok", "es-eur"]);
  });
});

describe("shipsToAr relevado hoy (amazon-ar)", () => {
  const entries: CatalogEntry[] = [
    base({
      slug: "envia",
      shipsToAr: { freeShipping: false, checked: "2026-10-01" },
      ml: { price: 500000, url: "https://meli.la/1", checked: "2026-10-31" },
    }),
    base({
      slug: "no-envia",
      shipsToAr: { freeShipping: true, checked: "2026-10-01" },
      ml: { price: 500000, url: "https://meli.la/2", checked: "2026-10-31" },
    }),
    base({
      slug: "relevado-ayer",
      shipsToAr: { freeShipping: false, checked: "2026-10-01" },
      ml: { price: 500000, url: "https://meli.la/3", checked: "2026-10-31" },
    }),
  ];
  const amazonPrices: AmazonPrices = {
    generatedAt: "2026-10-31T10:00:00Z",
    date: "2026-10-31",
    items: {
      "envia": { amount: 250, currency: "USD", checked: "2026-10-31", shipsToAr: { ships: true, free: true, checked: "2026-10-31" } },
      "no-envia": { amount: 250, currency: "USD", checked: "2026-10-31", shipsToAr: { ships: false, free: null, checked: "2026-10-31" } },
      "relevado-ayer": { amount: 250, currency: "USD", checked: "2026-10-31", shipsToAr: { ships: true, free: true, checked: "2026-10-30" } },
    },
  };

  it("mergeAmazonPrices pisa shipsToAr y setea shipsToArToday sólo si checked es hoy ART", () => {
    const merged = mergeAmazonPrices(entries, amazonPrices, 1200, 1.25, NOW_OCT_31);
    expect(merged[0].shipsToAr).toEqual({ freeShipping: true, checked: "2026-10-31" });
    expect(merged[0].shipsToArToday).toBe(true);
    expect(merged[1].shipsToAr).toEqual({ freeShipping: false, checked: "2026-10-31" });
    expect(merged[1].shipsToArToday).toBe(false);
    // Relevamiento de ayer: no pisa el shipsToAr del catálogo ni setea shipsToArToday.
    expect(merged[2].shipsToAr).toEqual({ freeShipping: false, checked: "2026-10-01" });
    expect(merged[2].shipsToArToday).toBeUndefined();
  });

  it("isComparable es false cuando shipsToArToday es false, aunque tenga los dos precios de hoy", () => {
    const merged = mergeAmazonPrices(entries, amazonPrices, 1200, 1.25, NOW_OCT_31);
    expect(isComparable(merged[0], null, NOW_OCT_31)).toBe(true);
    expect(isComparable(merged[1], null, NOW_OCT_31)).toBe(false);
    expect(isComparable(merged[2], null, NOW_OCT_31)).toBe(true);
    expect(isComparable({ ...merged[0], shipsToArToday: false }, null, NOW_OCT_31)).toBe(false);
    expect(isComparable({ ...merged[0], shipsToArToday: true }, null, NOW_OCT_31)).toBe(true);
  });
});

describe("freshPrice, logIfFewProducts y resolvePricesDate", () => {
  it("freshPrice exige la misma fecha ART de hoy (sin ventana de 24h)", () => {
    const itemHoy = {
      asin: "B001",
      store: "US" as const,
      title: "X",
      priceUsd: 100,
      priceFetchedAt: "2026-10-31T04:00:00Z", // 2026-10-31 01:00 ART
      imageUrl: null,
      availability: null,
    };
    const itemAyerReciente = {
      ...itemHoy,
      priceFetchedAt: "2026-10-31T02:50:00Z", // 2026-10-30 23:50 ART (hace <15hs pero otro día ART)
    };
    expect(freshPrice(itemHoy, NOW_OCT_31)).toEqual(itemHoy);
    expect(freshPrice(itemAyerReciente, NOW_OCT_31)).toBeNull();
  });

  it("logIfFewProducts emite MENOS_DE_100 cuando N < 100 sin lanzar error", () => {
    const spy = vi.fn();
    expect(logIfFewProducts(32, spy)).toBe(true);
    expect(spy).toHaveBeenCalledWith("MENOS_DE_100: 32 productos comparables");

    const spyOk = vi.fn();
    expect(logIfFewProducts(100, spyOk)).toBe(false);
    expect(spyOk).not.toHaveBeenCalled();
  });

  it("resolvePricesDate devuelve la fecha sólo cuando ambos archivos coinciden", () => {
    expect(
      resolvePricesDate(
        { generatedAt: "", date: "2026-10-31", items: {} },
        { generatedAt: "", date: "2026-10-31", items: {} },
      ),
    ).toBe("2026-10-31");
    expect(
      resolvePricesDate(
        { generatedAt: "", date: "2026-10-31", items: {} },
        { generatedAt: "", date: "2026-10-30", items: {} },
      ),
    ).toBe("");
    expect(resolvePricesDate(null, null)).toBe("");
  });
});

describe("regla de foto", () => {
  it("un producto sin foto no es comparable aunque tenga los dos precios de hoy", () => {
    const now = Date.parse("2026-10-31T15:00:00-03:00");
    const conTodo = base({ verified: true, ml: { price: 100000, url: "https://www.mercadolibre.com.ar/p/MLA1", checked: "2026-10-31" }, amazonArs: 90000, amazonSource: "amazon", amazonChecked: "2026-10-31" } as Partial<CatalogEntry>);
    expect(isComparable(conTodo, null, now)).toBe(true);
    expect(isComparable({ ...conTodo, image: undefined }, null, now)).toBe(false);
  });
});
