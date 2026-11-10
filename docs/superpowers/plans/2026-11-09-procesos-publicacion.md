# Cuatro procesos de publicación — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separar la verificación diaria de lo publicado (proceso 2) y la republicación a 3 días (proceso 4) del alta de nuevos (proceso 1), con una lista «no revisar 7 días», y revisar dudosos (proceso 3) solo con dos modelos de NVIDIA.

**Architecture:** Un archivo de estado `worker/output/publicacion.json` (clave = slug) dice en qué situación está cada producto. Cada etapa (Chrome, Amazon, ML) ya saltea productos con `motivo_catalogo`; se le suma `motivo_estado`, que saltea según el estado y el modo de la corrida. El deployer no cambia: lo que no se consulta hoy no tiene precio de hoy y queda `FILTRADO` solo. Después de cada deploy, un paso nuevo `estado` lee el desglose y mueve cada producto de situación.

**Tech Stack:** Python 3 (worker, tools), pytest; `tools/cadena.py` en el host de la VM; API compatible OpenAI de NVIDIA (`https://integrate.api.nvidia.com/v1/chat/completions`).

**Spec:** `docs/superpowers/specs/2026-11-09-procesos-publicacion-design.md`

## Global Constraints

- Reglas 1–4 de `AGENTS.md`: sin precio del día de los dos lados no se publica; nada viejo ni inventado; error en producción se arregla ya; caída de cantidad = error hasta demostrar lo contrario.
- «No revisar»: **7 días**. Republicación: **3 días** (3 consultas, desde el día siguiente a la salida).
- Aviso fuerte si salen **más de 10** publicados en una corrida (no frena el deploy).
- Envío para un publicado: regla de `PRODUCT.md` (`ARSHIPPING_MAX_DAYS`, 14 días). El proceso 1 sigue exigiendo Chrome del día.
- Modelos del proceso 3: `mistralai/mistral-large-4-1t-a52b` y `minimaxai/minimax-m3.1-flash` (los dos de `~/.claude/scripts/opencode-free.json`, proveedor `nvfree`).
- Todo log con hora ART; marcadores en MAYÚSCULAS con `_` (convención de `logs-cadena`).
- Textos para Alejandro en castellano rioplatense; nunca la palabra «catálogo».
- Los tests corren en la VM (memoria «nada corre en la PC»): `ssh docker 'docker exec -w /app/worker franquicia400-weboffers-worker-1 python -m pytest -q <archivo>'` después de subir con `git archive`; el hook local `test-relacionado` también corre los de la PC.

## Review Focus

1. Corrida con Amazon bloqueado: los 116 salen el mismo día → tienen que entrar al proceso 4 (no a «no revisar») y debe salir `PUBLICACION_ALERTA`. Test en Task 1 (`test_salida_masiva_va_a_republicacion_y_alerta`).
2. `publicacion.json` ausente o corrupto: nada puede quedar sin verificar ni publicarse a ciegas → se trata como «sin estado» y el modo `verificacion` toma el último desglose como fuente (Task 1, `test_estado_ausente`).
3. Dos deploys el mismo día (cadena + `--ahora`): un producto en republicación no puede consumir 2 de sus 3 intentos el mismo día. Test en Task 1 (`test_un_intento_por_dia`).
4. NVIDIA devuelve texto que no es JSON, o tarda: el par queda en revisión y va a Alejandro; nunca se aprueba por defecto (Task 6).
5. Un producto `no_revisar` que el proceso 1 «descubre» de nuevo antes de vencer: no entra (Task 2, `test_descubrimiento_respeta_no_revisar`).

---

### Task 1: Estado de publicación (`worker/publicacion.py`)

**Files:**
- Create: `worker/publicacion.py`
- Test: `worker/test_publicacion.py`

