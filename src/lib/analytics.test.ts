import { afterEach, describe, expect, it, vi } from "vitest";
import {
  _resetCalculadora,
  aplicarTagAmazon,
  canalDeSesion,
  navegadorDeApp,
  resolverTagAmazon,
  tagDeEnlace,
  ahorroPct,
  captureUtms,
  capturarFbc,
  metaHabilitado,
  enviarMeta,
  salidaAttrs,
  salidaEvento,
  sessionUtms,
  shouldTrack,
  track,
  trackCalculadora,
  trackSalida,
  umamiNoSeCarga,
  umamiListo,
} from "./analytics";

function memoria() {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v) };
}

describe("medición de Meta sin cookies", () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it("guarda el último fbclid, lo conserva entre páginas y lo recorta", () => {
    const store = memoria();
    expect(capturarFbc("?fbclid=abcdefghijk", store, 123)).toBe("fb.1.123.abcdefghijk");
    expect(capturarFbc("", store)).toBe("fb.1.123.abcdefghijk");
    expect(capturarFbc("?fbclid=otro_id1234", store, 456)).toBe("fb.1.456.otro_id1234");
    expect(capturarFbc("?fbclid=" + "a".repeat(600), store, 789)).toBe("fb.1.789." + "a".repeat(500));
    expect(capturarFbc("?fbclid=inválido!", store)).toBe("fb.1.789." + "a".repeat(500));
    expect(capturarFbc("", null)).toBeNull();
  });

  it("tolera almacenamiento bloqueado", () => {
    const blocked = { getItem: () => { throw new Error("bloqueado"); }, setItem: () => { throw new Error("bloqueado"); } };
    expect(capturarFbc("?fbclid=abcdefghijk", blocked, 123)).toBe("fb.1.123.abcdefghijk");
    expect(capturarFbc("", blocked)).toBeNull();
    expect(metaHabilitado({ prod: true, search: "", local: blocked, store: null })).toBe(true);
  });

  it("respeta producción, notrack persistido, webdriver, DNT y la marca del dueño", () => {
    const store = memoria();
    const local = memoria();
    const values = { prod: true, search: "", webdriver: false, dnt: null, local, store };
    expect(metaHabilitado(values)).toBe(true);
    expect(metaHabilitado({ ...values, prod: false })).toBe(false);
    expect(metaHabilitado({ ...values, webdriver: true })).toBe(false);
    expect(metaHabilitado({ ...values, dnt: "1" })).toBe(false);
    local.setItem("umami.disabled", "1");
    expect(metaHabilitado(values)).toBe(false);
    local.setItem("umami.disabled", "0");
    expect(metaHabilitado({ ...values, search: "?notrack=1" })).toBe(false);
    expect(metaHabilitado(values)).toBe(false);
  });

  const deps = () => ({
    location: { href: "https://ofertas.knunet.com/?fbclid=abcdefghijk#seccion", search: "?fbclid=abcdefghijk" },
    navigator: { sendBeacon: vi.fn(() => true) },
    crypto: { randomUUID: () => "12345678-abcd-abcd-abcd-123456789012" },
    fetch: vi.fn<typeof fetch>(async () => new Response()), store: memoria(),
  });

  it("manda JSON por Beacon con id sin guiones, URL sin hash y atribución", async () => {
    const d = deps();
    enviarMeta("ClickAfiliado", { tienda: "ml", slug: "ssd" }, d);
    const [url, blob] = d.navigator.sendBeacon.mock.calls[0] as unknown as [string, Blob];
    expect(url).toBe("/api/evento");
    expect(blob.type).toBe("application/json");
    const body = JSON.parse(await blob.text());
    expect(body).toMatchObject({ event: "ClickAfiliado", event_id: "12345678abcdabcdabcd123456789012",
      url: "https://ofertas.knunet.com/?fbclid=abcdefghijk", data: { tienda: "ml", slug: "ssd" } });
    expect(body.fbc).toMatch(/^fb\.1\.\d+\.abcdefghijk$/);
    expect(d.fetch).not.toHaveBeenCalled();
  });

  it.each(["ausente", "false", "excepción"])("usa fetch keepalive si Beacon está %s", async mode => {
    const d = deps();
    const nav = mode === "ausente" ? {} : { sendBeacon: () => {
      if (mode === "excepción") throw new Error("falló");
      return false;
    } };
    d.fetch.mockRejectedValue(new Error("sin red"));
    expect(() => enviarMeta("PageView", undefined, { ...d, navigator: nav, crypto: {} })).not.toThrow();
    expect(d.fetch).toHaveBeenCalledWith("/api/evento", expect.objectContaining({ method: "POST", keepalive: true,
      headers: { "content-type": "application/json" } }));
    const body = JSON.parse(String(d.fetch.mock.calls[0][1]?.body));
    expect(body.event_id).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
    await Promise.resolve();
  });

  it("tolera fallas sincrónicas del transporte y URL inválida", () => {
    const d = deps();
    expect(() => enviarMeta("PageView", undefined, { ...d, navigator: {}, fetch: () => { throw new Error("falló"); } })).not.toThrow();
    expect(() => enviarMeta("PageView", undefined, { ...d, location: { href: "rota", search: "" } })).not.toThrow();
  });
});
type UmamiWin = NonNullable<Parameters<typeof umamiListo>[0]>;
type UmamiProps = Parameters<NonNullable<UmamiWin["umami"]>["track"]>[1];

