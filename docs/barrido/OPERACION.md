# Operación y validación pendiente

Esta entrega agrega adquisición independiente. No encadena ni despliega el flujo nuevo.
No modifica el catálogo, offers.json ni la cantidad publicada. La comparación real de cobertura y
cantidad publicada corresponde a la tarea 10 antes de retirar las fuentes anteriores.

Desde `/opt/docker/franquicia400` en la VM, con estos archivos ya copiados al checkout:

```sh
docker compose -f worker/docker-compose.yml build weboffers-barrido
docker compose -f worker/docker-compose.yml up -d --no-deps weboffers-barrido
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

Validación local con dependencias instaladas de worker/barrido/requirements.txt:

```sh
python -m pytest worker -q -p no:cacheprovider
```

En esta sesión Windows las dependencias de prueba se instalaron fuera del repo en
`E:/Repositorios/.barrido-test-deps`, porque la instalación de usuario no tiene permisos.
Se usó PYTHONPATH a ese directorio y TEMP/TMP en `E:/Repositorios/.barrido-test-tmp`, porque
pytest tampoco puede leer el directorio temporal predeterminado. Esto no cambia la imagen Docker.

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

Pruebas en este entorno Windows: usar el PYTHONPATH de dependencias provisto y TEMP/TMP en
`E:/Repositorios/.barrido-test-tmp` para evitar el temporal restringido. No se instala ni cambia
ninguna dependencia de producción por esta validación.