**Interfaces:**
- Produces:
  - `cargar(output: Path) -> dict` — lee `publicacion.json`; ausente o inválido → `{}` y línea `PUBLICACION_ESTADO_INVALIDO`.
  - `guardar(output: Path, estado: dict) -> None` — `publish.write_atomic`.
  - Forma de cada entrada: `{"situacion": "publicado"|"republicacion"|"no_revisar", "desde": "AAAA-MM-DD", "hasta": "AAAA-MM-DD"|None, "intentos": int, "ultimoIntento": "AAAA-MM-DD"|None, "motivo": str, "asin": str}`. Sin entrada = candidato.
  - `motivo_estado(product: dict, estado: dict, today: str, modo: str) -> str | None` — `modo` ∈ `"verificacion"` (proceso 2+4: consulta publicado y republicación) / `"alta"` (proceso 1: consulta sin entrada y `no_revisar` vencido). Devuelve `"no_revisar"`, `"no_publicado"` o `"verificado_en_otro_proceso"`, o `None` si se consulta.
  - `transicion(estado: dict, desglose: dict[str, tuple[str, str]], today: str) -> tuple[dict, dict]` — `desglose` = slug → (`"PUBLICADO"|"FILTRADO"`, primer motivo `FALLA`). Devuelve (estado nuevo, cuentas `{"salieron", "republicados", "a_no_revisar", "nuevos_publicados"}`).
  - `parse_desglose(texto: str) -> dict[str, tuple[str, str]]` — de las líneas `PRODUCTO <slug> asin=… origen=… PUBLICADO|FILTRADO k=ok(..)|FALLA(..)…`.
  - Constantes `NO_REVISAR_DIAS = 7`, `REPUBLICACION_INTENTOS = 3`, `ALERTA_SALIDAS = 10`.

Reglas de `transicion` (sólo productos presentes en el desglose; los ausentes no cambian):

| Antes | Desglose | Después |
|---|---|---|
| sin entrada / `no_revisar` vencido | PUBLICADO | `publicado` |
| sin entrada / `no_revisar` vencido | FILTRADO | `no_revisar`, `hasta = today + 7`, motivo |
| `no_revisar` vigente | cualquiera | sin cambio |
| `publicado` | PUBLICADO | sin cambio |
| `publicado` | FILTRADO | `republicacion`, `desde = today`, `intentos = 0` |
| `republicacion` | PUBLICADO | `publicado` |
| `republicacion` | FILTRADO, `ultimoIntento != today`, `desde != today` | `intentos += 1`; si llega a 3 → `no_revisar` 7 días |

- [ ] **Step 1: Write the failing tests** en `worker/test_publicacion.py`:
  - `test_parse_desglose` — dos líneas reales copiadas de `desglose-2026-11-09-0710.log` (sandisk PUBLICADO; asus-tuf FILTRADO) → `{"sandisk-extreme-portable-ssd-1tb": ("PUBLICADO", ""), "asus-tuf-gaming-vg27aq3a": ("FILTRADO", "envio_gratis")}`.
  - Un test por fila de la tabla (`test_publicado_que_falla_va_a_republicacion`, `test_tercer_fallo_va_a_no_revisar_7_dias` con `hasta == "2026-11-19"` partiendo de `today="2026-11-12"`, etc.).
  - `test_un_intento_por_dia` — dos `transicion` con el mismo `today` → `intentos == 1`.
  - `test_salida_masiva_va_a_republicacion_y_alerta` — 116 publicados, todos FILTRADO → 116 en `republicacion`, `cuentas["salieron"] == 116`.
  - `test_motivo_estado_modos` — matriz situación × modo → motivo esperado (tabla de Interfaces).
  - `test_estado_ausente` — `cargar` sobre archivo inexistente → `{}`; sobre `"{"` → `{}` y la línea en la salida.
- [ ] **Step 2:** Correr `python -m pytest worker/test_publicacion.py -q` → FAIL (`ModuleNotFoundError: publicacion`).
- [ ] **Step 3:** Implementar en `worker/publicacion.py` las firmas de arriba.
- [ ] **Step 4:** Mismo comando → PASS.
- [ ] **Step 5:** Commit `feat(publicacion): estado publicado / republicación / no revisar`.

