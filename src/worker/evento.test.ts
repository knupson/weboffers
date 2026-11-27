import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { EventoInput } from "./evento";

const input: EventoInput = { event: "PageView", event_id: "evento_123", url: "https://ofertas.knunet.com/productos/ssd/" };
const env = { ASSETS: { fetch: vi.fn() }, ML_CLIENT_ID: "", ML_CLIENT_SECRET: "",
  META_PIXEL_ID: "1105426165854603", META_CAPI_TOKEN: "token-secreto-no-registrar" };
let worker: typeof import("./index");
let events: typeof import("./evento");
let pending: Promise<unknown>[];
const ctx = { waitUntil: (p: Promise<unknown>) => { pending.push(p); } };
const request = (body: unknown = input, headers: HeadersInit = {}) => new Request("https://ofertas.knunet.com/api/evento", {
  method: "POST", headers, body: JSON.stringify(body),
});

beforeEach(async () => {
  vi.resetModules();
  worker = await import("./index");
  events = await import("./evento");
  pending = [];
  vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 200 })));
});
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe("/api/evento", () => {
  it.each([
    { ...input, event: "Purchase" },
    { ...input, event_id: "corto" },
    { ...input, event_id: "a".repeat(65) },
    { ...input, event_id: "evento con espacios" },
    { ...input, url: "https://otro.com/" },
    { ...input, url: "https://ofertas.knunet.com.ejemplo.com/" },
    { ...input, url: "http://ofertas.knunet.com/" },
    { ...input, url: "rota" }, null,
  ])("rechaza datos inválidos: %j", async (body) => {
    expect((await worker.default.fetch(request(body), env, ctx)).status).toBe(400);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("rechaza otro origen y acepta el propio", async () => {
    expect((await worker.default.fetch(request(input, { Origin: "https://otro.com" }), env, ctx)).status).toBe(403);
    expect(fetch).not.toHaveBeenCalled();
    expect((await worker.default.fetch(request(input, { Origin: "https://ofertas.knunet.com" }), env, ctx)).status).toBe(204);
    await Promise.all(pending);
  });

  it("rechaza JSON roto y cuerpos mayores a 4 KB, incluso sin Content-Length", async () => {
    expect((await worker.default.fetch(new Request(request().url, { method: "POST", body: "{" }), env, ctx)).status).toBe(400);
    expect((await worker.default.fetch(request({ ...input, extra: "á".repeat(2100) }), env, ctx)).status).toBe(413);
    expect((await worker.default.fetch(request(input, { "Content-Length": "4097" }), env, ctx)).status).toBe(413);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("PageView incluye IP, navegador y fbc válido", () => {
    const fbc = "fb.1.1795770000000.abcdefghijk";
    expect(events.buildCapiEvents({ ...input, fbc }, new Headers({ "CF-Connecting-IP": "192.0.2.1", "User-Agent": "navegador" }), 123)).toEqual([{
      event_name: "PageView", event_id: input.event_id, event_time: 123, action_source: "website", event_source_url: input.url,
      user_data: { client_ip_address: "192.0.2.1", client_user_agent: "navegador", fbc },
    }]);
    expect(events.buildCapiEvents(input, new Headers(), 123)[0].user_data).toEqual({});
  });

  it("descarta fbc inválido y sanea los datos del clic antes de enviarlos", async () => {
    await worker.default.fetch(request({ ...input, event: "ClickAfiliado", fbc: "inválido", data: {
      tienda: "amazon", slug: " ssd ", categoria: "Audio", ubicacion: "x".repeat(110), boton: " Ver ",
      precio_usd: 150, ahorro_pct: "20", extra: "descartar",
    } }), env, ctx);
    await Promise.all(pending);
    const [url, options] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("https://graph.facebook.com/v23.0/1105426165854603/events");
    const payload = JSON.parse(String(options?.body));
    expect(payload.access_token).toBe(env.META_CAPI_TOKEN);
    expect(payload.data).toHaveLength(2);
    expect(payload.data[0]).toMatchObject({ event_name: "ClickAfiliado", event_id: input.event_id, user_data: {},
      custom_data: { tienda: "amazon", slug: "ssd", categoria: "Audio", ubicacion: "x".repeat(100), boton: "Ver", precio_usd: 150 } });
    expect(payload.data[0].custom_data).not.toHaveProperty("ahorro_pct");
    expect(payload.data[0].custom_data).not.toHaveProperty("extra");
    expect(payload.data[1]).toMatchObject({ event_name: "InitiateCheckout", event_id: `${input.event_id}-ic`,
      custom_data: { content_ids: ["ssd"], content_type: "product", content_category: "Audio", currency: "USD", value: 150 } });
    expect(options?.signal).toBeInstanceOf(AbortSignal);
  });

  it("omite datos opcionales ausentes y valores no finitos", () => {
    const result = events.buildCapiEvents({ ...input, event: "ClickAfiliado" }, new Headers(), 123);
    expect(result[1]).toHaveProperty("custom_data", { content_type: "product", currency: "USD" });
    const nonFinite = events.buildCapiEvents({ ...input, event: "ClickAfiliado", data: { precio_usd: Infinity } }, new Headers(), 123);
    expect(nonFinite[1]).not.toHaveProperty("custom_data.value");
  });

  it("responde sin esperar a Meta y registra el trabajo con waitUntil", async () => {
    let finish!: (r: Response) => void;
    vi.mocked(fetch).mockImplementation(() => new Promise(resolve => { finish = resolve; }));
    expect((await worker.default.fetch(request(), env, ctx)).status).toBe(204);
    expect(pending).toHaveLength(1);
    finish(new Response());
    await Promise.all(pending);
  });

  it("sin token o pixel responde 204, sin fetch, y avisa una vez por isolate", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    for (const missing of [{ META_CAPI_TOKEN: undefined }, { META_PIXEL_ID: undefined }]) {
      expect((await worker.default.fetch(request(), { ...env, ...missing }, ctx)).status).toBe(204);
    }
    expect(fetch).not.toHaveBeenCalled();
    expect(warn).toHaveBeenCalledExactlyOnceWith("[evento] Meta no configurado");
  });

  it.each(["http", "excepción"])("un fallo de Meta (%s) no expone secretos ni cambia el 204", async (mode) => {
    const consoles = ["warn", "log", "error", "info", "debug"] as const;
    const spies = consoles.map(key => vi.spyOn(console, key).mockImplementation(() => {}));
    if (mode === "http") vi.mocked(fetch).mockResolvedValue(new Response(env.META_CAPI_TOKEN, { status: 500 }));
    else vi.mocked(fetch).mockRejectedValue(new Error(env.META_CAPI_TOKEN));
    const response = await worker.default.fetch(request(), env, ctx);
    expect(response.status).toBe(204);
    expect(await response.text()).toBe("");
    await Promise.all(pending);
    expect(console.warn).toHaveBeenCalledWith(mode === "http" ? "[evento] Meta HTTP 500" : "[evento] Meta HTTP error");
    for (const spy of spies) expect(JSON.stringify(spy.mock.calls)).not.toContain(env.META_CAPI_TOKEN);
  });

  it.each(["GET", "PUT", "OPTIONS"])("%s responde 405 con Allow POST", async method => {
    const response = await worker.default.fetch(new Request(request().url, { method }), env, ctx);
    expect(response.status).toBe(405);
    expect(response.headers.get("allow")).toBe("POST");
    expect(fetch).not.toHaveBeenCalled();
  });
});
