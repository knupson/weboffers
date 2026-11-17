#!/bin/bash
# Entrypoint de weboffers-warp: corre el /entrypoint.sh de la imagen y se cae si muere warp-svc.
#
# 17/11: el kernel mató warp-svc por memoria (04:37:45, «Memory cgroup out of memory: Killed process
# (warp-svc) anon-rss:503212kB» con el tope de 512 MB). gost, el proxy SOCKS5, siguió vivo como proceso
# principal: el contenedor quedó «Up» sin túnel ni DNS (127.0.2.3:53 connection refused) y Docker no
# reinicia un contenedor por estar unhealthy. Saliendo con código 1, «restart: unless-stopped» lo levanta solo.
set -u

/entrypoint.sh &
principal=$!

# Como PID 1, bash ignora SIGTERM si no hay trap: «docker restart» esperaba 10 s y mataba todo con SIGKILL.
detener() {
  kill "$principal" 2>/dev/null
  sudo pkill -TERM -x warp-svc 2>/dev/null
  wait "$principal" 2>/dev/null
  exit 0
}
trap detener TERM INT

# warp-svc arranca dentro del entrypoint; se le da tiempo antes de vigilarlo.
# «sleep & wait» deja que el trap corra enseguida en vez de esperar a que termine el sleep.
sleep 30 & wait $!
while kill -0 "$principal" 2>/dev/null; do
  if ! pgrep -x warp-svc >/dev/null; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) WARP_SVC_CAIDO warp-svc no está corriendo; salgo para que Docker reinicie el contenedor"
    exit 1
  fi
  sleep 10 & wait $!
done
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) WARP_ENTRYPOINT_FIN el entrypoint de la imagen terminó; salgo para que Docker reinicie el contenedor"
exit 1