### Task 2: Cada etapa saltea según el estado

**Files:**
- Modify: `worker/requisitos.py` (helper), `worker/amazon_prices.py:385`, `worker/ml_prices.py:302`, `tools/altas_chrome.py:24-50`, `tools/reintento_amazon.py:15`, `worker/catalog_auto.py:216` (`existing_asins`)
- Modify: `worker/alta_state.py:15` (14 → `publicacion.NO_REVISAR_DIAS`)
- Test: `worker/test_requisitos.py` (nuevo o existente), `worker/test_amazon_prices.py`, `worker/test_ml_prices.py`, `worker/test_catalog_auto.py`

**Interfaces:**
- Consumes: `publicacion.cargar`, `publicacion.motivo_estado`.
- Produces: `requisitos.motivo_total(product, estado, today, modo, stores=("US","ES")) -> str | None` = `motivo_catalogo(product, stores) or motivo_estado(product, estado, today, modo)`. El modo sale de la variable de entorno `PUBLICACION_MODO` (default `"verificacion"`); `requisitos.modo_actual() -> str`.

- [ ] **Step 1: Failing tests:**
  - `test_amazon_saltea_no_revisar` — producto con estado `no_revisar` vigente → aparece en `salteos` con motivo `no_revisar` y en `ETAPA_RESUMEN … motivos_salteo=…no_revisar:1`.
  - `test_ml_saltea_no_publicado_en_verificacion` — igual para ML.
  - `test_chrome_alta_incluye_vencidos` — `asin_list(..., pending_only=True)` con `PUBLICACION_MODO=alta` devuelve pendientes + productos con `no_revisar` vencido.
  - `test_descubrimiento_respeta_no_revisar` — `existing_asins` en `maybe_grow` incluye los ASIN `no_revisar` vigentes (no se redescubren) y no los vencidos.
  - `test_rechazo_vence_a_7_dias` — `rejected_asins` con fecha de hace 7 días → no excluye; hace 6 → excluye.
- [ ] **Step 2:** `python -m pytest worker -q -k "saltea or incluye_vencidos or respeta_no_revisar or vence_a_7"` → FAIL.
- [ ] **Step 3:** Reemplazar las llamadas a `motivo_catalogo` de las 4 etapas por `motivo_total(..., publicacion.cargar(output), today, modo_actual())`; en `catalog_auto.maybe_grow` sumar a `existing_asins` los ASIN con `no_revisar` vigente; cambiar el 14 de `rejected_asins`.
- [ ] **Step 4:** `python -m pytest worker -q` → todo PASS (los 777 actuales + nuevos).
- [ ] **Step 5:** Commit `feat(publicacion): cada etapa consulta sólo lo que le toca a su proceso`.

### Task 3: Paso `estado` después del deploy (`tools/actualizar_publicacion.py`)

**Files:**
- Create: `tools/actualizar_publicacion.py`
- Test: `worker/test_actualizar_publicacion.py`
- Modify: `tools/vigia_franquicia.py:31` (sumar `PUBLICACION_ALERTA` a `MARCAS_FALLA`), `worker/test_vigia_franquicia.py`

**Interfaces:**
- Consumes: `publicacion.parse_desglose`, `publicacion.transicion`, `cargar`, `guardar`.
- Produces: CLI `python /app/tools/actualizar_publicacion.py --desglose -` (texto por stdin) → escribe `publicacion.json`, imprime una línea por cambio `PUBLICACION_CAMBIO <slug> <antes>-><después> motivo=<m>` y al final `PUBLICACION_OK publicados=N republicacion=N no_revisar=N salieron=N republicados=N`; si `salieron > 10`, además `PUBLICACION_ALERTA salieron=N motivos=<motivo:cuenta,…>`. Exit 1 si el desglose no tiene ninguna línea `PRODUCTO` (no toca el estado).

