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
