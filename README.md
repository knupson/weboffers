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
| Worker del sitio | `src/worker/` | Entrada de Cloudflare Workers: sirve los estáticos y la ruta `/api/buscar` (Mercado Libre en vivo). No es el worker Python de `worker/` |
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

## Worker del sitio: secretos y `/api/buscar`

El Worker (`src/worker/index.ts`, compilado por wrangler) atiende sólo `/api/*`; el resto lo sirven los assets de `dist/` como antes.

Secretos (los carga el operador, nunca van en el repo):

```bash
npx wrangler secret put ML_CLIENT_ID
npx wrangler secret put ML_CLIENT_SECRET
```

Son las credenciales de la aplicación de Mercado Libre (`client_credentials`). Sin ellas la ruta responde 502 y la página de búsqueda muestra sólo las tiendas.

`GET /api/buscar?q=...`:

- `q` tiene que tener entre 2 y 80 caracteres; si no, 400.
- Pide un token de aplicación (se reutiliza hasta vencer), busca hasta 6 productos y toma el precio nuevo más bajo de cada uno. Los productos sin precio se descartan.
- Responde `{"q": "...", "results": [{"id", "name", "price", "url"}]}`. El `url` lleva los parámetros de afiliado. No se devuelven imágenes de Mercado Libre.
- Cache de 1 hora (Cache API) por `q` normalizada. Los errores de Mercado Libre no se cachean y responden 502 `{"error": "..."}`.

## Variables

| Variable | Dónde | Uso |
|---|---|---|
| `PUBLIC_AMAZON_US_TAG` / `PUBLIC_AMAZON_ES_TAG` | build | Tags de afiliado. Sin ellas los links salen sin tag |
| `OFFERS_URL` | build | URL pública de `offers.json` (opcional) |

El worker tiene sus propias variables, ver `worker/README.md`.
