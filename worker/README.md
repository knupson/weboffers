# Worker de datos

Requiere Python 3.12, `requests` y `Pillow`. Desde `worker/`:

```sh
python -m pip install requests Pillow pytest
python -m pytest -q --basetemp=.pytest_tmp -o cache_dir=.pytest_cache
python -u worker.py
```

Con Docker: `docker compose up -d --build`. La salida queda en
`worker/output/offers.json`; el catálogo se monta desde `../data` como solo lectura.

Todas las noches, entre las 20:00 y las 03:00 ART, el ciclo descubre pares de
Amazon y ML. El alta tiene dos fases:

1. El worker valida los pares de USD 100–400, obtiene la foto oficial de ML
   convertida a WebP (lado máximo 900) y guarda las entradas completas con
   `pendienteDesde` en `output/altas-pendientes.json`. Deduplica ASIN, slug y
   catalogId contra el catálogo, el automático y los pendientes. No los publica.
2. La cadena del host incluye los pendientes en la única pasada del Chrome real
   de la VM. Inmediatamente después, el paso `altas` ejecuta
   `python /app/tools/confirmar_altas.py` dentro del worker. Sólo promueve a
   `output/catalog-auto.json` si Chrome confirmó hoy envío gratis a Argentina y
   precio USD 100–400. Guarda `shipsToAr.freeShipping` y `shipsToAr.checked`.
   Amazon y ML relevan luego los precios para el deploy de esa misma noche.

Envío pago, ausencia de envío y precio fuera de rango quitan el pendiente y
guardan `{fecha, motivo, texto}` por ASIN en `output/altas-rechazadas.json`.
Ambos descubrimientos saltean esos ASIN durante 14 días. Si Chrome no dio datos,
el pendiente sigue: se cuenta una vez por fecha ART con `nochesSinDato` y
`ultimoIntentoEnvio`; al tercer día sin dato se rechaza con `sin_dato_3_noches`.
No se modifica ni migra ninguna entrada automática existente. Los cambios de
estado comparten `output/altas.lock` para evitar escrituras simultáneas.

Para confirmar un alta forzada con `tools/crecer_ahora.py` durante el día,
ejecutá en el host `sh tools/confirmar_altas.sh`: releva sólo pendientes y llama
a la misma promoción. Fusiona los resultados en `ar-chrome-AAAA-MM-DD.json`
sin borrar los otros ASIN del día. El worker no intenta conectarse al Chrome ni
usa amazon-ar para confirmar estas altas. La publicación sigue exigiendo los
dos precios de hoy y envío gratis confirmado.

Las fotos quedan en `output/products/`. `output/catalog-auto-state.json`
registra el intento antes de consultar, con un slot por noche (o por alta
forzada). `CATALOGO_OK` informa `pendientes=N`; cada par registra su decisión y
evidencia con horario ART. La promoción resume
`ALTAS_OK promovidas=X rechazadas=Y siguen_pendientes=Z`.

`CATALOG_AUTO_MAX_PAGES` permite fijar el tope de páginas de la corrida; sin
configurarlo, el descubrimiento termina al agotar las fuentes. Se usa la pausa
vigente de precios, backoff de 120 s ante vacío y una
pausa de 300 s cada 100 páginas. Las fallas salen por `DEPLOY_FAIL` y quedan en
el registro `amazon-run-<fecha>.json`, con `kind: "catalogo"`.

Worker y deployer fusionan ambos catálogos por ASIN o slug; siempre manda el
repositorio. El deployer copia las fotos antes del build sin pisar las existentes.
Para absorber las altas al repo desde Git Bash: `bash tools/sync_catalogo_auto.sh`.
Usa `ssh docker` y `/opt/docker/franquicia400/worker/output`; no hace commit ni push.

`CHECK_INTERVAL_SECONDS` vale 3600 por defecto. `CATALOG_PATH` acepta una ruta
absoluta o relativa a `worker/` y vale `../data/catalog.json` por defecto.
`OUTPUT_PATH` sigue la misma regla y vale `output/offers.json`.
SIGTERM y SIGINT solicitan el cierre al terminar el ciclo activo. Las llamadas
HTTP tienen timeout y los mensajes se imprimen inmediatamente.

Configurá `CREATORS_CLIENT_ID`, `CREATORS_CLIENT_SECRET`,
`CREATORS_PARTNER_TAG_US` y `CREATORS_PARTNER_TAG_ES` para habilitar la API por
tienda. Sin credenciales se informa modo offline y los campos comerciales
quedan en null. No se recuperan precios de salidas anteriores.

