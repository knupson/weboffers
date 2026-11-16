// Avisa a los buscadores de IndexNow (Bing, Yandex, Seznam...) todas las URLs del sitemap.
// Uso: node tools/indexnow.mjs   (después de un deploy)
import { readdirSync, readFileSync } from "node:fs";

const HOST = "ofertas.knunet.com";
// La clave sale de public/<clave>.txt (única fuente; misma regla que leerClaveIndexNow en worker/deployer/deploy.mjs):
// el único <clave>.txt cuyo contenido es su propio nombre.
const PUBLIC = new URL("../public/", import.meta.url);
const claves = readdirSync(PUBLIC)
  .map((file) => /^([A-Za-z0-9-]{8,128})\.txt$/.exec(file)?.[1])
  .filter((k) => k && readFileSync(new URL(`${k}.txt`, PUBLIC), "utf8").trim() === k);
if (claves.length !== 1) throw new Error(`se esperaba 1 archivo de clave en public/ y hay ${claves.length}`);
const KEY = claves[0];

const index = await (await fetch(`https://${HOST}/sitemap-index.xml`)).text();
const maps = [...index.matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]);
const urls = [];
for (const map of maps) urls.push(...[...(await (await fetch(map)).text()).matchAll(/<loc>([^<]+)<\/loc>/g)].map((m) => m[1]));

const res = await fetch("https://api.indexnow.org/indexnow", {
  method: "POST",
  headers: { "Content-Type": "application/json; charset=utf-8" },
  body: JSON.stringify({ host: HOST, key: KEY, keyLocation: `https://${HOST}/${KEY}.txt`, urlList: urls }),
});
console.log(`IndexNow: ${urls.length} URLs, respuesta ${res.status}`);
