import { describe, expect, it } from "vitest";
import { imagenAbsoluta, ogFicha } from "./og";

const SITE = "https://ofertas.knunet.com";
const garmin = { name: "Garmin Varia RTL515", ml: { price: 1115998, checked: "2026-11-13" }, amazonArs: 300000, amazonChecked: "2026-11-13" };

describe("ogFicha", () => {
  it("gana Amazon: nombre, precio puesto en casa, ahorro y fecha de los precios", () => {
    const og = ogFicha(garmin, "amazon", 820000, "/products/garmin-rtl515.webp", SITE);
    expect(og.title).toMatch(/^Garmin Varia RTL515: ~\$\s?300\.000 traído de Amazon, ahorrás ~\$\s?820\.000 vs Mercado Libre$/);
    expect(og.description).toMatch(/^Precios del 13\/11\. Mercado Libre \$\s?1\.115\.998 · Amazon puesto en tu casa ~\$\s?300\.000/);
    expect(og.image).toBe("https://ofertas.knunet.com/products/garmin-rtl515.webp");
  });

  it("gana Mercado Libre: lo dice sin inventar ahorro", () => {
    const og = ogFicha({ ...garmin, ml: { price: 250000, checked: "2026-11-13" }, amazonArs: 390000 }, "ml", 140000, null, SITE);
    expect(og.title).toMatch(/: \$\s?250\.000 en Mercado Libre, conviene más que traerlo$/);
    expect(og.image).toBeNull();
  });

  it("sin envío confirmado no promete «traído de Amazon» en el título", () => {
    expect(ogFicha(garmin, "sinEnvio", 0, null, SITE).title).toBe("Garmin Varia RTL515");
  });
});

describe("imagenAbsoluta", () => {
  it("HTTPS queda igual, ruta del sitio se vuelve absoluta, lo demás no sirve", () => {
    expect(imagenAbsoluta("https://m.media-amazon.com/images/I/x.jpg", SITE)).toBe("https://m.media-amazon.com/images/I/x.jpg");
    expect(imagenAbsoluta("/products/a.webp", SITE)).toBe("https://ofertas.knunet.com/products/a.webp");
    expect(imagenAbsoluta("http://inseguro/x.jpg", SITE)).toBeNull();
    expect(imagenAbsoluta(undefined, SITE)).toBeNull();
  });
});
