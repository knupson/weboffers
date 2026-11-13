import { afterEach, describe, expect, it, vi } from "vitest";
import {
  _resetCalculadora,
  ahorroPct,
  captureUtms,
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
function umami() {
  const llamadas: Array<[string, Record<string, unknown> | undefined]> = [];
  return { llamadas, win: { umami: { track: (e: string, d?: Record<string, string | number>) => llamadas.push([e, d]) } } };
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

  it("un solo evento por página, con el último monto tecleado", () => {
    vi.useFakeTimers();
    const u = umami();
    vi.stubGlobal("window", u.win);
    trackCalculadora(1);
    trackCalculadora(12);
    trackCalculadora(129.5);
    vi.advanceTimersByTime(1500);
    trackCalculadora(300);
    vi.advanceTimersByTime(1500);
    expect(u.llamadas.map(([e, d]) => [e, d?.monto_usd])).toEqual([["usar_calculadora", 129.5]]);
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
