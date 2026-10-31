import { readFileSync } from "node:fs";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const ROOT = path.resolve(import.meta.dirname, "../..");

function readRepoFile(relPath: string): string {
  return readFileSync(path.join(ROOT, relPath), "utf8");
}

function extractInlineGuardScript(): string {
  const baseAstro = readRepoFile("src/layouts/Base.astro");
  const match = baseAstro.match(/<script is:inline>\s*([\s\S]*?)\s*<\/script>/);
  if (!match) {
    throw new Error("No se encontró el <script is:inline> de la guarda en Base.astro");
  }
  return match[1];
}

interface MockElement {
  attrs: Record<string, string>;
  hidden: boolean;
  textContent: string;
  className: string;
  classList: {
    add: (...tokens: string[]) => void;
    remove: (...tokens: string[]) => void;
    contains: (token: string) => boolean;
  };
  getAttribute: (name: string) => string | null;
  setAttribute: (name: string, val: string) => void;
  removeAttribute: (name: string) => void;
  querySelectorAll: (selector: string) => MockElement[];
}

function createMockElement(
  initialAttrs: Record<string, string> = {},
  initialHidden = false,
  initialText = "",
  initialClass = "",
  childrenBySelector: Record<string, MockElement[]> = {},
): MockElement {
  const attrs = { ...initialAttrs };
  const classes = new Set(initialClass.split(/\s+/).filter(Boolean));
  const syncClassName = () => [...classes].join(" ");

  const el: MockElement = {
    attrs,
    hidden: initialHidden,
    textContent: initialText,
    get className() {
      return syncClassName();
    },
    set className(val: string) {
      classes.clear();
      for (const token of val.split(/\s+/).filter(Boolean)) {
        classes.add(token);
      }
    },
    classList: {
      add: (...tokens: string[]) => {
        for (const t of tokens) if (t) classes.add(t);
      },
      remove: (...tokens: string[]) => {
        for (const t of tokens) classes.delete(t);
      },
      contains: (token: string) => classes.has(token),
    },
    getAttribute: (name: string) => (name in attrs ? attrs[name] : null),
    setAttribute: (name: string, val: string) => {
      attrs[name] = String(val);
    },
    removeAttribute: (name: string) => {
      delete attrs[name];
    },
    querySelectorAll: (selector: string) => {
      const parts = selector.split(",").map((s) => s.trim());
      const out: MockElement[] = [];
      for (const part of parts) {
        for (const child of childrenBySelector[part] ?? []) {
          if (!out.includes(child)) out.push(child);
        }
      }
      return out;
    },
  };
  return el;
}

function buildGuardDom(checkedDate: string, bodyPricesDate = checkedDate) {
  // Estado inicial idéntico al HTML estático: precios y veredictos ocultos, aviso de actualización visible.
  const mlAmount = createMockElement({ "data-price-amount": "" }, true, "$ 500.000", "monto num");
  const mlStale = createMockElement({ "data-price-stale": "" }, false, "Precio en actualización", "precio-actualizando");
  const mlLabel = createMockElement({ "data-price-label": "" }, true, "precio del 31/10");
  const verdictText = createMockElement({ "data-verdict-text": "" }, true, "Mejor opción");
  const mlVerb = createMockElement({ "data-buy-verb": "" }, false, "Ver");
  const mlLink = createMockElement(
    { "data-buy-link": "ml", "data-winner": "ml" },
    false,
    "",
    "btn ghost sm",
    { "[data-buy-verb]": [mlVerb] },
  );
  const mlRow = createMockElement({ "data-winner": "ml" }, false, "", "fila-compra");

  const amzAmount = createMockElement({ "data-price-amount": "" }, true, "~$ 620.000", "monto num");
  const amzStale = createMockElement({ "data-price-stale": "" }, false, "Precio en actualización", "precio-actualizando");
  const amzSub = createMockElement({ "data-price-sub": "" }, true, "puesto en tu casa, estimado al 31/10");
  const amzVerb = createMockElement({ "data-buy-verb": "" }, false, "Ver");
  const amzLink = createMockElement(
    { "data-buy-link": "amazon" },
    false,
    "",
    "btn ghost sm",
    { "[data-buy-verb]": [amzVerb] },
  );
  const amzRow = createMockElement({}, false, "", "fila-compra");

  const block = createMockElement({ "data-checked": checkedDate }, false, "", "foot", {
    "[data-price-amount]": [mlAmount, amzAmount],
    "[data-price-label]": [mlLabel],
    "[data-price-sub]": [amzSub],
    "[data-verdict-text]": [verdictText],
    "[data-price-stale]": [mlStale, amzStale],
    ".fila-compra": [mlRow, amzRow],
    "[data-buy-link]": [mlLink, amzLink],
  });

  const banner = createMockElement({ "data-stale-banner": "" }, true, "Estamos actualizando los precios de hoy");

  const docListeners: Record<string, Array<() => void>> = {};
  const winListeners: Record<string, Array<() => void>> = {};

  const doc = {
    body: { dataset: { pricesDate: bodyPricesDate } },
    visibilityState: "visible",
    querySelector: (sel: string) => (sel === "[data-stale-banner]" ? banner : null),
    querySelectorAll: (sel: string) => (sel === "[data-checked]" ? [block] : []),
    addEventListener: (type: string, fn: () => void) => {
      (docListeners[type] ??= []).push(fn);
    },
    dispatchEvent: (type: string) => {
      for (const fn of docListeners[type] ?? []) fn();
    },
  };

  const win = {
    addEventListener: (type: string, fn: () => void) => {
      (winListeners[type] ??= []).push(fn);
    },
    dispatchEvent: (type: string) => {
      for (const fn of winListeners[type] ?? []) fn();
    },
  };

  return {
    doc,
    win,
    banner,
    block,
    mlAmount,
    mlStale,
    mlLabel,
    verdictText,
    mlVerb,
    mlLink,
    mlRow,
    amzAmount,
    amzStale,
    amzSub,
    amzVerb,
    amzLink,
    amzRow,
  };
}

