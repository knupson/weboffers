#!/usr/bin/env bash
# Instala el publicador de Meta de Franquicia 400 (cada 5 min) en el crontab del usuario del docker, sin duplicarlo.
# Uso desde la PC: scp tools/meta/meta_publicar.py docker:franquicia400-meta/ && ssh docker "bash -s" < tools/meta/instalar_cron_meta.sh
set -euo pipefail
mkdir -p "$HOME/logs"
LINEA="*/5 * * * * cd /home/claude/franquicia400-meta && python3 meta_publicar.py >> /home/claude/logs/meta_franquicia.log 2>&1"
{ crontab -l 2>/dev/null | grep -v 'franquicia400-meta && python3 meta_publicar.py' || true; echo "$LINEA"; } | crontab -
crontab -l | grep franquicia400-meta
