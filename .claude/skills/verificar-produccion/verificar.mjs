// Verificación de producción de Franquicia 400 (ofertas.knunet.com).
//   node .claude/skills/verificar-produccion/verificar.mjs foto       → guarda la cantidad publicada ANTES del cambio
//   node .claude/skills/verificar-produccion/verificar.mjs [comparar] → controles de DESPUÉS + 3 fichas al azar para Chrome
// Sale con 1 si algún control es FALLA. Todo lo que imprime sale de lo leído en esta corrida.
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = 'https://ofertas.knunet.com';
const here = path.dirname(fileURLToPath(import.meta.url));
const FOTO = path.join(here, 'ultima-foto.json');
const modo = process.argv[2] ?? 'comparar';

const hora = () => new Date().toLocaleString('sv-SE', { timeZone: 'America/Argentina/Buenos_Aires' });
const hoyAR = () => hora().slice(0, 10);
const get = async (url) => {
  const r = await fetch(`${url}${url.includes('?') ? '&' : '?'}v=${Date.now()}`, { headers: { 'cache-control': 'no-cache' } });
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return r.text();
};

const estado = JSON.parse(await get(`${SITE}/estado.json`));
console.log(`[${hora()}] estado.json: publicados=${estado.publicados} preciosDe=${estado.preciosDe} slotML=${estado.slot} sha=${estado.version?.sha?.slice(0, 7) ?? '—'}`);

if (modo === 'foto') {
  writeFileSync(FOTO, JSON.stringify({ at: hora(), publicados: estado.publicados, sha: estado.version?.sha ?? null }, null, 1));
  console.log(`Foto guardada en ${FOTO}. Después del cambio: correr sin argumentos.`);
} else {

const fallas = [];
const avisos = [];

// 1. Precios del día (regla de negocio 2: nada viejo).
if (estado.preciosDe !== hoyAR()) fallas.push(`precios de Amazon del ${estado.preciosDe}; hoy (ART) es ${hoyAR()}`);

// 2. Sitemap y estado.json tienen que contar lo mismo.
const sitemap = await get(`${SITE}/sitemap-0.xml`);
const fichas = [...new Set(sitemap.match(/https:\/\/ofertas\.knunet\.com\/productos\/[a-z0-9-]+\//g) ?? [])];
if (fichas.length !== estado.publicados) fallas.push(`sitemap tiene ${fichas.length} fichas y estado.json dice ${estado.publicados}`);

// 3. Cantidad publicada antes vs después (regla de negocio 4).
if (existsSync(FOTO)) {
  const antes = JSON.parse(readFileSync(FOTO, 'utf8'));
  const linea = `publicados antes=${antes.publicados} (foto ${antes.at}) → ahora=${estado.publicados}`;
  if (estado.publicados < antes.publicados) fallas.push(`CAÍDA: ${linea}. Es un error hasta que se demuestre lo contrario.`);
  else console.log(`OK  ${linea}`);
} else {
  avisos.push('no hay foto previa: correr `verificar.mjs foto` ANTES del próximo cambio para poder comparar');
}
if (estado.publicados < 100) avisos.push(`publicados=${estado.publicados}: debajo del mínimo de 100 que pidió Alejandro`);

// 4. ¿Lo publicado es lo último de main?
try {
  execFileSync('git', ['fetch', '-q', 'origin', 'main'], { stdio: 'ignore' });
  const main = execFileSync('git', ['rev-parse', 'origin/main'], { encoding: 'utf8' }).trim();
  const pub = /^[0-9a-f]{40}$/.test(estado.version?.sha ?? '') ? estado.version.sha : '';
  if (pub && pub !== main) {
    const cambios = execFileSync('git', ['diff', '--name-only', pub, main], { encoding: 'utf8' }).trim().split('\n').filter(Boolean);
    const sitio = cambios.filter((f) => /^(src|public|data|astro\.config|package)/.test(f));
    const msg = `publicado ${pub.slice(0, 7)} ≠ origin/main ${main.slice(0, 7)}; ${cambios.length} archivo(s) distintos, ${sitio.length} del sitio${sitio.length ? ': ' + sitio.slice(0, 5).join(', ') : ''}`;
    (sitio.length ? fallas : avisos).push(sitio.length ? `${msg}. Falta desplegar (bash tools/deploy.sh).` : msg);
  } else if (pub) console.log(`OK  publicado = origin/main (${main.slice(0, 7)})`);
} catch (e) {
  avisos.push(`no pude comparar con origin/main: ${e.message.split('\n')[0]}`);
}

// 5. Tres fichas al azar con sus links de tienda, para comparar en Chrome.
const muestra = fichas.sort(() => Math.random() - 0.5).slice(0, 3);
console.log('\nFichas para comparar en Chrome (precio de la página vs tienda):');
for (const url of muestra) {
  const completo = await get(url);
  // Sólo el producto de la ficha: después del primer <h2>Más … vienen las tarjetas de relacionados.
  const corte = completo.search(/<h2>Más /);
  const html = corte > 0 ? completo.slice(0, corte) : completo;
  const fecha = html.match(/data-prices-date="([^"]+)"/)?.[1] ?? '—';
  const amazon = [...new Set(html.match(/https:\/\/www\.amazon\.com\/dp\/[A-Z0-9]+\?tag=[a-z0-9-]+/g) ?? [])];
  const ml = [...new Set((html.match(/https:\/\/www\.mercadolibre\.com\.ar\/[^"]+/g) ?? []).map((u) => u.replaceAll('&amp;', '&')))];
  if (fecha !== hoyAR()) fallas.push(`${url} tiene data-prices-date=${fecha}`);
  console.log(`- ${url}  (precios del ${fecha})\n    Amazon: ${amazon.join(' | ') || 'SIN LINK'}\n    ML:     ${ml.join(' | ') || 'SIN LINK'}`);
  if (!amazon.length || !ml.length) fallas.push(`${url} sin link de ${!amazon.length ? 'Amazon' : 'Mercado Libre'}`);
}

console.log('');
for (const a of avisos) console.log(`AVISO ${a}`);
for (const f of fallas) console.log(`FALLA ${f}`);
console.log(fallas.length ? `\n${fallas.length} falla(s).` : '\nControles automáticos OK. Falta la comparación en Chrome.');
process.exitCode = fallas.length ? 1 : 0;
}