- [ ] **Step 1: Failing tests:** `test_cli_escribe_estado_y_resumen` (desglose de 3 líneas por stdin → archivo y `PUBLICACION_OK publicados=2 …`), `test_cli_desglose_vacio_no_toca_estado` (exit 1, archivo igual), `test_alerta_mas_de_10` (11 salidas → línea `PUBLICACION_ALERTA salieron=11`), `test_vigia_detecta_publicacion_alerta`.
- [ ] **Step 2:** `python -m pytest worker/test_actualizar_publicacion.py worker/test_vigia_franquicia.py -q` → FAIL.
- [ ] **Step 3:** Implementar; leer y escribir bajo `alta_state.update_state` (mismo lock `altas.json`) para no pisar `confirmar_altas`.
- [ ] **Step 4:** Mismo comando → PASS.
- [ ] **Step 5:** Commit `feat(publicacion): el desglose de cada deploy mueve a cada producto de situación`.

### Task 4: `tools/cadena.py` — una corrida diaria con los procesos en orden

**Files:**
- Modify: `tools/cadena.py:183-238`, `worker/worker.py:68-90` (bucle), `worker/catalog_auto.py:176-196` (ventana horaria), `worker/deployer/deploy.mjs` (bucle de 10 min), crontab de la VM, unidad `franquicia-tras-alta.path`
- Test: `worker/test_cadena.py`, `worker/test_worker.py`, `worker/test_catalog_auto.py`, `worker/test_deployer.py`

Cambios (pedido literal: «Todos los script se tienen que correr 1 sola vez por dia»):
- Una sola corrida (cron 03:30, `cadena.py`), en este orden y cada paso una vez: **verificación** `chrome → amazon → ml → deploy → estado` con `PUBLICACION_MODO=verificacion`; después **alta** `buscar → dudosos → chrome --pendientes → altas → amazon → ml → deploy --ahora → estado` con `PUBLICACION_MODO=alta`. El modo viaja con `-e PUBLICACION_MODO=…` en cada `docker exec` y a `envio_ar_chrome.sh`. Si el bloque de verificación falla, el de alta corre igual (procesos separados); cada bloque deja su `ETAPA_RESUMEN`.
- Paso `buscar`: `python /app/tools/crecer_ahora.py` (ya existe, llama `maybe_grow(force=True)`). `maybe_grow` deja de tener ventana 20:00–03:00 y de reintentar por hora; el bucle del worker deja de llamarlo.
- Bucle del worker (`worker.py main`): queda sólo Telegram (`POST_HOURS = (12, 20)`, fuera de alcance). Amazon, ML, fichas ML y alta salen del bucle; los corre la cadena.
- Deployer: sin bucle de 10 minutos; despliega sólo con `deploy.mjs` llamado por la cadena (`--ahora` en el segundo deploy, como hoy).
- Se borra la unidad `franquicia-tras-alta.path` y el `alta-terminada.json` deja de usarse.
- El corte «sin altas promovidas» del bloque alta sólo aplica si tampoco hay `no_revisar` vencidos (`ALTAS_OK … vencidos=N`, Task 2).
- Paso `estado`: `sh -c "docker exec DEPLOYER cat <desglose> | docker exec -i -w /app/worker WORKER python /app/tools/actualizar_publicacion.py --desglose -"`, con la ruta guardada por `deploy`/`deploy_ahora` en `self.desglose`. Sin desglose → `PASO_FAIL estado sin desglose`.

