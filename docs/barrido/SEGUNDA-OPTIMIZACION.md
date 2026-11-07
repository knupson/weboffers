# Segunda optimización del barrido — 07/11/2026

Alcance: rama `feat/barrido`, sobre los cambios de pacing, consultas y prefiltro de ML. Código y pruebas preparados; sin ejecutar Python, tests, instalaciones ni barrido en la PC. Sin commit ni deploy, por pedido de Alejandro. No se modifica `vendor` ni el catálogo.

## Criterios de cierre

- Conocidos: usar `ml.catalogId`, obtener precio actual, saltear búsqueda y prefiltro; volver a buscar si no hay oferta local nueva válida.
- Variantes: ninguna adquisición durante Amazon; al terminar ML, sólo para elegibles con candidatos, con cupo y checkpoint Amazon originales.
- Refinamientos: guardar sólo IDs de filtros durante siete días configurables, separar por tienda/nodo/idioma/destino y reutilizar la preconsulta sólo con parámetros idénticos.
- Métricas: mismo desglose en resumen y fin de etapa; pruebas locales escritas para verificarlo en la VM.

## Archivos

| Archivo dentro de `worker/barrido/` | Cambio |
| --- | --- |
| `ml_lookup.py` | Lee `ml.catalogId` del catálogo principal y automático; atajo con precio del día y fallback registrado. Al terminar, encadena variantes con una fuente Amazon por tienda. Desglosa intentos ML reales, incluidos reintentos y páginas de ofertas. |
| `__main__.py` | Pasa `--catalog` y `--catalog-auto` al lookup. |
| `runner.py` | Difiere las variantes, cuenta tarjetas patrocinadas y duplicados, e informa únicos de esta ejecución. Rechaza variantes adquiridas tras cambiar el día ART. |
| `state.py` | Superpone variantes confirmadas al materializar el JSONL sin cambiar sus campos ni las páginas inmutables. Reanuda reservas fallidas o pendientes sin consumir otro lugar del cupo. Admite checkpoints previos con el TTL nuevo por defecto. |
| `config.py` | Agrega `refinements_ttl_days=7`, disponible como `--refinements-ttl-days`. Cero desactiva la reutilización entre llamadas. |
| `refinements.py` | Clave sin fecha, TTL desde `observed_at`, refresh explícito y redescubrimiento ante caché corrupta. No cachea productos ni precios. |
| `amazon_source.py` | Conserva la preconsulta en memoria y compara todos los parámetros antes de reutilizarla. Usa el TTL configurado. |
| `events.py` | Clasifica HTTP en `search`, `detail/variations`, `warm-up`, `location`, `ml_search`, `ml_price` y `other`; publica métricas por etapa. |
| `test_round2.py` | Pruebas de esta ronda, sin red. |
| `fixtures/round2.json` | Catálogo sintético con la forma real del campo ML, una oferta y refinamientos. El ID de catálogo reproduce un ID observado en el archivo local; precios de la fixture sintéticos. |
| `test_ml_lookup.py` | Actualiza las expectativas del resumen y del paso CLI sin aflojar el contrato del registro de candidatos. |
| `test_acceptance.py` | Amazon conserva `variations=None` hasta terminar ML. |

Este documento registra el alcance y los cálculos. La confirmación mediante ejecución queda pendiente en el contenedor de la VM.

## Cálculo del ahorro, no medición posterior

Base informada por Alejandro: 60 pedidos Amazon (31 búsquedas, 17 detalles, 9 portadas y 3 de ubicación), 780 tarjetas, 497 ASIN únicos, 284 elegibles; 30 elegibles conocidos y 17 con variantes. Los duplicados de tarjetas calculados son `780 − 497 = 283`. Las 300 tarjetas patrocinadas son otra dimensión: pueden solaparse con los duplicados.

1. **Conocidos:** sea K la cantidad de esos 30 que efectivamente tenga `ml.catalogId` válido y mantenga oferta local nueva. Si antes cada uno necesitaba una búsqueda más un pedido de ofertas, pasan de `2K` a `K`: ahorro de K pedidos ML, hasta 30 en ese escenario. El dato de 224 campos ML sobre 241 productos del catálogo no permite saber K entre esos 30. Fallback, paginación, autenticación y 429 pueden aumentar los pedidos reales; no se omiten para forzar el número uno.
2. **Variantes:** sea V la cantidad de los 17 que consiga candidatos ML y entre en el cupo. Los detalles pasan de 17 a V: ahorro de `17 − V` pedidos de detalle, entre 0 y 17 si cada variante requiere un único pedido, como en la base informada. Warm-ups, ubicación y reintentos se cuentan aparte. El helper comparte el transporte configurado de Amazon y conserva su estado por tienda.
3. **Refinamientos:** con caché vigente se evita una preconsulta por tienda/nodo/contexto que antes vencía cada día. Para esta categoría, una ejecución diaria durante siete días pasa de siete preconsultas a una: seis pedidos menos por ciclo, bajo ese supuesto. La primera ejecución de la nueva caché no ahorra esa preconsulta. No se pueden atribuir las once búsquedas por encima de veinte páginas a refinamientos sin su log.
4. **Reutilización de página 1:** con el descubrimiento actual siempre se agrega el filtro «nuevo», y a veces también el de Argentina. Cambian los parámetros, por lo que una preconsulta con resultados no equivale a la página final: ahorro adicional actual cero. Se conserva la salida temprana para una preconsulta vacía. La prueba con filtros sin cambios cubre la rama de reutilización exacta.
5. **Métricas:** ahorro directo cero; permiten medir la próxima corrida. Amazon informa tarjetas, únicos y duplicados de las páginas adquiridas en esta ejecución. ML informa productos procesados en esta ejecución; los totales del checkpoint siguen separados. La tasa usa los pedidos de la etapa, incluidas variantes diferidas y auxiliares, divididos por los elegibles procesados; sin denominador devuelve `null`.

Con caché ya vigente y manteniendo iguales todos los pedidos auxiliares, el cálculo condicional Amazon sería `60 − (17 − V) − 1 = 42 + V`. No es una predicción medida: la cantidad V y los nuevos warm-ups/reintentos se conocen recién al ejecutar.

## Pruebas preparadas

- Atajo con ID realista, sin construir consultas ni filtrar candidatos; se usa el precio nuevo, nunca el guardado en catálogo.
- Fallback ante ofertas vacías, usadas, internacionales y 404; no se vuelve a pedir el ID que ya falló.
- Catálogo sin campo ML, sin ID o con ID inválido: búsqueda normal.
- Amazon no pide variantes; métricas de patrocinados, duplicados, únicos y clases de pedido.
- Variantes sólo con ML, cupo persistido, materialización, reanudación sin repetir lo confirmado y reintento de fallos.
- Encadenado completo lookup → variantes con una segunda ejecución sin pedidos adicionales.
- Caché entre días, vencimiento al séptimo día, TTL configurable, refresh, claves separadas y corrupción.
- Reutilización de preconsulta con parámetros iguales y segunda búsqueda cuando cambian.
- Igualdad entre métricas retornadas, resumen persistido y `BARRIDO_ETAPA_FIN` para el lookup.

Validación en esta PC: lectura del diff y `git diff --check`. Las pruebas no se ejecutaron. Los catálogos no se editaron; no se midió una nueva cantidad publicada ni se desplegó.

Mensaje de commit propuesto: `Optimizá el barrido con atajos ML, variantes diferidas y métricas por pedido`.
