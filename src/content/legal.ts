export type LegalId = "afiliados" | "privacidad" | "cookies" | "terminos";

export interface LegalDoc {
  id: LegalId;
  title: string;
  summary: string;
  updated: string;
  sections: Array<{ heading: string; body: string[]; bullets?: string[] }>;
}

// Borrador editorial: conviene que lo revise un abogado.
export const LEGAL: Record<LegalId, LegalDoc> = {
  afiliados: {
    id: "afiliados",
    title: "Afiliación con Amazon y Mercado Libre",
    summary: "Cómo ganamos plata con este sitio y qué significa para vos.",
    updated: "30 de octubre de 2026",
    sections: [
      {
        heading: "Qué declaramos",
        body: [
          "En calidad de Afiliado de Amazon, obtengo ingresos por las compras adscritas que cumplen los requisitos aplicables.",
          "Participamos en el Programa de Afiliados de Amazon (Amazon.com y Amazon.es). Los links a Amazon llevan un código de seguimiento. Si comprás después de entrar por uno, Amazon nos paga una comisión.",
          "También participamos en el Programa de Afiliados y Creadores de Mercado Libre. Los links a Mercado Libre (meli.la y los que llevan matt_word) también llevan un código, y si comprás por ellos Mercado Libre nos paga una comisión.",
          "Que cobremos de las dos tiendas no cambia el veredicto: recomendamos la que te deja el producto más barato puesto en tu casa, y a igual precio, Mercado Libre, porque llega antes y sin aduana.",
        ],
      },
      {
        heading: "Cuánto pagás vos",
        body: [
          "Lo mismo que si entraras a Amazon por tu cuenta. La comisión la paga Amazon, no se suma a tu compra.",
        ],
      },
      {
        heading: "Precios e imágenes",
        body: [
          "Los precios que mostramos los consulta un proceso automático a Amazon y llevan la fecha y hora de la consulta. Si un precio tiene más de 24 horas, no lo mostramos.",
          "Los precios cambian todo el tiempo. El que vale es el que ves en Amazon cuando pagás.",
        ],
      },
      {
        heading: "Marcas",
        body: [
          "Amazon y el logo de Amazon son marcas de Amazon.com, Inc. o de sus afiliadas. Las marcas de los fabricantes son de sus dueños y las nombramos sólo para identificar los productos.",
        ],
      },
    ],
  },
  privacidad: {
    id: "privacidad",
    title: "Privacidad",
    summary: "Qué datos tocamos. Resumen: casi ninguno.",
    updated: "30 de octubre de 2026",
    sections: [
      {
        heading: "Quién es el responsable",
        body: [
          "Responsable: Alejandro Benzoni (Argentina). Contacto: ofertas@knunet.com. Por ese mail podés hacer cualquier consulta o pedido sobre tus datos.",
        ],
      },
      {
        heading: "Lo que no hacemos",
        body: [
          "No hay cuentas, formularios ni pagos. No te pedimos nombre, CUIT, mail ni dirección. Los números que cargás en la calculadora se procesan en tu navegador y no se envían a ningún servidor nuestro.",
        ],
      },
      {
        heading: "Lo que sí pasa",
        body: ["Hay tres conexiones técnicas:"],
        bullets: [
          "Para saber cuánta gente visita el sitio usamos una analítica propia y libre (Umami, en un servidor del responsable, analytics.knunet.com; sin terceros). Cuenta páginas vistas, de qué sitio llegaste, país (deducido de la IP en el momento, que no se guarda), navegador, sistema, tamaño de pantalla y qué links a Amazon tocaste. No usa cookies ni identificadores guardados en tu navegador, y si tu navegador pide «no rastrear» (Do Not Track) no se cuenta nada. Los datos se usan sólo para mejorar el sitio y no se comparten.",
          "Tu navegador consulta la cotización del dólar a dolarapi.com cuando abrís la calculadora. Ese servicio ve tu dirección IP, como cualquier sitio que visites.",
          "Cloudflare, que aloja el sitio, registra datos técnicos de las visitas (IP, navegador, página) para entregar el contenido y protegerlo de abusos.",
        ],
      },
      {
        heading: "Links a Amazon",
        body: [
          "Cuando hacés clic en un link a Amazon pasás a regirte por las políticas de Amazon. Nosotros no recibimos tus datos de compra, sólo reportes agregados de ventas y comisiones.",
        ],
      },
      {
        heading: "Tus derechos",
        body: [
          "La Ley 25.326 te da derecho de acceso, rectificación y supresión sobre tus datos personales. Pedilo a ofertas@knunet.com. La Agencia de Acceso a la Información Pública es el órgano de control y atiende denuncias y reclamos.",
        ],
      },
    ],
  },
  cookies: {
    id: "cookies",
    title: "Cookies",
    summary: "Este sitio no instala cookies propias.",
    updated: "30 de octubre de 2026",
    sections: [
      {
        heading: "Nuestro sitio",
        body: [
          "No usamos cookies propias ni píxeles de publicidad. La analítica (Umami, propia) funciona sin cookies ni identificadores guardados en tu navegador y respeta «no rastrear». Por eso no hay un banner de consentimiento.",
        ],
      },
      {
        heading: "Cuando salís a Amazon",
        body: [
          "Al entrar a Amazon por uno de nuestros links, Amazon puede guardar sus propias cookies en su dominio para registrar de dónde viniste. Eso se rige por la política de cookies de Amazon, no por la nuestra.",
        ],
      },
      {
        heading: "Si esto cambia",
        body: [
          "Si más adelante sumamos alguna cookie propia, actualizamos esta página y agregamos el aviso de consentimiento antes de activarla.",
        ],
      },
    ],
  },
  terminos: {
    id: "terminos",
    title: "Términos del simulador",
    summary: "El simulador es una estimación, no una liquidación de aduana.",
    updated: "30 de octubre de 2026",
    sections: [
      {
        heading: "Qué es y qué no es",
        body: [
          "La calculadora estima el costo de traer una compra por courier a Argentina. No reemplaza el consejo de un despachante ni la liquidación final que hagan Amazon, el courier o ARCA.",
        ],
      },
      {
        heading: "Reglas en las que se basa",
        body: ["Tomamos como base el Decreto 1065/2024 y la RG ARCA 5608/2024, con estos puntos:"],
        bullets: [
          "Franquicia de USD 400 de valor FOB por envío, hasta 5 envíos por año y por persona. Dentro de la franquicia no se pagan derechos de importación ni tasa de estadística.",
          "El excedente sobre USD 400 no entra en la franquicia y paga derechos de importación y tasa de estadística.",
          "El resto de los tributos se rigen por el régimen general de importación.",
        ],
      },
      {
        heading: "IVA",
        body: [
          "Calculamos con 21% por defecto. La alícuota que corresponde a cada producto depende de su posición arancelaria y no pudimos confirmarla en las normas del régimen courier. Podés cambiarla a mano. Si tenés dudas, consultá con un despachante o en el micrositio de envíos internacionales de ARCA.",
        ],
      },
      {
        heading: "Responsable y contacto",
        body: [
          "Este sitio es de Alejandro Benzoni (Argentina). Si encontrás un error en la cuenta o en un producto, escribí a ofertas@knunet.com.",
        ],
      },
      {
        heading: "Derechos sobre el excedente",
        body: [
          "El porcentaje de derechos de importación depende del producto. Usamos 35% como estimación editable. Si tu compra queda por debajo de USD 400 de FOB, este valor no influye.",
        ],
      },
    ],
  },
};
