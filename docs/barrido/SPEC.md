# Barrido diario: contrato v1 (07/11/2026)

## Alcance

Adquisición diaria Amazon US y ES, seguida de lookup ML. «Todos» significa resultados accesibles de nodos
configurados, no exhaustividad de catálogo. Nuevo es condición nueva; conocidos también se guardan.
No publica ni modifica el catálogo actual. Tareas 1–9 y 11; integración (tarea 10) pendiente.
Medido 07/11: ML highlights y products/search 200, sites/MLA/search categoría+precio 403;
Amazon /s desde VM: `503 dogs page (after 4 sessions)`; /dp funciona. No eludimos ese bloqueo.

## Configuración

`categorias.json`: `{version:1, stores:{US:{nodes:[{id,name,kind:"root"|"leaf"}],exclude:[id]},ES:...}}`.
Nodos Amazon explícitos: root se consulta tal cual, SIN expansión implícita. Para particionar se
versionan hojas. ML no tiene nodos ni barrido de categorías o destacados.
La lista inicial es configurable y no garantiza cobertura total. Los nodos iniciales US/ES deben
validarse en la primera consulta real; los refinamientos se descubren en ejecución, nunca se inventan.
Rango real fijo USD 100–400; `--min-usd`/`--max-usd` sólo se admiten con `--dry-run`.
US USD; ES EUR con límites locales redondeados hacia afuera al centavo
y validación final USD. El rango define los productos Amazon a comparar; no limita el precio ML.
ML convierte ARS a USD con MEP. Cotizaciones positivas, finitas y de HOY ART con fuente/fecha.
Sin tasa del día falla ML; ES queda `skipped` con `BARRIDO_ES_SIN_COTIZACION` y
`fecha_recibida` literal. ES corre sólo los días con cotizaciones oficial y EUR del mismo día ART;
no se reutilizan tasas del último día hábil durante fines de semana o feriados. US no necesita tasas externas.
Pausa Amazon 5 s/página y ML 0,3 s/llamada; backoff 30,60 s con tope 120; N=3 bloqueos consecutivos
por página. Los errores transitorios tienen contador independiente (`transient_retries=3`) y el mismo
backoff con tope; `BARRIDO_REINTENTO` conserva el motivo literal y la clase del error.
Transporte interno una sesión bloqueada/intento y cero reintentos
de red; calentamiento, ubicación y click-through observables siguen permitidos. Variantes: 20 intentos
diarios por tienda persistidos ANTES de consultar. Todo configurable, no es un ritmo seguro medido.

## JSONL: contrato exacto

`output/barrido/<store>-AAAA-MM-DD.jsonl`; una fila por (store,id). Campos de primer nivel:

| Campo | Tipo y significado |
|---|---|
| schema_version | entero 1 |
| store, id | US/ES, ASIN |
| observed_at, date | timestamp ISO -03:00 y fecha ART |
| title | string o null |
| currency | USD/EUR |
| price, price_usd | número positivo local/convertido o null |
| exchange_rate | {value,source,observed_at}; USD identidad 1 |
| condition | new o null; Amazon evidencia del filtro nuevo aplicado |
| shipping_text | texto crudo o null |
| shipping_class | gratis/pago/no_envia/desconocido/envia_costo_desconocido |
| located_ar | booleano, sesión exacta confirmada AR |
| has_variations, variations_text | booleano/string o null si ausentes |
| variations | respuesta cruda o null |
| known | booleano, identidad del catálogo suministrado |
| eligible | booleano para adquisición posterior; NO autoriza publicación |
| rejection_reasons | lista de strings |
| provenance | lista de {category_id,category_name,page,url} |
| raw | objeto completo parser/API; Amazon incluye card_html |

raw conserva marca, lista, cupón, opciones, reseñas, estrellas, comprados, patrocinado, imagen y links
si existen. HTML evita pérdidas del parser. Precio ausente/fuera de rango, moneda errónea, condición
no nueva o envío desconocido deja eligible=false y motivo; se conserva como evidencia.
Ausencia de has_variations es null. Variantes sólo si eligible y hay indicio; cap persistente diario.

## Ubicación y envío compartidos

ships=False → no_envia; ships=None → desconocido; ships=True/free=True → gratis;
ships=True/free=False → pago; ships=True/free=None → envia_costo_desconocido. No inventar costo.
parse_delivery conserva compatibilidad histórica de amazon-ar; adaptador de tarjetas exige evidencia
de costo para pago. Una tarjeta sin Argentina sólo sirve con sesión exacta confirmada AR; ubicación
fallida deja desconocido. No tomar ubicación de otro idioma/sesión. Negativos explícitos predominan.
ES incluye «no se puede enviar», «no se envía», «ENVÍO GRATIS», «entrega GRATIS», «envío de 6,99 €»,
«6,99 € de envío» y «pedidos superiores a 99 €». Prime no equivale a envío AR.

