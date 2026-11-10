#!/bin/sh
set -eu
# Escucha sólo en la IP fija de Chrome en la red interna barrido-cdp (no en chrome-salida) y acepta
# sólo clientes de esa subred: el CDP no queda alcanzable desde ninguna otra red.
: "${CDP_BIND_IP:?falta CDP_BIND_IP}"
: "${CDP_ALLOWED:?falta CDP_ALLOWED}"
socat "TCP-LISTEN:9222,bind=${CDP_BIND_IP},range=${CDP_ALLOWED},reuseaddr,fork" TCP:127.0.0.1:9222 &
pid=$!
# Vigía (medido 07/11): si Chrome se reinicia, este contenedor queda en la red vieja sin la IP y el CDP
# rechaza conexiones. Al perder la IP (o morir socat) sale con error; restart: unless-stopped lo vuelve
# a unir a la red nueva de Chrome.
while kill -0 "$pid" 2>/dev/null; do
  ip -4 addr show 2>/dev/null | grep -q "inet ${CDP_BIND_IP}/" || { echo "$(date -Iseconds) CDP_SIN_IP ${CDP_BIND_IP}: salgo para reengancharme"; kill "$pid"; exit 1; }
  sleep 10
done
echo "$(date -Iseconds) CDP_SOCAT_TERMINO"; exit 1
