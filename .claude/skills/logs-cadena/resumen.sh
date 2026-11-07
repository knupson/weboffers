#!/usr/bin/env bash
# Resumen de logs de la cadena de Franquicia 400 en una sola llamada (VM docker + pi3).
# Uso (Git Bash, raíz del repo): bash .claude/skills/logs-cadena/resumen.sh [AAAA-MM-DD]   (default: hoy ART)
set -uo pipefail
# ART = UTC-3 fijo (sin horario de verano). Git Bash no trae zoneinfo: TZ=America/... cae a UTC.
art() { date -u -d '-3 hours' "$@"; }
F="${1:-$(art +%F)}"
echo "=== Logs del $F — leídos $(art '+%F %T') ART ==="

ssh docker "F=$F bash -s" <<'EOF'
L=/home/claude/logs
for n in cadena tras-alta; do
  echo; echo "--- $L/$n-$F.log (pasos) ---"
  if [ -f "$L/$n-$F.log" ]; then
    grep -E 'PASO_(INICIO|OK|FALLA|ERROR|CORTE)|ERROR|Traceback' "$L/$n-$F.log" | grep -v PASO_SIGUE | tail -25
  else echo "(no existe)"; fi
done
echo; echo "--- lock de la cadena ---"; ls -l "$L/cadena.lock" 2>/dev/null || echo "(sin lock)"
echo; echo "--- worker: /opt/docker/franquicia400/worker/output/logs/worker-$F.log (últimas 8) ---"
tail -8 "/opt/docker/franquicia400/worker/output/logs/worker-$F.log" 2>/dev/null || echo "(no existe)"
echo; echo "--- deployer: /state/logs/deployer-$F.log (hora UTC, últimas 6) ---"
docker exec franquicia400-weboffers-deployer-1 sh -c "tail -6 /state/logs/deployer-$F.log" 2>&1
echo; echo "--- deployer: desgloses del día ---"
docker exec franquicia400-weboffers-deployer-1 sh -c "ls -t /state/logs/ | grep 'desglose-$F' | head -5" 2>&1
for f in vigia_franquicia envio_ar_chrome recordatorio_franquicia meta_franquicia; do
  echo; echo "--- $L/$f.log (últimas 4) ---"; tail -4 "$L/$f.log" 2>/dev/null || echo "(no existe)"
done
echo; echo "--- contenedores ---"
docker ps -a --filter name=franquicia400 --format '{{.Names}}  {{.Status}}'
EOF

echo; echo "--- pi3: /home/claude/vigia_externo.log (últimas 3) ---"
ssh -o ConnectTimeout=5 pi3 'tail -3 /home/claude/vigia_externo.log' 2>&1
