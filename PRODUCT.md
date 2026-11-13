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
| Etiqueta «Bajó USD N esta semana» | Precio de Amazon.com de hoy contra los 7 días anteriores del historial (sólo precios relevados ese mismo día); ver «Bajó de precio» abajo | `bajadaDePrecio` en `src/lib/bajas-precio.ts`, `resumirHistorialAmazon` en `worker/deployer/deploy.mjs` (13/11) |

Una sola corrida por día (cron 03:30, `tools/cadena.py`): verificación de publicados y republicación, y después alta de nuevos con revisión de dudosos por NVIDIA. Diseño: `docs/superpowers/specs/2026-11-09-procesos-publicacion-design.md`.

## Bajó de precio (13/11)

Etiqueta «Bajó USD N esta semana» en tarjetas y ficha, sin precio tachado ni «antes/ahora». Sale sólo si se cumplen las tres reglas (`src/lib/bajas-precio.ts`):

1. Al menos **3 días** con precio de Amazon en los **7 días anteriores** a hoy (las altas recientes no la llevan).
2. El precio de hoy bajó **5 % o más, o USD 10 o más**, contra la **mediana** de esos días.
3. El precio de hoy es el **mínimo** de la semana (si un día subió de golpe y volvió, no cuenta como bajada).

Sólo Amazon.com (USD) y sólo con el precio de hoy. El historial sale de `output/historial/AAAA-MM-DD-amazon-prices.json` (`worker/publish.py`, 60 días); el deployer lo resume en `data/historial-amazon.json` descartando los ítems con `checked` distinto de la fecha del archivo. La etiqueta se oculta como el resto de los precios si la página quedó vieja. `click_amazon` lleva `bajo_precio` y `bajada_usd`.

## Búsqueda en vivo de Mercado Libre (`/api/buscar`, 13/11)

`src/worker/index.ts` busca hasta 30 productos de catálogo y pide sus precios en tandas de 6 hasta juntar 6 con precio (máximo 32 consultas, límite de Cloudflare 50). Un producto que responde 404 «No winners found» no tiene vendedores hoy: es «sin precio», no una falla (igual que `worker/ml_prices.py`). Si ninguno tiene vendedores responde 200 sin resultados y la página muestra «Seguí buscando»; sólo da 502 si fallan todas las consultas de precio. Antes del 13/11 ese 404 contaba como falla y la búsqueda daba 502 (ej. «garmin»).

## UTMs de difusión (13/11)

Todo link al sitio desde redes lleva `utm_source=<red>&utm_medium=social&utm_campaign=<tipo de pieza>` y el detalle en `utm_content`:

| Origen | UTMs |
|---|---|
| Telegram (producto del día, automático) | `utm_source=telegram&utm_medium=social&utm_campaign=producto-diario&utm_content=<slug>` (`worker/telegram.py`) |
| Reel de Facebook (automático) | `utm_source=facebook&utm_medium=social&utm_campaign=reel-diario&utm_content=reel-DD-MM` (`tools/generar_y_encolar_reel.sh`) |
| Bio de Instagram (manual) | `https://ofertas.knunet.com/?utm_source=instagram&utm_medium=social&utm_campaign=bio` — los Reels de IG dicen «link en la bio». **Cargada el 13/11** y verificada en el perfil público. Instagram le agrega por su cuenta `utm_content=link_in_bio` y `fbclid` al pasar por `l.instagram.com`. El link sólo se edita desde la app del celular (la web lo bloquea). |

Hasta el 13/11 Telegram usaba `utm_medium=canal` y el Reel de FB `utm_campaign=reel-DD-MM`. Visitas desde la casa, la VM y pi3 no cuentan (`IGNORE_IP` de Umami); para revisar el sitio sin ensuciar métricas, abrirlo con `?notrack=1`.
