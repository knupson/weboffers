#!/bin/sh
set -eu
# Escucha sólo en la IP fija de Chrome en la red interna barrido-cdp (no en chrome-salida) y acepta
# sólo clientes de esa subred: el CDP no queda alcanzable desde ninguna otra red.
: "${CDP_BIND_IP:?falta CDP_BIND_IP}"
: "${CDP_ALLOWED:?falta CDP_ALLOWED}"
exec socat "TCP-LISTEN:9222,bind=${CDP_BIND_IP},range=${CDP_ALLOWED},reuseaddr,fork" TCP:127.0.0.1:9222