Los endpoints y el formato remoto de Creators API son provisionales: revisá
los TODO de `creators_api.py` contra
https://affiliate-program.amazon.com/creatorsapi/docs/ antes de usar credenciales
reales. Solo se aceptan precios identificados como USD; queda pendiente definir
la conversión de EUR para ES. `priceFetchedAt` se genera al recibir un precio válido.
El modo `api` indica que hay credenciales para alguna tienda del catálogo;
si una consulta falla, los productos afectados salen con campos nulos.

Las cotizaciones vienen de DolarAPI; si falla alguna, `rates` queda en null.
`CF_DEPLOY_HOOK_URL` es opcional: recibe un POST tras escribir una salida cuyo
hash cambió. El hash excluye únicamente `generatedAt`; cambios en las fechas
de consulta también cuentan. El hash previo se lee del archivo, incluso tras
reiniciar. Si falla el hook, el ciclo informa el error y no reintenta el aviso
hasta que cambie nuevamente el contenido.

## Precios de Amazon (`weboffers-amazon-scraper`)

Como todavía no tenemos acceso a la API oficial de Amazon, el servicio
`weboffers-amazon-scraper` levanta en un contenedor aislado el scraper HTTP de
`omkarcloud/amazon-scraper` fijado al commit
`8ffd4f976c705d009ec06d8e4e3e15fc77e35cee`. Corre sin variables de entorno,
sin secretos, sin volúmenes montados del host, sin puertos publicados al
exterior y con límite de memoria de 256 MB; sólo el worker puede consultarlo en
la red interna de Compose (`http://weboffers-amazon-scraper:8000`).

La cadena de las 03:30 ART ejecuta `amazon_prices.py` después de Chrome;
el ciclo horario conserva las 04:00 ART como respaldo. Consulta `/products/bulk`
en tandas de hasta 10 ASINs para los productos verificados que tienen `asin` y
bloque `ml`, y escribe `output/amazon-prices.json`. Si un producto falla, se
conserva el precio anterior hasta 3 días. Si ningún producto responde bien, se
registra `AMAZON_SCRAPER_FAIL` en los logs. Ese precio en USD/EUR nunca se
muestra crudo en el sitio: sólo se usa para calcular el total estimado en ARS
puesto en tu casa y el veredicto diario.

Para reconstruir el servicio en la Raspberry Pi:

```sh
docker compose -p franquicia400 build --no-cache weboffers-amazon-scraper
docker compose -p franquicia400 up -d weboffers-amazon-scraper
```

## Envío a Argentina (`weboffers-amazon-ar`)

Amazon decide si envía un producto a Argentina según la ubicación del comprador,
así que el servicio `weboffers-amazon-ar` (build propio en `./amazon-ar`) clona
el mismo scraper fijado al commit `8ffd4f97...` y, al arrancar, reemplaza
`amazon.fetch.set_location` para consultar "desde Argentina" (probeado en la Pi4:
con esa location, `products.details(asin, "US")` devuelve `delivery` con texto a
Argentina y precio numérico cuando envía, y `delivery` vacío con precio null
cuando no). Expone sólo en la red interna de Compose
`GET http://weboffers-amazon-ar:8001/ar-shipping?asins=A,B,C` (máx 5 ASINs), sin
puertos publicados, sin volúmenes y con 256 MB de límite.

Una vez por día, después de la consulta de precios, `amazon_prices.py` pide
`/ar-shipping` en lotes de 5 (timeout 240 s, pausa 3 s) para los mismos productos
y guarda en `amazon-prices.json` por slug `shipsToAr: {ships, free, checked}`.
Si falla un producto no se guarda nada para él (queda desconocido) y nunca se
reutilizan valores de días anteriores; con `AMAZON_AR_URL` vacío se omite el paso.

En el sitio, `mergeAmazonPrices` usa ese relevamiento sólo si `checked` es hoy
(ART): pisa `shipsToAr` con `{freeShipping, checked}` y setea `shipsToArToday`;
`isComparable` devuelve false cuando `shipsToArToday === false`, así los
productos que Amazon no envía a Argentina no se muestran (no hay comparación
posible).

## Precios de Mercado Libre y deployer

