import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type WorkerModule = typeof import("./index");
type CacheLike = { match(k: string): Promise<Response | undefined>; put(k: string, r: Response): Promise<void> };

const env = {
  ASSETS: { fetch: vi.fn(async () => new Response("estático", { status: 200 })) },
  ML_CLIENT_ID: "id-de-prueba",
  ML_CLIENT_SECRET: "secreto-de-prueba",
};

const memoryCache = () => {
  const store = new Map<string, Response>();
  const cache: CacheLike & { store: Map<string, Response> } = {
    store,
    match: async (k) => store.get(k)?.clone(),
    put: async (k, r) => {
      store.set(k, r);
    },
  };
  return cache;
};

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

// Mock de la API de Mercado Libre según la URL pedida.
function mlFetch(opts: { search?: unknown; items?: Record<string, unknown>; tokenStatus?: number; failItemsFor?: string[]; noWinnersFor?: string[] } = {}) {
  return vi.fn<typeof fetch>(async (input) => {
    const url = new URL(String(input));
    if (url.pathname === "/oauth/token") {
      if (opts.tokenStatus && opts.tokenStatus !== 200) return new Response('{"error":"invalid_client"}', { status: opts.tokenStatus });
      return json({ access_token: "APP_USR-token", expires_in: 21600 });
    }
    if (url.pathname === "/products/search") return json(opts.search ?? { results: [] });
    const itemsMatch = /^\/products\/([^/]+)\/items$/.exec(url.pathname);
    if (itemsMatch) {
      const id = decodeURIComponent(itemsMatch[1]);
      if (opts.failItemsFor?.includes(id)) return new Response("boom", { status: 500 });
      // 13/11: así responde ML un producto de catálogo sin vendedores activos hoy.
      if (opts.noWinnersFor?.includes(id)) return json({ message: "No winners found", error: "not_found", status: 404, cause: [] }, 404);
      return json(opts.items?.[id] ?? { results: [] });
    }
    return new Response("no mockeado", { status: 404 });
  });
}

const search = (q: string) => new Request(`https://ofertas.knunet.com/api/buscar?q=${encodeURIComponent(q)}`);

let worker: WorkerModule;
let cache: ReturnType<typeof memoryCache>;

