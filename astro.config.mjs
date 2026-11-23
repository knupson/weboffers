import { defineConfig } from "astro/config";
import preact from "@astrojs/preact";
import sitemap from "@astrojs/sitemap";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import { loadComparableSlugs } from "./src/lib/data.ts";
import { guiasSinPagina, loadGuias, redireccionesGuias } from "./src/lib/guias.ts";

const comparableSlugs = await loadComparableSlugs();

export default defineConfig({
  site: "https://ofertas.knunet.com",
  output: "static",
  integrations: [
    preact(),
    {
      // Una guía dinámica bajo su mínimo no se genera; en vez de 404 la mandamos con 301 al índice (el sticker o el anuncio que apunta ahí no queda roto).
      name: "redirecciones-guias",
      hooks: {
        "astro:build:done": async ({ dir, logger }) => {
          // Se mira lo que de verdad se generó: si la guía tiene página, nunca lleva 301.
          const slugs = guiasSinPagina(loadGuias(), (slug) => fs.existsSync(fileURLToPath(new URL(`guias/${slug}/index.html`, dir))));
          const extra = redireccionesGuias(slugs);
          if (!extra) return;
          fs.appendFileSync(fileURLToPath(new URL("_redirects", dir)), extra);
          logger.info(`GUIAS_REDIRECCION ${slugs.join(",")}`);
        },
      },
    },
    sitemap({
      filter: (page) => {
        const m = page.match(/\/productos\/([^/]+)\/?$/);
        return m ? comparableSlugs.has(m[1]) : true;
      },
    }),
  ],
});