- [ ] **Step 1: Failing tests** con el `popen` falso que ya usa `test_cadena.py`: `test_orden_verificacion_y_despues_alta` (secuencia exacta de los 13 pasos), `test_cada_paso_una_vez`, `test_modo_viaja_en_el_entorno`, `test_falla_verificacion_alta_corre_igual`, `test_estado_recibe_el_desglose_del_deploy`; en `test_worker.py` `test_bucle_no_llama_precios_ni_alta`; en `test_catalog_auto.py` `test_sin_ventana_horaria` (reemplaza a `test_retry_missing_mep_before_three`, `test_failed_before_scraping_retries_same_night` y `test_expired_running_retries`); en `test_deployer.py` `test_sin_bucle_de_reintento`.
- [ ] **Step 2:** `python -m pytest worker/test_cadena.py worker/test_worker.py worker/test_catalog_auto.py worker/test_deployer.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** Mismo comando → PASS.
- [ ] **Step 5:** Commit `feat(cadena): una corrida por día; verificación y alta como bloques separados`.
- [ ] **Step 6 (en Task 7, al desplegar):** `ssh docker 'sudo systemctl disable --now franquicia-tras-alta.path'` y confirmar con `systemctl is-enabled` → `disabled`; el crontab queda con una sola línea de `cadena.py` (03:30).

### Task 5: Arranque del estado (`tools/inicializar_publicacion.py`)

**Files:**
- Create: `tools/inicializar_publicacion.py`
- Test: `worker/test_inicializar_publicacion.py`

**Interfaces:**
- CLI `python /app/tools/inicializar_publicacion.py --hoy AAAA-MM-DD` con todos los desgloses concatenados por stdin, cada bloque precedido por `### desglose-AAAA-MM-DD-HHMM.log` (la cadena de la VM los arma con `for f in …; do echo "### $f"; cat $f; done`). Se niega si `publicacion.json` ya existe (salvo `--forzar`).
- Reglas: `PUBLICADO` en el último desglose → `publicado`. `FILTRADO` en el último pero `PUBLICADO` en alguno anterior → `republicacion` con `desde` = día siguiente al último `PUBLICADO`; si ya pasaron 3 días → `no_revisar` 7. El resto → `no_revisar` con `hasta = hoy + (crc32(asin) % 7) + 1` (escalonado).
- Imprime `PUBLICACION_INICIAL publicados=N republicacion=N no_revisar=N`.

- [ ] **Step 1: Failing tests:** `test_inicial_reparte_los_tres_grupos` (3 desgloses sintéticos), `test_escalonado_en_7_dias` (100 ASIN sintéticos → todos los `hasta` entre hoy+1 y hoy+7, y ningún día vacío), `test_no_pisa_estado_existente`.
- [ ] **Step 2:** `python -m pytest worker/test_inicializar_publicacion.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(publicacion): estado inicial desde los desgloses`.

### Task 6: Dudosos con NVIDIA (`tools/dudosos_nvidia.py`)

**Files:**
- Create: `tools/dudosos_nvidia.py`
- Test: `worker/test_dudosos_nvidia.py`
- Modify: `worker/docker-compose.yml` (variable `NVIDIA_API_KEY: ${NVIDIA_API_KEY:-}` en `weboffers-worker`), `tools/vigia_franquicia.py:31` (`DUDOSO_PARA_ALEJANDRO`)

**Interfaces:**
- Consumes: `tools/revisar_altas.py` (`review(catalog, output, action, pairs, motivo, as_json)`), `altas-revision.json`, ML `/products/{catalogId}` (`ml_prices.get_json`).
- Produces:
  - `evidencia(row: dict, ficha_amazon: dict, ficha_ml: dict) -> dict` — campos lado a lado: título, marca, modelo, capacidad, color, identificadores (UPC/EAN/GTIN/MPN), variante.
  - `votar(modelo: str, evidencia: dict, post=requests.post) -> tuple[str, str]` — devuelve (`"aprobar"|"rechazar"|"invalido"`, motivo). Pide JSON `{"decision": "aprobar"|"rechazar", "motivo": "…"}`, `temperature=0`, timeout 120 s; cualquier error o JSON inválido → `"invalido"`.
  - `decidir(votos: list[tuple[str,str]]) -> str` — `"aprobar"`/`"rechazar"` sólo si los dos votos coinciden y ninguno es `invalido`; si no, `"alejandro"`.
  - CLI sin argumentos: para cada par de la cola, junta evidencia (ficha de Amazon por el servidor `amazon-ar`, `AMAZON_AR_URL`, endpoint de detalle que usa `recolectar_fichas.py`; ficha de ML por API), vota con los 2 modelos, ejecuta `revisar_altas` o deja el par y escribe `DUDOSO_PARA_ALEJANDRO par=<asin:catalogId> votos=<…> evidencia=<ruta json>`. Línea por par `DUDOSO_DECISION par=… decision=… votos=modelo1:…,modelo2:…`. Sin `NVIDIA_API_KEY` → `DUDOSOS_SIN_CLAVE` y exit 0 (no frena la cadena).

