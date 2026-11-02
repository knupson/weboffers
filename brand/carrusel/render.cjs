// Uso (desde la raíz): python brand/carrusel/datos.py <slugs...> && node brand/carrusel/render.cjs
// Genera out/carrusel-1..7.png (1080x1350) y out/historia-1..5.png (1080x1920).
const { chromium } = require("C:/Users/KnuPwns/AppData/Local/npm-cache/_npx/13ab0715f9f30c2e/node_modules/playwright");
const fs = require("fs");
const path = require("path");

const OUT = path.join(__dirname, "out");
const D = JSON.parse(fs.readFileSync(path.join(OUT, "datos.json"), "utf8"));
const R = "file:///E:/Repositorios/Personal/weboffers";
const N = D.productos.length + 2;
const ars = (n) => "$ " + Math.round(n).toLocaleString("es-AR");
const foto = (s) => `${R}/public/products/${s}.webp`;
const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;");

const css = (w, h) => `
@font-face{font-family:U;src:url(${R}/brand/ultra.woff2)}
@font-face{font-family:A;src:url(${R}/brand/archivo.woff2);font-weight:100 900}
*{box-sizing:border-box;margin:0}
html,body{width:${w}px;height:${h}px;background:#141210;color:#f4efe4;font-family:A;overflow:hidden}
body{position:relative;padding:72px;display:flex;flex-direction:column}
.t{font:400 92px/1.02 U;color:#f2c230;text-shadow:5px 5px 0 #d7262b,9px 9px 0 #0b0a09}
.cat{font:700 26px A;letter-spacing:.12em;text-transform:uppercase;color:#6ec6f0}
.num{position:absolute;top:72px;right:72px;font:700 26px A;color:#a39a8f}
.name{font:800 52px/1.08 A;margin-top:14px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ph{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;padding:20px 0}
.ph img{max-width:100%;max-height:100%;object-fit:contain;filter:drop-shadow(0 24px 40px rgba(0,0,0,.55))}
.rows{display:grid;grid-template-columns:1fr 1fr;gap:20px}
.row{border:3px solid #3a332d;border-radius:18px;padding:20px 24px;position:relative}
.row.win{border-color:#3ccf7a;background:rgba(60,207,122,.08)}
.row .l{font:700 26px A;color:#cfc6ba}
.row .p{font:800 54px/1.1 A;margin-top:6px}
.row .s{font:500 21px A;color:#a39a8f}
.badge{position:absolute;top:-18px;right:18px;background:#3ccf7a;color:#0b0a09;font:900 22px A;padding:4px 14px;border-radius:999px}
.ah{font:400 54px U;color:#f2c230;margin-top:26px;text-shadow:3px 3px 0 #d7262b}
.foot{font:600 24px A;color:#a39a8f;margin-top:18px}
.blue{color:#6ec6f0}
`;

const page = (w, h, body) => `<!doctype html><html><head><meta charset="utf-8"><style>${css(w, h)}</style></head><body>${body}</body></html>`;

const portada = () => page(1080, 1350, `
<div class="t" style="font-size:120px;margin-top:40px">¿Amazon o<br>Mercado<br>Libre?</div>
<div style="font:700 44px/1.2 A;margin-top:40px;max-width:820px">${D.productos.length} productos del CyberMonday con los dos precios de hoy</div>
<div style="flex:1;position:relative;margin-top:30px">${D.productos.map((p, i) =>
  `<img src="${foto(p.slug)}" style="position:absolute;bottom:0;left:${i * 17.5 - 2}%;width:34%;height:95%;object-fit:contain;transform:rotate(${(i - 2) * 5}deg);filter:drop-shadow(0 16px 24px rgba(0,0,0,.6))">`).join("")}</div>
<div class="foot" style="font-size:30px">Precios del ${D.fecha} · deslizá →</div>`);

const producto = (p, i) => {
  const row = (k, l, pr, s) => `<div class="row${p.gana === k ? " win" : ""}">${p.gana === k ? '<span class="badge">GANA</span>' : ""}<div class="l">${l}</div><div class="p">${pr}</div>${s ? `<div class="s">${s}</div>` : ""}</div>`;
  return page(1080, 1350, `
<div class="num">${i + 2}/${N}</div>
<div class="cat">${esc(p.category)}</div>
<div class="name" style="max-width:860px">${esc(p.name)}</div>
<div class="ph"><img src="${foto(p.slug)}"></div>
<div class="rows">${row("ml", "Mercado Libre", ars(p.ml), "")}${row("amazon", "Traerlo de Amazon", "~" + ars(p.az), "estimado puesto en tu casa")}</div>
<div class="ah">Ahorrás ~${ars(p.ahorro)}</div>
<div class="foot">Precios del ${D.fecha} · ${D.link}</div>`);
};

const cierre = () => page(1080, 1350, `
<div class="num">${N}/${N}</div>
<div class="t" style="margin-top:60px">Comparamos ${D.total} productos todos los días</div>
<div style="font:500 38px/1.35 A;margin-top:50px">Amazon sólo gana si ahorrás 10% o más con envío gratis. Si no, conviene Mercado Libre: llega en días y tiene garantía.</div>
<div style="flex:1"></div>
<div class="t" style="font-size:110px">Link en la bio</div>
<div class="blue" style="font:800 48px A;margin-top:24px">${D.link}</div>`);

const historia = (p) => page(1080, 1920, `
<div style="height:180px"></div>
<div class="t" style="font-size:104px;text-align:center">¿Amazon o<br>Mercado Libre?</div>
<div class="ph"><img src="${foto(p.slug)}"></div>
<div class="name" style="text-align:center;font-size:56px">${esc(p.name)}</div>
<div style="font:700 46px A;text-align:center;margin-top:36px">Mirá cuál conviene hoy</div>
<div class="blue" style="font:800 50px A;text-align:center;margin-top:16px">${D.link}</div>
<div style="height:250px"></div>`);

(async () => {
  const b = await chromium.launch();
  const shots = [
    ...[portada(), ...D.productos.map(producto), cierre()].map((h, i) => [h, 1080, 1350, `carrusel-${i + 1}.png`]),
    ...D.productos.map((p, i) => [historia(p), 1080, 1920, `historia-${i + 1}.png`]),
  ];
  for (const [html, w, h, name] of shots) {
    const pg = await b.newPage({ viewport: { width: w, height: h } });
    const tmp = path.join(OUT, "_placa.html");
    fs.writeFileSync(tmp, html);
    await pg.goto("file:///" + tmp.replace(/\\/g, "/"), { waitUntil: "load" });
    await pg.evaluate(() => document.fonts.ready);
    await pg.screenshot({ path: path.join(OUT, name) });
    await pg.close();
    console.log(name);
  }
  await b.close();
})();
