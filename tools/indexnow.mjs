// Avisa a los buscadores de IndexNow (Bing, Yandex, Seznam...) todas las URLs del sitemap.
// Uso: node tools/indexnow.mjs   (después de un deploy)
const HOST = "ofertas.knunet.com";
const KEY = "4c6b2954da1fb15ffbe9500994ed7f54";

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
