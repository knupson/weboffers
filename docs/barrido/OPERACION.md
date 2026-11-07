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
Cambios de rango, nodos, conocidos o políticas en un día ya iniciado requieren otro `--output`.
`--refresh-refinements` fuerza redescubrimiento del cache diario. No borrar un lock sin verificar
que no hay otro proceso de barrido activo. Tras una caída, quitar sólo run.lock de ese output.

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