function umami() {
  const llamadas: Array<[string, Record<string, unknown> | undefined]> = [];
  return { llamadas, win: { umami: { track: (e: string, d?: UmamiProps) => llamadas.push([e, d]) } } };
}

describe("UTMs first-touch en la sesión", () => {
  it("guarda las de la landing y no las pisa una página posterior con otras", () => {
    const s = memoria();
    expect(captureUtms("?utm_source=telegram&utm_medium=social&utm_campaign=producto-del-dia&x=1", s))
      .toEqual({ utm_source: "telegram", utm_medium: "social", utm_campaign: "producto-del-dia" });
    expect(captureUtms("?utm_source=facebook&utm_campaign=otra", s).utm_source).toBe("telegram");
    expect(sessionUtms(s)).toEqual({ utm_source: "telegram", utm_medium: "social", utm_campaign: "producto-del-dia" });
  });

  it("sin UTMs no guarda nada y recorta valores largos", () => {
    const s = memoria();
    expect(captureUtms("?q=ssd", s)).toEqual({});
    expect(captureUtms(`?utm_content=${"x".repeat(300)}`, s).utm_content).toHaveLength(100);
  });

  it("storage roto o JSON inválido no rompe", () => {
    const roto = { getItem: () => { throw new Error("bloqueado"); }, setItem: () => { throw new Error("bloqueado"); } };
    expect(captureUtms("?utm_source=a", roto)).toEqual({ utm_source: "a" });
    const s = memoria();
    s.setItem("f400_utm", "{no es json");
    expect(sessionUtms(s)).toEqual({});
  });
});

describe("higiene", () => {
  it("no registra Chrome automatizado", () => {
    expect(shouldTrack("", true, memoria())).toBe(false);
  });
  it("?notrack=1 apaga toda la sesión", () => {
    const s = memoria();
    expect(shouldTrack("?notrack=1", false, s)).toBe(false);
    expect(shouldTrack("", false, s)).toBe(false);
    expect(shouldTrack("", false, memoria())).toBe(true);
  });
});

