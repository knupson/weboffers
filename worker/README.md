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
