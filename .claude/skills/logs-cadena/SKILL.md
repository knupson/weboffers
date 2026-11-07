---
name: logs-cadena
description: Mapa verificado de los logs de Franquicia 400 (cadena 03:30, tras-alta, worker, deployer, vigías, Chrome de envío, Meta) en la VM docker y pi3, con un script que resume el día en una llamada. Usar ANTES de afirmar la causa de cualquier error de la cadena, del catálogo o del deploy, y cuando Alejandro pregunte qué pasó en una corrida.
---

# Logs de la cadena (Franquicia 400)

La regla 2 de errores de `AGENTS.md` dice que la causa sale de un log leído, citando línea y hora. Esta skill dice dónde está cada log. Rutas verificadas el 07/11/2026 en la VM `docker`.

## Primero: resumen del día en una llamada

```bash
bash .claude/skills/logs-cadena/resumen.sh            # hoy (ART)
bash .claude/skills/logs-cadena/resumen.sh 2026-11-06 # otro día
```

Imprime los pasos de la cadena y de tras-alta, el lock, las últimas líneas del worker, el deployer y los vigías, el estado de los contenedores y el vigía externo de pi3. Después, profundizar sólo en el log que corresponda.

## Mapa

| Qué | Dónde | Cómo se lee | Hora |
|---|---|---|---|
| Cadena nocturna (`tools/cadena.py`, cron 03:30): pasos `chrome → altas → amazon → ml → deploy` | VM `/home/claude/logs/cadena-AAAA-MM-DD.log` + `.json` (inicio, fin, segundos y estado de cada paso) | `ssh docker 'grep -v PASO_SIGUE /home/claude/logs/cadena-<F>.log'` | ART |
| Tras el alta (`franquicia-tras-alta.path` → `cadena.py --tras-alta`) | VM `/home/claude/logs/tras-alta-AAAA-MM-DD.log` + `.json` | igual que arriba | ART |
| Lock (cadena en curso) | VM `/home/claude/logs/cadena.lock` | `ls -l` | — |
| Worker (precios, altas `ALTAS_OK`, auditoría) | VM `/opt/docker/franquicia400/worker/output/logs/worker-AAAA-MM-DD.log`, `auditoria-pares.log` (= `/app/output/logs` en los contenedores worker y deployer) | `ssh docker 'tail -50 …'` | ART |
| Deployer (deploys, `DEPLOY_MANUAL`, próximo previsto) | volumen `franquicia400_deployer-state` → `/state/logs/deployer-AAAA-MM-DD.log` | `ssh docker 'docker exec franquicia400-weboffers-deployer-1 tail -50 /state/logs/deployer-<F>.log'` | **UTC** (`…Z`): restar 3 h |
| Desglose de publicación (por qué entra o no cada producto) | `/state/logs/desglose-AAAA-MM-DD-HHMM.log` en el deployer | `docker exec … ls -t /state/logs` | ART en el nombre |
| Vigía (cron cada 15 min) | VM `/home/claude/logs/vigia_franquicia.log` | `tail` | ART |
| Chrome de envío AR | VM `/home/claude/logs/envio_ar_chrome.log` | `tail` | ART |
| Controles de WhatsApp (7:30 sitio, 12:20/20:20 Telegram, 19:10 reel, 15:30 sitio13) | VM `/home/claude/logs/recordatorio_franquicia.log` | `tail` | ART |
| Publicación en Meta (cron cada 5 min) | VM `/home/claude/logs/meta_franquicia.log`, `meta_publicar.log` | `tail` | ART |
| Scraper de Amazon / servidor AR | contenedores `franquicia400-weboffers-amazon-scraper-1`, `…-amazon-ar-1` | `ssh docker 'docker logs --since 2h <contenedor>'` | — |
| Vigía externo (pi3, cron cada 10 min, avisa por Telegram) | pi3 `/home/claude/vigia_externo.log` | `ssh pi3 'tail -20 /home/claude/vigia_externo.log'` | ART |
| Estado público del build | `https://ofertas.knunet.com/estado.json` | `curl -s` | — |

Los crons están en `ssh docker 'crontab -l'` y la unidad systemd en `ssh docker 'systemctl status franquicia-tras-alta.path'`.

## Marcadores útiles para grep

- Cadena: `PASO_INICIO`, `PASO_OK`, `PASO_SIGUE` (latido; filtrarlo), y cualquier otro `PASO_*` que no sea OK. También `FILTRO <motivo> fallas=N`.
- Worker: `ALTAS_OK promovidas=… rechazadas=… siguen_pendientes=…`.
- Deployer: `DEPLOY_FASE <fase> ok|…`, `DEPLOY_OK publicado con precios del …` (trae la ruta del desglose), `DEPLOY_MANUAL ok`, `Próximo despliegue previsto`.
- Vigías y controles: `VIGIA_OK`, `VIGIA_EXTERNO_OK`, `FRANQUICIA_CONTROL_OK`, `ENVIO_AR_CHROME_OK`; cualquier variante sin `_OK` es la que hay que mirar.

## Reglas al citar

- Citar archivo, línea textual y hora: «`cadena-2026-11-07.log` 03:54:03 `PASO_OK deploy 90.5s`».
- Si el log no alcanza para saber la causa, se agrega el log primero (regla 2) y no se afirma nada.
- Si una ruta de esta tabla no existe, la tabla está vieja: relevar de nuevo (`ssh docker 'ls -t /home/claude/logs'`, `docker inspect … Mounts`) y actualizar esta skill en el mismo turno.
