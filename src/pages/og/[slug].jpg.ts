// Imagen para la vista previa al compartir una ficha (13/11): JPEG 1200×630 con la foto del producto.
// WhatsApp no garantiza WebP y descarta imágenes de más de ~300 KB, así que se genera un JPEG liviano en el build
// a partir de la foto local (/products/<slug>.webp|.jpg). Sin foto local no hay endpoint y la ficha usa og.png.
import sharp from "sharp";
import { isComparable, loadProducts } from "../../lib/data";
import { fotoLocal } from "../../lib/og-foto";

const ANCHO = 1200;
const ALTO = 630;
const FONDO = { r: 244, g: 239, b: 228 }; // --crema


export async function getStaticPaths() {
  const { products } = await loadProducts();
  return products
    .filter((p) => isComparable(p))
    .map((p) => ({ p, archivo: fotoLocal(p.price?.imageUrl ?? p.image) }))
    .filter(({ archivo }) => archivo)
    .map(({ p, archivo }) => ({ params: { slug: p.slug }, props: { archivo } }));
}

export async function GET({ props }: { props: { archivo: string } }) {
  const foto = await sharp(props.archivo)
    .resize({ width: ANCHO - 120, height: ALTO - 80, fit: "contain", background: { ...FONDO, alpha: 1 } })
    .flatten({ background: FONDO })
    .toBuffer();
  const jpg = await sharp({ create: { width: ANCHO, height: ALTO, channels: 3, background: FONDO } })
    .composite([{ input: foto, gravity: "centre" }])
    .jpeg({ quality: 82, mozjpeg: true })
    .toBuffer();
  return new Response(new Uint8Array(jpg), { headers: { "content-type": "image/jpeg" } });
}
