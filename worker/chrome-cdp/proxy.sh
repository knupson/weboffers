#!/bin/sh
set -eu
# Se lee la interfaz compartida; no se depende del hostname del sidecar.
cdp_ip=$(ip -4 addr show dev eth0 | awk '/inet / {split($2, parts, "/"); print parts[1]; exit}')
test -n "$cdp_ip"
# El bind específico evita disputar el listener de loopback de Chrome.
exec socat "TCP-LISTEN:9222,bind=${cdp_ip},reuseaddr,fork" TCP:127.0.0.1:9222
