import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { recorte } from "./recorte";

describe("recorte", () => {
  const raiz = mkdtempSync(join(tmpdir(), "recorte-"));
  mkdirSync(join(raiz, "public/products/recorte"), { recursive: true });
  writeFileSync(join(raiz, "public/products/recorte/reloj.webp"), "");

  it("usa la foto recortada cuando existe", () => {
    expect(recorte("/products/reloj.webp", raiz)).toBe("/products/recorte/reloj.webp");
  });
  it("cae a la original si no hay recorte, si no es local o si no hay foto", () => {
    expect(recorte("/products/mochila.webp", raiz)).toBeNull();
    expect(recorte("https://m.media-amazon.com/images/I/x.jpg", raiz)).toBeNull();
    expect(recorte("/products/../secreto.webp", raiz)).toBeNull();
    expect(recorte(null, raiz)).toBeNull();
  });
});
