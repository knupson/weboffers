// Genera todos los activos de identidad visual de FRANQUICIA 400 · KnuNet:
// - public/favicon-32.png (32x32)
// - public/favicon.ico (ICO binario válido con el PNG 32x32 embebido)
// - public/apple-touch-icon.png (180x180)
// - public/icon-192.png (192x192)
// - public/icon-512.png (512x512)
// - public/og.png (1200x630 OpenGraph card)
// - brand/brandkit-board.png (1600x1200 tablero 3x3 de sistema de marca según skill brandkit)

import { chromium } from '@playwright/test';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');
const pub = join(root, 'public');
mkdirSync(pub, { recursive: true });
mkdirSync(here, { recursive: true });

const b64 = (relPath) => readFileSync(join(root, relPath)).toString('base64');

const fontCond700 = b64('node_modules/@fontsource/barlow-condensed/files/barlow-condensed-latin-700-normal.woff2');
const fontCond600 = b64('node_modules/@fontsource/barlow-condensed/files/barlow-condensed-latin-600-normal.woff2');
const fontBarlow500 = b64('node_modules/@fontsource/barlow/files/barlow-latin-500-normal.woff2');
const fontStencil = b64('node_modules/@fontsource/saira-stencil-one/files/saira-stencil-one-latin-400-normal.woff2');
const fontMono = b64('node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-700-normal.woff2');

const fontFacesCss = `
  @font-face { font-family: 'BC'; font-weight: 700; src: url(data:font/woff2;base64,${fontCond700}) format('woff2'); }
  @font-face { font-family: 'BC'; font-weight: 600; src: url(data:font/woff2;base64,${fontCond600}) format('woff2'); }
  @font-face { font-family: 'B'; font-weight: 500; src: url(data:font/woff2;base64,${fontBarlow500}) format('woff2'); }
  @font-face { font-family: 'ST'; font-weight: 400; src: url(data:font/woff2;base64,${fontStencil}) format('woff2'); }
  @font-face { font-family: 'JM'; font-weight: 700; src: url(data:font/woff2;base64,${fontMono}) format('woff2'); }
`;

function createIcoFromPng(pngBuffer) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // Reserved
  header.writeUInt16LE(1, 2); // Type 1 = ICO
  header.writeUInt16LE(1, 4); // 1 image

  const dir = Buffer.alloc(16);
  dir.writeUInt8(32, 0);      // width 32
  dir.writeUInt8(32, 1);      // height 32
  dir.writeUInt8(0, 2);       // palette
  dir.writeUInt8(0, 3);       // reserved
  dir.writeUInt16LE(1, 4);    // color planes
  dir.writeUInt16LE(32, 6);   // bits per pixel
  dir.writeUInt32LE(pngBuffer.length, 8); // size
  dir.writeUInt32LE(22, 12);  // offset (6 + 16)

  return Buffer.concat([header, dir, pngBuffer]);
}

const browser = await chromium.launch();

// 1. Iconos cuadrados (32, 180, 192, 512)
const iconSizes = [
  { name: 'favicon-32.png', size: 32 },
  { name: 'apple-touch-icon.png', size: 180 },
  { name: 'icon-192.png', size: 192 },
  { name: 'icon-512.png', size: 512 },
];

