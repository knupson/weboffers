# Franquicia 400

Calculadora de costo final para comprar hardware en Amazon y traerlo a Argentina por courier (franquicia de USD 400). Sitio estático en Astro, publicado en Cloudflare, con un worker que actualiza precios y dólar.

Dominio: https://ofertas.knunet.com

## Piezas

| Pieza | Dónde | Qué hace |
|---|---|---|
| Sitio | `src/` | Astro estático, calculadora como isla Preact |
| Catálogo | `data/catalog.json` | Lista blanca de ASIN curada a mano |
| Ofertas | `data/offers.json` o `OFFERS_URL` | Salida del worker: dólar y precios con fecha |
| Worker | `worker/` | Consulta Amazon (Creators API) y dolarapi, publica `offers.json` y dispara el rebuild |
| Contrato | `docs/SPEC.md` | Esquemas y reglas de la calculadora |

## Reglas de datos

- Nada de precios ni ratings escritos a mano. Salen de `offers.json`.
- Fotos: la de Amazon sólo si viene de la API (`offers.json`). Mientras tanto, foto oficial del fabricante en `public/products/` (con su origen embebido); nunca una imagen de Amazon bajada a mano.
- Amazon.es cobra en euros: la calculadora convierte con el euro oficial cruzado con el dólar oficial (dolarapi).
- Un precio con más de 24 horas no se muestra.
- Sin credenciales de la API el worker corre en modo `offline` y el sitio sale sin precios.
- IVA por defecto 21%. El 10,5% no está verificado.

## Comandos

```bash
npm install
npm run dev
npm test           # vitest: calculadora y dólar
npm run build      # genera dist/
npx wrangler deploy
```

## Variables

| Variable | Dónde | Uso |
|---|---|---|
| `PUBLIC_AMAZON_US_TAG` / `PUBLIC_AMAZON_ES_TAG` | build | Tags de afiliado. Sin ellas los links salen sin tag |
| `OFFERS_URL` | build | URL pública de `offers.json` (opcional) |

El worker tiene sus propias variables, ver `worker/README.md`.
