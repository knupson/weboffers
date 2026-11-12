import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = process.cwd();

describe("rutas inexistentes", () => {
  it("12/11: Cloudflare responde 404 real, no la portada con 200", () => {
    const config = JSON.parse(fs.readFileSync(path.join(root, "wrangler.jsonc"), "utf8"));
    expect(config.assets.not_found_handling).toBe("404-page");
  });
  it("hay una página 404 que el build convierte en dist/404.html", () => {
    const page = fs.readFileSync(path.join(root, "src/pages/404.astro"), "utf8");
    expect(page).toContain("No encontramos esa página");
  });
});