describe("guarda de precios y estado inicial en HTML/CSS", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renderiza precios y veredictos ocultos por defecto en ProductCard.astro, [slug].astro y global.css", () => {
    for (const file of ["src/components/ProductCard.astro", "src/pages/productos/[slug].astro"]) {
      const content = readRepoFile(file);
      const amounts = content.match(/<span[^>]*data-price-amount[^>]*>/g) ?? [];
      expect(amounts.length).toBe(2);
      for (const tag of amounts) {
        expect(tag).toMatch(/\bhidden\b/);
      }

      const labels = content.match(/<small[^>]*data-price-label[^>]*>/g) ?? [];
      expect(labels.length).toBe(1);
      expect(labels[0]).toMatch(/\bhidden\b/);

      const subs = content.match(/<small[^>]*data-price-sub[^>]*>/g) ?? [];
      expect(subs.length).toBe(1);
      expect(subs[0]).toMatch(/\bhidden\b/);

      const verdicts = content.match(/<(?:span|p)[^>]*data-verdict-text[^>]*>/g) ?? [];
      expect(verdicts.length).toBe(2);
      for (const tag of verdicts) {
        expect(tag).toMatch(/\bhidden\b/);
      }

      const stales = content.match(/<span[^>]*data-price-stale[^>]*>/g) ?? [];
      expect(stales.length).toBe(2);
      for (const tag of stales) {
        expect(tag).not.toMatch(/\bhidden\b/);
      }

      // Ninguna fila ni link de compra sale con estilo ganador antes de correr la guarda
      expect(content).not.toMatch(/fila-compra\s+ganadora/);
      expect(content).not.toMatch(/class="gana\s+(ml|amazon)"/);
    }

    const css = readRepoFile("src/styles/global.css");
    expect(css).toContain('[data-checked]:not([data-fresh="true"])');
  });

  it("habilita precios y veredicto únicamente cuando la fecha ART coincide con data-checked", () => {
    const script = extractInlineGuardScript();
    const runGuard = new Function("document", "window", script);

    // 1) Si JS aún no corrió (o falla), todo permanece oculto y se ve 'Precio en actualización'
    const domToday = buildGuardDom("2026-10-31");
    expect(domToday.mlAmount.hidden).toBe(true);
    expect(domToday.verdictText.hidden).toBe(true);
    expect(domToday.mlStale.hidden).toBe(false);

    // 2) Al correr en el mismo día ART (2026-10-31 12:00 ART), revela precios y veredicto
    vi.setSystemTime(new Date("2026-10-31T15:00:00Z"));
    runGuard(domToday.doc, domToday.win);

    expect(domToday.banner.hidden).toBe(true);
    expect(domToday.block.getAttribute("data-fresh")).toBe("true");
    expect(domToday.mlAmount.hidden).toBe(false);
    expect(domToday.amzAmount.hidden).toBe(false);
    expect(domToday.mlLabel.hidden).toBe(false);
    expect(domToday.mlLabel.textContent).toBe("precio de hoy");
    expect(domToday.amzSub.hidden).toBe(false);
    expect(domToday.verdictText.hidden).toBe(false);
    expect(domToday.mlStale.hidden).toBe(true);
    expect(domToday.amzStale.hidden).toBe(true);
    expect(domToday.mlRow.classList.contains("ganadora")).toBe(true);
    expect(domToday.mlRow.classList.contains("ml")).toBe(true);
    expect(domToday.mlLink.className).toBe("gana ml");
    expect(domToday.mlVerb.textContent).toBe("Comprar");
    expect(domToday.amzVerb.textContent).toBe("Comprar");

    // 3) Si se carga en otro día ART (2026-11-01 01:00 ART), mantiene ocultos los precios y muestra el banner
    const domStale = buildGuardDom("2026-10-31");
    vi.setSystemTime(new Date("2026-11-01T04:00:00Z"));
    runGuard(domStale.doc, domStale.win);

    expect(domStale.banner.hidden).toBe(false);
    expect(domStale.block.getAttribute("data-fresh")).toBeNull();
    expect(domStale.mlAmount.hidden).toBe(true);
    expect(domStale.amzAmount.hidden).toBe(true);
    expect(domStale.verdictText.hidden).toBe(true);
    expect(domStale.mlStale.hidden).toBe(false);
    expect(domStale.mlRow.classList.contains("ganadora")).toBe(false);
    expect(domStale.mlLink.className).toBe("btn ghost sm");
    expect(domStale.mlVerb.textContent).toBe("Ver");
  });

  it("reevalúa al cruzar la medianoche ART con la pestaña abierta, en visibilitychange y en pageshow", () => {
    const script = extractInlineGuardScript();
    const runGuard = new Function("document", "window", script);

    // 1) Abre la pestaña a las 23:59:50 ART del 2026-10-31 (02:59:50Z del 2026-11-01)
    vi.setSystemTime(new Date("2026-11-01T02:59:50.000Z"));
    const dom = buildGuardDom("2026-10-31");
    runGuard(dom.doc, dom.win);

    expect(dom.banner.hidden).toBe(true);
    expect(dom.mlAmount.hidden).toBe(false);
    expect(dom.mlLabel.textContent).toBe("precio de hoy");
    expect(dom.verdictText.hidden).toBe(false);
    expect(dom.mlStale.hidden).toBe(true);
    expect(dom.mlRow.classList.contains("ganadora")).toBe(true);
    expect(dom.mlLink.className).toBe("gana ml");
    expect(dom.mlVerb.textContent).toBe("Comprar");

    // Avanza 9 segundos (23:59:59 ART): todavía es 2026-10-31
    vi.advanceTimersByTime(9_000);
    expect(dom.mlAmount.hidden).toBe(false);
    expect(dom.banner.hidden).toBe(true);

    // Cruza medianoche ART (avanza 1.1s más -> 00:00:00.100 ART del 2026-11-01)
    vi.advanceTimersByTime(1_100);
    expect(dom.banner.hidden).toBe(false);
    expect(dom.block.getAttribute("data-fresh")).toBeNull();
    expect(dom.mlAmount.hidden).toBe(true);
    expect(dom.amzAmount.hidden).toBe(true);
    expect(dom.mlLabel.hidden).toBe(true);
    expect(dom.amzSub.hidden).toBe(true);
    expect(dom.verdictText.hidden).toBe(true);
    expect(dom.mlStale.hidden).toBe(false);
    expect(dom.amzStale.hidden).toBe(false);
    expect(dom.mlRow.classList.contains("ganadora")).toBe(false);
    expect(dom.mlLink.className).toBe("btn ghost sm");
    expect(dom.mlVerb.textContent).toBe("Ver");

    // 2) Si el dispositivo estuvo suspendido y vuelve la visibilidad otro día (visibilitychange)
    vi.setSystemTime(new Date("2026-10-31T20:00:00Z"));
    const domVis = buildGuardDom("2026-10-31");
    runGuard(domVis.doc, domVis.win);
    expect(domVis.mlAmount.hidden).toBe(false);

    // El reloj del sistema salta al día siguiente sin disparar el timer y la pestaña recupera visibilidad
    vi.setSystemTime(new Date("2026-11-01T12:00:00Z"));
    domVis.doc.dispatchEvent("visibilitychange");
    expect(domVis.banner.hidden).toBe(false);
    expect(domVis.mlAmount.hidden).toBe(true);
    expect(domVis.verdictText.hidden).toBe(true);
    expect(domVis.mlStale.hidden).toBe(false);
    expect(domVis.mlLink.className).toBe("btn ghost sm");
    expect(domVis.mlVerb.textContent).toBe("Ver");

    // 3) Si vuelve desde bfcache otro día (pageshow)
    vi.setSystemTime(new Date("2026-10-31T20:00:00Z"));
    const domPageShow = buildGuardDom("2026-10-31");
    runGuard(domPageShow.doc, domPageShow.win);
    expect(domPageShow.mlAmount.hidden).toBe(false);

    vi.setSystemTime(new Date("2026-11-01T14:00:00Z"));
    domPageShow.win.dispatchEvent("pageshow");
    expect(domPageShow.banner.hidden).toBe(false);
    expect(domPageShow.mlAmount.hidden).toBe(true);
    expect(domPageShow.verdictText.hidden).toBe(true);
    expect(domPageShow.mlStale.hidden).toBe(false);
  });
});
