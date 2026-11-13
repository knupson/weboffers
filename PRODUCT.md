# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Compradores argentinos en general (confirmado 2026-10-30): no sólo gente de hardware, también quien busca hogar, cocina o electrodomésticos. Entran desde el celular o la PC queriendo saber si conviene traer algo de Amazon en vez de comprarlo en Argentina, donde el mismo producto suele costar bastante más.

## Product Purpose

Sitio de afiliados de Amazon (Amazon.com y Amazon.es). Muestra productos que conviene traer por courier y cuánto salen puestos en tu casa. Éxito = clicks a Amazon con el tag de afiliado (`knunet-20` US, `knunet-21` ES) que terminan en compra. Es lo único que importa comercialmente.

## Positioning

Hace la cuenta argentina que Amazon no hace: franquicia de USD 400 por envío, IVA, dólar MEP y dólar tarjeta del día, y comparación contra el precio local que carga el visitante.

## Operating Context

- Primera acción buscada: ir directo a Amazon desde la tarjeta del producto (confirmado). La calculadora es respaldo para quien duda.
- Buscador y búsquedas curadas a Amazon con tag: monetizan aunque el producto no esté en el catálogo.
- Worker en Python (Pi4) que, con credenciales de Creators API, publica `offers.json` con precio, imagen y fecha.

## Capabilities and Constraints

- Astro estático + islas Preact, Cloudflare Workers Static Assets, dominio `ofertas.knunet.com`.
- Prohibido mostrar precios, ratings o fotos de Amazon que no vengan de su API con menos de 24 h. Sin API: fotos oficiales del fabricante (decisión del user 2026-10-30) y la API las reemplaza cuando exista.
- Imágenes de producto generadas con IA: prohibidas (engañan sobre el producto real). Imaginería propia (portada, categorías, OG) sí.
- Calculadora: IVA 21% por defecto; 10,5% sólo elegido por el usuario y marcado como no verificado. Límites: USD 3.000 FOB, 5 envíos por año, 50 kg.
- Catálogo: 41 productos con ASIN verificados (tecnología en Amazon.com, cocina, hogar y cuidado personal de 220 V en Amazon.es).

## Brand Commitments

- Nombre: Franquicia 400. Proyecto de KnuNet, pero con identidad visual propia: no debe parecerse a knunet.com ni a blackseam.knunet.com (pedido explícito).
- Voz: castellano rioplatense con voseo, directo y confiable, datos concretos, sin exageraciones ni urgencias inventadas, sin emojis, sin rayas largas.
- Divulgación de afiliado de Amazon visible.

## Evidence on Hand

- ASIN verificados en `data/catalog.json`. Cotizaciones reales de dolarapi.com.
- No hay: precios, fotos de producto, reseñas, testimonios ni métricas de ahorro reales. No inventarlas.

## Product Principles

1. Cada pantalla empuja a un click de afiliado honesto.
2. La cuenta argentina es el diferencial: visible, simple y verificable.
3. Nada inventado: lo que no viene de Amazon o de una fuente real, no se muestra.
4. Funciona igual de bien en el celular.

## Límites de antigüedad

Los que aplica el código (relevados el 07/11/2026). Si un dato pasa su límite, el producto o la sección no se muestran; nunca se rellena con un dato anterior.

| Dato | Límite | Dónde se controla |
|---|---|---|
| Precio de Mercado Libre | Sólo del día (fecha ART) | `ml_hoy` en `comparableChecks`, `src/lib/data.ts` |
| Precio de Amazon | Sólo del día (fecha ART) | `amazon_hoy` en `comparableChecks`, `src/lib/data.ts` |
| Envío a Argentina confirmado | Hasta 14 días calendario ART | `ARSHIPPING_MAX_DAYS` en `src/lib/data.ts` y `worker/amazon_prices.py` |
| Dólar MEP | El del build; si dolarapi.com no responde, respaldo de hasta 3 días. Sin eso, el build falla | `loadProducts`, `src/lib/data.ts` |
| Ficha técnica de Mercado Libre | Hasta 7 días | `validMlSheet`, `src/lib/ml-fichas.ts` |
| Producto que sale del sitio | Se reconsulta 3 días (republicación); después «no revisar» 7 días | `transicion`, `worker/publicacion.py` (09/11) |
| Candidato que no cumple | «No revisar» 7 días; al vencer vuelve al alta con Chrome del día | `worker/publicacion.py`, `tools/confirmar_altas.py` (09/11) |
| Marca «Lo más vendido esta semana» (`mas-vendidos.json`, destacados de ML) | Hasta 7 días desde su `fecha`; se renueva en la cadena (`alta:mas_vendidos`) y, si ML no da destacados o el alta corta antes, queda la del día que se obtuvo | `MAS_VENDIDOS_DIAS` en `src/lib/mas-vendidos.ts`, `tools/actualizar_mas_vendidos.py` (13/11) |

Una sola corrida por día (cron 03:30, `tools/cadena.py`): verificación de publicados y republicación, y después alta de nuevos con revisión de dudosos por NVIDIA. Diseño: `docs/superpowers/specs/2026-11-09-procesos-publicacion-design.md`.