describe("clicks salientes", () => {
  const p = { slug: "garmin-rtl515", category: "Deportes", amazonUsd: 149.99, ml: { price: 1115998 }, amazonArs: 300000 };

  it("los atributos del enlace llevan los datos y el evento los convierte", () => {
    const attrs = salidaAttrs("amazon", "ficha", p, "veredicto");
    expect(attrs).toEqual({
      "data-salida": "amazon", "data-salida-ubicacion": "ficha", "data-salida-slug": "garmin-rtl515",
      "data-salida-categoria": "Deportes", "data-salida-precio-usd": "149.99", "data-salida-ahorro-pct": "73",
      "data-salida-boton": "veredicto", "data-salida-bajada-usd": "0",
    });
    // dataset del DOM: data-salida-precio-usd → salidaPrecioUsd
    const ds = { salida: "amazon", salidaUbicacion: "ficha", salidaSlug: "garmin-rtl515", salidaCategoria: "Deportes",
      salidaPrecioUsd: "149.99", salidaAhorroPct: "73", salidaBoton: "veredicto" };
    expect(salidaEvento(ds)).toEqual({ event: "click_amazon", data: {
      slug: "garmin-rtl515", categoria: "Deportes", precio_usd: 149.99, ahorro_pct: 73, ubicacion: "ficha", boton: "veredicto" } });
    expect(salidaEvento({ salida: "ml", salidaUbicacion: "busqueda_vivo" })).toEqual({ event: "click_ml", data: { ubicacion: "busqueda_vivo" } });
    expect(salidaEvento({ salida: "otra" })).toBeNull();
  });

  it("click_amazon lleva bajo_precio y bajada_usd; click_ml no", () => {
    const attrs = salidaAttrs("amazon", "portada", { ...p, bajadaUsd: 18 });
    expect(attrs["data-salida-bajada-usd"]).toBe("18");
    expect(salidaEvento({ salida: "amazon", salidaUbicacion: "portada", salidaBajadaUsd: "18" })?.data)
      .toMatchObject({ bajo_precio: true, bajada_usd: 18 });
    expect(salidaEvento({ salida: "amazon", salidaUbicacion: "ficha", salidaBajadaUsd: "0" })?.data)
      .toMatchObject({ bajo_precio: false, bajada_usd: 0 });
    expect(salidaAttrs("ml", "portada", { ...p, bajadaUsd: 18 })["data-salida-bajada-usd"]).toBeUndefined();
    expect(salidaEvento({ salida: "ml", salidaUbicacion: "portada", salidaBajadaUsd: "18" })?.data).not.toHaveProperty("bajo_precio");
  });

  it("el ahorro es de Amazon contra ML; negativo si ML sale menos; null sin los dos precios", () => {
    expect(ahorroPct(1000, 700)).toBe(30);
    expect(ahorroPct(250000, 390000)).toBe(-56);
    expect(ahorroPct(null, 700)).toBeNull();
    expect(ahorroPct(0, 700)).toBeNull();
  });

  it("el evento suma las UTMs de la sesión", () => {
    const s = memoria();
    captureUtms("?utm_source=instagram&utm_medium=social&utm_campaign=reel-13-11", s);
    const u = umami();
    trackSalida({ salida: "ml", salidaSlug: "a", salidaUbicacion: "portada" }, u.win, s);
    expect(u.llamadas).toEqual([["click_ml", { slug: "a", ubicacion: "portada",
      utm_source: "instagram", utm_medium: "social", utm_campaign: "reel-13-11" }]]);
  });

  it("sin Umami (bloqueador o notrack) no falla", () => {
    expect(() => track("click_amazon", {}, {}, memoria())).not.toThrow();
    expect(() => track("click_amazon", {}, { umami: { track: () => { throw new Error("x"); } } }, memoria())).not.toThrow();
  });
});

