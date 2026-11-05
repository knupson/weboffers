#!/bin/sh
# Lanza mediciones dentro del worker (en segundo plano). Salida en output/limites/<modo>.salida.
# Uso en la VM: sh /opt/docker/franquicia400/tools/medir_limites.sh <modo> [<modo> ...]
# Varios modos = uno detrás del otro (Amazon precios y envío AR comparten IP: nunca en paralelo).
CADENA=""
for m in "$@"; do
  CADENA="$CADENA python /app/tools/medir_limites.py $m > /app/output/limites/$m.salida 2>&1;"
done
docker exec -d -w /app/worker franquicia400-weboffers-worker-1 sh -c "mkdir -p /app/output/limites; $CADENA"
