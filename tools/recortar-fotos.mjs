// Recorta el fondo blanco liso de las fotos de producto (public/products/*.webp) y deja la versión
// con transparencia en public/products/recorte/. Corre antes del build (npm prebuild).
// Si la foto no tiene un fondo blanco que toque el borde, o el recorte se come el producto,
// no se genera nada y la página usa la foto original.
import { readdir, stat, mkdir } from "node:fs/promises";
import { join } from "node:path";
import sharp from "sharp";

const SRC = "public/products";
const OUT = join(SRC, "recorte");
const TOL = 42; // suma de (255 - canal) en los tres canales: ~5,5 % por canal
const MIN_FONDO = 0.08; // si menos del 8 % es fondo, no era una foto de estudio
const MIN_PRODUCTO = 0.05; // si queda menos del 5 % opaco, el recorte se comió el producto

async function recortar(file) {
  const { data, info } = await sharp(join(SRC, file)).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h } = info;
  const n = w * h;
  // Fondo = blanco liso o ya transparente (algunas fotos vienen con margen transparente alrededor del blanco).
  const blanco = (i) => data[i * 4 + 3] < 16 || 765 - data[i * 4] - data[i * 4 + 1] - data[i * 4 + 2] <= TOL;
  const fondo = new Uint8Array(n);
  const cola = new Int32Array(n);
  let fin = 0;
  const sembrar = (i) => { if (!fondo[i] && blanco(i)) { fondo[i] = 1; cola[fin++] = i; } };
  for (let x = 0; x < w; x++) { sembrar(x); sembrar((h - 1) * w + x); }
  for (let y = 0; y < h; y++) { sembrar(y * w); sembrar(y * w + w - 1); }
  for (let k = 0; k < fin; k++) {
    const i = cola[k], x = i % w;
    if (x > 0) sembrar(i - 1);
    if (x < w - 1) sembrar(i + 1);
    if (i >= w) sembrar(i - w);
    if (i < n - w) sembrar(i + w);
  }
  if (fin / n < MIN_FONDO || 1 - fin / n < MIN_PRODUCTO) return false;
  for (let i = 0; i < n; i++) {
    if (fondo[i]) { data[i * 4 + 3] = 0; continue; }
    // Borde suave: el píxel de producto pegado al fondo queda semitransparente (saca el halo blanco).
    const x = i % w;
    const toca = (x > 0 && fondo[i - 1]) || (x < w - 1 && fondo[i + 1]) || (i >= w && fondo[i - w]) || (i < n - w && fondo[i + w]);
    if (toca) data[i * 4 + 3] = 110;
  }
  await sharp(data, { raw: { width: w, height: h, channels: 4 } })
    .trim({ threshold: 1 })
    .webp({ quality: 86, alphaQuality: 90 })
    .toFile(join(OUT, file));
  return true;
}

await mkdir(OUT, { recursive: true });
const files = (await readdir(SRC).catch(() => [])).filter((f) => f.endsWith(".webp"));
let hechas = 0, salteadas = 0, iguales = 0;
for (const file of files) {
  const fuente = await stat(join(SRC, file));
  const previa = await stat(join(OUT, file)).catch(() => null);
  if (previa && previa.mtimeMs >= fuente.mtimeMs) { iguales++; continue; }
  try {
    if (await recortar(file)) hechas++; else salteadas++;
  } catch (e) {
    salteadas++;
    console.warn(`[recortar-fotos] ${file}: ${e.message}`);
  }
}
console.log(`[recortar-fotos] ${new Date().toISOString()} fotos=${files.length} recortadas=${hechas} sin_recorte=${salteadas} ya_estaban=${iguales}`);
