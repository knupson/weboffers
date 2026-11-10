# Operación y validación pendiente

Esta entrega agrega adquisición independiente. No encadena ni despliega el flujo nuevo.
No modifica el catálogo, offers.json ni la cantidad publicada. La comparación real de cobertura y
cantidad publicada corresponde a la tarea 10 antes de retirar las fuentes anteriores.

Desde `/opt/docker/franquicia400` en la VM, con estos archivos ya copiados al checkout:

```sh
docker compose -f worker/docker-compose.yml build weboffers-barrido weboffers-chrome-cdp
docker compose -f worker/docker-compose.yml up -d weboffers-barrido
docker compose -f worker/docker-compose.yml exec -T weboffers-barrido python -m barrido --store US --category 541966 --dry-run
```

La consulta usa sólo la primera página filtrada de esa categoría; si falta cache realiza antes
una preconsulta de refinamientos. Imprime count y total_pages. No pide variantes ni avanza checkpoint.
Con bloqueo hace tres intentos lógicos con pausas 30 y 60 s; termina con BARRIDO_BLOQUEADO,
el error literal y código no cero. No inventa una corrida exitosa ni toma datos de ayer.

Ingreso HTTP desde la herramienta manual ya autorizada, desde el checkout local:

```sh
ssh docker 'docker exec -i -w /app franquicia400-weboffers-worker-1 python - barrido/probe country=US node=541966' < tools/probar_scraper.py
```

Una corrida completa se ejecuta con el mismo comando CLI sin `--dry-run`. `--max-pages 1` permite
probar reanudación y deja estado parcial si quedan páginas. Repetir sin ese límite continúa.
El rango real es siempre USD 100–400; sólo `--dry-run` permite cambiarlo. Cambios de políticas
o de la definición de un nodo existente requieren otro `--output`. Se puede ampliar el conjunto
de nodos o correr `--category` y después la corrida completa. Los conocidos se recalculan leyendo
`ml.catalogId` y ASIN de ambos catálogos; `catalog-auto.json` se busca junto al directorio del barrido
(por defecto `/app/output/catalog-auto.json`) o en `--catalog-auto`.
`--refresh-refinements` fuerza redescubrimiento del cache diario. El lock guarda PID y hora;
se recupera automáticamente si murió el proceso o superó `--max-run-hours` (8 horas por defecto),
registrando `BARRIDO_LOCK_HUERFANO`.

ES corre sólo los días en que oficial y EUR tienen cotización del mismo día ART. Durante fines
de semana o feriados pueden seguir con fecha del último día hábil: se rechazan, se registra
`BARRIDO_ES_SIN_COTIZACION fecha_recibida=<fecha literal>` y ES queda `skipped`; las otras tiendas
continúan. No se rellenan tasas viejas. `skipped` no provoca error de salida por sí solo.

Una categoría fallida registra `BARRIDO_ERROR` con el error literal y no interrumpe las restantes;
la tienda queda `partial`. Los timeouts, conexiones y 5xx tienen reintentos separados de bloqueos.
Hay pausa antes de cada categoría y después de la preconsulta de refinamientos.
Más de la mitad de páginas sin ubicación AR confirmada deja `partial` con
`ubicacion_ar_no_confirmada`; se ajusta con `--unlocated-page-ratio` (0,5 por defecto).

Validación exclusivamente en el contenedor de la VM, con las dependencias de pruebas instaladas:

```sh
python -m pytest worker -q -p no:cacheprovider
```

La PC se usa para escribir y coordinar. No ejecutar tests, sondeos ni el barrido en Windows.

## Respaldo de búsquedas con Chrome (07/11/2026)

`BARRIDO_CHROME_CDP=http://weboffers-chrome:9222` habilita el respaldo exclusivamente para `/s`,
después de agotar las sesiones configuradas del transporte y recibir un bloqueo. Sin esa variable,
el comportamiento anterior se conserva. Los errores transitorios del transporte no activan Chrome.
Cada página conserva sus filtros, rango de precio y paginación; el parser y las verificaciones
de envío por tarjeta siguen siendo los mismos. Un filtro de envío gratis nunca prueba por sí solo
que el producto tenga envío gratis a Argentina. `BARRIDO_FILTROS` informa los identificadores por categoría;
la caché de refinamientos tiene versión nueva para redescubrir el filtro aun si la anterior no venció.