describe("calculadora", () => {
  afterEach(() => {
    _resetCalculadora();
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("sin monto válido no hay evento", () => {
    vi.useFakeTimers();
    const u = umami();
    vi.stubGlobal("window", u.win);
    trackCalculadora(0);
    trackCalculadora(NaN);
    vi.advanceTimersByTime(3000);
    expect(u.llamadas).toEqual([]);
  });

  it("un solo evento por página, sin el monto tecleado", () => {
    vi.useFakeTimers();
    const u = umami();
    vi.stubGlobal("window", u.win);
    trackCalculadora(1);
    trackCalculadora(12);
    trackCalculadora(129.5);
    vi.advanceTimersByTime(1500);
    trackCalculadora(300);
    vi.advanceTimersByTime(1500);
    expect(u.llamadas).toEqual([["usar_calculadora", {}]]);
    expect(JSON.stringify(u.llamadas)).not.toMatch(/monto|129/);
  });
});

describe("cola mientras Umami carga", () => {
  afterEach(() => _resetCalculadora());

  it("lo que pasa antes de que cargue Umami (aunque el cargador corra después) sale cuando carga", () => {
    const s = memoria();
    track("buscar_producto", { termino: "garmin", resultados: 1 }, {}, s);
    const u = umami();
    umamiListo(u.win);
    expect(u.llamadas).toEqual([["buscar_producto", { termino: "garmin", resultados: 1 }]]);
  });

  it("si el cargador decide no medir (notrack o webdriver), la cola se vacía y no vuelve a crecer", () => {
    const s = memoria();
    track("buscar_producto", { termino: "ssd", resultados: 3 }, {}, s);
    umamiNoSeCarga();
    track("filtrar_categoria", { categoria: "Audio" }, {}, s);
    const u = umami();
    umamiListo(u.win);
    expect(u.llamadas).toEqual([]);
  });
});

describe("tag de Amazon por canal", () => {
  const tags = { instagram: "f400-ig-20", facebook: "", telegram: "f400-tg-20", meta_ads: "f400-ads-20" };
  const link = "https://www.amazon.com/dp/B086TVFX1D?tag=knunet-20";

  it("sin UTM queda el tag principal del enlace", () => {
    expect(resolverTagAmazon({}, tags)).toBeNull();
    expect(aplicarTagAmazon(link, resolverTagAmazon({}, tags))).toBe(link);
    expect(tagDeEnlace(link)).toBe("knunet-20");
  });

  it("con UTM de un canal con tag cargado, reemplaza tag=", () => {
    const tag = resolverTagAmazon({ utm_source: "instagram", utm_medium: "social" }, tags);
    expect(tag).toBe("f400-ig-20");
    expect(tagDeEnlace(aplicarTagAmazon(link, tag))).toBe("f400-ig-20");
  });

  it("utm_medium pago (paid, cpc) es meta_ads aunque la fuente sea facebook", () => {
    expect(canalDeSesion({ utm_source: "facebook", utm_medium: "cpc" })).toBe("meta_ads");
    expect(canalDeSesion({ utm_source: "instagram", utm_medium: "Paid" })).toBe("meta_ads");
    expect(resolverTagAmazon({ utm_source: "facebook", utm_medium: "paid" }, tags)).toBe("f400-ads-20");
  });

  it("canal sin tag cargado, o tag inválido, cae al principal", () => {
    expect(resolverTagAmazon({ utm_source: "facebook", utm_medium: "social" }, tags)).toBeNull();
    expect(resolverTagAmazon({ utm_source: "telegram" }, { telegram: "con espacios y &" })).toBeNull();
    expect(resolverTagAmazon({ utm_source: "tiktok" }, tags)).toBeNull();
  });

  it("sólo toca Amazon.com: Amazon.es y URLs rotas quedan igual", () => {
    const es = "https://www.amazon.es/dp/B0X?tag=knunet-21";
    expect(aplicarTagAmazon(es, "f400-ig-20")).toBe(es);
    expect(aplicarTagAmazon("no es url", "f400-ig-20")).toBe("no es url");
  });
});

describe("navegadorDeApp", () => {
  it("reconoce el navegador interno de Instagram y Facebook, no Chrome ni Safari", () => {
    expect(navegadorDeApp("Mozilla/5.0 (Linux; Android 14; wv) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36 Instagram 355.0.0.0.0 Android")).toBe(true);
    expect(navegadorDeApp("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 [FBAN/FBIOS;FBAV/480.0]")).toBe(true);
    expect(navegadorDeApp("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36")).toBe(false);
    expect(navegadorDeApp(undefined)).toBe(false);
  });
});
