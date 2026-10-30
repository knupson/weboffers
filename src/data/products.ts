export type ProductCategory =
  | "Monitores"
  | "Mini PCs & Cómputo"
  | "Almacenamiento & Periféricos"
  | "Audio & VR"
  | "Café & Domótica 220V";

export interface OfferProduct {
  id: string;
  slug: string;
  asin: string;
  ncmCode: string;
  store: "US" | "ES";
  name: string;
  brand: string;
  category: ProductCategory;
  stamp: string;
  priceUsd: number;
  previousPriceUsd: number;
  shippingUsd: number;
  vatRate: 0.105 | 0.21;
  localArgentinaPriceArs: number;
  localReferenceSource: string;
  commissionRate: number;
  rating: number;
  reviewsCount: number;
  imageUrl: string;
  voltageSpec: string;
  weightKg: string;
  shortSummary: string;
  idealProfile: string;
  scores: {
    calidadPrecio: number;
    rendimiento: number;
    construccion: number;
    ahorroVsLocal: number;
  };
  pros: string[];
  cons: string[];
  specs: Record<string, string>;
  updatedAt: string;
}

export const PRODUCTS_DATA: OfferProduct[] = [
  {
    id: "asus-tuf-vg27aq3a",
    slug: "asus-tuf-gaming-27-qhd-180hz",
    asin: "B0BZR9F1V9",
    ncmCode: "8528.52.20",
    store: "US",
    name: "ASUS TUF Gaming 27\" QHD (VG27AQ3A) 180Hz Fast IPS",
    brand: "ASUS",
    category: "Monitores",
    stamp: "ARANCEL 0% · IVA 10,5%",
    priceUsd: 219,
    previousPriceUsd: 269,
    shippingUsd: 48,
    vatRate: 0.105,
    localArgentinaPriceArs: 695000,
    localReferenceSource: "Retailers AR / Hardgamers",
    commissionRate: 0.03,
    rating: 4.7,
    reviewsCount: 3420,
    imageUrl: "/products/asus-tuf-vg27aq3a.jpg",
    voltageSpec: "100-240V 50/60Hz (Directo a 220V)",
    weightKg: "6,1 kg",
    shortSummary:
      "Monitor QHD 1440p de 27 pulgadas con panel Fast IPS a 180Hz reales, 1ms GTG y validación G-Sync Compatible. Uno de los modelos con mayor brecha de precio frente al canal local.",
    idealProfile:
      "Escritorios de desarrollo y gaming competitivo que buscan saltar de 1080p a 1440p a 180Hz pagando menos de la mitad que en tiendas locales.",
    scores: {
      calidadPrecio: 9.7,
      rendimiento: 9.4,
      construccion: 9.0,
      ahorroVsLocal: 9.8,
    },
    pros: [
      "Tributa únicamente 10,5% de IVA bajo franquicia de USD 400 FOB",
      "Panel Fast IPS QHD (2560x1440) a 180Hz con ELMB Sync y Variable Overdrive",
      "Fuente conmutada 100-240V automática: se enchufa directo en Argentina sin transformador",
    ],
    cons: [
      "Base de fábrica con regulación de inclinación y giro pero sin ajuste de altura (admite brazo VESA 100x100)",
      "Brillo pico de 250 nits pensado para uso en interiores controlados",
    ],
    specs: {
      "Panel / Resolución": "27\" Fast IPS · 2560x1440 (QHD)",
      "Frecuencia / Respuesta": "180 Hz nativos · 1 ms (GTG)",
      "Conectividad": "2x HDMI 2.0, 1x DisplayPort 1.4, Salida 3.5mm",
      "Espacio de Color": "130% sRGB · 96% DCI-P3 · G-Sync Compatible",
      "Tensión Eléctrica AR": "100-240V Automático (Directo a 220V)",
      "Peso Volumétrico": "6,1 kg (Caja AmazonGlobal)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "aoc-q27g3xmn-miniled",
    slug: "aoc-q27g3xmn-27-qhd-miniled-hdr1000",
    asin: "B0C8Z6823P",
    ncmCode: "8528.52.20",
    store: "US",
    name: "AOC Q27G3XMN 27\" QHD Mini-LED 180Hz (336 Zonas · DisplayHDR 1000)",
    brand: "AOC",
    category: "Monitores",
    stamp: "MINI-LED REAL · IVA 10,5%",
    priceUsd: 279,
    previousPriceUsd: 319,
    shippingUsd: 54,
    vatRate: 0.105,
    localArgentinaPriceArs: 890000,
    localReferenceSource: "Importadores locales / ML",
    commissionRate: 0.03,
    rating: 4.6,
    reviewsCount: 1940,
    imageUrl: "/products/aoc-q27g3xmn-miniled.jpg",
    voltageSpec: "100-240V 50/60Hz (Directo a 220V)",
    weightKg: "7,2 kg",
    shortSummary:
      "Retroiluminación Mini-LED de matriz completa (FALD de 336 zonas) con certificación VESA DisplayHDR 1000 real y picos de 1200 nits. Inconseguible en el mercado argentino a este rango.",
    idealProfile:
      "Jugadores de títulos single-player HDR y creadores que buscan contraste cercano a OLED sin riesgo de quemado (burn-in) para trabajar 10 horas por día.",
    scores: {
      calidadPrecio: 9.8,
      rendimiento: 9.7,
      construccion: 9.1,
      ahorroVsLocal: 9.7,
    },
    pros: [
      "HDR verdadero de 1000+ nits con atenuación local en 336 zonas independientes",
      "Contraste nativo 4500:1 que sube a más de 40.000:1 con Local Dimming activo",
      "Base ergonómica completa con regulación de altura, giro y modo vertical (Pivot)",
    ],
    cons: [
      "Ángulos de visión laterales más acotados que en un panel IPS tradicional",
      "Menú OSD con botonera física inferior en lugar de joystick",
    ],
    specs: {
      "Panel / Resolución": "27\" Fast VA Mini-LED (336 zonas) · 2560x1440",
      "Frecuencia / Respuesta": "180 Hz · 1 ms GTG · Adaptive-Sync",
      "Conectividad": "2x HDMI 2.0, 1x DisplayPort 1.4",
      "Espacio de Color": "VESA DisplayHDR 1000 (1200 nits pico) · 99% sRGB",
      "Tensión Eléctrica AR": "100-240V Automático (Fuente interna)",
      "Peso Volumétrico": "7,2 kg (Caja AmazonGlobal)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "lg-ultragear-27gp850",
    slug: "lg-ultragear-27-nano-ips-qhd-180hz",
    asin: "B093MTSTKD",
    ncmCode: "8528.52.20",
    store: "US",
    name: "LG UltraGear 27\" QHD Nano IPS (27GP850-B) 180Hz 1ms",
    brand: "LG",
    category: "Monitores",
    stamp: "CALIBRADO NANO IPS",
    priceUsd: 249,
    previousPriceUsd: 329,
    shippingUsd: 52,
    vatRate: 0.105,
    localArgentinaPriceArs: 785000,
    localReferenceSource: "Tiendas oficiales AR",
    commissionRate: 0.03,
    rating: 4.8,
    reviewsCount: 5190,
    imageUrl: "/products/lg-ultragear-27gp850.jpg",
    voltageSpec: "100-240V 50/60Hz (Directo a 220V)",
    weightKg: "6,8 kg",
    shortSummary:
      "Panel Nano IPS de LG Display con cobertura del 98% del espectro DCI-P3, hub USB 3.0 integrado y columna regulable en altura y rotación.",
    idealProfile:
      "Diseño gráfico, edición de video y gaming donde se priorizan ángulos de visión perfectos y fidelidad cromática de fábrica.",
    scores: {
      calidadPrecio: 9.4,
      rendimiento: 9.5,
      construccion: 9.5,
      ahorroVsLocal: 9.5,
    },
    pros: [
      "Columna ergonómica completa: regula altura (110mm), inclinación y rotación a 90 grados",
      "Cobertura de color 98% DCI-P3 con calibración de fábrica verificada",
      "Hub USB 3.0 de dos puertos integrado en el chasis trasero",
    ],
    cons: [
      "Contraste nativo típico de tecnología IPS (~1000:1)",
      "Patas en V profundas (conviene usar con brazo VESA en escritorios de menos de 60cm)",
    ],
    specs: {
      "Panel / Resolución": "27\" Nano IPS · 2560x1440 (QHD)",
      "Frecuencia / Respuesta": "165 Hz nativos (180 Hz OC) · 1 ms GtG",
      "Conectividad": "2x HDMI 2.0, 1x DP 1.4, Hub 2x USB 3.0",
      "Espacio de Color": "98% DCI-P3 · 10-bit (8-bit + FRC) · G-Sync",
      "Tensión Eléctrica AR": "100-240V Automático (Directo a 220V)",
      "Peso Volumétrico": "6,8 kg (Caja AmazonGlobal)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "beelink-ser5-max-ryzen7",
    slug: "mini-pc-beelink-ser5-max-ryzen-7-32gb-1tb",
    asin: "B0C2P486S4",
    ncmCode: "8471.50.10",
    store: "US",
    name: "Beelink SER5 MAX Mini PC AMD Ryzen 7 5800H (32GB RAM + 1TB NVMe)",
    brand: "Beelink",
    category: "Mini PCs & Cómputo",
    stamp: "FLETE MINIMO · IVA 10,5%",
    priceUsd: 329,
    previousPriceUsd: 409,
    shippingUsd: 24,
    vatRate: 0.105,
    localArgentinaPriceArs: 920000,
    localReferenceSource: "Importadores locales / ML",
    commissionRate: 0.04,
    rating: 4.6,
    reviewsCount: 2140,
    imageUrl: "/products/beelink-ser5-max-ryzen7.jpg",
    voltageSpec: "100-240V 50/60Hz (Directo a 220V)",
    weightKg: "0,95 kg",
    shortSummary:
      "Workstation compacta de 8 núcleos y 16 hilos (TDP optimizado a 54W) con 32GB de RAM y 1TB SSD PCIe preinstalados. Al pesar menos de 1 kilo paga un flete internacional mínimo.",
    idealProfile:
      "Programadores, laboratorios domésticos (Proxmox, Docker, Home Assistant) y puestos de trabajo multipantalla que buscan silencio y bajo consumo.",
    scores: {
      calidadPrecio: 9.8,
      rendimiento: 9.5,
      construccion: 9.2,
      ahorroVsLocal: 9.9,
    },
    pros: [
      "Caja de menos de 1 kg: el costo de envío puerta a puerta desde EE.UU. es de apenas USD 24",
      "Incluye 32GB de RAM en doble canal y SSD NVMe de 1TB listos para arrancar",
      "Soporta hasta 3 monitores 4K a 60Hz en simultáneo (HDMI + DisplayPort + USB-C)",
    ],
    cons: [
      "Memoria DDR4 3200MHz (si buscás DDR5 y gráficos RDNA3, mirá el GMKtec K6)",
    ],
    specs: {
      "Panel / Resolución": "Salida triple pantalla 4K@60Hz (HDMI + DP + USB-C)",
      "Frecuencia / Respuesta": "AMD Ryzen 7 5800H (8C/16T hasta 4.4 GHz · 54W TDP)",
      "Conectividad": "3x USB 3.2, 1x USB 2.0, USB-C datos/video, LAN Gigabit, WiFi 6",
      "Espacio de Color": "32GB RAM SO-DIMM Dual Channel + 1TB M.2 PCIe NVMe",
      "Tensión Eléctrica AR": "Fuente externa 100-240V 19V (Directo a 220V)",
      "Peso Volumétrico": "0,95 kg (Caja compacta)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "gmktec-nucbox-k6-ryzen7",
    slug: "mini-pc-gmktec-nucbox-k6-ryzen-7-7840hs-ddr5",
    asin: "B0CQ4W8B2J",
    ncmCode: "8471.50.10",
    store: "US",
    name: "GMKtec NucBox K6 AMD Ryzen 7 7840HS (32GB DDR5 + 1TB PCIe 4.0)",
    brand: "GMKtec",
    category: "Mini PCs & Cómputo",
    stamp: "TOPE FRANQUICIA · RADEON 780M",
    priceUsd: 389,
    previousPriceUsd: 479,
    shippingUsd: 26,
    vatRate: 0.105,
    localArgentinaPriceArs: 1190000,
    localReferenceSource: "Importadores locales / ML",
    commissionRate: 0.04,
    rating: 4.7,
    reviewsCount: 890,
    imageUrl: "/products/gmktec-nucbox-k6-ryzen7.jpg",
    voltageSpec: "100-240V 50/60Hz (Directo a 220V)",
    weightKg: "1,10 kg",
    shortSummary:
      "Al filo exacto de los USD 400 FOB libres de arancel: arquitectura Zen 4 (Ryzen 7 7840HS), gráfica integrada Radeon 780M (RDNA3), doble puerto Ethernet 2.5GbE y USB4 de 40 Gbps.",
    idealProfile:
      "Usuarios técnicos que quieren el máximo poder de cómputo posible sin cruzar la barrera de USD 400 FOB para servidores pesados, compilación o gaming 1080p.",
    scores: {
      calidadPrecio: 9.9,
      rendimiento: 9.8,
      construccion: 9.3,
      ahorroVsLocal: 9.9,
    },
    pros: [
      "Queda USD 11 por debajo del límite de USD 400 FOB: ahorrás más de USD 140 de aranceles",
      "Doble placa de red Intel 2.5GbE ideal para virtualización, pfSense/OPNsense o cluster",
      "Puerto USB4 frontal de 40Gbps compatible con placas de video externas (eGPU) y monitores",
    ],
    cons: [
      "En el perfil de BIOS 'Performance (65W)' el ventilador superior se vuelve audible a plena carga",
    ],
    specs: {
      "Panel / Resolución": "GPU AMD Radeon 780M (12 CUs RDNA3 a 2700 MHz)",
      "Frecuencia / Respuesta": "AMD Ryzen 7 7840HS (8C/16T Zen 4 hasta 5.1 GHz)",
      "Conectividad": "USB4 (40Gbps), HDMI 2.0, DP, 2x RJ45 2.5GbE, WiFi 6E",
      "Espacio de Color": "32GB DDR5 5600MHz + 1TB SSD M.2 2280 PCIe 4.0",
      "Tensión Eléctrica AR": "Fuente GaN 100-240V (Directo a 220V)",
      "Peso Volumétrico": "1,10 kg (Caja compacta)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "samsung-990-pro-4tb",
    slug: "ssd-nvme-samsung-990-pro-4tb-pcie-4",
    asin: "B0CHGT1GCM",
    ncmCode: "8523.51.90",
    store: "US",
    name: "Samsung 990 PRO 4TB SSD NVMe M.2 PCIe Gen4 (7450 MB/s)",
    brand: "Samsung",
    category: "Almacenamiento & Periféricos",
    stamp: "CAJA 100G · ENVIO USD 14",
    priceUsd: 299,
    previousPriceUsd: 359,
    shippingUsd: 14,
    vatRate: 0.105,
    localArgentinaPriceArs: 840000,
    localReferenceSource: "Tiendas de hardware AR",
    commissionRate: 0.03,
    rating: 4.8,
    reviewsCount: 8420,
    imageUrl: "/products/samsung-990-pro-4tb.jpg",
    voltageSpec: "Slot M.2 2280 (3.3V bus PCIe)",
    weightKg: "0,12 kg",
    shortSummary:
      "Unidad de estado sólido tope de línea PCIe 4.0 con caché DRAM dedicada y 4TB en diseño de una sola cara (single-sided), apta tanto para PC de escritorio como para notebooks y PS5.",
    idealProfile:
      "Edición de video 4K/8K, bases de datos locales, colecciones de modelos LLM/pesos locales y expansión de notebooks sin sobrecalentamiento.",
    scores: {
      calidadPrecio: 9.6,
      rendimiento: 9.9,
      construccion: 9.8,
      ahorroVsLocal: 9.6,
    },
    pros: [
      "Relación peso-valor imbatible para Courier: paga apenas USD 14 de envío y 10,5% de IVA",
      "Diseño single-sided de 4TB: entra sin problemas en slots M.2 delgados de ultrabooks y Mini PCs",
      "Lectura secuencial de 7450 MB/s y escritura de 6900 MB/s con memoria caché LPDDR4 propia",
    ],
    cons: [
      "Conviene mantener actualizado el firmware mediante Samsung Magician",
    ],
    specs: {
      "Panel / Resolución": "Formato M.2 2280 (Single-Sided) · 4 TB reales",
      "Frecuencia / Respuesta": "Lectura 7.450 MB/s · Escritura 6.900 MB/s",
      "Conectividad": "Interfaz PCIe Gen 4.0 x4 / NVMe 2.0",
      "Espacio de Color": "Controladora Samsung Pascal + 4GB DRAM LPDDR4",
      "Tensión Eléctrica AR": "Alimentación directa por bus M.2",
      "Peso Volumétrico": "0,12 kg (Sobre acolchado AmazonGlobal)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "keychron-q1-max-wireless",
    slug: "teclado-mecanico-keychron-q1-max-qmk-via-aluminio",
    asin: "B0CWV2X9H2",
    ncmCode: "8471.60.52",
    store: "US",
    name: "Keychron Q1 Max QMK/VIA Custom Mechanical Keyboard (Chasis CNC Aluminio)",
    brand: "Keychron",
    category: "Almacenamiento & Periféricos",
    stamp: "CHASIS CNC 6063 · IVA 10,5%",
    priceUsd: 209,
    previousPriceUsd: 229,
    shippingUsd: 31,
    vatRate: 0.105,
    localArgentinaPriceArs: 620000,
    localReferenceSource: "Importadores custom AR",
    commissionRate: 0.04,
    rating: 4.7,
    reviewsCount: 960,
    imageUrl: "/products/keychron-q1-max-wireless.jpg",
    voltageSpec: "Batería 4000mAh / Carga USB-C 5V",
    weightKg: "2,15 kg",
    shortSummary:
      "Teclado mecánico custom formato 75% mecanizado en aluminio 6063 CNC con montaje Double-Gasket, switches Gateron Jupiter intercambiables en caliente (Hot-Swap), dongle 2.4GHz de 1000Hz y programación abierta QMK/VIA.",
    idealProfile:
      "Desarrolladores y entusiastas del tipeo que quieren un chasis macizo de aluminio de casi 2 kilos con firmware abierto QMK/VIA sin aduana comercial.",
    scores: {
      calidadPrecio: 9.5,
      rendimiento: 9.8,
      construccion: 9.9,
      ahorroVsLocal: 9.5,
    },
    pros: [
      "Cuerpo íntegro de aluminio anodizado CNC con acústica amortiguada por 6 capas internas",
      "Conectividad triple: 2.4 GHz (1000 Hz), Bluetooth 5.1 (3 equipos) y USB-C cableado",
      "Configuración de macros y capas en tiempo real desde navegador web con VIA sin instalar software basura",
    ],
    cons: [
      "Por su chasis de aluminio macizo pesa 1,73 kg desnudo: no es un teclado pensado para llevar en mochila",
    ],
    specs: {
      "Panel / Resolución": "Formato 75% (81 teclas + perilla rotativa programable)",
      "Frecuencia / Respuesta": "Polling Rate 1000 Hz (2.4GHz y USB-C) · Hot-Swap 5 pines",
      "Conectividad": "2.4 GHz inalámbrico, Bluetooth 5.1, USB Tipo-C",
      "Espacio de Color": "Keycaps PBT Double-Shot KSA + Switches Gateron Jupiter",
      "Tensión Eléctrica AR": "Carga por USB-C (incluye teclas para Windows y macOS)",
      "Peso Volumétrico": "2,15 kg (Caja completa)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "sony-wh-1000xm5",
    slug: "auriculares-sony-wh-1000xm5-cancelacion-ruido",
    asin: "B09XS7JWHH",
    ncmCode: "8518.30.00",
    store: "US",
    name: "Sony WH-1000XM5 Auriculares Inalámbricos Noise Cancelling (8 Micrófonos)",
    brand: "Sony",
    category: "Audio & VR",
    stamp: "ENVIO USD 18 · REFERENCIA ANC",
    priceUsd: 298,
    previousPriceUsd: 399,
    shippingUsd: 18,
    vatRate: 0.21,
    localArgentinaPriceArs: 790000,
    localReferenceSource: "Sony Store AR / Retailers",
    commissionRate: 0.04,
    rating: 4.7,
    reviewsCount: 11400,
    imageUrl: "/products/sony-wh-1000xm5.jpg",
    voltageSpec: "Carga USB-C PD (5V/9V)",
    weightKg: "0,65 kg",
    shortSummary:
      "Referencia en cancelación activa de ruido con doble procesador Sony QN1 + V1, matriz de 8 micrófonos con filtrado de viento por IA, codec LDAC de alta resolución y conexión Bluetooth multipunto real.",
    idealProfile:
      "Trabajo remoto en ambientes ruidosos, vuelos largos y llamadas técnicas donde el aislamiento de voz es crítico.",
    scores: {
      calidadPrecio: 9.4,
      rendimiento: 9.9,
      construccion: 9.5,
      ahorroVsLocal: 9.6,
    },
    pros: [
      "Supresión de ruido de frecuencias medias y agudas líder del segmento junto con calidad de micrófono en llamadas",
      "Caja liviana (650g): el flete internacional desde EE.UU. cuesta apenas USD 18",
      "Conexión simultánea a 2 dispositivos (por ejemplo, PC de trabajo y teléfono) con cambio automático",
    ],
    cons: [
      "Las copas giran en plano pero la diadema no se pliega hacia adentro como en el modelo XM4",
    ],
    specs: {
      "Panel / Resolución": "Drivers de fibra de carbono de 30mm · Hi-Res Audio LDAC",
      "Frecuencia / Respuesta": "Procesador Dual QN1 + V1 · 8 micrófonos ANC",
      "Conectividad": "Bluetooth 5.2 Multipunto + Cable 3.5mm incluido",
      "Espacio de Color": "Autonomía de 30 hs con ANC (carga rápida: 3 min = 3 hs)",
      "Tensión Eléctrica AR": "Carga universal por puerto USB-C",
      "Peso Volumétrico": "0,65 kg (Estuche rígido plegable incluido)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "meta-quest-3s-128gb",
    slug: "meta-quest-3s-128gb-realidad-mixta",
    asin: "B0D92X9Y5P",
    ncmCode: "9504.50.00",
    store: "US",
    name: "Meta Quest 3S 128GB Visor de Realidad Mixta y Virtual (Snapdragon XR2 Gen 2)",
    brand: "Meta",
    category: "Audio & VR",
    stamp: "SUB-USD 300 · XR2 GEN 2",
    priceUsd: 299,
    previousPriceUsd: 349,
    shippingUsd: 29,
    vatRate: 0.21,
    localArgentinaPriceArs: 860000,
    localReferenceSource: "Importadores VR Argentina",
    commissionRate: 0.04,
    rating: 4.8,
    reviewsCount: 4120,
    imageUrl: "/products/meta-quest-3s-128gb.jpg",
    voltageSpec: "Cargador USB-C 100-240V incluido",
    weightKg: "1,15 kg",
    shortSummary:
      "Integra exactamente el mismo procesador Qualcomm Snapdragon XR2 Gen 2, 8GB de RAM, passthrough a todo color y mandos Touch Plus del Quest 3, pero a USD 299 FOB para entrar holgado en la franquicia sin arancel.",
    idealProfile:
      "Simulación (Assetto Corsa, MSFS, iRacing vía PCVR), juegos autónomos sin cables y escritorio virtual de 3 pantallas gigantes.",
    scores: {
      calidadPrecio: 9.8,
      rendimiento: 9.7,
      construccion: 9.4,
      ahorroVsLocal: 9.7,
    },
    pros: [
      "Mismo chip gráfico XR2 Gen 2 (doble de potencia GPU que Quest 2) y compatibilidad total con exclusivos de Quest 3",
      "Funciona autónomo o conectado a tu PC gamer por WiFi 6E (AirLink / Virtual Desktop / Steam Link)",
      "Ahorro neto superior a $230.000 ARS frente a revendedores locales",
    ],
    cons: [
      "Utiliza lentes Fresnel con ajuste de 3 posiciones en lugar de las lentes Pancake del Quest 3 de USD 499",
    ],
    specs: {
      "Panel / Resolución": "1832 x 1920 px por ojo · 90 / 120 Hz · Passthrough RGB",
      "Frecuencia / Respuesta": "Qualcomm Snapdragon XR2 Gen 2 + 8GB RAM + 128GB",
      "Conectividad": "WiFi 6E, Bluetooth 5.2, USB-C (Meta Quest Link)",
      "Espacio de Color": "2x Mandos Meta Quest Touch Plus con seguimiento sin aros",
      "Tensión Eléctrica AR": "Cargador USB-C 18W multivoltaje 100-240V",
      "Peso Volumétrico": "1,15 kg (Caja original)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "delonghi-dedica-ec885-es",
    slug: "cafetera-express-delonghi-dedica-arte-ec885-220v",
    asin: "B09V1L6B7H",
    ncmCode: "8516.71.00",
    store: "ES",
    name: "De'Longhi Dedica Arte EC885.M Cafetera Express Manual (220V Europeo)",
    brand: "De'Longhi",
    category: "Café & Domótica 220V",
    stamp: "220V NATIVO · AMAZON ESPAÑA",
    priceUsd: 215,
    previousPriceUsd: 280,
    shippingUsd: 49,
    vatRate: 0.21,
    localArgentinaPriceArs: 690000,
    localReferenceSource: "Tiendas electro AR",
    commissionRate: 0.05,
    rating: 4.6,
    reviewsCount: 6430,
    imageUrl: "/products/delonghi-dedica-ec885-es.jpg",
    voltageSpec: "220-240V 50Hz Nativo (Sin transformador)",
    weightKg: "4,20 kg",
    shortSummary:
      "Importada directamente desde Amazon España (.es): trabaja a 220V-240V 50Hz nativos de fábrica para conectarse directo a la red argentina sin autotransformadores pesados. Incluye lanceta profesional MyLatte Art.",
    idealProfile:
      "Café espresso en casa con chasis de acero inoxidable de apenas 15 cm de ancho, filtros no presurizados de mayor capacidad y texturizador de leche real.",
    scores: {
      calidadPrecio: 9.6,
      rendimiento: 9.3,
      construccion: 9.6,
      ahorroVsLocal: 9.6,
    },
    pros: [
      "Al despacharse desde Amazon España viene para 220V 50Hz de fábrica (clave en equipos de resistencia térmica de 1300W)",
      "Al cruzar a exportación fuera de la Unión Europea, Amazon España descuenta el 21% de IVA español antes de sumar el IVA argentino",
      "Incluye jarra lechera de acero inoxidable y tamper metálico de serie",
    ],
    cons: [
      "Tributa 21% de IVA aduanero por pertenecer al rubro de electrodomésticos de hogar",
    ],
    specs: {
      "Panel / Resolución": "Bomba italiana de 15 bares + Calentamiento Thermoblock (35s)",
      "Frecuencia / Respuesta": "Varilla de vapor inoxidable MyLatte Art para microespuma",
      "Conectividad": "Chasis metálico slim de 14,9 cm de ancho",
      "Espacio de Color": "Portafiltro 51mm + Tamper + Jarra de leche incluidos",
      "Tensión Eléctrica AR": "220-240V ~ 50/60Hz 1300W Nativo (Amazon.es)",
      "Peso Volumétrico": "4,20 kg (Courier DHL/UPS desde Madrid/Barcelona)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "roborock-q5-pro-es",
    slug: "robot-aspirador-roborock-q5-pro-lidar-5500pa",
    asin: "B0C7V9B8K2",
    ncmCode: "8508.11.00",
    store: "ES",
    name: "Roborock Q5 Pro Robot Aspirador LiDAR 5500 Pa DuoRoller (220V Europeo)",
    brand: "Roborock",
    category: "Café & Domótica 220V",
    stamp: "LIDAR + DUOROLLER · 220V",
    priceUsd: 249,
    previousPriceUsd: 349,
    shippingUsd: 55,
    vatRate: 0.21,
    localArgentinaPriceArs: 890000,
    localReferenceSource: "Importadores domótica AR",
    commissionRate: 0.05,
    rating: 4.7,
    reviewsCount: 2980,
    imageUrl: "/products/roborock-q5-pro-es.jpg",
    voltageSpec: "Base 220-240V Nativa (Amazon.es)",
    weightKg: "5,10 kg",
    shortSummary:
      "Navegación láser LiDAR PreciSense con mapeo multi-planta, sistema de doble cepillo de goma contrarrotante DuoRoller (heredado de la serie S8) y 5500 Pa de succión con depósito gigante de 770 ml.",
    idealProfile:
      "Departamentos y casas con mascotas o alfombras que necesitan navegación láser real e integración con Home Assistant o Alexa sin pagar precios locales inflados.",
    scores: {
      calidadPrecio: 9.7,
      rendimiento: 9.6,
      construccion: 9.5,
      ahorroVsLocal: 9.8,
    },
    pros: [
      "Doble rodillo de goma maciza DuoRoller que evita enredos de pelo y levanta suciedad pesada en alfombras",
      "Batería de 5200 mAh con hasta 240 minutos de autonomía continua (cubre hasta 350 m2)",
      "Integración nativa con la app de Roborock y con el plugin oficial de Home Assistant",
    ],
    cons: [
      "Módulo de mopa húmeda pasiva por gravedad (pensado para repaso de polvo fino, no fregado sónico)",
    ],
    specs: {
      "Panel / Resolución": "Telémetro Láser LiDAR PreciSense 360° + Mapas 3D",
      "Frecuencia / Respuesta": "Succión HyperForce 5500 Pa + Doble cepillo DuoRoller",
      "Conectividad": "WiFi 2.4 GHz · App Roborock / Alexa / Home Assistant",
      "Espacio de Color": "Depósito de polvo de 770 ml + Tanque de agua de 180 ml",
      "Tensión Eléctrica AR": "Base de carga 100-240V / 220V Nativa",
      "Peso Volumétrico": "5,10 kg (Caja AmazonGlobal)",
    },
    updatedAt: "Hoy",
  },
  {
    id: "anker-prime-27650-powerbank",
    slug: "power-bank-anker-prime-27650mah-250w-gan",
    asin: "B0BYNYBTYK",
    ncmCode: "8507.60.00",
    store: "US",
    name: "Anker Prime Power Bank 27.650 mAh (99,54 Wh) 250W USB-C PD 3.1",
    brand: "Anker",
    category: "Almacenamiento & Periféricos",
    stamp: "250W PD 3.1 · APTO CABINA",
    priceUsd: 149,
    previousPriceUsd: 179,
    shippingUsd: 21,
    vatRate: 0.21,
    localArgentinaPriceArs: 460000,
    localReferenceSource: "Importadores accesorios AR",
    commissionRate: 0.04,
    rating: 4.7,
    reviewsCount: 3180,
    imageUrl: "/products/anker-prime-27650-powerbank.jpg",
    voltageSpec: "USB-C PD 3.1 Bidireccional (hasta 140W por puerto)",
    weightKg: "0,67 kg",
    shortSummary:
      "Batería externa de grado instrumental con 99,54 Wh (justo en el límite legal de 100 Wh permitido por TSA/ANAC para llevar en cabina de avión), entrega combinada de 250W y telemetría en pantalla OLED en tiempo real.",
    idealProfile:
      "Profesionales móviles que necesitan alimentar notebooks de alto consumo (MacBook Pro 16, ThinkPad, ROG Ally / Steam Deck) lejos de un tomacorriente.",
    scores: {
      calidadPrecio: 9.4,
      rendimiento: 9.9,
      construccion: 9.8,
      ahorroVsLocal: 9.5,
    },
    pros: [
      "Entrega hasta 140W por un solo puerto USB-C (protocolo PD 3.1) y 250W combinados en sus 3 salidas",
      "Pantalla digital integrada que muestra watts de entrada/salida por puerto, temperatura y tiempo restante",
      "Capacidad de 99,54 Wh certificada para subir en equipaje de mano en cualquier aerolínea",
    ],
    cons: [
      "Para recargarla a 170W necesita un cargador USB-C GaN de 100W o superior",
    ],
    specs: {
      "Panel / Resolución": "Capacidad 27.650 mAh / 99,54 Wh (Apto Cabina TSA/ANAC)",
      "Frecuencia / Respuesta": "Salida máxima 250W (2x USB-C 140W PD 3.1 + 1x USB-A 65W)",
      "Conectividad": "Telemetría en display frontal + Bluetooth App Anker",
      "Espacio de Color": "Recarga rápida por doble USB-C hasta 170W (0 a 80% en 35 min)",
      "Tensión Eléctrica AR": "Estándar universal USB Power Delivery 3.1",
      "Peso Volumétrico": "0,67 kg",
    },
    updatedAt: "Hoy",
  },
];