beforeEach(async () => {
  vi.resetModules(); // el token vive en módulo: cada test arranca limpio
  worker = await import("./index");
  cache = memoryCache();
  vi.stubGlobal("caches", { default: cache });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("bestNewPrice", () => {
  it("elige el precio nuevo más bajo, acepta condición ausente y descarta usados", () => {
    expect(
      worker.bestNewPrice([
        { price: 900, condition: "new" },
        { price: 100, condition: "used" },
        { price: 800 },
        { price: "x", condition: "new" },
      ]),
    ).toBe(800);
  });

  it("devuelve null si no hay ningún precio válido", () => {
    expect(worker.bestNewPrice([{ price: 10, condition: "used" }])).toBeNull();
  });
});

describe("productUrl", () => {
  it("arma el link con los parámetros de afiliado", () => {
    expect(worker.productUrl("MLA12345")).toBe(
      "https://www.mercadolibre.com.ar/p/MLA12345?matt_word=ale_benzoni&matt_tool=58527537",
    );
  });
});

describe("/api/buscar", () => {
  it("valida el largo de q con 400", async () => {
    const f = mlFetch();
    vi.stubGlobal("fetch", f);
    expect((await worker.default.fetch(search("a"), env)).status).toBe(400);
    expect((await worker.default.fetch(search("x".repeat(81)), env)).status).toBe(400);
    expect((await worker.default.fetch(new Request("https://x.test/api/buscar"), env)).status).toBe(400);
    expect(f).not.toHaveBeenCalled();
  });

  it("devuelve el precio nuevo más bajo, descarta productos sin precio y no manda imágenes", async () => {
    vi.stubGlobal(
      "fetch",
      mlFetch({
        search: {
          results: [
            { id: "MLA1", name: "Monitor 27", pictures: [{ url: "https://http2.mlstatic.com/x.jpg" }] },
            { id: "MLA2", name: "Monitor sin stock" },
          ],
        },
        items: {
          MLA1: {
            results: [
              { price: 250000, condition: "new" },
              { price: 150000, condition: "used" },
              { price: 240000, condition: "new" },
            ],
          },
          MLA2: { results: [] },
        },
      }),
    );
    const res = await worker.default.fetch(search("monitor"), env);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { q: string; results: unknown[] };
    expect(body).toEqual({
      q: "monitor",
      results: [
        {
          id: "MLA1",
          name: "Monitor 27",
          price: 240000,
          url: "https://www.mercadolibre.com.ar/p/MLA1?matt_word=ale_benzoni&matt_tool=58527537",
        },
      ],
    });
    expect(JSON.stringify(body)).not.toContain("mlstatic");
    expect(res.headers.get("cache-control")).toBe("public, max-age=3600");
  });

  it("cachea por q normalizada: la segunda consulta no sale a Mercado Libre", async () => {
    const f = mlFetch({
      search: { results: [{ id: "MLA1", name: "SSD" }] },
      items: { MLA1: { results: [{ price: 1000, condition: "new" }] } },
    });
    vi.stubGlobal("fetch", f);
    await worker.default.fetch(search("SSD  2TB"), env);
    const callsAfterFirst = f.mock.calls.length;
    const second = await worker.default.fetch(search(" ssd 2tb "), env);
    expect(second.status).toBe(200);
    expect(f.mock.calls.length).toBe(callsAfterFirst);
    expect(cache.store.size).toBe(1);
  });

  it("pide el token una sola vez mientras no venza", async () => {
    const f = mlFetch({ search: { results: [] } });
    vi.stubGlobal("fetch", f);
    await worker.default.fetch(search("ryzen 7"), env);
    await worker.default.fetch(search("garmin fenix"), env);
    const tokenCalls = f.mock.calls.filter(([i]) => String(i).endsWith("/oauth/token"));
    expect(tokenCalls).toHaveLength(1);
  });

  it("responde 502 sin secretos si falla el token", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal("fetch", mlFetch({ tokenStatus: 401 }));
    const res = await worker.default.fetch(search("monitor"), env);
    expect(res.status).toBe(502);
    const text = await res.text();
    expect(text).toContain("error");
    expect(text).not.toContain("secreto-de-prueba");
    expect(text).not.toContain("id-de-prueba");
  });

  it("responde 502 si todas las consultas de precio fallan, y no cachea el error", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.stubGlobal("fetch", mlFetch({ search: { results: [{ id: "MLA1", name: "A" }] }, failItemsFor: ["MLA1"] }));
    const res = await worker.default.fetch(search("monitor"), env);
    expect(res.status).toBe(502);
    expect(cache.store.size).toBe(0);
  });

  // 13/11: /api/buscar daba 502 en producción con «garmin»: los 6 primeros productos del catálogo respondían
  // 404 «No winners found» y el worker lo contaba como falla (ml_prices.py ya lo trataba como «sin vendedores»).
  it("404 «No winners found» no es una falla: sigue buscando más abajo hasta juntar resultados", async () => {
    const ids = Array.from({ length: 30 }, (_, i) => `MLA${100 + i}`);
    const conPrecio = new Set(["MLA106", "MLA108", "MLA110", "MLA114", "MLA125", "MLA129"]);
    const fetchMock = mlFetch({
      search: { results: ids.map((id) => ({ id, name: `Garmin ${id}` })) },
      noWinnersFor: ids.filter((id) => !conPrecio.has(id)),
      items: Object.fromEntries([...conPrecio].map((id, i) => [id, { results: [{ price: 100000 + i, condition: "new", currency_id: "ARS" }] }])),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await worker.handleBuscar(search("garmin"), env as never, cache);
    expect(res.status).toBe(200);
    const body = (await res.json()) as { results: Array<{ id: string }> };
    expect(body.results.map((r) => r.id)).toEqual([...conPrecio]);
    const searchUrl = new URL(String(fetchMock.mock.calls.find(([u]) => String(u).includes("/products/search"))![0]));
    expect(searchUrl.searchParams.get("limit")).toBe("30");
    // token + búsqueda + como mucho 30 precios: dentro del límite de 50 subrequests de Cloudflare
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(32);
  });

  it("deja de pedir precios apenas junta 6 resultados", async () => {
    const ids = Array.from({ length: 30 }, (_, i) => `MLA${200 + i}`);
    const fetchMock = mlFetch({
      search: { results: ids.map((id) => ({ id, name: `Joystick ${id}` })) },
      items: Object.fromEntries(ids.map((id) => [id, { results: [{ price: 50000, condition: "new" }] }])),
    });
    vi.stubGlobal("fetch", fetchMock);
    const res = await worker.handleBuscar(search("joystick ps5"), env as never, cache);
    expect(((await res.json()) as { results: unknown[] }).results).toHaveLength(6);
    expect(fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/items")).length).toBe(6);
  });

  it("si ningún producto tiene vendedores responde 200 sin resultados (no 502)", async () => {
    const ids = ["MLA1", "MLA2", "MLA3"];
    vi.stubGlobal("fetch", mlFetch({ search: { results: ids.map((id) => ({ id, name: id })) }, noWinnersFor: ids }));
    const res = await worker.handleBuscar(search("kindle"), env as never, cache);
    expect(res.status).toBe(200);
    expect(((await res.json()) as { results: unknown[] }).results).toEqual([]);
  });

  it("rechaza métodos que no son GET y rutas /api desconocidas", async () => {
    const post = await worker.default.fetch(new Request("https://x.test/api/buscar?q=monitor", { method: "POST" }), env);
    expect(post.status).toBe(405);
    expect((await worker.default.fetch(new Request("https://x.test/api/otra"), env)).status).toBe(404);
  });

  it("deja pasar el resto de las rutas a los assets estáticos", async () => {
    const res = await worker.default.fetch(new Request("https://x.test/buscar/"), env);
    expect(await res.text()).toBe("estático");
    expect(env.ASSETS.fetch).toHaveBeenCalled();
  });
});
