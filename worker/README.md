# Worker de datos

Requiere Python 3.12 y `requests`. Desde `worker/`:

```sh
python -m pip install requests pytest
python -m pytest -q --basetemp=.pytest_tmp -o cache_dir=.pytest_cache
python -u worker.py
```

Con Docker: `docker compose up -d --build`. La salida queda en
`worker/output/offers.json`; el catálogo se monta desde `../data` como solo lectura.

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

## Precios de Mercado Libre y deployer

`ml_prices.py` consulta la API de Mercado Libre con client_credentials. Una vez
por día, desde las 07:00 ART, recalcula `output/ml-prices.json` para los productos
verificados que tienen `ml.catalogId`. El veredicto pasa a `amazon` sólo si el
total de Amazon en ARS (`totalUsd × MEP`) ahorra al menos 10% y el envío a
Argentina es gratis; si no hay total de Amazon o falta el MEP, queda el veredicto
del catálogo. Si una consulta falla, se conserva el valor anterior del archivo.

Variables (sin valores en el repo; van en `worker/.env` del Pi):
`ML_CLIENT_ID`, `ML_CLIENT_SECRET` (worker) y `CLOUDFLARE_API_TOKEN`,
`CLOUDFLARE_ACCOUNT_ID` (deployer). Sin ellas, el worker omite ML y el deployer
registra `DEPLOY_OFF`.

Totales de Amazon: crear a mano `worker/amazon-totals.json` con `{"slug": totalUsd}`
(precio + cargos de importación en USD). Está en `.gitignore`; no lo commitees.
Montarlo antes de levantar el stack, porque si no existe Docker crea un directorio
en su lugar.

Mapeo de catálogo (sólo lectura, escribe `output/ml-candidates.json` para revisar):

```sh
docker compose -p franquicia400 exec weboffers-worker python /app/tools/ml_catalog_map.py --output /app/output/ml-candidates.json
```

El `catalogId` elegido se copia a mano en `data/catalog.json` (`ml.catalogId`); el
script no escribe el catálogo.

El servicio `weboffers-deployer` corre a las 07:30 ART. Si `ml-prices.json` es de
hoy y cambió, clona `main` de GitHub en el volumen `deployer-work`, copia el archivo
a `data/ml-prices.json`, hace `npm ci`, `npm run build` y `npx wrangler deploy`.
Logs: `DEPLOY_OK`, `DEPLOY_SKIP`, `DEPLOY_FAIL`, `DEPLOY_OFF`. Límite de memoria
1.5 GB: el build de Astro en la Pi 4 puede ser justo; si falla por memoria, subir
el límite o hacer el build en otra máquina.

Despliegue manual desde Windows: `tools/deploy.sh` (baja el JSON del Pi, build y deploy).
