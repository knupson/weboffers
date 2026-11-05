#!/bin/sh
# Único comando que puede ejecutar la llave vigia_pi3 de la VM docker (forced command en authorized_keys de pi3).
# Guarda una línea corta de estado (máx 200 bytes) que manda el vigía de la VM: "ok" o "sin-internet".
head -c 200 | tr -cd 'a-zA-Z0-9 :_.-' > /home/claude/vigia-latido.tmp && mv /home/claude/vigia-latido.tmp /home/claude/vigia-latido.txt
