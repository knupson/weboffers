# Barrido diario: contrato v1 (07/11/2026)

## Alcance

Adquisición diaria independiente US, ES y ML. «Todos» significa resultados accesibles de nodos
configurados, no exhaustividad de catálogo. Nuevo es condición nueva; conocidos también se guardan.
No publica ni modifica el catálogo actual. Tareas 1–9 y 11; integración (tarea 10) pendiente.
Medido 07/11: ML highlights y products/search 200, sites/MLA/search categoría+precio 403;
Amazon /s desde VM: `503 dogs page (after 4 sessions)`; /dp funciona. No eludimos ese bloqueo.

## Configuración

`categorias.json`: `{version:1, stores:{US:{nodes:[{id,name,kind:"root"|"leaf"}],exclude:[id]},ES:...,ML:...}}`.
Nodos Amazon explícitos: root se consulta tal cual, SIN expansión implícita. Para particionar se
versionan hojas. ML expande raíces por /categories/{id} hasta hojas, excluye subárboles y deduplica.
La lista inicial es configurable y no garantiza cobertura total. Los nodos iniciales US/ES deben
validarse en la primera consulta real; los refinamientos se descubren en ejecución, nunca se inventan.
Rango real fijo USD 100–400; `--min-usd`/`--max-usd` sólo se admiten con `--dry-run`.
US USD; ES EUR con límites locales redondeados hacia afuera al centavo
y validación final USD; ML ARS/MEP, filtro después de ofertas. La fuente vieja ML abarca 60–2400:
medir cobertura antes de retirarla. Cotizaciones positivas, finitas y de HOY ART con fuente/fecha.
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
| store, id | US/ES/ML, ASIN o ID catálogo ML |
| observed_at, date | timestamp ISO -03:00 y fecha ART |
| title | string o null |
| currency | USD/EUR/ARS |
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
no nueva o envío desconocido deja eligible=false y motivo; se conserva como evidencia. ML exige
oferta ARS explícita, condition=new, sin CBT; shipping_class sale de shipping de oferta local.
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
ML: highlights/MLA/category/{cat} → PRODUCT → products/{id} y products/{id}/items paginado.
No sites/MLA/search. products/search queda para matching futuro. Conservar respuestas, deduplicar
IDs y procedencias. La respuesta highlights completa se guarda una vez por página; cada fila guarda
sólo su entrada propia. Highlights no es catálogo exhaustivo. 401/403/429/error: falla visible con cuerpo
literal, no lista vacía. Sin MEP de hoy falla ML; no se prueba cuota real desde fixtures.

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