Playwright sólo se conecta por `connect_over_cdp`: no se descarga un navegador en el worker,
no se ejecuta `playwright install` y no se crean contextos de incógnito. La conexión reutiliza el
contexto persistente y una pestaña, sin paralelismo. Las pausas de refinamientos y entre páginas
siguen a cargo del runner. Al terminar una tienda se desconecta Playwright sin cerrar Chrome.
El perfil exclusivo queda en `worker/chrome-barrido/`, excluido de Git y del contexto de build.

Antes de la primera búsqueda se lee `#glow-ingress-line2`. Si no dice Argentina, se usa el flujo glow
de `amazon_shipping.apply_ar_location`: GET del modal, token CSRF del modal y POST a `address-change`
con `locationType=COUNTRY`, `district=AR`, `countryCode=AR`. Ese adaptador no usa código postal:
no se toma el código local US/ES de `sites.py`. Además de exigir éxito en la respuesta, se recarga y
se verifica Argentina en la cabecera. Se vuelve a comprobar en cada búsqueda. Si no se confirma,
`BARRIDO_UBICACION_FALLIDA` detiene esa tienda sin procesar su página; las otras tiendas pueden continuar.

La imagen fijada de LinuxServer usa 1 GiB de memoria y 1 GiB de shm según el pedido. No publica
puertos al host. Hay reportes de [CDP escuchando sólo en loopback pese al flag de dirección](https://github.com/linuxserver/docker-chromium/issues/71),
y el [reporte de Chrome exige un user-data-dir propio](https://github.com/linuxserver/docker-chrome/issues/11).
Por eso `weboffers-chrome-cdp` comparte el namespace de red de Chrome y usa socat desde la IP interna
del contenedor en 9222 hacia `127.0.0.1:9222`; el bind específico no disputa el puerto de loopback.
No se depende de `--remote-debugging-address=0.0.0.0`. La exposición efectiva del digest debe verificarse
en la VM con el procedimiento de abajo. El discovery CDP usa Host localhost y reemplaza la autoridad
del WebSocket anunciado por la del endpoint configurado, para no conectar al loopback del worker.

`BARRIDO_CHROME_INICIO` y `BARRIDO_CHROME_FIN` registran URL, motivo del respaldo y, al terminar,
milisegundos, bytes de HTML, HTTP, motivo de bloqueo y clase de error. No incluyen cookies ni tokens.
Si Chrome devuelve perros, captcha o WAF, se conserva el tratamiento de bloqueo del runner.

Validación en la VM, desde la raíz del checkout actualizado (no ejecutada en la PC):

```sh
docker compose -f worker/docker-compose.yml config --quiet
docker compose -f worker/docker-compose.yml build weboffers-barrido weboffers-chrome-cdp
# La imagen productiva no trae pytest: contenedor efímero, sin iniciar el servidor ni Chrome.
docker compose -f worker/docker-compose.yml run --rm --no-deps weboffers-barrido sh -c 'pip install --no-cache-dir pytest && python -m pytest /app/barrido -q -p no:cacheprovider'
docker compose -f worker/docker-compose.yml up -d weboffers-barrido
# Listener nativo de Chrome, desde su propio namespace.
docker compose -f worker/docker-compose.yml exec -T weboffers-chrome curl --fail --silent http://127.0.0.1:9222/json/version
# Listener del sidecar desde el worker: también valida DNS/red y el Host de discovery.
docker compose -f worker/docker-compose.yml exec -T weboffers-barrido python -c 'import requests; r=requests.get("http://weboffers-chrome:9222/json/version", headers={"Host":"localhost:9222"}, timeout=10); r.raise_for_status(); print(r.json()["Browser"])'
docker compose -f worker/docker-compose.yml exec -T weboffers-barrido python -m barrido --store US --category 541966 --dry-run --refresh-refinements
```

Las pruebas usan fixtures sintéticos de sidebars US/ES, ubicación, resultados y bloqueo; simulan
CDP y prohíben tanto las solicitudes HTTP como las conexiones Playwright reales. Instalar pytest
requiere red durante la preparación del contenedor efímero; las pruebas mismas no la usan.
Para verificar el fallback real, el dry-run debe mostrar el agotamiento del transporte seguido
de `BARRIDO_CHROME_INICIO/FIN` y `BARRIDO_FILTROS` con `p_n_is_free_shipping`. Si el transporte responde,
esa corrida no verifica Chrome. Revisar `ubicacion_ar`, envío y contadores; no tomar los fixtures
como una medición de cobertura. Este cambio no publica productos ni modifica el catálogo en producción.

Pendiente de aceptación real A6: build en VM, US completo, ES, reinicio real, verificar cinco pares
tarjeta/ficha y procedencia/alcance de nodos iniciales. Los fixtures son sintéticos rotulados.
La cuota ML, cobertura de nodos, tasa tolerable y coincidencia tarjeta/ficha no se deducen de tests.

## R6 — ML busca contrapartes de Amazon (decisión 07/11)

Ya no se ejecuta `--store ML`: no hay categorías ni destacados de ML en este barrido.
El producto se compara porque existe en Amazon entre USD 100 y 400. Orden completo, ejecutando
cada paso cuando termina el anterior: Amazon US, Amazon ES si hay cotizaciones del día, `ml-lookup`.
Desde worker (o dentro del servicio `weboffers-barrido`):

```sh
python -m barrido --store US
python -m barrido --store ES
python -m barrido --step ml-lookup
python -m barrido --step ml-lookup --date 2026-11-07 --limit 5 --dry-run
```

La fecha de ejemplo debe reemplazarse por hoy ART. ES sin tasas del día queda `skipped`;
ML exige MEP del día aunque ES se omita. Los comandos no instalan scheduler ni conectan tarea 10.
Mediciones del 07/11 conservadas: `/highlights/MLA/category/...` y `/products/search` dieron 200;
`/sites/MLA/search` con categoría+precio dio 403. El primer endpoint deja de usarse por decisión
de diseño. Amazon `/s` desde VM dio `503 dogs page (after 4 sessions)` y `/dp` funcionó.
Estos hechos no establecen una cuota ni garantizan disponibilidad actual.

Entrada: JSONL Amazon US/ES de hoy. Sólo USD 100–400 y envío `gratis` o `desconocido`.
`desconocido` entra porque la tarjeta puede omitir el envío; sólo `gratis` sigue siendo elegible
más adelante. No se publican candidatos por haber encontrado una oferta ML.
Salida: `ml-candidatos-AAAA-MM-DD.jsonl`. Revisar consultas/modelos, precio ARS, conversión MEP,
identidad de oferta y estado por fila. Máximo cinco catálogos distintos por producto Amazon.
`--limit N` procesa N pendientes; repetir sin límite continúa. Si quedan filas, el estado es
parcial y devuelve código no cero. El dry-run usa primeras N filas
filtradas (5 por defecto), hace consultas reales y no escribe el archivo oficial ni checkpoints.

Reanudar con el mismo comando, directorio y fecha: conserva ?xitos y ausencias confirmadas,
reintenta errores y reconstruye sin duplicados. Un 403/429 corta el paso con
`BARRIDO_ML_BLOQUEADO`, cuerpo literal y HTTP. Resolver el bloqueo antes de reanudar; nunca
interpretarlo como cero resultados. `--ml-pause` controla la pausa entre pedidos.
Los logs llevan hora ART y terminan con contadores de productos con candidatos, sin resultados
y errores; un paso bloqueado o con errores devuelve código no cero.

Pruebas: ejecutar la suite en el contenedor de la VM. La entrega de observabilidad no ejecutó
tests ni programas del producto en la PC.

## Observabilidad exhaustiva (07/11)

Cada evento tiene hora ART ISO 8601, nombre y un objeto JSON en una sola línea.
Los saltos de línea de errores y pilas se escapan dentro del JSON. Cada corrida tiene `run_id`
y PID; cada pedido tiene `request_id`. Los IDs de sesión son identificadores locales aleatorios,
sin cookies ni tokens reales. El mismo evento se escribe en stdout y en el archivo persistente.

| Archivo | Contenido |
|---|---|
| `/app/output/logs/barrido-AAAA-MM-DD.log` | Todos los eventos de adquisición, append y fecha ART del evento; rota al pasar medianoche |
| `/app/output/barrido/latido.json` | Último `BARRIDO_LATIDO`, reemplazado atómicamente con un temporal en el mismo directorio |
| `/app/output/barrido/resumen-AAAA-MM-DD.json` | Resumen por tienda y tasas de comparaciones cuando tarea 10 las informe |
| `/app/output/barrido/state/…` | Evidencia diaria, páginas, checkpoints y candidatos ya existentes; el HTML permanece en la evidencia de página |

El servicio ya monta `worker/output:/app/output`. En el host de la VM los primeros dos archivos
quedan en `/opt/docker/franquicia400/worker/output/logs/` y `…/output/barrido/`.
Con `--output` personalizado, el log queda en `<output>/../logs/` y el latido en `<output>/latido.json`.
También los dry-runs escriben telemetría; no escriben evidencia oficial ni checkpoints ML.
No borrar el directorio montado al recrear el contenedor. El append conserva las corridas anteriores.

Lectura, dentro del contenedor que ejecuta el barrido (importa para el espacio de PID):

```sh
python -m barrido.logs
python -m barrido.logs --fecha 2026-11-07 --desde 17:00
python -m barrido.logs --output /app/output/barrido
```

Devuelve JSON con la secuencia de inicios/finales por etapa, pedidos por minuto, segundos de
espera por motivo, descartes por motivo, errores/bloqueos con el literal disponible, último
latido y estado de la corrida. Una línea truncada queda señalada con su número y literal;
no se pierde el resto del archivo. `--desde HH:MM` filtra por hora ART inclusive; puede dejar
el inicio de una etapa afuera del intervalo. El estado usa el último latido del intervalo:
`finalizado`, `no_vive`, `vivo`, `vivo_sin_avance`, `sin_latido`,
`latido_vencido_identidad_no_confirmada` o `sin_permiso_para_verificar_pid`.
Un PID reutilizado después de reiniciar no prueba que siga viva la corrida: un latido de más
de 120 s se informa como identidad no confirmada. No consultar PID desde otro contenedor.

| Evento | Qué explica |
|---|---|
| `BARRIDO_PROCESO_INICIO/FIN` | Versión/commit al inicio, hash de configuración, argumentos, PID y estado final; el fin incluye el estado completo |
| `BARRIDO_ETAPA_INICIO/FIN` | `amazon_us`, `amazon_es`, `ml_lookup`; duración y diferencias de contadores de la etapa |
| `BARRIDO_HTTP_INICIO/FIN` | Tienda, etapa, categoría, página/ASIN, método, path y parámetros permitidos, sesión, intento lógico y de transporte, AR confirmado, status, bytes, ms y bloqueo |
| `BARRIDO_REDIRECCION` | Cada salto HTTP, antes de seguirlo; cada destino tiene su propio par de eventos HTTP |
| `BARRIDO_SESION`, `BARRIDO_SESION_FALLA`, `BARRIDO_ROTACION`, `BARRIDO_CAMBIO_SALIDA` | Creación, causa literal de falla, descarte y eventual cambio de salida del vendor |
| `BARRIDO_CALENTAMIENTO_INICIO/FIN` | Obtención de cookies/token y resultado o causa de falla |
| `BARRIDO_UBICACION_INICIO/FIN`, `…_OMITIDA`, `…_FALLIDA`, `…_DESCONOCIDA` | Pedido de AR, confirmación, motivo de omisión/falla y evidencia insuficiente |
| `BARRIDO_CAPTCHA_INICIO/FIN`, `BARRIDO_POW` | Click en continue shopping, resultado y resolución del intersticial; sus pedidos también pasan por HTTP |
| `BARRIDO_ESPERA`, `BARRIDO_ESPERA_FIN` | Segundos previstos, motivo (`pausa_entre_paginas`, `pausa_refinamientos`, `pausa_ml`, `backoff_bloqueo`, `backoff_transitorio`) y hora ART de final previsto |
| `BARRIDO_REINTENTO`, `BARRIDO_ERROR`, `BARRIDO_BLOQUEADO` | Error literal, HTTP, clasificación y reintento o agotamiento |
| `BARRIDO_DESCARTE`, `BARRIDO_CONSERVADO` | ASIN, motivo y valor causante; incluye filtros de entrada ML y cada oferta ML evaluada |
| `BARRIDO_PAGINA_CONTADORES`, `BARRIDO_PAGINA` | Conservados y descartados, desglose por motivo, volumen y duración de la página |
| `BARRIDO_ML_PAGINA_CONTADORES` | Ofertas válidas y descartadas por motivo en cada página ML, antes de elegir la más barata |
| `BARRIDO_PERSISTIDO` | Finalizó la escritura de página/checkpoint o candidatos ML |
| `BARRIDO_ML_BUSQUEDA`, `BARRIDO_ML_PRODUCTO`, `BARRIDO_ML_OK` | Consulta, cantidad de candidatos, resultado de cada ASIN y resumen del lookup |
| `BARRIDO_LATIDO` | Cada 60 s, etapa/tienda/categoría/página/ASIN, acción y segundos en ella, pedido actual, contadores y segundos sin avance |
| `BARRIDO_SIN_AVANCE` | Desde `--stall-seconds` (300 por defecto), estado completo y pila real del hilo principal, repetido cada latido mientras continúe |
| `BARRIDO_EXCEPCION`, `BARRIDO_CORTADO` | Traceback completo antes de salir; SIGTERM/SIGINT con nombre de señal y estado actual |
| `BARRIDO_CATEGORIAS`, `BARRIDO_CATEGORIA_VACIA`, `BARRIDO_VARIANTES`, `BARRIDO_LIMITE` | Alcance, categoría sin filas, pedido de variantes y límite manual |
| `BARRIDO_ES_SIN_COTIZACION`, `BARRIDO_LOCK_HUERFANO`, `BARRIDO_OK/FALLA`, `BARRIDO_ML_LIMITE` | Tasa rechazada, recuperación de lock y resultado o límite del paso |

`intento` es el intento lógico del runner; `intento_transporte` cuenta las vueltas internas de
`_request`. Un calentamiento y una búsqueda pueden compartir intento, con distintos request IDs.
Las cotizaciones también tienen eventos HTTP (`tienda=COTIZACION`, contador `requests_other`),
sin inflar `requests_amazon` ni `requests_ml`. ML incluye el POST de OAuth y cada página de ofertas.
Las redirecciones se siguen explícitamente para registrar todos los saltos; se quitan Authorization
y Cookie al cambiar de host. El formulario captcha conserva su política de no seguir redirecciones.

Los contadores de etapa incluyen `requests_amazon`, `requests_ml`, `products`, `eligible`,
`ml_candidates` y `comparisons` (reservado para tarea 10), además de errores, bloqueos y consultas.
Los descartes por motivo pueden sumar más que las filas descartadas: una fila puede fallar por
precio y envío. `ya_conocido` en Amazon tiene `alcance=novedades` y un contador separado:
conserva la evidencia diaria. En ML significa lookup ya confirmado. Duplicados se conservan en
la evidencia de página y se unifican al materializar, como antes.
Las tasas `comparaciones_por_consulta` y `comparaciones_por_minuto` son `null` hasta contar con
comparaciones. No se interpreta una ausencia como cero comparaciones medidas.

El latido no cuenta como avance. Una espera intencional mayor al umbral también puede producir
`SIN_AVANCE`: la acción y su `hasta` explican por qué. El estado actual incluye el pedido en curso,
por lo que un HTTP sin respuesta no queda oculto hasta su timeout.
El servidor HTTP ocioso emite latidos con `observando_avance=false`: no genera alertas por
inactividad ni sobrescribe `latido.json` de una adquisición por CLI. Al atender un barrido se
habilita nuevamente el control de avance. El lector prioriza los latidos de adquisición.
SIGKILL, caída del host o corte eléctrico no permiten ejecutar un handler: quedan el último
inicio HTTP/latido y la falta de fin. El lector informa esa evidencia sin inventar la causa.

No se registran headers, cuerpos HTTP, HTML, cookies ni credenciales. Los parámetros usan una
lista permitida; los desconocidos se reemplazan por `[OCULTO]`. Los errores JSON de ML conservan
el literal con secretos redactados; una respuesta HTML no se copia al error. No hay fsync por
evento: se vacía y cierra el archivo en cada línea; la durabilidad frente a corte eléctrico
depende del sistema de archivos del host.
Si falla la escritura del log, `BARRIDO_LOG_ERROR` informa el error en stdout y se sigue emitiendo
el evento original; un fallo de escritura del latido produce `BARRIDO_EXCEPCION` con origen `latido`.

Identidad de imagen: al construir en la VM, pasar `BARRIDO_GIT_COMMIT` con el SHA del checkout.
Compose lo transmite como argumento de build y la imagen lo conserva. Sin ese dato se registra
`no_disponible`, junto con `version=observabilidad-v1`; no se inventa un commit.

Pruebas nuevas: `worker/barrido/test_observability.py`. Cubren inicio antes del transporte,
pares HTTP, secretos, OAuth, dogs con sesión nueva y reintento, pausas, latido sin espera real,
archivo atómico, pila principal, señales simuladas, traceback, append/medianoche ART, resumen
y lector. La fixture `fixtures/observabilidad.log` muestra una página simulada con bloqueo/reintento.
Ejecutar en la VM la suite de `worker` para cubrir además los callers compartidos de `ml_prices`.
