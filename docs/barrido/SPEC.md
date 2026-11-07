# Barrido diario de productos (Amazon US, Amazon ES, Mercado Libre)

Estado: borrador 07/11/2026, para revisión cruzada antes de implementar.

## Objetivo

Una vez por día, un proceso automático trae **todos** los productos nuevos de las categorías de tecnología
con precio entre **USD 100 y 400**, con **todos los datos** que la tienda muestra (incluido el envío a
Argentina y las variantes), y los deja en un archivo del día con un log que permita saber qué pasó en cada
página. Reemplaza los pasos 3 y 7 del alta actual (`tools/discover_products.py`, `tools/crecer_desde_ml.py`),
que el 06/11 tardaron 6 h 29 min (log del worker, 07:52→14:21), filtran el precio después de bajar todo y no dejan log de lo que bajaron.

## Por qué un scraper propio

El scraper actual es `omkarcloud/amazon-scraper` fijado en `8ffd4f976c705d009ec06d8e4e3e15fc77e35cee`
(licencia MIT, se conserva el aviso). Ya sale por nuestra IP. Limitaciones medidas el 07/11:

1. `/best-sellers` no acepta precio (máx. 2 páginas = 100 productos).
2. `/search` y `/categories/products` aceptan `min_price`/`max_price`, pero el filtro «nuevo» hace una
   consulta previa extra para leer el id del filtro (`amazon/search.py:37-65`, `_refinement_ids`).
3. `/scrape` con un link de búsqueda descarta precio y filtros (`amazon/products.py:194-208`).
4. Sin log por página: no se sabe cuántas páginas, cuántos productos ni dónde falló.
5. Bloqueo: en las pruebas del 07/11 a partir de las 14:5x (sondeos 14:54 y 15:09) toda búsqueda (`/s`) da `503 dogs page (after 4 sessions)`; las fichas
   (`/dp`) siguen andando. Un scraper propio no evita el bloqueo (misma IP): tiene que medirlo y frenar.

La parte de transporte (`amazon/fetch.py`: sesiones, cookies, captcha «continue shopping», ubicación) y de
lectura (`amazon/parsers.py`) se conserva tal cual. Se cambia la capa de consultas y se agrega el barrido.

## Requisitos

R1. **Una consulta por página con todos los filtros**: categoría (nodo), `low-price`/`high-price`, condición
    «nuevo» y, si Amazon lo ofrece, «envía a Argentina». Los ids de filtros específicos del marketplace se
    leen una vez por corrida y se cachean en disco (con fecha) para no repetir la consulta previa.
R2. **Todas las categorías de tecnología**: lista configurable de nodos raíz por tienda (archivo JSON
    versionado), con exclusiones. Se recorren todas las páginas que Amazon devuelva (`total_pages`).
R3. **Datos por producto** (todo lo que traiga la tarjeta de búsqueda, sin descartar campos): asin, título,
    marca, precio, precio de lista, cupón, envío (texto y opciones), estrellas, reseñas, «comprados el último
    mes», patrocinado, `has_variations`, `variations_text`, imagen, link, categoría y página de origen.
R4. **Envío a Argentina**: la sesión consulta con ubicación Argentina (como `worker/amazon-ar/ar_server.py:117`
    `apply_ar_location`). Por producto se guarda el texto de envío crudo y una clasificación
    `gratis | pago | no_envia | desconocido` usando las mismas reglas que `ar_server.parse_delivery`.
R5. **Variantes**: en la búsqueda se guarda lo que venga (`has_variations`, `variations_text`). El detalle de
    variantes (`/products/variations`) se pide sólo para los productos que pasan los filtros, con tope diario
    configurable y log.
R6. **Tiendas**: Amazon US y Amazon ES (el transporte ya soporta `country=ES`). Mercado Libre por su API
    oficial (credenciales existentes en `worker/.env`, módulo `worker/ml_prices.py`): más vendidos por
    categoría de tecnología con precio convertido a USD con el MEP del día y el mismo rango 100-400.
R7. **Salida**: `output/barrido/<tienda>-AAAA-MM-DD.jsonl` (una línea por producto) + `resumen.json` del día
    (por categoría: páginas, productos, en rango, con envío, fallas, segundos). Escritura atómica.
R8. **Log por página** (con hora ART en cada línea): `BARRIDO_PAGINA tienda= categoria= pagina= de= productos=
    segundos= http=`; errores `BARRIDO_ERROR ... motivo=<texto literal>`; fin `BARRIDO_OK` / `BARRIDO_FALLA`
    con totales. Nunca un error sin su texto.
R9. **Ritmo y bloqueo**: pausa configurable entre páginas; ante `503 dogs page`/captcha: backoff exponencial
    con tope y, si se repite N veces seguidas, corta la tienda (no la corrida) y deja `BARRIDO_BLOQUEADO`
    con la hora. Se reanuda desde la última página guardada (checkpoint) en la próxima corrida del día.
R10. **Reanudable e idempotente**: checkpoint por tienda/categoría/página; re-correr el mismo día no duplica.
R11. **Contenedor propio** en `worker/barrido/` (Dockerfile, sin secretos en la imagen), servicio en
    `worker/docker-compose.yml` de la red interna, sin puertos expuestos. Disparo diario encadenado desde la
    cadena existente (`tools/cadena.py`), no por horario suelto.
R12. **Tests**: parsers con fixtures HTML/JSON guardados (sin red), armado de URL con todos los filtros,
    clasificación de envío, checkpoint/reanudación, backoff. `python -m pytest worker -q` verde.
R13. **Herramienta de prueba**: `tools/probar_scraper.py` sigue siendo la única vía manual (hook
    `.claude/hooks/scraper-solo-con-herramienta.mjs`) y se adapta al servicio nuevo.

## Lo que hay que medir (no se asume)

| Pregunta | Cómo se mide | Cuándo |
|---|---|---|
| ¿Existe filtro «envía a Argentina» en la barra lateral? | `refinements` de una búsqueda con ubicación AR | primera búsqueda desbloqueada |
| ¿El envío de la tarjeta coincide con el de la ficha? | 5 productos, tarjeta vs `/products/details` | ídem |
| Páginas por categoría con filtros | `total_pages`/`count` de la página 1 de cada categoría | primera corrida |
| Ritmo que tolera Amazon | log R8 + R9 a distintas pausas | primeras corridas |
| ML: ¿la API permite más vendidos/búsqueda por categoría con nuestro token? | una llamada por endpoint, log del HTTP | antes de implementar R6 |

## Criterios de aceptación

A1. Una corrida completa de 1 categoría de Amazon US deja jsonl + resumen + log con todas las líneas R8.
A2. Todos los productos del jsonl tienen precio entre 100 y 400 o `precio=null` marcado explícitamente.
A3. Cada producto tiene clasificación de envío AR; se muestra un ejemplo de `gratis` o `pago` y uno de `no_envia`.
A4. Cortar el proceso a mitad y relanzarlo continúa desde el checkpoint sin duplicar.
A5. Un bloqueo simulado (fixture 503) produce `BARRIDO_BLOQUEADO` y no tumba las otras tiendas.
A6. Integrado en la VM (contenedor arriba, disparado por la cadena) y verificado con una corrida real.

## Fuera de alcance (v1)

Matching Amazon↔ML (sigue `tools/match_candidates.py`), publicación en el sitio, proxies pagos.