## Adquisición y dry-run

Transporte/parser MIT versionados desde 8ffd4f976c705d009ec06d8e4e3e15fc77e35cee; UPSTREAM.md y
hashes conservan origen/cambios. Directo, sin proxies. Una consulta lógica por página con nodo,
low-price/high-price, condición nueva descubierta, page y fs=true. Filtro AR sólo si observado explícito.
Preconsulta una vez por contexto. Cache JSON {context,refinements,observed_at} por fecha ART, tienda,
nodo, idioma y destino AR. Falta condición nueva: falla. Falta filtro AR: log y clasificación por tarjeta.
--refresh-refinements invalida cache. Si Amazon cambia filtros, invalidar con esa opción.
DRY-RUN obtiene sólo página 1 filtrada por categoría (+preconsulta si falta cache), imprime count,
total_pages y cantidad de categorías; no variantes ni checkpoint de producción. No estima duración
ni exhaustividad. total_pages es máximo visible, no total independiente. Seguir next habilitado;
Sin paginación ni next, la página de resultados es la última; cero resultados registra
`BARRIDO_CATEGORIA_VACIA`. Repetición de secuencia ASIN/página incorrecta → parcial con error explícito.
No fijar límite arbitrario de páginas. Tope de operador → parcial, nunca completo.
## Paso ML: `ml-lookup` (R6)

Se ejecuta después de Amazon US y ES (ES sólo con tasas del mismo día). Lee exclusivamente
`US-AAAA-MM-DD.jsonl` y `ES-AAAA-MM-DD.jsonl` del día ART actual, nunca archivos anteriores.
Deduplica por (store, ASIN), exige fecha/tienda coincidentes, `price_usd` finito en 100–400
(inclusive) y `shipping_class` en `gratis` o `desconocido`. Se incluye `desconocido` porque la tarjeta
de búsqueda puede omitir el envío: buscar una contraparte no confirma elegibilidad. Sólo `gratis`
sigue siendo elegible y la confirmación posterior de envío a Argentina sigue siendo obligatoria.
Se omiten `pago`, `no_envia`, `envia_costo_desconocido` y precios ausentes/fuera de rango.

Consulta la API oficial `/products/search?status=active&site_id=MLA&q=<consulta>`:
primero marca + código de modelo extraído del título completo (incluye paréntesis como S36GD),
y, si no hay candidatos con oferta local, título limpio. Consultas repetidas se deduplican.
Máximo cinco productos de catálogo distintos consultados por fila Amazon, entre ambas consultas.
Para cada uno recorre `/products/{id}/items`, elige la oferta más barata con `condition=new`,
`currency_id=ARS`, precio positivo finito y sin CBT/internacional. Usa `get_json`, `cheapest_new`
y `is_international` compartidos de `ml_prices`; no usa `find_ml_candidates` porque oculta errores
ni `clean_title_for_ml` porque elimina el modelo entre paréntesis y vive fuera de la imagen worker.
El precio USD es ARS multiplicado por la tasa inversa MEP validada y congelada para el día.
404 «no winners» significa sin oferta; otros errores conservan el literal, nunca simulan vacío.

Salida `output/barrido/ml-candidatos-AAAA-MM-DD.jsonl`, una fila por (store, ASIN):

```json
{"store":"US","asin":"B0EJEMPLO1","amazon_title":"Samsung S36GD","amazon_price_usd":200,"shipping_class":"desconocido","queries_used":["Samsung S36GD"],"candidates":[{"catalogId":"MLAEJEMPLO","name":"Samsung S36GD","price_ars":200000,"price_usd":200,"itemId":"MLA1001","condition":"new"}],"lookup_status":"ok","error":null}
```

Ejemplo sintético, no precio medido. `lookup_status`: `ok`, `sin_resultados` o `error`;
`error` contiene el literal completo en fallas y null en los otros estados. Una falla descarta
candidatos parciales de esa fila. Estado en `state/AAAA-MM-DD/ml-lookup/records`, usando el módulo
`state`: registro atómico antes de reconstruir el JSONL atómico, sin append ni duplicados.
Filas `ok`/`sin_resultados` no se reconsultan; `error` se reemplaza al reintentar ese ASIN.
Un corte entre registro y materialización se recupera sin nueva consulta. El mismo ASIN de US y ES
conserva dos filas. El archivo es entrada futura del matcher (tarea 10), sin conectar todavía.

`--step ml-lookup [--date AAAA-MM-DD] [--limit N] [--dry-run]`. La fecha sólo puede ser hoy ART;
se comprueba también durante las consultas. `--limit` limita productos pendientes por ejecución;
con `--dry-run` toma sólo las primeras N filas filtradas (5 por defecto), imprime consultas y
cantidades, sin crear lock, estado ni archivo oficial y sin usar checkpoints de producción.
Pausa `ml_pause` antes de cada pedido. 403/429 corta inmediatamente todo el paso, registra la fila
con error y permite reanudarla. Sin reintentos internos ante bloqueo.

