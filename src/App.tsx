import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  Barcode,
  Calculator,
  Check,
  CheckSquare,
  Cookie,
  Cpu,
  FileText,
  Funnel,
  Lightning,
  MagnifyingGlass,
  Package,
  PaperPlaneTilt,
  Plus,
  Scales,
  ShieldCheck,
  SlidersHorizontal,
  SunDim,
  TerminalWindow,
  Truck,
  WarningOctagon,
  X,
} from "@phosphor-icons/react";
import {
  AFFILIATE_CONFIG,
  buildAmazonAffiliateUrl,
  buildAmazonSearchAffiliateUrl,
} from "./config/affiliate";
import {
  COOKIE_STORAGE_KEY,
  CookieConsentState,
  DEFAULT_COOKIE_CONSENT,
  LEGAL_DOCUMENTS,
  LegalDocId,
} from "./data/legal";
import {
  OfferProduct,
  ProductCategory,
  PRODUCTS_DATA,
} from "./data/products";
import {
  calculateCourierArgentina,
  ExchangeRates,
  FALLBACK_RATES,
  fetchLiveExchangeRates,
} from "./utils/courierCalculator";

type ThemeMode = "manifiesto" | "hud";

const CATEGORIES: Array<"Todas" | ProductCategory> = [
  "Todas",
  "Monitores",
  "Mini PCs & Cómputo",
  "Almacenamiento & Periféricos",
  "Audio & VR",
  "Café & Domótica 220V",
];

