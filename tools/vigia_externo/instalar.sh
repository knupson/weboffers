#!/usr/bin/env bash
# Instala el vigía externo de Franquicia 400 en la pi3 (05/11). Correr desde la raíz del repo en Git Bash:
#   bash tools/vigia_externo/instalar.sh
# Qué hace:
#  1. En la VM docker: crea la llave ~/.ssh/vigia_pi3 (si no existe).
#  2. En la pi3: copia recibir_latido.sh y vigia_externo.py, agrega la llave de la VM a authorized_keys
#     RESTRINGIDA (command=recibir_latido.sh, restrict: sólo puede escribir el latido), guarda el token del bot
#     de Telegram y el chat en ~/.vigia_externo.env (600) y agrega el cron cada 10 min.
#  3. Prueba: manda un latido desde la VM, corre el vigía externo y manda un mensaje de prueba por Telegram.
set -euo pipefail
cd "$(dirname "$0")/../.."
TMP="$(mktemp -d)"; trap 'rm -rf -- "$TMP"' EXIT

ssh docker 'test -f ~/.ssh/vigia_pi3 || ssh-keygen -q -t ed25519 -N "" -C "vigia-franquicia@docker" -f ~/.ssh/vigia_pi3; cat ~/.ssh/vigia_pi3.pub' > "$TMP/pub"
echo "command=\"/home/claude/recibir_latido.sh\",restrict $(cat "$TMP/pub")" > "$TMP/authline"
{ ssh docker 'grep -E "^TELEGRAM_BOT_TOKEN=" /opt/docker/franquicia400/worker/.env'; echo "TELEGRAM_CHAT_ID=6831776066"; } > "$TMP/env"

scp -q tools/vigia_externo/recibir_latido.sh tools/vigia_externo/vigia_externo.py "$TMP/authline" "$TMP/env" pi3:/home/claude/
ssh pi3 'set -e; cd ~
mv env .vigia_externo.env; chmod 600 .vigia_externo.env; chmod 755 recibir_latido.sh
[ -f .ssh/authorized_keys.bak-vigia ] || cp -p .ssh/authorized_keys .ssh/authorized_keys.bak-vigia
grep -q vigia-franquicia .ssh/authorized_keys || cat authline >> .ssh/authorized_keys
rm authline
LINEA="*/10 * * * * /usr/bin/python3 /home/claude/vigia_externo.py >> /home/claude/vigia_externo.log 2>&1"
{ crontab -l 2>/dev/null | grep -v vigia_externo.py || true; echo "$LINEA"; } | crontab -
crontab -l | grep vigia_externo'

ssh docker 'echo ok | ssh -i ~/.ssh/vigia_pi3 -o BatchMode=yes -o StrictHostKeyChecking=accept-new claude@192.168.3.254'
ssh pi3 'cat ~/vigia-latido.txt; echo; python3 ~/vigia_externo.py; python3 -c "import sys; sys.path.insert(0, \"/home/claude\"); import vigia_externo as v; v.telegram(\"Prueba: vigía externo de Franquicia 400 instalado en la pi3.\")" && echo "TELEGRAM_OK"'