- [ ] **Step 0 (verificación, sin código):** desde la VM, con la clave en el `.env` del worker (`reg query HKCU\Environment /v NVIDIA_API_KEY` en la PC → `.env` de la VM, sin imprimirla), un `curl` de una línea a cada modelo. Hecho = los dos devuelven 200. Si uno falla, frenar y avisar con el error literal (cambiar modelo es decisión de Alejandro).
- [ ] **Step 1: Failing tests** (con `post` falso): `test_dos_aprobar_aprueba`, `test_desacuerdo_va_a_alejandro`, `test_json_invalido_va_a_alejandro`, `test_timeout_va_a_alejandro`, `test_sin_clave_no_frena`, `test_evidencia_lado_a_lado` (fichas de Ottocast reales, `B0HFR45YLX`).
- [ ] **Step 2:** `python -m pytest worker/test_dudosos_nvidia.py -q` → FAIL.
- [ ] **Step 3:** Implementar.
- [ ] **Step 4:** PASS.
- [ ] **Step 5:** Commit `feat(dudosos): revisión diaria con dos modelos de NVIDIA`.

### Task 7: Integrar, arrancar y verificar en producción

**Files:**
- Modify: `.claude/skills/logs-cadena/SKILL.md` (marcadores nuevos `PUBLICACION_*`, `DUDOSO_*`, paso `estado`), `PRODUCT.md` (fila «No revisar 7 días / republicación 3 días»), `docs/SPEC.md` si describe la cadena.

- [ ] **Step 1:** Antes de desplegar, anotar la cantidad publicada: `curl -s https://ofertas.knunet.com/estado.json` → `publicados`.
- [ ] **Step 2:** Revisión con el agente `revisor-reglas-negocio` sobre el rango de commits; resolver lo que marque.
- [ ] **Step 3:** `bash tools/actualizar_worker.sh` (push a `main` + VM). Esperado: worker recreado.
- [ ] **Step 4:** Estado inicial en la VM: `ssh docker` → desgloses por stdin a `inicializar_publicacion.py --hoy <hoy>`. Referencia del 09/11 07:10: 116 publicados, 5 publicados alguna vez, 170 nunca; el resultado real se cita tal cual y cada diferencia se explica con el desglose.
- [ ] **Step 5:** Corrida manual de la cadena con `PUBLICACION_MODO=verificacion` (`ssh docker python3 /opt/docker/franquicia400/tools/cadena.py`). Hecho = `ETAPA_RESUMEN chrome entran=` igual a publicados + republicación, `PASO_OK estado`, y `estado.json` con `publicados` igual o mayor al del Step 1 (si es menor: regla 4, explicar producto por producto con el desglose antes de cerrar).
- [ ] **Step 6:** Skill `verificar-produccion` sobre `ofertas.knunet.com`.
- [ ] **Step 7:** Commit de docs + skill y push.
- [ ] **Step 8:** Memoria de estado con «Vale hasta»: recalibrar los 7 días el 23/11 con las líneas `PUBLICACION_CAMBIO` (cuántos volvieron a publicarse al vencer `no_revisar`).
