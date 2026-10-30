export type LegalDocId = "afiliados" | "privacidad" | "cookies" | "terminos";

export interface LegalSection {
  heading: string;
  paragraphs: string[];
  bullets?: string[];
}

export interface LegalDocument {
  id: LegalDocId;
  code: string;
  title: string;
  subtitle: string;
  updatedAt: string;
  sections: LegalSection[];
}

export interface CookieConsentState {
  decided: boolean;
  necessary: true;
  analytics: boolean;
  affiliateAttribution: boolean;
  updatedAt: string;
}

export const DEFAULT_COOKIE_CONSENT: CookieConsentState = {
  decided: false,
  necessary: true,
  analytics: false,
  affiliateAttribution: true,
  updatedAt: "2026-10-29",
};

export const COOKIE_STORAGE_KEY = "f400_cookie_consent_v1";

export const LEGAL_DOCUMENTS: Record<LegalDocId, LegalDocument> = {
  afiliados: {
    id: "afiliados",
    code: "PLIEGO LEGAL 01 · ACUERDO OPERATIVO AMAZON",
    title: "Divulgación de Afiliados de Amazon",
    subtitle:
      "Declaración de transparencia comercial conforme a la Sección 5 del Acuerdo Operativo de Amazon Associates y guías de divulgación de la FTC.",
    updatedAt: "29 de octubre de 2026",
    sections: [
      {
        heading: "1. Declaración obligatoria de afiliación",
        paragraphs: [
          "En calidad de Afiliado de Amazon, obtengo ingresos por las compras adscritas que cumplen los requisitos aplicables.",
          "FRANQUICIA 400 · KnuNet (ofertas.knunet.com) participa en el Programa de Afiliados de Amazon Services LLC (Amazon.com en Estados Unidos) y en el Programa de Afiliados de Amazon EU S.à r.l. (Amazon.es en España), programas de publicidad para afiliados diseñados para ofrecer a sitios web un modo de obtener comisiones por publicidad mediante la inclusión de enlaces a Amazon.com y Amazon.es.",
        ],
      },
      {
        heading: "2. Impacto nulo en el precio que pagás",
        paragraphs: [
          "Cuando hacés clic en un botón de inspección o compra hacia Amazon desde esta plataforma, el enlace incluye un código de identificación (parámetro tag). Si concretás una compra dentro de la ventana de atribución reglamentaria de Amazon (24 horas desde el clic, o hasta 89 días si agregás el producto al carrito durante esa sesión), Amazon nos liquida una comisión porcentual sobre el valor FOB del artículo.",
          "El precio del producto, el costo de envío internacional AmazonGlobal y el cálculo de tributos de importación que vos pagás en el checkout de Amazon son exactamente los mismos que si entraras escribiendo la dirección de forma directa.",
        ],
      },
      {
        heading: "3. Exactitud de precios y disponibilidad",
        paragraphs: [
          "Los precios de los productos en USD/EUR, los costos estimados de flete internacional y las referencias del mercado local argentino se relevan periódicamente con fines comparativos y de simulación.",
          "Dado que Amazon actualiza tarifas, cupones, stock y costos de flete por peso volumétrico en tiempo real, el único valor vinculante para tu operación es el exhibido en la pantalla de pago final (Checkout) de Amazon.com o Amazon.es al momento de confirmar la orden.",
        ],
      },
      {
        heading: "4. Propiedad intelectual y marcas registradas",
        paragraphs: [
          "Amazon, AmazonGlobal y el logotipo de Amazon son marcas comerciales de Amazon.com, Inc. o de sus sociedades vinculadas. Los nombres de fabricantes y líneas de hardware (ASUS, LG, AOC, Beelink, GMKtec, Samsung, Keychron, Sony, Meta, De'Longhi, Roborock, Anker) pertenecen a sus respectivos titulares y se citan exclusivamente con fines descriptivos y de comparación técnica.",
        ],
      },
    ],
  },
  privacidad: {
    id: "privacidad",
    code: "PLIEGO LEGAL 02 · LEY 25.326 ARGENTINA + RGPD",
    title: "Política de Privacidad y Protección de Datos",
    subtitle:
      "Marco de tratamiento de información bajo la Ley N° 25.326 de Protección de los Datos Personales de la República Argentina y estándares internacionales.",
    updatedAt: "29 de octubre de 2026",
    sections: [
      {
        heading: "1. Principio de recolección mínima (Zero-PII)",
        paragraphs: [
          "FRANQUICIA 400 · KnuNet funciona como una herramienta pública de consulta técnica y simulación arancelaria. No exigimos creación de cuentas, no procesamos pagos, no solicitamos tarjetas de crédito ni recolectamos nombres, domicilios, números de CUIT/CUIL ni correos electrónicos dentro del sitio.",
        ],
      },
      {
        heading: "2. Datos técnicos que procesamos",
        paragraphs: [
          "El funcionamiento de la plataforma involucra únicamente tres flujos técnicos acotados:",
        ],
        bullets: [
          "Consultas en vivo de cotizaciones cambiarias desde tu navegador hacia la API pública DolarApi.com para obtener el valor del Dólar MEP, Dólar Tarjeta y Dólar Oficial.",
          "Almacenamiento local en tu propio navegador (localStorage) para recordar el sustrato visual elegido (Modo Manifiesto o Modo HUD), la lista de productos cargados en el comparador y tus preferencias de privacidad.",
          "Telemetría agregada y anónima de tráfico web (sólo si habilitás la categoría Analítica en el panel de cookies) mediante nuestra instancia propia de Umami Analytics alojada en infraestructura KnuNet, sin cesión de datos a redes publicitarias.",
        ],
      },
      {
        heading: "3. Enlaces externos hacia Amazon y Telegram",
        paragraphs: [
          "Al abandonar ofertas.knunet.com mediante un enlace hacia Amazon.com, Amazon.es o t.me (Telegram), pasás a regirte por las políticas de privacidad y condiciones de uso de dichas plataformas. KnuNet no recibe de Amazon tus datos personales ni tu identidad como comprador: únicamente informes estadísticos agregados de unidades vendidas y comisiones devengadas.",
        ],
      },
      {
        heading: "4. Derechos del titular y autoridad de control (Ley 25.326)",
        paragraphs: [
          "En cumplimiento de la Ley N° 25.326 y las disposiciones de la Agencia de Acceso a la Información Pública (AAIP), se informa que el titular de los datos personales tiene la facultad de ejercer el derecho de acceso a los mismos en forma gratuita a intervalos no inferiores a seis meses, salvo que se acredite un interés legítimo al efecto conforme lo establecido en el artículo 14, inciso 3 de la Ley N° 25.326.",
          "La Agencia de Acceso a la Información Pública, en su carácter de Órgano de Control de la Ley N° 25.326, tiene la atribución de atender las denuncias y reclamos que interpongan quienes resulten afectados en sus derechos por incumplimiento de las normas vigentes en materia de protección de datos personales.",
        ],
      },
    ],
  },
  cookies: {
    id: "cookies",
    code: "PLIEGO LEGAL 03 · ALMACENAMIENTO LOCAL Y COOKIES",
    title: "Política de Cookies y Almacenamiento Local",
    subtitle:
      "Detalle técnico de las claves de almacenamiento local y cookies de atribución utilizadas por la plataforma.",
    updatedAt: "29 de octubre de 2026",
    sections: [
      {
        heading: "1. Cómo usamos el almacenamiento del navegador",
        paragraphs: [
          "En ofertas.knunet.com no instalamos cookies publicitarias invasivas ni píxeles de seguimiento de redes sociales (como Meta Pixel o Google Ads). Utilizamos exclusivamente claves de almacenamiento local (window.localStorage) para preservar el estado de tu sesión técnica.",
        ],
      },
      {
        heading: "2. Categorías configurables en el panel de control",
        paragraphs: [
          "Podés modificar tu configuración en cualquier momento desde el pie de página del sitio:",
        ],
        bullets: [
          "Técnicas Estrictamente Necesarias (Siempre activas): guardan el tema visual seleccionado (f400_theme), la matriz de comparación activa y el registro de tu decisión en el banner de privacidad (f400_cookie_consent_v1).",
          "Analítica Técnica Anónima (Opcional): registra métricas agregadas de rendimiento y páginas vistas sin identificar al usuario ni usar cookies de rastreo cruzado.",
          "Atribución de Afiliados en Salida (Activa al hacer clic hacia Amazon): cuando pulsás voluntariamente un botón de compra hacia Amazon.com o Amazon.es, Amazon registra en su propio dominio una cookie de atribución de 24 horas asociada al identificador del sitio para reconocer la referencia comercial.",
        ],
      },
      {
        heading: "3. Purga manual de datos locales",
        paragraphs: [
          "Podés borrar en un clic todo el estado guardado en tu navegador desde el botón 'Restablecer preferencias de cookies' en el pie de página o limpiando el almacenamiento del sitio en las herramientas de desarrollador de tu navegador.",
        ],
      },
    ],
  },
  terminos: {
    id: "terminos",
    code: "PLIEGO LEGAL 04 · CONDICIONES DE USO Y REGIMEN COURIER",
    title: "Términos de Uso y Alcance del Simulador Aduanero",
    subtitle:
      "Condiciones operativas del simulador arancelario y reglas vigentes del régimen de Pequeños Envíos Courier hacia la República Argentina.",
    updatedAt: "29 de octubre de 2026",
    sections: [
      {
        heading: "1. Carácter orientativo de las simulaciones",
        paragraphs: [
          "FRANQUICIA 400 · KnuNet provee una calculadora arancelaria automatizada basada en la normativa aduanera argentina vigente (Decreto 1065/2024 y Resolución General ARCA 5617/2024). Los cálculos constituyen una estimación técnica orientativa y no reemplazan el asesoramiento de un despachante de aduana ni la liquidación definitiva practicada por AmazonGlobal o la Dirección General de Aduanas (DGA / ARCA).",
        ],
      },
      {
        heading: "2. Reglas vigentes del régimen de Pequeños Envíos Courier",
        paragraphs: [
          "Para que un envío internacional ingrese bajo el régimen simplificado de Courier Privado (DHL, UPS, FedEx, AmazonGlobal) sin intervención de despachante, la operación debe cumplir de forma simultánea los siguientes requisitos reglamentarios:",
        ],
        bullets: [
          "Franquicia libre de derechos de importación y tasa estadística: aplica sobre los primeros USD 400 de valor FOB (costo de la mercadería en origen, sin contar flete ni seguro) por cada envío. Aun dentro de la franquicia de USD 400, el envío tributa el Impuesto al Valor Agregado (IVA) aduanero correspondiente.",
          "Alícuota de IVA según posición arancelaria (NCM): los bienes de informática y tecnología alcanzados por el artículo 28 inc. e) de la Ley de IVA (monitores, mini PCs, notebooks, almacenamiento SSD, periféricos de cómputo) tributan 10,5% de IVA; el resto de los rubros de consumo general (audio, cafeteras, aspiradoras robot, hogar, indumentaria) tributa 21% de IVA.",
          "Excedente sobre USD 400 FOB: si el valor del producto supera los USD 400 FOB (hasta el tope máximo permitido de USD 3.000 FOB por envío), los primeros USD 400 mantienen la exención y únicamente el monto que exceda los USD 400 abona derechos de importación más el 3% de tasa de estadística.",
          "Límites físicos y de frecuencia anual: cada paquete no puede superar los 50 kg de peso bruto, no puede contener más de 3 unidades de la misma especie, no debe tener fin comercial y se permite un máximo de 5 envíos por persona por año calendario.",
          "Requisitos del destinatario en ARCA (ex AFIP): contar con CUIT/CUIL, Clave Fiscal con Nivel de Seguridad 3 o superior y Domicilio Fiscal Electrónico constituido.",
        ],
      },
      {
        heading: "3. Garantía de depósito de importación de AmazonGlobal",
        paragraphs: [
          "Cuando comprás un producto vendido o enviado por Amazon con el servicio AmazonGlobal Internacional hacia Argentina, Amazon cobra por adelantado un 'Depósito de tasas de importación' (Import Fees Deposit). Si el costo aduanero real al cruzar la Aduana argentina resulta mayor que el depósito estimado, Amazon absorbe la diferencia sin cobrarte un centavo extra; si resulta menor, Amazon te reintegra automáticamente el saldo a favor en tu medio de pago original.",
        ],
      },
    ],
  },
};
