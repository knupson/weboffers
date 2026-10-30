# Spec de reconstrucción (contrato entre piezas)

Stack: Astro estático + islas Preact, Cloudflare Workers Static Assets. Worker de datos en Python (Pi4/dockerhost).
Voz: castellano rioplatense, plano, sin emojis, sin rayas largas. Código y nombres en inglés/castellano técnico, comentarios mínimos.

## Regla de datos (Amazon Associates)
- Nada de precios, ratings ni imágenes escritos a mano. Precio/imagen sólo vienen de `offers.json`, con `priceFetchedAt`.
- Precio con más de 24 h de antigüedad: la UI lo oculta.
- Sin API configurada el worker corre en modo `offline`: `priceUsd: null`. El sitio sale igual (calculadora + fichas sin precio).

## data/catalog.json (curado a mano, lista blanca)
Array de `{ asin, store: "US"|"ES", slug, name, brand, category, ncm?: string, weightKg?: number, voltage?: string, summary: string, verified: boolean }`.
Sin scores, sin ratings, sin precio local inventado.

## offers.json (salida del worker, consumida por el sitio en build)
```
{
  "generatedAt": ISO8601,
  "mode": "api" | "offline",
  "rates": { "mep": number, "tarjeta": number, "oficial": number, "fetchedAt": ISO8601, "source": "dolarapi.com" } | null,
  "items": [{ "asin": string, "store": "US"|"ES", "title": string|null, "priceUsd": number|null, "priceFetchedAt": ISO8601|null, "imageUrl": string|null, "availability": string|null }]
}
```

## Calculadora (src/lib/calc)
`calculate({ fobUsd, shippingUsd, ivaRate = 0.21, dutyRate = 0.35 }, rates)` devuelve desglose.
- Franquicia: USD 400 FOB por envío. Hasta ahí, derecho de importación y tasa de estadística = 0.
- Excedente = max(0, fob - 400). Derecho = excedente * dutyRate. Tasa estadística = excedente * 0.03.
- Base IVA = fob + shipping + derecho + tasa. IVA = base * ivaRate.
- IVA por defecto 21%. El 10,5% NO está verificado: sólo aceptable como valor elegido por el usuario, con aviso.
- Salida en USD, ARS@MEP y ARS@tarjeta. Sin afirmaciones sobre "recargos" del dólar tarjeta.
- Límites que debe señalar (warnings): fob > 3000 (fuera de courier), 5 envíos/año, 50 kg.
- Funciones puras, sin I/O. Redondeo a centavos sólo en la salida.
