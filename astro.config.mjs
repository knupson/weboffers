import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";
import sitemap from "@astrojs/sitemap";
import { loadComparableSlugs } from "./src/lib/data.ts";

const comparableSlugs = await loadComparableSlugs();

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