`ml_prices.py` consulta la API de Mercado Libre con client_credentials. Una vez
por día, después de Amazon en la cadena (respaldo a las 06:00 ART), recalcula
`output/ml-prices.json` para los productos verificados que tienen `ml.catalogId`.
El total de Amazon en USD se calcula con la misma fórmula del sitio (envío,
derechos e impuestos sobre el precio diario de `amazon-prices.json`, o sobre el
`listPrice` oficial del catálogo como respaldo). El veredicto pasa a `amazon`
sólo si el total en ARS (`totalUsd × MEP`) ahorra al menos 10% y el envío a
Argentina es gratis; si no hay precio o falta el MEP, queda el veredicto del
catálogo. Si una consulta de ML falla, se conserva el valor anterior del archivo.

Variables (sin valores en el repo; van en `worker/.env` del Pi):
`ML_CLIENT_ID`, `ML_CLIENT_SECRET` (worker) y `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ACCOUNT_ID` (deployer). Sin ellas, el worker omite ML y el deployer
registra `DEPLOY_OFF`.

Mapeo de catálogo (sólo lectura, escribe `output/ml-candidates.json` para revisar):

```sh
docker compose -p franquicia400 exec weboffers-worker python /app/tools/ml_catalog_map.py --output /app/output/ml-candidates.json
```

El `catalogId` elegido se copia a mano en `data/catalog.json` (`ml.catalogId`); el
script no escribe el catálogo.

El servicio `weboffers-deployer` publica al ver `output/cadena-AAAA-MM-DD.json`
y ambos archivos de precios del día; revisa el marcador cada minuto. Conserva
las 07:00 ART como respaldo. Si los precios de hoy cambiaron, clona `main` de GitHub en el volumen
`deployer-work`, copia `ml-prices.json` y `amazon-prices.json` a `data/`, hace
`npm ci`, `npm run build` y `npx wrangler deploy`.
Logs: `DEPLOY_OK`, `DEPLOY_SKIP`, `DEPLOY_FAIL`, `DEPLOY_OFF`. Límite de memoria
1.5 GB: el build de Astro en la Pi 4 puede ser justo; si falla por memoria, subir
el límite o hacer el build en otra máquina.

Despliegue manual desde Windows: `tools/deploy.sh` (baja `ml-prices.json` y
`amazon-prices.json` del Pi, hace build y deploy).

## Cadena nocturna en el host

Cron (hora ART, reemplaza el cron independiente de Chrome):

```cron
30 3 * * * /usr/bin/python3 /opt/docker/franquicia400/tools/cadena.py
```

Ejecuta Chrome → altas → Amazon → ML → marcador y espera del deployer. Los límites por
paso son 3000/300/5400/1800/1800 segundos; el límite global es 12000 segundos.
Una falla queda registrada y no bloquea los pasos siguientes. Los refresh usan
un bloqueo exclusivo por archivo en output, también respetado por el ciclo horario.
`force=True` adelanta el inicio; conserva fecha diaria, reintentos, slots y ritmo.
Los logs del host están en `/home/claude/logs/cadena-AAAA-MM-DD.log` y `.json`;
el JSON se guarda atómicamente al iniciar y al terminar cada paso. El vigía lo
controla desde las 05:30 ART. El worker registra las ejecuciones forzadas con
DailyLog y el deployer informa inicio, fin y duración de sus fases.

El log detalla cada artículo: Chrome registra ASIN, slugs, envío, gratuidad,
precio y evidencia; Amazon registra fuente, precio o motivo de omisión/falla;
ML registra precio y fecha, ausencia, falla o conflicto de variantes. Estas
líneas también quedan en DailyLog, con fecha y hora ART completas.

Durante el build, el endpoint `estado.json` genera un informe privado usando
los mismos productos de `loadProducts`, las mismas cotizaciones y el mismo
instante que usa para contar `publicados`. `comparableChecks` es la única
fuente de filtros; evalúa todos aunque fallen los primeros. El deployer guarda
el informe en `/state/logs/desglose-AAAA-MM-DD-HHMM.log`, compara el total con
`estado.json` y emite `DEPLOY_ALERT` si difieren. El origen repo/auto sale del
overlay efectivo, con prioridad del repo. No se agregan consultas de precios
ni dependencias para generar el desglose.

`DEPLOY_OK/FAIL` incluye la ruta del informe de ese intento. La cadena copia
su contenido completo después del resultado, conservando los horarios ART.
Si el build no llegó a generar el informe, se registra
`DESGLOSE_NO_DISPONIBLE`; nunca se toma el informe de un build anterior.
