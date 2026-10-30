// Genera favicon PNG/ICO, íconos de la app y la imagen OG desde SVG con sharp.
import sharp from "sharp";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pub = join(root, "public");
const mark = readFileSync(join(pub, "favicon.svg"));

const png = (size) => sharp(mark, { density: 72 * (size / 32) }).resize(size, size).png().toBuffer();

function ico(pngBuffer) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(1, 4);
  const dir = Buffer.alloc(16);
  dir.writeUInt8(32, 0);
  dir.writeUInt8(32, 1);
  dir.writeUInt16LE(1, 4);
  dir.writeUInt16LE(32, 6);
  dir.writeUInt32LE(pngBuffer.length, 8);
  dir.writeUInt32LE(22, 12);
  return Buffer.concat([header, dir, pngBuffer]);
}

const p32 = await png(32);
writeFileSync(join(pub, "favicon-32.png"), p32);
writeFileSync(join(pub, "favicon.ico"), ico(p32));
writeFileSync(join(pub, "apple-touch-icon.png"), await png(180));
writeFileSync(join(pub, "icon-192.png"), await png(192));
writeFileSync(join(pub, "icon-512.png"), await png(512));

const og = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#f3f4f6"/>
  <g transform="translate(80 80) scale(3)">
    <rect width="32" height="32" rx="9" fill="#2445e6"/>
    <path d="M16 7.5v11.5M10.5 14l5.5 5.5 5.5-5.5M9 24.5h14" stroke="#fff" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
  <text x="80" y="330" font-family="Segoe UI, Arial, sans-serif" font-size="72" font-weight="600" fill="#111317" letter-spacing="-2">Hardware de Amazon,</text>
  <text x="80" y="415" font-family="Segoe UI, Arial, sans-serif" font-size="72" font-weight="600" fill="#111317" letter-spacing="-2">con la cuenta hecha para Argentina.</text>
  <text x="80" y="520" font-family="Segoe UI, Arial, sans-serif" font-size="32" fill="#5a616d">Franquicia de USD 400, IVA y dólar del día · ofertas.knunet.com</text>
</svg>`;
writeFileSync(join(pub, "og.png"), await sharp(Buffer.from(og)).png().toBuffer());
console.log("ok");
