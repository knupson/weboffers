import fs from "node:fs";
import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";
import sitemap from "@astrojs/sitemap";

function readJson(rel) {
  try {
    return JSON.parse(fs.readFileSync(new URL(rel, import.meta.url), "utf-8"));
  } catch {
    return null;
  }
}

function getComparableSlugs() {
  const catalog = readJson("./data/catalog.json") ?? [];
  const mlPrices = readJson("./data/ml-prices.json")?.items ?? {};
  const amazonPrices = readJson("./data/amazon-prices.json")?.items ?? {};
  return new Set(
    catalog
      .filter((p) => {
        if (!p.verified || !p.asin || !p.ml) return false;
        const mlPrice = mlPrices[p.slug]?.price ?? p.ml?.price ?? 0;
        const amzPrice = amazonPrices[p.slug]?.amount ?? p.listPrice?.sale ?? p.listPrice?.amount ?? 0;
        return Number.isFinite(mlPrice) && mlPrice > 0 && Number.isFinite(amzPrice) && amzPrice > 0;
      })
      .map((p) => p.slug),
  );
}

const comparableSlugs = getComparableSlugs();

export default defineConfig({
  site: "https://ofertas.knunet.com",
  output: "static",
  integrations: [
    preact(),
    sitemap({
      filter: (page) => {
        const m = page.match(/\/productos\/([^/]+)\/?$/);
        return m ? comparableSlugs.has(m[1]) : true;
      },
    }),
  ],
});