Cada línea lleva hora ART: `BARRIDO_ML_BUSQUEDA` (asin, consulta, candidatos de búsqueda,
segundos), `BARRIDO_ML_ERROR` (asin, motivo literal, http), `BARRIDO_ML_BLOQUEADO` (mismos campos)
y al terminar `BARRIDO_ML_OK` (total, con_candidatos, sin_resultados, errores), incluso si hubo
fallas. Este evento resume contadores: el estado y el código de salida determinan el resultado.
Bloqueo, errores pendientes o límite con filas pendientes producen salida no cero; el límite
registra `BARRIDO_ML_LIMITE`. No se afirma cuota real desde fixtures.

## Persistencia y observabilidad

Estado diario `output/barrido/state/AAAA-MM-DD/<store>`. Página JSON atómica inmutable antes del
checkpoint (siguiente página). Página es fuente de verdad: corte antes de checkpoint se recupera.
JSONL atómico reconstruido, sin append; deduplica y acumula provenance. Configuración y tasas
fijadas por día/tienda; se admiten subconjuntos de nodos compatibles y ampliar el alcance.
Los conocidos se recalculan con `catalog.json` y `catalog-auto.json` en cada ejecución y no se congelan.
Día nuevo comienza página 1. Lock exclusivo con PID y hora de inicio; se recupera con
`BARRIDO_LOCK_HUERFANO` si el proceso murió o superó `max_run_hours` (8 por defecto).
`resumen-AAAA-MM-DD.json` con estados por tienda y métricas por categoría: páginas, productos,
en rango, `envio_gratis`, `envio_pago`, `envio_desconocido`, `no_envia`, fallas y segundos.
Sólo envío gratis confirmado es elegible; pago y costo desconocido se rechazan con
`envio_pago` y `envio_costo_desconocido` y no consumen variantes.
Cada categoría fallida conserva error literal y estado `failed`; las otras continúan y la tienda queda `partial`.
Ubicación AR se intenta una vez por sesión; una excepción registra `BARRIDO_UBICACION_FALLIDA`
y deja el envío desconocido. Si más del 50% de páginas carece de ubicación confirmada, la tienda
queda `partial`, razón `ubicacion_ar_no_confirmada`; umbral configurable con `unlocated_page_ratio`.
Se persiste la ubicación por página para conservar ese diagnóstico al reanudar.
Cada línea propia lleva timestamp ART ISO y campos JSON. BARRIDO_PAGINA: tienda,categoria,pagina,
de (null si desconocido),productos,segundos,http (real o null). BARRIDO_HTTP observa intentos sin
credenciales. BARRIDO_ERROR/BARRIDO_BLOQUEADO: motivo literal completo, tipo, HTTP disponible;
saltos de línea escapados. Bloqueo tras N termina esa categoría; página fallida no avanza. Reanudar
mismo día desde primera no confirmada. BARRIDO_OK sólo completo; parcial/fallido BARRIDO_FALLA y
exit CLI no cero. No fabricar datos si /s sigue bloqueado.

## Servicio y tarea 10 posterior

Cuarto servicio weboffers-barrido, contexto worker, red interna compose, sin puertos publicados,
output persistente, catálogo read-only y credenciales por entorno. tools/probar_scraper.py sigue único
ingreso manual: control ASIN, moneda correcta, errores completos y paginación anidada; hook intacto.
Endpoint barrido/probe ejecuta dry-run. Sin cron nuevo.
Tarea 10 futura: barrido → adaptar JSONL a candidatos con ml → alta → Chrome → confirmar altas →
Amazon → ML → deploy. --tras-alta no reingresa. Cambiar maybe_grow/run_once sólo entonces; matching
requiere candidatos ml y publicación sigue exigiendo ambos precios de hoy y envío confirmado.
No tocar tools/cadena.py, worker/catalog_auto.py ni worker/worker.py ahora. No retirar fuente vieja
hasta comparar cobertura/cantidad publicada. Esta entrega no cambia cantidad publicada ni despliega.

## Validación

Tests worker/barrido/test_*.py y worker/test_probar_scraper.py; fixtures sintéticos rotulados (NO
mediciones reales), sin red. Esquema, cache, URL, US/ES, tasas vencidas, ofertas ML, corte antes de
checkpoint, lock, dedup, nuevo día, backoff, bloqueo aislado y variantes persistentes cubren A1–A5.
`python -m pytest worker -q -p no:cacheprovider` verde. A6 pendiente en VM: build, categoría US
completa, ES, reinicio y cinco comparaciones tarjeta/ficha. Si sigue bloqueo registrar literal y no
afirmar aceptación real. Errores no autorizan publicación ni relleno con días anteriores.