function formatArs(amount: number): string {
  return new Intl.NumberFormat("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatUsd(amount: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: amount % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  }).format(amount);
}

export function App() {
  // Tema visual (Modo Manifiesto / Modo HUD)
  const [theme, setTheme] = useState<ThemeMode>(() => {
    try {
      const saved = localStorage.getItem("f400_theme");
      return saved === "hud" || saved === "manifiesto" ? saved : "manifiesto";
    } catch {
      return "manifiesto";
    }
  });

  // Cotizaciones cambiarias en vivo
  const [rates, setRates] = useState<ExchangeRates>(FALLBACK_RATES);

  // Filtros del catálogo
  const [selectedCategory, setSelectedCategory] = useState<"Todas" | ProductCategory>("Todas");
  const [selectedStore, setSelectedStore] = useState<"ALL" | "US" | "ES">("ALL");
  const [selectedVatFilter, setSelectedVatFilter] = useState<"ALL" | "105" | "210">("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [sortBy, setSortBy] = useState<"savings" | "priceAsc" | "score">("savings");

  // Matriz comparativa (hasta 4 unidades)
  const [compareIds, setCompareIds] = useState<string[]>([
    "asus-tuf-vg27aq3a",
    "aoc-q27g3xmn-miniled",
    "lg-ultragear-27gp850",
  ]);

  // Modal de inspección técnica de producto
  const [inspectedProduct, setInspectedProduct] = useState<OfferProduct | null>(null);

  // Modal de pliegos legales
  const [activeLegalDoc, setActiveLegalDoc] = useState<LegalDocId | null>(null);

  // Estado de consentimiento de cookies y almacenamiento local
  const [cookieConsent, setCookieConsent] = useState<CookieConsentState>(() => {
    try {
      const raw = localStorage.getItem(COOKIE_STORAGE_KEY);
      if (!raw) return DEFAULT_COOKIE_CONSENT;
      const parsed = JSON.parse(raw) as CookieConsentState;
      return { ...DEFAULT_COOKIE_CONSENT, ...parsed };
    } catch {
      return DEFAULT_COOKIE_CONSENT;
    }
  });
  const [showCookieConfig, setShowCookieConfig] = useState(false);

  // Estado del Simulador Aduanero Interactivo
  const [simName, setSimName] = useState<string>("Simulación libre Courier AR");
  const [simPriceUsd, setSimPriceUsd] = useState<number>(279);
  const [simShippingUsd, setSimShippingUsd] = useState<number>(54);
  const [simVatRate, setSimVatRate] = useState<0.105 | 0.21>(0.105);
  const [simLocalArs, setSimLocalArs] = useState<number>(890000);
  const [simSearchQuery, setSimSearchQuery] = useState<string>("AOC Q27G3XMN Mini LED");
  const [simSearchStore, setSimSearchStore] = useState<"US" | "ES">("US");

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("f400_theme", theme);
    } catch {
      // Ignorar si el navegador bloquea storage
    }
  }, [theme]);

  useEffect(() => {
    fetchLiveExchangeRates().then(setRates);
  }, []);

  // Cerrar modales con tecla Escape
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setInspectedProduct(null);
        setActiveLegalDoc(null);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  function saveCookieDecision(next: CookieConsentState) {
    const updated: CookieConsentState = {
      ...next,
      decided: true,
      necessary: true,
      updatedAt: new Date().toISOString().slice(0, 10),
    };
    setCookieConsent(updated);
    setShowCookieConfig(false);
    try {
      localStorage.setItem(COOKIE_STORAGE_KEY, JSON.stringify(updated));
    } catch {
      // Ignorar si storage no disponible
    }
  }

  const enrichedProducts = useMemo(() => {
    return PRODUCTS_DATA.map((product) => {
      const courier = calculateCourierArgentina(
        product.priceUsd,
        product.shippingUsd,
        rates,
        product.vatRate,
        product.commissionRate
      );
      const netSavingsArs = Math.max(
        0,
        product.localArgentinaPriceArs - courier.finalTotalArsMep
      );
      const savingsPercent = Math.round(
        (netSavingsArs / product.localArgentinaPriceArs) * 100
      );
      const discountUsdPercent = Math.round(
        ((product.previousPriceUsd - product.priceUsd) / product.previousPriceUsd) * 100
      );
      return {
        ...product,
        courier,
        netSavingsArs,
        savingsPercent,
        discountUsdPercent,
      };
    });
  }, [rates]);

  const filteredProducts = useMemo(() => {
    return enrichedProducts
      .filter((p) => {
        const matchesCat =
          selectedCategory === "Todas" || p.category === selectedCategory;
        const matchesStore =
          selectedStore === "ALL" || p.store === selectedStore;
        const matchesVat =
          selectedVatFilter === "ALL" ||
          (selectedVatFilter === "105" && p.vatRate === 0.105) ||
          (selectedVatFilter === "210" && p.vatRate === 0.21);
        const q = searchQuery.toLowerCase().trim();
        const matchesQuery =
          !q ||
          p.name.toLowerCase().includes(q) ||
          p.brand.toLowerCase().includes(q) ||
          p.asin.toLowerCase().includes(q) ||
          p.ncmCode.toLowerCase().includes(q) ||
          p.shortSummary.toLowerCase().includes(q);
        return matchesCat && matchesStore && matchesVat && matchesQuery;
      })
      .sort((a, b) => {
        if (sortBy === "savings") return b.netSavingsArs - a.netSavingsArs;
        if (sortBy === "priceAsc")
          return a.courier.finalTotalArsMep - b.courier.finalTotalArsMep;
        return b.scores.calidadPrecio - a.scores.calidadPrecio;
      });
  }, [
    enrichedProducts,
    selectedCategory,
    selectedStore,
    selectedVatFilter,
    searchQuery,
    sortBy,
  ]);

  const comparedProducts = useMemo(() => {
    return enrichedProducts.filter((p) => compareIds.includes(p.id));
  }, [enrichedProducts, compareIds]);

  const simResult = useMemo(() => {
    return calculateCourierArgentina(
      simPriceUsd,
      simShippingUsd,
      rates,
      simVatRate
    );
  }, [simPriceUsd, simShippingUsd, rates, simVatRate]);

  const simNetSavingsArs = Math.max(0, simLocalArs - simResult.finalTotalArsMep);
  const simSavingsPercent =
    simLocalArs > 0 ? Math.round((simNetSavingsArs / simLocalArs) * 100) : 0;

  function toggleCompare(id: string) {
    setCompareIds((prev) => {
      if (prev.includes(id)) {
        return prev.filter((item) => item !== id);
      }
      if (prev.length >= 4) {
        return [...prev.slice(1), id];
      }
      return [...prev, id];
    });
  }

  function loadProductIntoSimulator(product: OfferProduct) {
    setSimName(product.name);
    setSimPriceUsd(product.priceUsd);
    setSimShippingUsd(product.shippingUsd);
    setSimVatRate(product.vatRate);
    setSimLocalArs(product.localArgentinaPriceArs);
    setSimSearchQuery(product.name.split("(")[0].trim());
    setSimSearchStore(product.store);
    const el = document.getElementById("simulador");
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }
  }

  const mepVsTarjetaGap = Math.round(
    ((rates.tarjeta - rates.mep) / rates.tarjeta) * 100
  );

  return (
    <div className="min-h-screen flex flex-col">
      {/* Cinta superior de precaución industrial */}
      <div className="hazard-rule" aria-hidden="true" />

      {/* Barra de Telemetría Cambiaria y Conmutador de Sustrato */}
      <div
        style={{
          backgroundColor: "var(--bg-alt)",
          borderBottom: "1px solid var(--line-strong)",
        }}
      >
        <div className="shell-container py-2 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-stencil tracking-widest text-[11px] px-2 py-0.5 border border-[var(--accent)] text-[var(--accent)]">
              ARCA · RG 5617
            </span>
            <span className="font-mono-tab font-medium">
              FRANQUICIA COURIER: <strong>USD 400 FOB EXENTO ARANCEL</strong>
            </span>
            <span
              className="hidden xl:inline"
              style={{ color: "var(--muted)" }}
            >
              | Sólo IVA (10,5% / 21%)
            </span>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <div className="flex items-center gap-2.5 font-mono-tab text-xs">
              <span>
                MEP:{" "}
                <strong style={{ color: "var(--ok)" }}>${rates.mep}</strong>
              </span>
              <span style={{ color: "var(--line)" }}>|</span>
              <span>
                TARJETA:{" "}
                <strong style={{ color: "var(--accent)" }}>
                  ${rates.tarjeta}
                </strong>
              </span>
              <span
                className="hidden sm:inline px-1.5 py-0.5 text-[11px] font-bold"
                style={{
                  backgroundColor: "var(--ok-bg)",
                  color: "var(--ok)",
                  border: "1px solid var(--ok)",
                }}
              >
                AHORRO MEP -{mepVsTarjetaGap}%
              </span>
              <span
                className="hidden xl:inline text-[11px]"
                style={{ color: "var(--muted)" }}
              >
                [{rates.isLive ? `DolarApi ${rates.updatedAt}` : rates.updatedAt}]
              </span>
            </div>

            <button
              type="button"
              onClick={() =>
                setTheme((prev) => (prev === "manifiesto" ? "hud" : "manifiesto"))
              }
              className="theme-switch-btn btn-industrial btn-secondary px-2.5 py-1 text-[11px]"
              title="Alternar entre Modo Manifiesto (Papel Aduanero) y Modo HUD (CRT KnuNet)"
            >
              {theme === "manifiesto" ? (
                <>
                  <TerminalWindow weight="bold" className="w-3.5 h-3.5" />
                  MODO HUD CRT
                </>
              ) : (
                <>
                  <SunDim weight="bold" className="w-3.5 h-3.5" />
                  MODO MANIFIESTO
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Cabecera Estructural Principal */}
      <header
        className="md:sticky md:top-0 z-30"
        style={{
          backgroundColor: "var(--surface)",
          borderBottom: "2px solid var(--line-strong)",
        }}
      >
        <div className="shell-container py-3.5 flex flex-wrap items-center justify-between gap-4">
          <a
            href="#top"
            className="flex items-center gap-3.5 no-underline"
            style={{ color: "var(--ink)" }}
          >
            <img
              src="/favicon.svg"
              alt="Sello FRANQUICIA 400 · KnuNet"
              className="w-11 h-11 shrink-0"
            />
            <div>
              <div className="flex items-center gap-2">
                <span className="font-cond font-bold text-2xl tracking-tight leading-none uppercase">
                  FRANQUICIA 400
                </span>
                <span
                  className="font-mono-tab text-[11px] font-bold px-1.5 py-0.5"
                  style={{
                    backgroundColor: "var(--bg-alt)",
                    border: "1px solid var(--line)",
                    color: "var(--muted)",
                  }}
                >
                  KNUNET
                </span>
              </div>
              <p
                className="font-mono-tab text-[11px] mt-1"
                style={{ color: "var(--muted)" }}
              >
                DESPACHO TECNICO Y COMPARADOR COURIER · ESTADOS UNIDOS + ESPAÑA
              </p>
            </div>
          </a>

          {/* Navegación por Módulos */}
          <nav
            aria-label="Secciones principales"
            className="flex flex-wrap items-center gap-1.5"
          >
            <a
              href="#catalogo"
              className="btn-industrial btn-secondary px-3 py-1.5 text-xs"
            >
              <Barcode weight="bold" className="w-4 h-4" />
              01 / CATALOGO ({PRODUCTS_DATA.length})
            </a>
            <a
              href="#simulador"
              className="btn-industrial btn-secondary px-3 py-1.5 text-xs"
            >
              <Calculator weight="bold" className="w-4 h-4" />
              02 / SIMULADOR ADUANA
            </a>
            <a
              href="#comparador"
              className="btn-industrial btn-secondary px-3 py-1.5 text-xs"
            >
              <Scales weight="bold" className="w-4 h-4" />
              03 / MATRIZ ({compareIds.length}/4)
            </a>
            <a
              href="#protocolo"
              className="btn-industrial btn-secondary px-3 py-1.5 text-xs hidden sm:inline-flex"
            >
              <ShieldCheck weight="bold" className="w-4 h-4" />
              04 / PROTOCOLO ARCA
            </a>
          </nav>
        </div>

        {/* Franja Reglamentaria de Transparencia Amazon Associates (Visible above-the-fold) */}
        <div
          style={{
            backgroundColor: "var(--bg-alt)",
            borderTop: "1px solid var(--line)",
          }}
        >
          <div className="shell-container py-1.5 flex flex-wrap items-center justify-between gap-2 text-[11px]">
            <p style={{ color: "var(--muted)" }} className="font-mono-tab">
              <strong>AVISO REGLAMENTARIO:</strong>{" "}
              {AFFILIATE_CONFIG.amazonDisclosureShort} El precio para vos no cambia.
            </p>
            <div className="flex items-center gap-3 font-mono-tab">
              <button
                type="button"
                onClick={() => setActiveLegalDoc("afiliados")}
                className="underline cursor-pointer bg-transparent border-0 p-0 text-[11px]"
                style={{ color: "var(--accent)" }}
              >
                Ver pliego de afiliación
              </button>
              <span style={{ color: "var(--line)" }}>|</span>
              <button
                type="button"
                onClick={() => setActiveLegalDoc("terminos")}
                className="underline cursor-pointer bg-transparent border-0 p-0 text-[11px]"
                style={{ color: "var(--muted)" }}
              >
                Alcance del simulador
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Bloque Hero / Manifiesto Operativo */}
      <section
        id="top"
        style={{
          borderBottom: "2px solid var(--line-strong)",
          backgroundColor: "var(--surface)",
        }}
      >
        <div className="shell-container py-8 lg:py-10">
          <div
            className="grid lg:grid-cols-12"
            style={{
              border: "1px solid var(--line-strong)",
              backgroundColor: "var(--bg)",
            }}
          >
            {/* Columna Izquierda: Tesis y Buscador Rápido */}
            <div
              className="lg:col-span-8 p-6 sm:p-8 flex flex-col justify-between gap-6"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="customs-stamp">
                    DESPACHO PUERTA A PUERTA · RG 5617
                  </span>
                  <span className="customs-stamp-ok">
                    <Check weight="bold" className="w-3.5 h-3.5" />
                    0% ARANCEL HASTA USD 400 FOB
                  </span>
                </div>

                <h1
                  className="font-cond font-bold uppercase tracking-tight"
                  style={{
                    fontSize: "clamp(2.2rem, 4.6vw, 3.85rem)",
                    lineHeight: 0.94,
                    color: "var(--ink)",
                  }}
                >
                  EL NUMERO REAL PUESTO EN TU PUERTA,{" "}
                  <span style={{ color: "var(--accent)" }}>
                    SIN SOBREPRECIO LOCAL.
                  </span>
                </h1>

                <p
                  className="text-base sm:text-lg max-w-[66ch]"
                  style={{ color: "var(--muted)" }}
                >
                  Relevamos hardware de informática, periféricos y electro 220V en{" "}
                  <strong style={{ color: "var(--ink)" }}>
                    Amazon Estados Unidos y Amazon España
                  </strong>{" "}
                  con envío Courier habilitado a Argentina por debajo de los{" "}
                  <strong style={{ color: "var(--ink)" }}>USD 400 FOB</strong>.
                  Calculamos flete, alícuota exacta de IVA (10,5% o 21%) al{" "}
                  <strong style={{ color: "var(--ink)" }}>
                    Dólar MEP (${rates.mep})
                  </strong>{" "}
                  y lo medimos contra lo que te piden acá.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-3 pt-2">
                <a
                  href="#catalogo"
                  className="btn-industrial btn-primary px-5 py-3 text-sm"
                >
                  <Barcode weight="bold" className="w-4 h-4" />
                  INSPECCIONAR PLANILLA DE HARDWARE
                </a>
                <a
                  href="#simulador"
                  className="btn-industrial btn-secondary px-5 py-3 text-sm"
                >
                  <Calculator weight="bold" className="w-4 h-4" />
                  ABRIR SIMULADOR ADUANERO LIBRE
                </a>
              </div>
            </div>

            {/* Columna Derecha: Parámetros de Liquidación Vigentes */}
            <div
              className="lg:col-span-4 flex flex-col justify-between"
              style={{
                backgroundColor: "var(--bg-alt)",
                borderLeft: "1px solid var(--line)",
              }}
            >
              <div
                className="p-5 border-b"
                style={{ borderColor: "var(--line)" }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-cond font-bold uppercase text-sm tracking-wider">
                    PARAMETROS DE LIQUIDACION
                  </span>
                  <span className="font-mono-tab text-xs" style={{ color: "var(--accent)" }}>
                    DECRETO 1065/24
                  </span>
                </div>
                <p
                  className="text-xs mt-1"
                  style={{ color: "var(--muted)" }}
                >
                  Condiciones vigentes para Pequeños Envíos Courier Privado (DHL, UPS, FedEx, AmazonGlobal).
                </p>
              </div>

              <div className="grid grid-cols-2 divide-x divide-y divide-[var(--line)] font-mono-tab">
                <div className="p-4">
                  <span
                    className="block text-[10px] uppercase"
                    style={{ color: "var(--muted)" }}
                  >
                    TOPE EXENTO ARANCEL
                  </span>
                  <strong className="text-xl block mt-0.5" style={{ color: "var(--ink)" }}>
                    USD 400
                  </strong>
                  <span className="text-[11px]" style={{ color: "var(--ok)" }}>
                    Valor FOB mercadería
                  </span>
                </div>

                <div className="p-4">
                  <span
                    className="block text-[10px] uppercase"
                    style={{ color: "var(--muted)" }}
                  >
                    IVA INFORMATICA
                  </span>
                  <strong className="text-xl block mt-0.5" style={{ color: "var(--ink)" }}>
                    10,5%
                  </strong>
                  <span className="text-[11px]" style={{ color: "var(--muted)" }}>
                    Monitores, Mini PC, SSD
                  </span>
                </div>

                <div className="p-4">
                  <span
                    className="block text-[10px] uppercase"
                    style={{ color: "var(--muted)" }}
                  >
                    IVA CONSUMO GRAL
                  </span>
                  <strong className="text-xl block mt-0.5" style={{ color: "var(--ink)" }}>
                    21,0%
                  </strong>
                  <span className="text-[11px]" style={{ color: "var(--muted)" }}>
                    Audio, VR, Café, Robots
                  </span>
                </div>

                <div className="p-4">
                  <span
                    className="block text-[10px] uppercase"
                    style={{ color: "var(--muted)" }}
                  >
                    CUPO PERSONAL
                  </span>
                  <strong className="text-xl block mt-0.5" style={{ color: "var(--ink)" }}>
                    5 / AÑO
                  </strong>
                  <span className="text-[11px]" style={{ color: "var(--muted)" }}>
                    Máx. 3 iguales · 50 kg
                  </span>
                </div>
              </div>

              <div
                className="p-4 text-xs"
                style={{
                  borderTop: "1px solid var(--line)",
                  backgroundColor: "var(--surface)",
                }}
              >
                <div className="flex items-start gap-2">
                  <Lightning
                    weight="fill"
                    className="w-4 h-4 shrink-0 mt-0.5"
                    style={{ color: "var(--accent)" }}
                  />
                  <p style={{ color: "var(--muted)" }}>
                    <strong style={{ color: "var(--ink)" }}>Regla MEP:</strong>{" "}
                    pagando el resumen en dólares con Dólar MEP antes del vencimiento evitás el 30% de recargo del Dólar Tarjeta.
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Contenedor Principal de Módulos */}
      <main className="shell-container py-10 space-y-16 flex-1">
        {/* =====================================================================
            MODULO 01: PLANILLA DE DESPACHO E INSPECCION DE HARDWARE
           ===================================================================== */}
        <section id="catalogo" className="space-y-6 scroll-mt-24">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-4 border-b-2 border-[var(--line-strong)]">
            <div>
              <div className="font-mono-tab text-xs uppercase tracking-widest" style={{ color: "var(--accent)" }}>
                MODULO 01 // RELEVAMIENTO DE UNIDADES SUB-USD 400
              </div>
              <h2 className="font-cond font-bold text-3xl sm:text-4xl uppercase tracking-tight mt-1">
                PLANILLA DE DESPACHO E INSPECCION TECNICA
              </h2>
            </div>
            <p className="text-xs font-mono-tab" style={{ color: "var(--muted)" }}>
              MOSTRANDO {filteredProducts.length} DE {PRODUCTS_DATA.length} ITEMS VERIFICADOS · VALORES EN ARS AL MEP (${rates.mep})
            </p>
          </div>

          {/* Barra de Filtrado Ortogonal */}
          <div
            className="grid lg:grid-cols-12 gap-3 p-4"
            style={{
              backgroundColor: "var(--surface)",
              border: "1px solid var(--line-strong)",
            }}
          >
            {/* Categorías */}
            <div className="lg:col-span-7 flex flex-wrap gap-1.5 items-center">
              {CATEGORIES.map((category) => {
                const active = selectedCategory === category;
                return (
                  <button
                    key={category}
                    type="button"
                    onClick={() => setSelectedCategory(category)}
                    className={`btn-industrial px-3 py-1.5 text-xs ${
                      active ? "btn-primary" : "btn-secondary"
                    }`}
                  >
                    {category}
                  </button>
                );
              })}
            </div>

            {/* Filtros secundarios: Origen, IVA, Búsqueda y Orden */}
            <div className="lg:col-span-5 grid sm:grid-cols-3 gap-2">
              <div className="relative flex items-center sm:col-span-1">
                <MagnifyingGlass
                  weight="bold"
                  className="w-3.5 h-3.5 absolute left-2.5 pointer-events-none"
                  style={{ color: "var(--muted)" }}
                />
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Modelo, ASIN, NCM..."
                  aria-label="Buscar por modelo, código ASIN o posición NCM"
                  className="input-technical py-1.5 text-xs"
                  style={{ paddingLeft: "2rem", paddingRight: "0.5rem" }}
                />
              </div>

              <select
                value={`${selectedStore}:${selectedVatFilter}`}
                onChange={(e) => {
                  const [st, vt] = e.target.value.split(":") as [
                    "ALL" | "US" | "ES",
                    "ALL" | "105" | "210"
                  ];
                  setSelectedStore(st);
                  setSelectedVatFilter(vt);
                }}
                aria-label="Filtrar por tienda de origen y alícuota de IVA"
                className="input-technical py-1.5 px-2 text-xs"
              >
                <option value="ALL:ALL">Origen + IVA: Todos</option>
                <option value="ALL:105">Sólo IVA 10,5% (Informática)</option>
                <option value="ALL:210">Sólo IVA 21,0% (General)</option>
                <option value="US:ALL">Sólo Amazon EE.UU. (.com)</option>
                <option value="ES:ALL">Sólo Amazon España (.es 220V)</option>
              </select>

              <select
                value={sortBy}
                onChange={(e) =>
                  setSortBy(e.target.value as "savings" | "priceAsc" | "score")
                }
                aria-label="Ordenar productos"
                className="input-technical py-1.5 px-2 text-xs"
              >
                <option value="savings">Orden: Mayor ahorro ARS</option>
                <option value="priceAsc">Orden: Menor precio final</option>
                <option value="score">Orden: Mayor nota técnica</option>
              </select>
            </div>
          </div>

          {/* Grilla de Unidades de Hardware */}
          {filteredProducts.length === 0 ? (
            <div
              className="p-10 text-center space-y-3"
              style={{
                backgroundColor: "var(--surface)",
                border: "1px solid var(--line)",
              }}
            >
              <p className="font-mono-tab text-sm" style={{ color: "var(--muted)" }}>
                No se encontraron unidades con los filtros aplicados.
              </p>
              <button
                type="button"
                onClick={() => {
                  setSelectedCategory("Todas");
                  setSelectedStore("ALL");
                  setSelectedVatFilter("ALL");
                  setSearchQuery("");
                }}
                className="btn-industrial btn-primary px-4 py-2 text-xs"
              >
                RESTABLECER FILTROS
              </button>
            </div>
          ) : (
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-5">
              {filteredProducts.map((item) => {
                const isSelectedForCompare = compareIds.includes(item.id);
                const affiliateLink = buildAmazonAffiliateUrl(item.asin, item.store);

                return (
                  <article key={item.id} className="dispatch-card">
                    <div>
                      {/* Encabezado de Celda: Posición Arancelaria + Sello */}
                      <div
                        className="px-4 py-2.5 flex items-center justify-between gap-2 text-[11px] font-mono-tab"
                        style={{
                          backgroundColor: "var(--bg-alt)",
                          borderBottom: "1px solid var(--line)",
                        }}
                      >
                        <span style={{ color: "var(--muted)" }}>
                          NCM <strong>{item.ncmCode}</strong> ·{" "}
                          <strong>
                            {item.store === "ES" ? "AMAZON.ES (UE)" : "AMAZON.COM (US)"}
                          </strong>
                        </span>
                        <span className="customs-stamp text-[10px] py-0.5 px-2">
                          {item.stamp}
                        </span>
                      </div>

                      {/* Placa Fotográfica de Estudio */}
                      <div
                        className="product-plate cursor-pointer"
                        onClick={() => setInspectedProduct(item)}
                      >
                        <img
                          src={item.imageUrl}
                          alt={item.name}
                          loading="lazy"
                          width={360}
                          height={270}
                        />
                        <div
                          className="absolute top-2.5 left-2.5 font-mono-tab text-[10px] px-2 py-0.5"
                          style={{
                            backgroundColor: "#141311",
                            color: "#FAF8F4",
                          }}
                        >
                          ASIN: {item.asin}
                        </div>
                        <div
                          className="absolute bottom-2.5 left-2.5 font-mono-tab text-[10px] px-2 py-0.5"
                          style={{
                            backgroundColor: "#F2EFE9",
                            color: "#141311",
                            border: "1px solid #CEC8BA",
                          }}
                        >
                          {item.voltageSpec}
                        </div>
                        <div
                          className="absolute bottom-2.5 right-2.5 font-mono-tab font-bold text-xs px-2 py-0.5"
                          style={{
                            backgroundColor: "#146338",
                            color: "#FAF8F4",
                          }}
                        >
                          INDICE {item.scores.calidadPrecio}/10
                        </div>
                      </div>

                      {/* Identificación y Resumen Técnico */}
                      <div className="p-4 space-y-2.5">
                        <div className="flex items-center justify-between text-[11px] font-mono-tab">
                          <span
                            className="uppercase font-bold"
                            style={{ color: "var(--accent)" }}
                          >
                            {item.category}
                          </span>
                          <span style={{ color: "var(--muted)" }}>
                            PESO: {item.weightKg} · {item.reviewsCount.toLocaleString("es-AR")} OPINIONES
                          </span>
                        </div>

                        <h3
                          onClick={() => setInspectedProduct(item)}
                          className="font-cond font-bold text-xl leading-tight uppercase cursor-pointer hover:underline"
                          style={{ color: "var(--ink)" }}
                        >
                          {item.name}
                        </h3>

                        <p
                          className="text-xs line-clamp-2"
                          style={{ color: "var(--muted)" }}
                        >
                          {item.shortSummary}
                        </p>
                      </div>
                    </div>

                    {/* Cuadro de Liquidación Aduanera y Botonera */}
                    <div className="p-4 pt-0 space-y-3">
                      <div
                        className="font-mono-tab text-xs"
                        style={{
                          border: "1px solid var(--line)",
                          backgroundColor: "var(--bg)",
                        }}
                      >
                        <div
                          className="px-3 py-1.5 flex items-center justify-between border-b"
                          style={{ borderColor: "var(--line)" }}
                        >
                          <span style={{ color: "var(--muted)" }}>
                            VALOR FOB ({item.store}):
                          </span>
                          <div className="flex items-center gap-2">
                            <span
                              className="line-through text-[11px]"
                              style={{ color: "var(--muted)" }}
                            >
                              {formatUsd(item.previousPriceUsd)}
                            </span>
                            <strong style={{ color: "var(--ink)" }}>
                              {formatUsd(item.priceUsd)}
                            </strong>
                            <span
                              className="text-[10px] px-1 font-bold"
                              style={{
                                backgroundColor: "var(--accent-soft)",
                                color: "var(--accent)",
                              }}
                            >
                              -{item.discountUsdPercent}%
                            </span>
                          </div>
                        </div>

                        <div
                          className="px-3 py-1.5 flex items-center justify-between border-b text-[11px]"
                          style={{ borderColor: "var(--line)" }}
                        >
                          <span style={{ color: "var(--muted)" }}>
                            FLETE ({formatUsd(item.shippingUsd)}) + IVA ({item.vatRate * 100}%):
                          </span>
                          <span>
                            +{formatUsd(item.shippingUsd + item.courier.totalTaxesUsd)}
                          </span>
                        </div>

                        <div
                          className="px-3 py-2 flex items-baseline justify-between"
                          style={{ backgroundColor: "var(--bg-alt)" }}
                        >
                          <div>
                            <span className="text-[10px] uppercase block font-bold">
                              FINAL EN PUERTA (MEP):
                            </span>
                            <span
                              className="text-[11px]"
                              style={{ color: "var(--muted)" }}
                            >
                              {formatUsd(item.courier.finalTotalUsd)} totales
                            </span>
                          </div>
                          <strong
                            className="text-xl font-bold"
                            style={{ color: "var(--accent)" }}
                          >
                            {formatArs(item.courier.finalTotalArsMep)}
                          </strong>
                        </div>
                      </div>

                      {/* Comparativa contra Canal Local */}
                      <div
                        className="px-3 py-2 flex items-center justify-between text-xs font-mono-tab"
                        style={{
                          backgroundColor: "var(--ok-bg)",
                          border: "1px solid var(--ok)",
                          color: "var(--ok)",
                        }}
                      >
                        <span>
                          LOCAL AR:{" "}
                          <span className="line-through">
                            {formatArs(item.localArgentinaPriceArs)}
                          </span>
                        </span>
                        <strong>
                          AHORRAS {formatArs(item.netSavingsArs)} (-{item.savingsPercent}%)
                        </strong>
                      </div>

                      {/* Acciones de Tarjeta */}
                      <div className="grid grid-cols-12 gap-1.5">
                        <a
                          href={affiliateLink}
                          target="_blank"
                          rel="noopener noreferrer sponsored"
                          className="col-span-6 btn-industrial btn-primary py-2.5 px-2 text-xs"
                        >
                          VER EN AMAZON
                          <ArrowUpRight weight="bold" className="w-3.5 h-3.5" />
                        </a>

                        <button
                          type="button"
                          onClick={() => setInspectedProduct(item)}
                          className="col-span-3 btn-industrial btn-secondary py-2.5 px-2 text-xs"
                          title="Abrir pliego técnico completo"
                        >
                          FICHA
                        </button>

                        <button
                          type="button"
                          onClick={() => toggleCompare(item.id)}
                          className={`col-span-3 btn-industrial py-2.5 px-2 text-xs ${
                            isSelectedForCompare ? "btn-primary" : "btn-secondary"
                          }`}
                          title="Agregar o quitar de la matriz comparativa"
                        >
                          {isSelectedForCompare ? (
                            <>
                              <Check weight="bold" className="w-3.5 h-3.5" />
                              EN MATRIZ
                            </>
                          ) : (
                            <>
                              <Plus weight="bold" className="w-3.5 h-3.5" />
                              COMPARAR
                            </>
                          )}
                        </button>
                      </div>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        {/* =====================================================================
            MODULO 02: SIMULADOR ADUANERO INTERACTIVO (RG 5617 ARCA)
           ===================================================================== */}
        <section id="simulador" className="space-y-6 scroll-mt-24">
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-4 border-b-2 border-[var(--line-strong)]">
            <div>
              <h2 className="font-cond font-bold text-3xl sm:text-4xl uppercase tracking-tight">
                02 // SIMULADOR DE LIQUIDACION ADUANERA COURIER
              </h2>
              <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
                Ingresá el precio FOB y el costo de envío de cualquier publicación de Amazon para obtener el desglose impositivo exacto en pesos.
              </p>
            </div>

            {/* Carga rápida de ejemplos reales */}
            <div className="flex items-center gap-2">
              <span className="font-mono-tab text-xs" style={{ color: "var(--muted)" }}>
                CARGAR EJEMPLO:
              </span>
              <select
                onChange={(e) => {
                  const found = PRODUCTS_DATA.find((p) => p.id === e.target.value);
                  if (found) loadProductIntoSimulator(found);
                }}
                defaultValue="aoc-q27g3xmn-miniled"
                aria-label="Cargar producto de ejemplo en el simulador"
                className="input-technical py-1.5 px-2.5 text-xs w-auto"
              >
                {PRODUCTS_DATA.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.brand} - {formatUsd(p.priceUsd)} FOB ({p.store})
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div
            className="grid lg:grid-cols-12"
            style={{
              border: "1px solid var(--line-strong)",
              backgroundColor: "var(--surface)",
            }}
          >
            {/* Panel Izquierdo: Parámetros de Entrada */}
            <div
              className="lg:col-span-7 p-6 sm:p-8 space-y-6"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              <div className="flex items-center justify-between border-b pb-3" style={{ borderColor: "var(--line)" }}>
                <span className="font-cond font-bold uppercase text-lg">
                  DATOS DE ORIGEN DEL ENVIO
                </span>
                <span className="font-mono-tab text-xs" style={{ color: "var(--muted)" }}>
                  ITEM: {simName.slice(0, 34)}
                </span>
              </div>

              <div className="grid sm:grid-cols-3 gap-4">
                <div className="space-y-1.5">
                  <label
                    htmlFor="sim-fob"
                    className="block font-mono-tab text-xs font-bold uppercase"
                  >
                    1. VALOR FOB PRODUCTO (USD)
                  </label>
                  <input
                    id="sim-fob"
                    type="number"
                    min={1}
                    max={3000}
                    value={simPriceUsd}
                    onChange={(e) => setSimPriceUsd(Math.max(0, Number(e.target.value) || 0))}
                    className="input-technical"
                  />
                  <span className="block text-[11px]" style={{ color: "var(--muted)" }}>
                    Tope exento arancel: USD 400
                  </span>
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="sim-ship"
                    className="block font-mono-tab text-xs font-bold uppercase"
                  >
                    2. FLETE COURIER (USD)
                  </label>
                  <input
                    id="sim-ship"
                    type="number"
                    min={0}
                    max={1000}
                    value={simShippingUsd}
                    onChange={(e) => setSimShippingUsd(Math.max(0, Number(e.target.value) || 0))}
                    className="input-technical"
                  />
                  <span className="block text-[11px]" style={{ color: "var(--muted)" }}>
                    Costo de envío AmazonGlobal
                  </span>
                </div>

                <div className="space-y-1.5">
                  <label
                    htmlFor="sim-local"
                    className="block font-mono-tab text-xs font-bold uppercase"
                  >
                    3. PRECIO LOCAL AR (ARS)
                  </label>
                  <input
                    id="sim-local"
                    type="number"
                    min={0}
                    step={10000}
                    value={simLocalArs}
                    onChange={(e) => setSimLocalArs(Math.max(0, Number(e.target.value) || 0))}
                    className="input-technical"
                  />
                  <span className="block text-[11px]" style={{ color: "var(--muted)" }}>
                    Para medir tu ahorro neto
                  </span>
                </div>
              </div>

              {/* Selector de Posición Arancelaria / Alícuota IVA */}
              <div className="space-y-2">
                <span className="block font-mono-tab text-xs font-bold uppercase">
                  4. POSICION ARANCELARIA / ALICUOTA DE IVA ADUANERO
                </span>
                <div className="grid sm:grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setSimVatRate(0.105)}
                    className={`p-3.5 text-left border transition cursor-pointer ${
                      simVatRate === 0.105
                        ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                        : "border-[var(--line)] bg-[var(--bg)]"
                    }`}
                  >
                    <div className="flex items-center justify-between font-mono-tab text-xs font-bold">
                      <span>BIENES DE INFORMATICA (10,5% IVA)</span>
                      {simVatRate === 0.105 && (
                        <Check weight="bold" className="w-4 h-4" style={{ color: "var(--accent)" }} />
                      )}
                    </div>
                    <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                      Monitores, Mini PCs, Notebooks, SSD NVMe, Memorias, Teclados, Placas de video (Art. 28 inc. e Ley IVA).
                    </p>
                  </button>

                  <button
                    type="button"
                    onClick={() => setSimVatRate(0.21)}
                    className={`p-3.5 text-left border transition cursor-pointer ${
                      simVatRate === 0.21
                        ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                        : "border-[var(--line)] bg-[var(--bg)]"
                    }`}
                  >
                    <div className="flex items-center justify-between font-mono-tab text-xs font-bold">
                      <span>REGIMEN GENERAL (21,0% IVA)</span>
                      {simVatRate === 0.21 && (
                        <Check weight="bold" className="w-4 h-4" style={{ color: "var(--accent)" }} />
                      )}
                    </div>
                    <p className="text-xs mt-1" style={{ color: "var(--muted)" }}>
                      Auriculares, Visores VR, Cafeteras Express, Aspiradoras Robot, Power Banks, Hogar e Indumentaria.
                    </p>
                  </button>
                </div>
              </div>

              {/* Buscador Directo en Amazon con Tag Inyectado */}
              <div
                className="p-4 space-y-3"
                style={{
                  backgroundColor: "var(--bg-alt)",
                  border: "1px solid var(--line)",
                }}
              >
                <div className="flex items-center justify-between">
                  <span className="font-cond font-bold uppercase text-sm tracking-wide">
                    BUSCADOR DIRECTO EN AMAZON CON FILTRO COURIER
                  </span>
                  <div className="flex gap-1 font-mono-tab text-[11px]">
                    <button
                      type="button"
                      onClick={() => setSimSearchStore("US")}
                      className={`px-2 py-0.5 border cursor-pointer ${
                        simSearchStore === "US"
                          ? "border-[var(--accent)] text-[var(--accent)] font-bold"
                          : "border-[var(--line)] text-[var(--muted)]"
                      }`}
                    >
                      US (.com)
                    </button>
                    <button
                      type="button"
                      onClick={() => setSimSearchStore("ES")}
                      className={`px-2 py-0.5 border cursor-pointer ${
                        simSearchStore === "ES"
                          ? "border-[var(--accent)] text-[var(--accent)] font-bold"
                          : "border-[var(--line)] text-[var(--muted)]"
                      }`}
                    >
                      ES (.es 220V)
                    </button>
                  </div>
                </div>

                <div className="flex flex-col sm:flex-row gap-2">
                  <input
                    type="text"
                    value={simSearchQuery}
                    onChange={(e) => setSimSearchQuery(e.target.value)}
                    placeholder="Escribí marca y modelo exacto (ej. Beelink SER8, LG 27GR95QE...)"
                    aria-label="Término para buscar en Amazon"
                    className="input-technical flex-1 text-xs"
                  />
                  <a
                    href={buildAmazonSearchAffiliateUrl(simSearchQuery, simSearchStore)}
                    target="_blank"
                    rel="noopener noreferrer sponsored"
                    className="btn-industrial btn-primary px-4 py-2.5 text-xs shrink-0"
                  >
                    BUSCAR EN AMAZON.{simSearchStore === "ES" ? "ES" : "COM"}
                    <ArrowUpRight weight="bold" className="w-4 h-4" />
                  </a>
                </div>
              </div>
            </div>

            {/* Panel Derecho: Ticket de Liquidación Aduanera */}
            <div
              className="lg:col-span-5 p-6 sm:p-8 flex flex-col justify-between space-y-5"
              style={{
                backgroundColor: "var(--bg-alt)",
                borderLeft: "1px solid var(--line)",
              }}
            >
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-cond font-bold uppercase text-lg">
                    LIQUIDACION ADUANERA ESTIMADA
                  </span>
                  {simResult.qualifiesForFranchise ? (
                    <span className="customs-stamp-ok">
                      FRANQUICIA ACTIVA (0% ARANCEL)
                    </span>
                  ) : (
                    <span className="customs-stamp">
                      SUPERADO TOPE USD 400 (+{formatUsd(simResult.excessFobUsd)})
                    </span>
                  )}
                </div>

                <div
                  className="font-mono-tab text-xs divide-y divide-[var(--line)]"
                  style={{
                    border: "1px solid var(--line-strong)",
                    backgroundColor: "var(--surface)",
                  }}
                >
                  <div className="p-3 flex justify-between">
                    <span style={{ color: "var(--muted)" }}>Valor FOB Mercadería:</span>
                    <strong>{formatUsd(simResult.fobUsd)}</strong>
                  </div>
                  <div className="p-3 flex justify-between">
                    <span style={{ color: "var(--muted)" }}>Flete Internacional Courier:</span>
                    <strong>+{formatUsd(simResult.shippingUsd)}</strong>
                  </div>
                  <div
                    className="p-3 flex justify-between"
                    style={{ backgroundColor: "var(--bg)" }}
                  >
                    <span className="font-bold">Base Imponible CIF:</span>
                    <strong>{formatUsd(simResult.cifUsd)}</strong>
                  </div>
                  <div className="p-3 flex justify-between">
                    <span style={{ color: "var(--muted)" }}>
                      Derechos de Importación (35% s/excedente):
                    </span>
                    <strong style={{ color: simResult.importDutyUsd === 0 ? "var(--ok)" : "var(--ink)" }}>
                      {simResult.importDutyUsd === 0 ? "USD 0 (EXENTO)" : `+${formatUsd(simResult.importDutyUsd)}`}
                    </strong>
                  </div>
                  <div className="p-3 flex justify-between">
                    <span style={{ color: "var(--muted)" }}>
                      Tasa de Estadística (3% s/excedente):
                    </span>
                    <strong style={{ color: simResult.statisticalFeeUsd === 0 ? "var(--ok)" : "var(--ink)" }}>
                      {simResult.statisticalFeeUsd === 0 ? "USD 0 (EXENTO)" : `+${formatUsd(simResult.statisticalFeeUsd)}`}
                    </strong>
                  </div>
                  <div className="p-3 flex justify-between">
                    <span style={{ color: "var(--muted)" }}>
                      IVA Aduanero ({simResult.vatRate * 100}%):
                    </span>
                    <strong>+{formatUsd(simResult.vatUsd)}</strong>
                  </div>
                  <div
                    className="p-3.5 flex justify-between items-baseline"
                    style={{ backgroundColor: "var(--bg-alt)" }}
                  >
                    <span className="font-bold uppercase">TOTAL FINAL EN USD:</span>
                    <strong className="text-base" style={{ color: "var(--ink)" }}>
                      {formatUsd(simResult.finalTotalUsd)}
                    </strong>
                  </div>
                </div>

                {/* Conversión a Pesos: Dólar MEP vs Dólar Tarjeta */}
                <div
                  className="p-4 space-y-2"
                  style={{
                    border: "2px solid var(--line-strong)",
                    backgroundColor: "var(--surface)",
                  }}
                >
                  <div className="flex items-baseline justify-between">
                    <div>
                      <span className="font-cond font-bold uppercase text-sm block">
                        TOTAL PAGANDO CON DOLAR MEP (${rates.mep})
                      </span>
                      <span className="font-mono-tab text-[11px]" style={{ color: "var(--muted)" }}>
                        Con tarjeta USD o pagando el resumen antes del vencimiento
                      </span>
                    </div>
                    <strong
                      className="font-mono-tab text-2xl sm:text-3xl font-bold"
                      style={{ color: "var(--accent)" }}
                    >
                      {formatArs(simResult.finalTotalArsMep)}
                    </strong>
                  </div>

                  <div
                    className="pt-2 border-t flex items-center justify-between font-mono-tab text-xs"
                    style={{ borderColor: "var(--line)" }}
                  >
                    <span style={{ color: "var(--muted)" }}>
                      Si pagaras con Dólar Tarjeta (${rates.tarjeta}):{" "}
                      <span className="line-through">
                        {formatArs(simResult.finalTotalArsTarjeta)}
                      </span>
                    </span>
                    <span style={{ color: "var(--ok)" }} className="font-bold">
                      Ahorrás {formatArs(simResult.savingsUsingMepArs)} usando MEP
                    </span>
                  </div>
                </div>

                {/* Brecha frente al precio local ingresado */}
                {simLocalArs > 0 && (
                  <div
                    className="p-3.5 font-mono-tab text-xs flex items-center justify-between"
                    style={{
                      backgroundColor:
                        simNetSavingsArs > 0 ? "var(--ok-bg)" : "var(--warn-bg)",
                      border: `1px solid ${
                        simNetSavingsArs > 0 ? "var(--ok)" : "var(--warn)"
                      }`,
                      color: simNetSavingsArs > 0 ? "var(--ok)" : "var(--warn)",
                    }}
                  >
                    {simNetSavingsArs > 0 ? (
                      <>
                        <span>BRECHA VS. TIENDA LOCAL AR:</span>
                        <strong>
                          TE AHORRAS {formatArs(simNetSavingsArs)} (-{simSavingsPercent}%)
                        </strong>
                      </>
                    ) : (
                      <>
                        <span>COMPARATIVA LOCAL:</span>
                        <strong>EL PRECIO LOCAL ES IGUAL O MENOR</strong>
                      </>
                    )}
                  </div>
                )}
              </div>

              <p className="text-[11px] font-mono-tab" style={{ color: "var(--muted)" }}>
                Nota: AmazonGlobal calcula y retiene estos tributos en el checkout bajo su garantía de Depósito de Tasas de Importación (si Aduana cobra menos, te devuelven la diferencia).
              </p>
            </div>
          </div>
        </section>

        {/* =====================================================================
            MODULO 03: MATRIZ COMPARATIVA LADO A LADO
           ===================================================================== */}
        <section id="comparador" className="space-y-6 scroll-mt-24">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4 pb-4 border-b-2 border-[var(--line-strong)]">
            <div>
              <h2 className="font-cond font-bold text-3xl sm:text-4xl uppercase tracking-tight">
                03 // MATRIZ COMPARATIVA DE ESPECIFICACIONES Y COSTOS
              </h2>
              <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
                Inspección lado a lado de hasta 4 unidades del catálogo con desglose de impuestos y compatibilidad eléctrica.
              </p>
            </div>

            <div className="flex items-center gap-2">
              <select
                onChange={(e) => {
                  if (e.target.value) {
                    toggleCompare(e.target.value);
                    e.target.value = "";
                  }
                }}
                defaultValue=""
                aria-label="Agregar o quitar producto de la matriz comparativa"
                className="input-technical py-1.5 px-3 text-xs w-auto"
              >
                <option value="" disabled>
                  + Agregar / quitar unidad ({compareIds.length}/4)...
                </option>
                {enrichedProducts.map((p) => (
                  <option key={p.id} value={p.id}>
                    {compareIds.includes(p.id) ? "[ACTIVO] " : "[ + ] "}
                    {p.name.slice(0, 44)} ({formatUsd(p.priceUsd)})
                  </option>
                ))}
              </select>
            </div>
          </div>

          {comparedProducts.length === 0 ? (
            <div
              className="p-10 text-center space-y-3"
              style={{
                backgroundColor: "var(--surface)",
                border: "1px solid var(--line)",
              }}
            >
              <p className="font-mono-tab text-sm" style={{ color: "var(--muted)" }}>
                No tenés unidades cargadas en la matriz comparativa.
              </p>
              <button
                type="button"
                onClick={() =>
                  setCompareIds([
                    "asus-tuf-vg27aq3a",
                    "aoc-q27g3xmn-miniled",
                    "lg-ultragear-27gp850",
                  ])
                }
                className="btn-industrial btn-primary px-4 py-2 text-xs"
              >
                CARGAR COMPARATIVA DE MONITORES 27" QHD
              </button>
            </div>
          ) : (
            <div
              className="overflow-x-auto"
              style={{
                border: "1px solid var(--line-strong)",
                backgroundColor: "var(--surface)",
              }}
            >
              <table className="w-full text-left border-collapse min-w-[760px]">
                <thead>
                  <tr
                    style={{
                      backgroundColor: "var(--bg-alt)",
                      borderBottom: "2px solid var(--line-strong)",
                    }}
                  >
                    <th className="p-4 w-52 font-mono-tab text-xs uppercase">
                      PARAMETRO / UNIDAD
                    </th>
                    {comparedProducts.map((product) => (
                      <th
                        key={product.id}
                        className="p-4 align-top w-64 border-l"
                        style={{ borderColor: "var(--line)" }}
                      >
                        <div className="space-y-2.5">
                          <div className="flex items-center justify-between font-mono-tab text-[11px]">
                            <span
                              className="font-bold uppercase"
                              style={{ color: "var(--accent)" }}
                            >
                              {product.brand} · {product.store}
                            </span>
                            <button
                              type="button"
                              onClick={() => toggleCompare(product.id)}
                              className="btn-industrial btn-secondary px-1.5 py-0.5 text-[10px]"
                              title="Quitar de la matriz"
                            >
                              QUITAR
                            </button>
                          </div>

                          <div
                            className="h-32 flex items-center justify-center p-2"
                            style={{
                              backgroundColor: "#FFFFFF",
                              border: "1px solid var(--line)",
                            }}
                          >
                            <img
                              src={product.imageUrl}
                              alt={product.name}
                              className="max-h-full max-w-full object-contain"
                              loading="lazy"
                            />
                          </div>

                          <div className="font-cond font-bold text-base leading-tight uppercase">
                            {product.name}
                          </div>
                        </div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--line)] text-xs font-mono-tab">
                  <tr>
                    <td
                      className="p-3.5 font-bold"
                      style={{ backgroundColor: "var(--bg-alt)" }}
                    >
                      CODIGO ASIN / NCM
                    </td>
                    {comparedProducts.map((p) => (
                      <td
                        key={p.id}
                        className="p-3.5 border-l"
                        style={{ borderColor: "var(--line)" }}
                      >
                        {p.asin} · NCM {p.ncmCode}
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td
                      className="p-3.5 font-bold"
                      style={{ backgroundColor: "var(--bg-alt)" }}
                    >
                      VALOR FOB + FLETE
                    </td>
                    {comparedProducts.map((p) => (
                      <td
                        key={p.id}
                        className="p-3.5 border-l"
                        style={{ borderColor: "var(--line)" }}
                      >
                        <strong>{formatUsd(p.priceUsd)}</strong> + {formatUsd(p.shippingUsd)} envío
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td
                      className="p-3.5 font-bold"
                      style={{ backgroundColor: "var(--bg-alt)" }}
                    >
                      IVA ADUANERO AR
                    </td>
                    {comparedProducts.map((p) => (
                      <td
                        key={p.id}
                        className="p-3.5 border-l"
                        style={{ borderColor: "var(--line)" }}
                      >
                        {p.vatRate * 100}% (+{formatUsd(p.courier.vatUsd)}) · Arancel 0%
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td
                      className="p-3.5 font-bold"
                      style={{ backgroundColor: "var(--bg-alt)" }}
                    >
                      TOTAL PUESTO EN AR (MEP)
                    </td>
                    {comparedProducts.map((p) => (
                      <td
                        key={p.id}
                        className="p-3.5 border-l"
                        style={{ borderColor: "var(--line)" }}
                      >
                        <strong
                          className="text-base block"
                          style={{ color: "var(--accent)" }}
                        >
                          {formatArs(p.courier.finalTotalArsMep)}
                        </strong>
                        <span
                          className="text-[11px]"
                          style={{ color: "var(--muted)" }}
                        >
                          ({formatUsd(p.courier.finalTotalUsd)} finales)
                        </span>
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td
                      className="p-3.5 font-bold"
                      style={{ backgroundColor: "var(--bg-alt)" }}
                    >
                      AHORRO VS. CANAL LOCAL
                    </td>
                    {comparedProducts.map((p) => (
                      <td
                        key={p.id}
                        className="p-3.5 border-l font-bold"
                        style={{
                          borderColor: "var(--line)",
                          color: "var(--ok)",
                        }}
                      >
                        Ahorrás {formatArs(p.netSavingsArs)} (-{p.savingsPercent}%)
                      </td>
                    ))}
                  </tr>
                  <tr>
                    <td
                      className="p-3.5 font-bold"
                      style={{ backgroundColor: "var(--bg-alt)" }}
                    >
                      INDICE CALIDAD / PRECIO
                    </td>
                    {comparedProducts.map((p) => (
                      <td
                        key={p.id}
                        className="p-3.5 border-l"
                        style={{ borderColor: "var(--line)" }}
                      >
                        <span className="customs-stamp-ok">
                          {p.scores.calidadPrecio} / 10
                        </span>
                      </td>
                    ))}
                  </tr>
                  {[
                    "Panel / Resolución",
                    "Frecuencia / Respuesta",
                    "Conectividad",
                    "Espacio de Color",
                    "Tensión Eléctrica AR",
                    "Peso Volumétrico",
                  ].map((specKey) => (
                    <tr key={specKey}>
                      <td
                        className="p-3.5 font-bold"
                        style={{ backgroundColor: "var(--bg-alt)" }}
                      >
                        {specKey.toUpperCase()}
                      </td>
                      {comparedProducts.map((p) => (
                        <td
                          key={p.id}
                          className="p-3.5 border-l font-sans"
                          style={{ borderColor: "var(--line)" }}
                        >
                          {p.specs[specKey] || "-"}
                        </td>
                      ))}
                    </tr>
                  ))}
                  <tr>
                    <td
                      className="p-3.5 font-bold"
                      style={{ backgroundColor: "var(--bg-alt)" }}
                    >
                      ACCION DE COMPRA
                    </td>
                    {comparedProducts.map((p) => (
                      <td
                        key={p.id}
                        className="p-3.5 border-l"
                        style={{ borderColor: "var(--line)" }}
                      >
                        <a
                          href={buildAmazonAffiliateUrl(p.asin, p.store)}
                          target="_blank"
                          rel="noopener noreferrer sponsored"
                          className="btn-industrial btn-primary w-full py-2.5 px-3 text-xs"
                        >
                          VER EN AMAZON ({p.store})
                          <ArrowUpRight weight="bold" className="w-3.5 h-3.5" />
                        </a>
                      </td>
                    ))}
                  </tr>
                </tbody>
              </table>
            </div>
          )}
        </section>

        {/* =====================================================================
            MODULO 04: PROTOCOLO OPERATIVO DE IMPORTACION COURIER (ARCA)
           ===================================================================== */}
        <section id="protocolo" className="space-y-6 scroll-mt-24">
          <div className="pb-4 border-b-2 border-[var(--line-strong)]">
            <h2 className="font-cond font-bold text-3xl sm:text-4xl uppercase tracking-tight">
              04 // PROTOCOLO OPERATIVO DE COMPRA Y RECEPCION EN ARGENTINA
            </h2>
            <p className="text-sm mt-1" style={{ color: "var(--muted)" }}>
              Cuatro verificaciones técnicas obligatorias para despachar por Courier Privado sin retenciones aduaneras ni recargos cambiarios.
            </p>
          </div>

          <div
            className="grid md:grid-cols-2 lg:grid-cols-4 divide-y md:divide-y-0 md:divide-x divide-[var(--line)]"
            style={{
              border: "1px solid var(--line-strong)",
              backgroundColor: "var(--surface)",
            }}
          >
            <div className="p-5 space-y-2.5">
              <div className="flex items-center justify-between font-mono-tab text-xs">
                <span className="font-bold" style={{ color: "var(--accent)" }}>
                  PASO 01 / ARCA
                </span>
                <span style={{ color: "var(--muted)" }}>OBLIGATORIO</span>
              </div>
              <h3 className="font-cond font-bold text-xl uppercase">
                CLAVE FISCAL NIVEL 3 Y DOMICILIO ELECTRONICO
              </h3>
              <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                Antes de comprar, verificá en la web de ARCA (ex AFIP) que tenés tu CUIT/CUIL con Clave Fiscal Nivel 3 y el Domicilio Fiscal Electrónico adherido. El courier (DHL/UPS/FedEx) declara el despacho a tu CUIL de forma automática.
              </p>
            </div>

            <div className="p-5 space-y-2.5">
              <div className="flex items-center justify-between font-mono-tab text-xs">
                <span className="font-bold" style={{ color: "var(--accent)" }}>
                  PASO 02 / VOLTAJE Y ORIGEN
                </span>
                <span style={{ color: "var(--muted)" }}>220V AR</span>
              </div>
              <h3 className="font-cond font-bold text-xl uppercase">
                MULTIVOLTAJE EN EE.UU. O 220V NATIVO EN ESPAÑA
              </h3>
              <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                En tecnología (monitores, Mini PCs, cargadores GaN) las fuentes son 100-240V y podés comprar en Amazon.com sin problema. En electrodomésticos con motor o resistencia (cafeteras, aspiradoras), comprá siempre en Amazon España (.es) para recibir 220V 50Hz nativos.
              </p>
            </div>

            <div className="p-5 space-y-2.5">
              <div className="flex items-center justify-between font-mono-tab text-xs">
                <span className="font-bold" style={{ color: "var(--accent)" }}>
                  PASO 03 / LIQUIDACION MEP
                </span>
                <span style={{ color: "var(--ok)" }}>AHORRO -{mepVsTarjetaGap}%</span>
              </div>
              <h3 className="font-cond font-bold text-xl uppercase">
                STOP DEBIT Y PAGO DE RESUMEN EN DOLARES
              </h3>
              <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                No pagues en pesos al tipo de cambio Dólar Tarjeta. Comprá Dólar MEP en tu broker o banco, hacé Stop Debit del débito automático entre el cierre y el vencimiento, y aboná el saldo en dólares con tus USD en cuenta (o usá tarjeta prepaga en USD).
              </p>
            </div>

            <div className="p-5 space-y-2.5">
              <div className="flex items-center justify-between font-mono-tab text-xs">
                <span className="font-bold" style={{ color: "var(--accent)" }}>
                  PASO 04 / RECEPCION
                </span>
                <span style={{ color: "var(--muted)" }}>CUPO 5/AÑO</span>
              </div>
              <h3 className="font-cond font-bold text-xl uppercase">
                ENTREGA EN DOMICILIO SIN TRAMITE EN CORREO
              </h3>
              <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                A diferencia del Correo Argentino puerta a puerta, en Courier Privado no tenés que hacer declaración jurada ni pagar VEP. El camión de DHL, UPS o FedEx te entrega la caja en tu casa en 5 a 9 días hábiles.
              </p>
            </div>
          </div>
        </section>
      </main>

      {/* =====================================================================
          PIE DE PAGINA ESTRUCTURAL Y CUMPLIMIENTO LEGAL
         ===================================================================== */}
      <footer
        style={{
          backgroundColor: "var(--bg-alt)",
          borderTop: "2px solid var(--line-strong)",
        }}
      >
        <div className="shell-container py-10 space-y-8">
          <div className="grid md:grid-cols-12 gap-8">
            <div className="md:col-span-5 space-y-3">
              <div className="flex items-center gap-3">
                <img
                  src="/favicon.svg"
                  alt="Sello FRANQUICIA 400"
                  className="w-9 h-9"
                />
                <div>
                  <span className="font-cond font-bold text-xl uppercase block leading-none">
                    FRANQUICIA 400 · KNUNET
                  </span>
                  <span
                    className="font-mono-tab text-[11px]"
                    style={{ color: "var(--muted)" }}
                  >
                    ofertas.knunet.com · Nodo de telemetría comercial
                  </span>
                </div>
              </div>
              <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                {AFFILIATE_CONFIG.amazonDisclosureShort}
              </p>
              <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                {AFFILIATE_CONFIG.priceDisclaimer}
              </p>
            </div>

            <div className="md:col-span-4 space-y-2.5">
              <span className="font-cond font-bold uppercase text-sm tracking-wider block">
                PLIEGOS LEGALES Y TRANSPARENCIA
              </span>
              <ul className="space-y-1.5 text-xs font-mono-tab list-none p-0 m-0">
                <li>
                  <button
                    type="button"
                    onClick={() => setActiveLegalDoc("afiliados")}
                    className="underline cursor-pointer bg-transparent border-0 p-0 text-left"
                    style={{ color: "var(--ink)" }}
                  >
                    01. Divulgación de Afiliados de Amazon (Operating Agreement)
                  </button>
                </li>
                <li>
                  <button
                    type="button"
                    onClick={() => setActiveLegalDoc("privacidad")}
                    className="underline cursor-pointer bg-transparent border-0 p-0 text-left"
                    style={{ color: "var(--ink)" }}
                  >
                    02. Política de Privacidad y Protección de Datos (Ley 25.326)
                  </button>
                </li>
                <li>
                  <button
                    type="button"
                    onClick={() => setActiveLegalDoc("cookies")}
                    className="underline cursor-pointer bg-transparent border-0 p-0 text-left"
                    style={{ color: "var(--ink)" }}
                  >
                    03. Política de Cookies y Almacenamiento Local
                  </button>
                </li>
                <li>
                  <button
                    type="button"
                    onClick={() => setActiveLegalDoc("terminos")}
                    className="underline cursor-pointer bg-transparent border-0 p-0 text-left"
                    style={{ color: "var(--ink)" }}
                  >
                    04. Términos de Uso y Reglas del Simulador Courier
                  </button>
                </li>
              </ul>
            </div>

            <div className="md:col-span-3 space-y-3">
              <span className="font-cond font-bold uppercase text-sm tracking-wider block">
                CONTROLES DE PRIVACIDAD Y RED
              </span>
              <div className="space-y-2">
                <button
                  type="button"
                  onClick={() => {
                    setCookieConsent((prev) => ({ ...prev, decided: false }));
                    setShowCookieConfig(true);
                  }}
                  className="btn-industrial btn-secondary w-full py-2 px-3 text-xs justify-start"
                >
                  <Cookie weight="bold" className="w-4 h-4" />
                  CONFIGURAR PREFERENCIAS DE COOKIES
                </button>

                <a
                  href={AFFILIATE_CONFIG.parentUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="btn-industrial btn-secondary w-full py-2 px-3 text-xs justify-start"
                >
                  <TerminalWindow weight="bold" className="w-4 h-4" />
                  SISTEMA CENTRAL KNUNET.COM
                </a>
              </div>
            </div>
          </div>

          <div
            className="pt-6 border-t flex flex-wrap items-center justify-between gap-4 text-[11px] font-mono-tab"
            style={{ borderColor: "var(--line)", color: "var(--muted)" }}
          >
            <span>
              © {new Date().getFullYear()} FRANQUICIA 400 · KNUNET. TODOS LOS DERECHOS RESERVADOS.
            </span>
            <span>
              DATOS CAMBIARIOS: DOLARAPI.COM · NORMATIVA REFERENCIA: DECRETO 1065/2024 Y RG ARCA 5617/2024.
            </span>
          </div>
        </div>
      </footer>

      {/* =====================================================================
          MODAL DE INSPECCION TECNICA DE PRODUCTO
         ===================================================================== */}
      {inspectedProduct && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="modal-product-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
          style={{ backgroundColor: "rgba(17, 12, 8, 0.82)" }}
          onClick={() => setInspectedProduct(null)}
        >
          <div
            className="modal-sheet w-full max-w-3xl max-h-[90vh] overflow-y-auto"
            style={{
              backgroundColor: "var(--surface)",
              border: "2px solid var(--line-strong)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Cabecera del Modal */}
            <div
              className="p-4 sm:p-5 flex items-start justify-between gap-4 sticky top-0 z-10"
              style={{
                backgroundColor: "var(--bg-alt)",
                borderBottom: "1px solid var(--line-strong)",
              }}
            >
              <div>
                <div className="flex flex-wrap items-center gap-2 font-mono-tab text-xs">
                  <span className="customs-stamp">{inspectedProduct.stamp}</span>
                  <span style={{ color: "var(--muted)" }}>
                    ASIN: <strong>{inspectedProduct.asin}</strong> · NCM:{" "}
                    <strong>{inspectedProduct.ncmCode}</strong>
                  </span>
                </div>
                <h2
                  id="modal-product-title"
                  className="font-cond font-bold text-2xl sm:text-3xl uppercase mt-1.5 leading-tight"
                >
                  {inspectedProduct.name}
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setInspectedProduct(null)}
                aria-label="Cerrar pliego técnico"
                className="btn-industrial btn-secondary p-2"
              >
                <X weight="bold" className="w-5 h-5" />
              </button>
            </div>

            {/* Cuerpo del Pliego Técnico */}
            <div className="p-5 sm:p-6 space-y-6">
              <div className="grid sm:grid-cols-12 gap-5 items-center">
                <div
                  className="sm:col-span-5 h-52 flex items-center justify-center p-4"
                  style={{
                    backgroundColor: "#FFFFFF",
                    border: "1px solid var(--line)",
                  }}
                >
                  <img
                    src={inspectedProduct.imageUrl}
                    alt={inspectedProduct.name}
                    className="max-h-full max-w-full object-contain"
                  />
                </div>

                <div className="sm:col-span-7 space-y-3">
                  <div
                    className="p-3.5 text-xs space-y-1.5"
                    style={{
                      backgroundColor: "var(--bg)",
                      border: "1px solid var(--line)",
                    }}
                  >
                    <span
                      className="font-mono-tab font-bold uppercase block"
                      style={{ color: "var(--accent)" }}
                    >
                      PERFIL DE USO RECOMENDADO
                    </span>
                    <p style={{ color: "var(--ink)" }}>
                      {inspectedProduct.idealProfile}
                    </p>
                  </div>

                  {/* Barras de Evaluación Técnica */}
                  <div className="grid grid-cols-2 gap-2.5 font-mono-tab text-xs">
                    {[
                      {
                        label: "Calidad / Precio",
                        val: inspectedProduct.scores.calidadPrecio,
                      },
                      {
                        label: "Rendimiento Técnico",
                        val: inspectedProduct.scores.rendimiento,
                      },
                      {
                        label: "Construcción / Chasis",
                        val: inspectedProduct.scores.construccion,
                      },
                      {
                        label: "Brecha vs. Local AR",
                        val: inspectedProduct.scores.ahorroVsLocal,
                      },
                    ].map((metric) => (
                      <div
                        key={metric.label}
                        className="p-2.5"
                        style={{
                          backgroundColor: "var(--bg-alt)",
                          border: "1px solid var(--line)",
                        }}
                      >
                        <div className="flex justify-between text-[11px] mb-1">
                          <span>{metric.label}</span>
                          <strong>{metric.val}/10</strong>
                        </div>
                        <div
                          className="h-1.5 w-full"
                          style={{ backgroundColor: "var(--line)" }}
                        >
                          <div
                            className="h-full"
                            style={{
                              width: `${metric.val * 10}%`,
                              backgroundColor: "var(--accent)",
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Pros y Contras */}
              <div className="grid sm:grid-cols-2 gap-4">
                <div
                  className="p-4 space-y-2.5"
                  style={{
                    backgroundColor: "var(--ok-bg)",
                    border: "1px solid var(--ok)",
                  }}
                >
                  <span
                    className="font-cond font-bold uppercase text-sm tracking-wider block"
                    style={{ color: "var(--ok)" }}
                  >
                    PUNTOS FUERTES VERIFICADOS
                  </span>
                  <ul className="space-y-1.5 text-xs list-none p-0 m-0">
                    {inspectedProduct.pros.map((pro) => (
                      <li key={pro} className="flex items-start gap-2">
                        <Check
                          weight="bold"
                          className="w-4 h-4 shrink-0 mt-0.5"
                          style={{ color: "var(--ok)" }}
                        />
                        <span>{pro}</span>
                      </li>
                    ))}
                  </ul>
                </div>

                <div
                  className="p-4 space-y-2.5"
                  style={{
                    backgroundColor: "var(--warn-bg)",
                    border: "1px solid var(--warn)",
                  }}
                >
                  <span
                    className="font-cond font-bold uppercase text-sm tracking-wider block"
                    style={{ color: "var(--warn)" }}
                  >
                    LIMITACIONES A CONSIDERAR
                  </span>
                  <ul className="space-y-1.5 text-xs list-none p-0 m-0">
                    {inspectedProduct.cons.map((con) => (
                      <li key={con} className="flex items-start gap-2">
                        <WarningOctagon
                          weight="bold"
                          className="w-4 h-4 shrink-0 mt-0.5"
                          style={{ color: "var(--warn)" }}
                        />
                        <span>{con}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              {/* Tabla de Especificaciones de Placa */}
              <div
                style={{
                  border: "1px solid var(--line-strong)",
                  backgroundColor: "var(--bg)",
                }}
              >
                <div
                  className="px-4 py-2 font-cond font-bold uppercase text-sm"
                  style={{
                    backgroundColor: "var(--bg-alt)",
                    borderBottom: "1px solid var(--line)",
                  }}
                >
                  ESPECIFICACIONES TECNICAS Y ELECTRICAS
                </div>
                <div className="grid sm:grid-cols-2 divide-y sm:divide-y-0 sm:divide-x divide-[var(--line)] text-xs">
                  {Object.entries(inspectedProduct.specs).map(([k, v]) => (
                    <div
                      key={k}
                      className="p-3 flex justify-between gap-3 border-b"
                      style={{ borderColor: "var(--line)" }}
                    >
                      <span
                        className="font-mono-tab"
                        style={{ color: "var(--muted)" }}
                      >
                        {k}:
                      </span>
                      <strong className="text-right">{v}</strong>
                    </div>
                  ))}
                </div>
              </div>

              {/* Pie de Acción del Modal */}
              <div className="flex flex-col sm:flex-row gap-3 pt-2">
                <a
                  href={buildAmazonAffiliateUrl(
                    inspectedProduct.asin,
                    inspectedProduct.store
                  )}
                  target="_blank"
                  rel="noopener noreferrer sponsored"
                  className="btn-industrial btn-primary flex-1 py-3 px-4 text-sm"
                >
                  INSPECCIONAR OFERTA EN AMAZON.{inspectedProduct.store === "ES" ? "ES" : "COM"} (
                  {formatUsd(inspectedProduct.priceUsd)} FOB)
                  <ArrowUpRight weight="bold" className="w-4 h-4" />
                </a>
                <button
                  type="button"
                  onClick={() => {
                    loadProductIntoSimulator(inspectedProduct);
                    setInspectedProduct(null);
                  }}
                  className="btn-industrial btn-secondary py-3 px-4 text-xs"
                >
                  <Calculator weight="bold" className="w-4 h-4" />
                  ABRIR EN SIMULADOR ADUANA
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* =====================================================================
          MODAL DE PLIEGOS LEGALES (AFILIADOS / PRIVACIDAD / COOKIES / TERMINOS)
         ===================================================================== */}
      {activeLegalDoc && (
        <div
          role="dialog"
          aria-modal="true"
          aria-labelledby="modal-legal-title"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 overflow-y-auto"
          style={{ backgroundColor: "rgba(17, 12, 8, 0.82)" }}
          onClick={() => setActiveLegalDoc(null)}
        >
          <div
            className="modal-sheet w-full max-w-3xl max-h-[90vh] overflow-y-auto"
            style={{
              backgroundColor: "var(--surface)",
              border: "2px solid var(--line-strong)",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Cabecera del Pliego Legal */}
            <div
              className="p-4 sm:p-5 flex items-start justify-between gap-4 sticky top-0 z-10"
              style={{
                backgroundColor: "var(--bg-alt)",
                borderBottom: "1px solid var(--line-strong)",
              }}
            >
              <div>
                <span className="customs-stamp">
                  {LEGAL_DOCUMENTS[activeLegalDoc].code}
                </span>
                <h2
                  id="modal-legal-title"
                  className="font-cond font-bold text-2xl sm:text-3xl uppercase mt-1.5"
                >
                  {LEGAL_DOCUMENTS[activeLegalDoc].title}
                </h2>
                <p
                  className="font-mono-tab text-[11px] mt-0.5"
                  style={{ color: "var(--muted)" }}
                >
                  Última actualización: {LEGAL_DOCUMENTS[activeLegalDoc].updatedAt}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setActiveLegalDoc(null)}
                aria-label="Cerrar documento legal"
                className="btn-industrial btn-secondary p-2"
              >
                <X weight="bold" className="w-5 h-5" />
              </button>
            </div>

            {/* Selector rápido entre los 4 documentos legales */}
            <div
              className="px-5 py-2.5 flex flex-wrap gap-1.5 border-b"
              style={{
                backgroundColor: "var(--bg)",
                borderColor: "var(--line)",
              }}
            >
              {(["afiliados", "privacidad", "cookies", "terminos"] as LegalDocId[]).map(
                (docId) => (
                  <button
                    key={docId}
                    type="button"
                    onClick={() => setActiveLegalDoc(docId)}
                    className={`btn-industrial px-2.5 py-1 text-xs ${
                      activeLegalDoc === docId ? "btn-primary" : "btn-secondary"
                    }`}
                  >
                    {LEGAL_DOCUMENTS[docId].title}
                  </button>
                )
              )}
            </div>

            {/* Contenido del Pliego */}
            <div className="p-5 sm:p-6 space-y-5 text-sm leading-relaxed">
              <p
                className="p-3.5 font-mono-tab text-xs"
                style={{
                  backgroundColor: "var(--bg-alt)",
                  border: "1px solid var(--line)",
                  color: "var(--muted)",
                }}
              >
                {LEGAL_DOCUMENTS[activeLegalDoc].subtitle}
              </p>

              {LEGAL_DOCUMENTS[activeLegalDoc].sections.map((section) => (
                <div key={section.heading} className="space-y-2">
                  <h3 className="font-cond font-bold text-xl uppercase">
                    {section.heading}
                  </h3>
                  {section.paragraphs.map((p, idx) => (
                    <p key={idx} style={{ color: "var(--muted)" }}>
                      {p}
                    </p>
                  ))}
                  {section.bullets && (
                    <ul className="space-y-1.5 pl-5 text-xs" style={{ color: "var(--ink)" }}>
                      {section.bullets.map((b) => (
                        <li key={b}>{b}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* =====================================================================
          BANNER INDUSTRIAL DE CONSENTIMIENTO DE COOKIES Y ALMACENAMIENTO LOCAL
         ===================================================================== */}
      {!cookieConsent.decided && (
        <aside
          aria-label="Preferencias de cookies y almacenamiento local"
          className="fixed bottom-0 left-0 right-0 z-40 p-3 sm:p-4"
        >
          <div
            className="shell-container p-4 sm:p-5 shadow-2xl"
            style={{
              backgroundColor: "var(--surface)",
              border: "2px solid var(--line-strong)",
            }}
          >
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
              <div className="space-y-1.5 max-w-3xl">
                <div className="flex items-center gap-2">
                  <span className="customs-stamp">
                    CONTROL DE ALMACENAMIENTO LOCAL Y ATRIBUCION
                  </span>
                  <span className="font-mono-tab text-[11px]" style={{ color: "var(--muted)" }}>
                    LEY 25.326 + RGPD
                  </span>
                </div>
                <p className="text-xs leading-relaxed" style={{ color: "var(--muted)" }}>
                  Usamos almacenamiento local (<code className="font-mono-tab">localStorage</code>) para guardar tu tema visual y la matriz comparativa. Cuando pulsás un enlace hacia Amazon, Amazon registra en su propio dominio una cookie de atribución de afiliado de 24 horas. No usamos píxeles publicitarios de terceros.{" "}
                  <button
                    type="button"
                    onClick={() => setActiveLegalDoc("cookies")}
                    className="underline cursor-pointer bg-transparent border-0 p-0 text-xs"
                    style={{ color: "var(--accent)" }}
                  >
                    Leer pliego de cookies
                  </button>
                  .
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2 shrink-0">
                <button
                  type="button"
                  onClick={() => setShowCookieConfig((prev) => !prev)}
                  className="btn-industrial btn-secondary px-3 py-2 text-xs"
                >
                  <SlidersHorizontal weight="bold" className="w-3.5 h-3.5" />
                  {showCookieConfig ? "OCULTAR DETALLE" : "CONFIGURAR"}
                </button>
                <button
                  type="button"
                  onClick={() =>
                    saveCookieDecision({
                      ...cookieConsent,
                      analytics: false,
                      affiliateAttribution: true,
                    })
                  }
                  className="btn-industrial btn-secondary px-3.5 py-2 text-xs"
                >
                  SOLO ESENCIALES
                </button>
                <button
                  type="button"
                  onClick={() =>
                    saveCookieDecision({
                      ...cookieConsent,
                      analytics: true,
                      affiliateAttribution: true,
                    })
                  }
                  className="btn-industrial btn-primary px-4 py-2 text-xs"
                >
                  <Check weight="bold" className="w-3.5 h-3.5" />
                  ACEPTAR Y CONTINUAR
                </button>
              </div>
            </div>

            {showCookieConfig && (
              <div
                className="mt-4 pt-4 border-t grid sm:grid-cols-3 gap-3 text-xs font-mono-tab"
                style={{ borderColor: "var(--line)" }}
              >
                <div
                  className="p-3"
                  style={{
                    backgroundColor: "var(--bg)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <div className="flex items-center justify-between font-bold">
                    <span>1. TECNICAS NECESARIAS</span>
                    <span style={{ color: "var(--ok)" }}>SIEMPRE ACTIVAS</span>
                  </div>
                  <p className="mt-1 text-[11px] font-sans" style={{ color: "var(--muted)" }}>
                    Guardan el tema elegido (Manifiesto/HUD), los ítems del comparador y esta preferencia.
                  </p>
                </div>

                <label
                  className="p-3 cursor-pointer block"
                  style={{
                    backgroundColor: "var(--bg)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <div className="flex items-center justify-between font-bold">
                    <span>2. ANALITICA ANONIMA</span>
                    <input
                      type="checkbox"
                      checked={cookieConsent.analytics}
                      onChange={(e) =>
                        setCookieConsent((prev) => ({
                          ...prev,
                          analytics: e.target.checked,
                        }))
                      }
                    />
                  </div>
                  <p className="mt-1 text-[11px] font-sans" style={{ color: "var(--muted)" }}>
                    Telemetría propia (Umami KnuNet) sin cookies de seguimiento cruzado ni cesión a terceros.
                  </p>
                </label>

                <div
                  className="p-3"
                  style={{
                    backgroundColor: "var(--bg)",
                    border: "1px solid var(--line)",
                  }}
                >
                  <div className="flex items-center justify-between font-bold">
                    <span>3. ATRIBUCION EN SALIDA</span>
                    <span style={{ color: "var(--accent)" }}>AL CLICKEAR AMAZON</span>
                  </div>
                  <p className="mt-1 text-[11px] font-sans" style={{ color: "var(--muted)" }}>
                    Se activa únicamente en el dominio de Amazon cuando decidís abrir una oferta externa.
                  </p>
                </div>
              </div>
            )}
          </div>
        </aside>
      )}
    </div>
  );
}