for (const item of iconSizes) {
  const page = await browser.newPage({ viewport: { width: item.size, height: item.size } });
  await page.setContent(`
    <style>
      ${fontFacesCss}
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        width: ${item.size}px;
        height: ${item.size}px;
        background: #110C08;
        display: grid;
        place-items: center;
        overflow: hidden;
      }
      svg { width: 100%; height: 100%; display: block; }
    </style>
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" fill="none">
      <rect width="64" height="64" fill="#110C08"/>
      <polygon fill="#1A130D" points="12,3 52,3 61,12 61,52 52,61 12,61 3,52 3,12" />
      <polygon stroke="#FFA82E" stroke-width="2.4" points="13.5,5.5 50.5,5.5 58.5,13.5 58.5,50.5 50.5,58.5 13.5,58.5 5.5,50.5 5.5,13.5" />
      <path stroke="#C83E0B" stroke-width="2" d="M5.5 21H11.5M52.5 21H58.5M5.5 43H11.5M52.5 43H58.5" />
      <path fill="#FAF8F4" d="M15 16H31.5V22.5H21.8V29H29.8V35H21.8V48H15V16Z" />
      <path fill="#FFA82E" d="M42.5 16H49V34.5H52.5V40.5H49V48H42.5V40.5H32V34.5L42.5 16ZM42.5 25.5L37.4 34.5H42.5V25.5Z" />
    </svg>
  `);
  await page.evaluate(() => document.fonts.ready);
  const outPath = join(pub, item.name);
  await page.screenshot({ path: outPath });
  await page.close();
}

const png32 = readFileSync(join(pub, 'favicon-32.png'));
writeFileSync(join(pub, 'favicon.ico'), createIcoFromPng(png32));

// 2. OpenGraph 1200x630 (public/og.png)
{
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
  await page.setContent(`
    <style>
      ${fontFacesCss}
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        width: 1200px;
        height: 630px;
        background: #110C08;
        color: #ECD9BD;
        font-family: 'B', sans-serif;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
        padding: 48px 56px;
        position: relative;
        overflow: hidden;
        border: 2px solid #4A3522;
      }
      .grid-bg {
        position: absolute;
        inset: 0;
        background-image:
          linear-gradient(to right, rgba(255,168,46,0.06) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(255,168,46,0.06) 1px, transparent 1px);
        background-size: 40px 40px;
        pointer-events: none;
      }
      .stripe {
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 12px;
        background: repeating-linear-gradient(-45deg, #FFA82E 0 16px, #110C08 16px 32px);
      }
      .top {
        display: flex;
        justify-content: space-between;
        align-items: center;
        position: relative;
        z-index: 2;
        padding-top: 10px;
        border-bottom: 1px solid #33251A;
        padding-bottom: 22px;
      }
      .brand-lockup {
        display: flex;
        align-items: center;
        gap: 18px;
      }
      .seal {
        font: 400 22px/1 'ST', sans-serif;
        letter-spacing: 0.18em;
        color: #FFA82E;
        padding: 8px 14px;
        border: 1px solid #FFA82E;
        background: #1A130D;
      }
      .sub-id {
        font: 700 15px/1.2 'JM', monospace;
        letter-spacing: 0.14em;
        color: #A88F70;
      }
      .mid {
        position: relative;
        z-index: 2;
        margin: auto 0;
      }
      .kicker {
        font: 400 18px/1 'ST', sans-serif;
        letter-spacing: 0.24em;
        color: #C83E0B;
        background: rgba(200, 62, 11, 0.14);
        border: 1px solid #C83E0B;
        display: inline-block;
        padding: 6px 14px;
        margin-bottom: 20px;
      }
      h1 {
        font: 700 94px/0.9 'BC', sans-serif;
        text-transform: uppercase;
        color: #FFC06A;
        letter-spacing: -0.01em;
        text-shadow: 0 0 24px rgba(255, 150, 40, 0.28);
      }
      h1 span {
        color: #FAF8F4;
        text-shadow: none;
      }
      .lead {
        font: 500 26px/1.38 'B', sans-serif;
        color: #ECD9BD;
        max-width: 820px;
        margin-top: 20px;
      }
      .bottom {
        position: relative;
        z-index: 2;
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 1px;
        background: #4A3522;
        border: 1px solid #4A3522;
      }
      .cell {
        background: #18110B;
        padding: 16px 20px;
      }
      .cell .k {
        font: 600 13px/1 'BC', sans-serif;
        letter-spacing: 0.18em;
        color: #A88F70;
        text-transform: uppercase;
      }
      .cell .v {
        font: 700 32px/1.1 'JM', monospace;
        color: #FFA82E;
        margin-top: 6px;
      }
    </style>
    <div class="grid-bg"></div>
    <div class="stripe"></div>
    <div class="top">
      <div class="brand-lockup">
        <div class="seal">F400 · KNUNET</div>
        <div class="sub-id">MONITOR DE IMPORTACION COURIER · ARGENTINA</div>
      </div>
      <div class="sub-id">ARCA RG 5617 · AMAZON US + ES</div>
    </div>
    <div class="mid">
      <div class="kicker">ARANCEL 0% HASTA USD 400 FOB</div>
      <h1>HARDWARE PUERTA A PUERTA<br/><span>SIN SOBREPRECIO LOCAL</span></h1>
      <p class="lead">Calculadora aduanera en vivo con Dólar MEP, desglose real de IVA (10,5% / 21%) y comparador técnico contra tiendas de Argentina.</p>
    </div>
    <div class="bottom">
      <div class="cell"><div class="k">TOPE EXENTO ARANCEL</div><div class="v">USD 400</div></div>
      <div class="cell"><div class="k">IVA INFORMATICA</div><div class="v">10,5%</div></div>
      <div class="cell"><div class="k">AHORRO PROMEDIO</div><div class="v">38% - 54%</div></div>
      <div class="cell"><div class="k">ORIGEN VERIFICADO</div><div class="v">US / ES</div></div>
    </div>
  `);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: join(pub, 'og.png') });
  await page.close();
}

// 3. Brandkit Board 3x3 (1600x1200) siguiendo skill brandkit
{
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  await page.setContent(`
    <style>
      ${fontFacesCss}
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body {
        width: 1600px;
        height: 1200px;
        background: #0C0A08;
        padding: 28px;
        display: grid;
        grid-template-columns: repeat(3, 1fr);
        grid-template-rows: repeat(3, 1fr);
        gap: 18px;
        font-family: 'B', sans-serif;
      }
      .panel {
        background: #14110E;
        border: 1px solid #2B2118;
        position: relative;
        overflow: hidden;
        padding: 28px;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
      }
      .panel.light {
        background: #F2EFE9;
        border-color: #CEC8BA;
        color: #141311;
      }
      .p-num {
        font: 700 11px/1 'JM', monospace;
        letter-spacing: 0.18em;
        color: #8A7660;
        text-transform: uppercase;
      }
      .panel.light .p-num { color: #524D46; }
      .center {
        margin: auto;
        text-align: center;
      }
      .swatches {
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 10px;
        height: 220px;
        margin-top: 16px;
      }
      .sw {
        border: 1px solid rgba(255,255,255,0.12);
        padding: 12px;
        display: flex;
        flex-direction: column;
        justify-content: flex-end;
        font: 700 12px/1.3 'JM', monospace;
      }
      .construction-grid {
        background-image:
          linear-gradient(to right, rgba(255,168,46,0.14) 1px, transparent 1px),
          linear-gradient(to bottom, rgba(255,168,46,0.14) 1px, transparent 1px);
        background-size: 24px 24px;
      }
    </style>

    <!-- Panel 1: Logo Cover -->
    <div class="panel">
      <div class="p-num">01 / LOGO MARK & LOCKUP</div>
      <div class="center">
        <svg width="136" height="136" viewBox="0 0 64 64" fill="none">
          <polygon fill="#1A130D" points="12,3 52,3 61,12 61,52 52,61 12,61 3,52 3,12" />
          <polygon stroke="#FFA82E" stroke-width="2" points="13.5,5.5 50.5,5.5 58.5,13.5 58.5,50.5 50.5,58.5 13.5,58.5 5.5,50.5 5.5,13.5" />
          <path stroke="#C83E0B" stroke-width="1.8" d="M5.5 21H11.5M52.5 21H58.5M5.5 43H11.5M52.5 43H58.5" />
          <path fill="#FAF8F4" d="M15 16H31.5V22.5H21.8V29H29.8V35H21.8V48H15V16Z" />
          <path fill="#FFA82E" d="M42.5 16H49V34.5H52.5V40.5H49V48H42.5V40.5H32V34.5L42.5 16ZM42.5 25.5L37.4 34.5H42.5V25.5Z" />
        </svg>
        <div style="font:700 34px/1 'BC'; color:#FFC06A; letter-spacing:0.08em; margin-top:16px;">FRANQUICIA 400</div>
        <div style="font:700 11px/1 'JM'; color:#A88F70; letter-spacing:0.22em; margin-top:6px;">KNUNET · IMPORT TELEMETRY</div>
      </div>
      <div class="p-num">SISTEMA DE IDENTIDAD</div>
    </div>

    <!-- Panel 2: Logo Construction -->
    <div class="panel construction-grid">
      <div class="p-num">02 / GEOMETRIA DE CONSTRUCCION (OCTAGONO CHAMFER 45°)</div>
      <div class="center">
        <svg width="180" height="180" viewBox="0 0 100 100" fill="none">
          <circle cx="50" cy="50" r="42" stroke="rgba(255,168,46,0.35)" stroke-dasharray="3 3"/>
          <line x1="0" y1="50" x2="100" y2="50" stroke="rgba(200,62,11,0.45)"/>
          <line x1="50" y1="0" x2="50" y2="100" stroke="rgba(200,62,11,0.45)"/>
          <polygon stroke="#FFA82E" stroke-width="1.5" points="24,10 76,10 90,24 90,76 76,90 24,90 10,76 10,24" />
          <text x="50" y="57" text-anchor="middle" fill="#FAF8F4" font-family="BC" font-weight="700" font-size="34">F4</text>
        </svg>
      </div>
      <div class="p-num">ESCALA MINIMA: 16PX · RATIO 1:1</div>
    </div>

    <!-- Panel 3: Dual Substrate UI Surface -->
    <div class="panel light">
      <div class="p-num">03 / SUSTRATO MANIFIESTO ADUANERO (#F2EFE9)</div>
      <div style="border:2px solid #181614; background:#FAF8F4; padding:18px; margin:auto 0;">
        <div style="display:flex; justify-content:space-between; border-bottom:1px solid #CEC8BA; padding-bottom:10px;">
          <span style="font:400 14px 'ST'; color:#C83E0B; letter-spacing:0.12em;">DESPACHO COURIER</span>
          <span style="font:700 13px 'JM'; color:#146338; background:#E3F1E8; padding:2px 8px;">ARANCEL 0%</span>
        </div>
        <div style="font:700 32px/1 'BC'; color:#141311; margin-top:12px;">ASUS ROG STRIX 27" WOLED</div>
        <div style="display:flex; justify-content:space-between; align-items:baseline; margin-top:14px;">
          <span style="font:700 13px 'JM'; color:#524D46;">PUESTO EN ARGENTINA</span>
          <span style="font:700 28px 'JM'; color:#C83E0B;">$ 764.100</span>
        </div>
      </div>
      <div class="p-num">MODO PAPEL / MODO HUD</div>
    </div>

    <!-- Panel 4: Brand Essence -->
    <div class="panel">
      <div class="p-num">04 / TESIS DE PRODUCTO</div>
      <div style="margin:auto 0;">
        <div style="font:400 16px 'ST'; color:#FFA82E; letter-spacing:0.2em; margin-bottom:12px;">CERO HUMO</div>
        <div style="font:700 54px/0.92 'BC'; color:#FAF8F4; text-transform:uppercase;">EL NUMERO REAL PUESTO EN TU PUERTA.</div>
      </div>
      <div class="p-num">CASTELLANO RIOPLATENSE · FACTUAL</div>
    </div>

    <!-- Panel 5: Color System -->
    <div class="panel">
      <div class="p-num">05 / DISCIPLINA CROMATICA</div>
      <div class="swatches">
        <div class="sw" style="background:#F2EFE9; color:#141311;"><span>MANIFIESTO</span><span>#F2EFE9</span></div>
        <div class="sw" style="background:#110C08; color:#ECD9BD;"><span>HUD CRT</span><span>#110C08</span></div>
        <div class="sw" style="background:#C83E0B; color:#FAF8F4;"><span>PRECINTO</span><span>#C83E0B</span></div>
        <div class="sw" style="background:#FFA82E; color:#110C08;"><span>AMBAR KNU</span><span>#FFA82E</span></div>
      </div>
      <div class="p-num">WCAG AA / AAA VERIFICADO</div>
    </div>

    <!-- Panel 6: Typography -->
    <div class="panel light">
      <div class="p-num">06 / ARQUITECTURA TIPOGRAFICA SELF-HOSTED</div>
      <div style="margin:auto 0; display:grid; gap:14px;">
        <div>
          <div style="font:700 11px 'JM'; color:#524D46;">DISPLAY · BARLOW CONDENSED 700</div>
          <div style="font:700 44px/0.95 'BC'; color:#141311;">FRANQUICIA USD 400 FOB</div>
        </div>
        <div>
          <div style="font:700 11px 'JM'; color:#524D46;">SELLO · SAIRA STENCIL ONE</div>
          <div style="font:400 24px/1 'ST'; color:#C83E0B; letter-spacing:0.12em;">ARCA · RG 5617 / IVA 10,5%</div>
        </div>
        <div>
          <div style="font:700 11px 'JM'; color:#524D46;">TELEMETRIA · JETBRAINS MONO TABULAR</div>
          <div style="font:700 20px/1.2 'JM'; color:#141311;">FOB $379.00 + CIF $45.10 = $468.64</div>
        </div>
      </div>
      <div class="p-num">CERO GOOGLE FONTS EXTERNAS</div>
    </div>

    <!-- Panel 7: Customs Stamp & Telemetry -->
    <div class="panel">
      <div class="p-num">07 / TIMBRADO ARANCELARIO</div>
      <div class="center" style="border:2px solid #FFA82E; padding:22px 32px; background:#18110B;">
        <div style="font:400 28px 'ST'; color:#FFA82E; letter-spacing:0.18em;">EXENTO ARANCEL</div>
        <div style="font:700 14px 'JM'; color:#ECD9BD; margin-top:8px;">FOB &lt;= USD 400.00 · SOLO IVA</div>
      </div>
      <div class="p-num">SIMULADOR INTERACTIVO</div>
    </div>

    <!-- Panel 8: Legal & Compliance Seal -->
    <div class="panel">
      <div class="p-num">08 / CUMPLIMIENTO LEGAL INTEGRADO</div>
      <div style="margin:auto 0; border-left:3px solid #C83E0B; padding-left:18px;">
        <div style="font:700 26px/1.05 'BC'; color:#FFC06A; text-transform:uppercase;">AMAZON OPERATING AGREEMENT + LEY 25.326</div>
        <p style="font:500 15px/1.45 'B'; color:#A88F70; margin-top:10px;">Divulgación FTC/Amazon visible, pliego completo de Privacidad, Cookies configurables y Términos de Uso del simulador aduanero.</p>
      </div>
      <div class="p-num">AUDITORIA LISTA</div>
    </div>

    <!-- Panel 9: Infraestructura KnuNet -->
    <div class="panel">
      <div class="p-num">09 / DESPLIEGUE END-TO-END</div>
      <div style="margin:auto 0; font:700 15px/1.8 'JM'; color:#ECD9BD;">
        <div style="color:#FFA82E;">$ wrangler deploy --name weboffers</div>
        <div>&gt; Edge: Cloudflare Workers Assets</div>
        <div>&gt; Worker: pi4 (192.168.3.252)</div>
        <div>&gt; Repo: github.com/knupson/weboffers</div>
      </div>
      <div class="p-num">KNUNET INFRASTRUCTURE</div>
    </div>
  `);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: join(here, 'brandkit-board.png') });
  await page.close();
}

await browser.close();
console.log('Brand assets generated successfully.');
