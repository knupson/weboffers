#!/usr/bin/env python3
"""Corrida diaria del host: verificación y alta, encadenadas en bloques independientes."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import re
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import traceback

CHROME_TIMEOUT = 3000
ALTAS_TIMEOUT = 300
AMAZON_TIMEOUT = 5400
ML_TIMEOUT = 1800
DEPLOY_TIMEOUT = 1800
GLOBAL_TIMEOUT = 12000
# Buscar debe liberar la cadena de las 03:30 antes de las 20:00 ART.
# La reserva cubre los 240 s de identificadores y 60 s para cerrar y persistir.
BUSCAR_FIN_ART = 20
BUSCAR_RESERVA = 300
# Reservar también un minuto para cerrar procesos/logs antes de medianoche.
ALTA_RESERVA_FIN_DIA = 60
BUSCAR_TIMEOUT = 24 * 3600
# Rates: 3×20 s; Creators: 2 tiendas × 2×30 s; hook: 30 s = 210 s,
# más margen para inicio y escritura (los timeouts HTTP son por lectura).
OFFERS_TIMEOUT = 300
HEARTBEAT = 30
# 12/11: el motivo de un paso fallido viaja por WhatsApp (vigía). Eran las últimas 8 líneas crudas y en
# barrido_ml quedaban los JSON de cierre (BARRIDO_ML_SIN_TRADUCCION con 579 palabras): 11.222 caracteres.
# La salida completa sigue en cadena-AAAA-MM-DD.log; el motivo sólo resume.
MOTIVO_MAX = 400
LINEA_MAX = 200
MARCAS_ERROR = re.compile(r"_ERROR\b|\bERROR\b|Traceback|Exception|Timeout|Killed|\b\w+Error\b:")
CAMPOS_MOTIVO = ("asin", "categoria", "pagina", "motivo", "error", "reason", "tipo", "http")
ART = timezone(timedelta(hours=-3))
LOG_DIR = Path("/home/claude/logs")
REPO = Path(__file__).resolve().parents[1]
WORKER = "franquicia400-weboffers-worker-1"
DEPLOYER = "franquicia400-weboffers-deployer-1"
# 10/11: el alta sale del barrido (Amazon → ML → matcheo), no de crecer_ahora. Plazos propios por paso.
# Corrida A (19 raíces, pausa 3 s): 19 min 55 s. El ML de las 19 raíces se midió el 13/11 (ver BARRIDO_ML_TIMEOUT).
BARRIDO = "franquicia400-weboffers-barrido-1"
CHROME_BARRIDO = "franquicia400-weboffers-chrome-1"
BARRIDO_AMAZON_TIMEOUT = 2400
# 13/11: medido 1,7 s por producto (11/11: 1195 en 2052 s; 13/11: 4002 en 6753 s, 94 % del tope de 7200 s).
# Las esperas a ML fueron 910 s de esos 6753: el tiempo lo pone la cantidad de productos, no las pausas.
BARRIDO_ML_TIMEOUT = 9600
BARRIDO_ALTAS_TIMEOUT = 1800
BARRIDO_SALIDA = "/app/output/barrido"
# 13/11: «Lo más vendido» (destacados de ML) se renueva antes del deploy del alta. Medido el 13/11: 169,4 s.
# Sin destacados el script sale con 1 y no escribe nada; eso no es una falla del paso.
MAS_VENDIDOS_TIMEOUT = 600
# Chequeo real del Chrome del barrido (igual que el healthcheck del compose): abre y cierra una pestaña.
# 10/11: tras un OOM /json/version respondía 200 y el CDP no servía; Docker no reinicia un «unhealthy».
CHROME_CHEQUEO = ("id=$(curl -sf -m 10 -X PUT 'http://127.0.0.1:9222/json/new?about:blank' | "
                  "sed -n 's/.*\"id\": *\"\\([^\"]*\\)\".*/\\1/p' | head -1) && [ -n \"$id\" ] && "
                  "curl -sf -m 10 \"http://127.0.0.1:9222/json/close/$id\" >/dev/null")
CHROME_ESPERAS = 10  # tras el reinicio: hasta 10 chequeos separados por 3 s
# 11/11: tras el OOM de Chrome de las 04:20:57, abrir/cerrar pestaña daba OK pero connect_over_cdp vencía
# a los 30 s (6 de 6 a las 07:30). El chequeo usa ahora la misma conexión que el barrido y evalúa 1+1.
CHROME_CHEQUEO_CDP = ("import os; from barrido.chrome_search import ChromeSearch; "
                      "c = ChromeSearch(os.environ['BARRIDO_CHROME_CDP']); c._connect(); "
                      "ok = c.page.evaluate('1+1') == 2; c.close(); raise SystemExit(0 if ok else 1)")
CHROME_CHEQUEO_SEGUNDOS = 45  # connect_over_cdp tiene 30 s de timeout propio


def _linea_corta(linea):
    """Saca la hora ISO del principio y, si la línea trae JSON, deja sólo los campos que explican la falla."""
    linea = re.sub(r"^\d{4}-\d{2}-\d{2}T\S+\s+", "", linea.strip())
    inicio = linea.find("{")
    if inicio >= 0:
        try:
            datos = json.loads(linea[inicio:])
        except ValueError:
            datos = None
        if isinstance(datos, dict):
            campos = " ".join(f"{k}={datos[k]}" for k in CAMPOS_MOTIVO if datos.get(k) not in (None, ""))
            linea = f"{linea[:inicio].strip()} {campos}".strip()
    return linea if len(linea) <= LINEA_MAX else linea[:LINEA_MAX - 1] + "…"


def resumen_salida(lineas, limite=MOTIVO_MAX):
    """Motivo corto de un proceso que falló: primero las líneas con marca de error (las 3 últimas); si no hay,
    las últimas líneas sin JSON. Cada línea se recorta a LINEA_MAX y el total a `limite`."""
    lineas = [linea for linea in lineas if linea.strip()]
    errores = [linea for linea in lineas
               if MARCAS_ERROR.search(linea) and not linea.lstrip().startswith("Traceback (most recent")]
    elegidas = errores[-3:] or [linea for linea in lineas if "{" not in linea][-3:] or lineas[-2:]
    texto = " | ".join(_linea_corta(linea) for linea in elegidas)
    return texto if len(texto) <= limite else texto[:limite - 1] + "…"


class Cadena:
    def __init__(self, logs=LOG_DIR, popen=subprocess.Popen, clock=time.monotonic,
                 now=lambda: datetime.now(ART), sleep=time.sleep, modo="cadena"):
        self.modo = modo
        self.bloque = "verificacion"
        self.desglose = None
        self.deploy_skip = False
        self.logs = Path(logs)
        self.logs.mkdir(parents=True, exist_ok=True)
        self.popen, self.clock, self.now, self.sleep = popen, clock, now, sleep
        self.log_lock = threading.Lock()
        self.start = clock()
        self.deadline = self.start + GLOBAL_TIMEOUT
        self.fecha = now().astimezone(ART).date().isoformat()
        midnight = datetime.fromisoformat(self.fecha).replace(tzinfo=ART) + timedelta(days=1)
        self.alta_deadline = self.start + (midnight - now().astimezone(ART)).total_seconds() - ALTA_RESERVA_FIN_DIA
        self.summary = dict(fecha=self.fecha, inicio=self.stamp(), fin=None, segundos=0, pasos=[])
        self.save()

    def stamp(self):
        return self.now().astimezone(ART).isoformat(timespec="seconds")

    def log(self, text):
        with self.log_lock, (self.logs / f"{self.modo}-{self.fecha}.log").open("a", encoding="utf-8") as out:
            for line in str(text).splitlines():
                # Chrome y el desglose ya vienen fechados en ART: conservá su instante original.
                if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", line):
                    out.write(line + "\n")
                else:
                    out.write(f"{self.now().astimezone(ART):%Y-%m-%d %H:%M:%S} {line}\n")

    def save(self):
        self.summary["segundos"] = round(self.clock() - self.start, 1)
        target = self.logs / f"{self.modo}-{self.fecha}.json"
        temp = target.with_suffix(".json.tmp")
        temp.write_text(json.dumps(self.summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(target)

    def process(self, command, deadline, paso, emit=True):
        if self.clock() >= deadline:
            raise TimeoutError("timeout")
        child = self.popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, encoding="utf-8", errors="replace", start_new_session=True)
        stdout_lines, stderr_lines = [], []

        def read(stream, lines):
            for line in stream:
                lines.append(line)
                if emit:
                    self.log(line.rstrip("\r\n"))

        readers = [threading.Thread(target=read, args=(stream, lines), daemon=True)
                   for stream, lines in ((child.stdout, stdout_lines), (child.stderr, stderr_lines))]
        for reader in readers:
            reader.start()
        try:
            while True:
                remaining = deadline - self.clock()
                if remaining <= 0:
                    raise TimeoutError("timeout")
                try:
                    child.wait(timeout=min(HEARTBEAT, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if self.clock() >= deadline:
                        raise TimeoutError("timeout")
                    self.log(f"PASO_SIGUE {self.bloque}:{paso} {self.clock() - self.step_start:.1f}s")
        except BaseException as exc:
            # Mata también los procesos locales descendientes del shell de Chrome.
            try:
                if os.name == "posix":
                    os.killpg(child.pid, signal.SIGKILL)
                else:
                    child.kill()
            except ProcessLookupError:
                pass
            child.wait()
            if isinstance(exc, TimeoutError):
                for reader in readers:
                    reader.join()
                tail = resumen_salida("".join(stderr_lines + stdout_lines).splitlines())
                raise TimeoutError(f"timeout: {tail}" if tail else "timeout") from exc
            raise
        finally:
            for reader in readers:
                reader.join()
            child.stdout.close()
            child.stderr.close()
        stdout, stderr = "".join(stdout_lines), "".join(stderr_lines)
        # El motivo resume la salida; quien necesite clasificar una falla mira la salida completa.
        self.ultima_salida = stdout
        if not emit and child.returncode:
            self.log(stdout)
            self.log(stderr)
        if child.returncode:
            tail = resumen_salida((stderr + "\n" + stdout).splitlines())
            # La ruta del desglose puede quedar fuera de las últimas líneas.
            report = re.search(r"desglose=\S+", stdout)
            if report and report[0] not in tail:
                tail += " | " + report[0]
            reason = "timeout" if child.returncode == 124 else "timeout o SIGKILL" if child.returncode == 137 else "error"
            raise RuntimeError(f"{reason} (código {child.returncode}): {tail}")
        return stdout

    def docker(self, container, *args, cwd=None, stdin=False, env=None):
        command = ["docker", "exec"]
        if stdin:
            command.append("-i")
        command += ["-e", f"PUBLICACION_MODO={self.bloque}"]
        for key, value in (env or {}).items():
            command += ["-e", f"{key}={value}"]
        if cwd:
            command += ["-w", cwd]
        return command + [container, *args]

    def deploy(self, deadline, ahora=False):
        self.desglose = None
        self.deploy_skip = False
        try:
            out = self.process(self.docker(DEPLOYER, "node", "/app/deploy.mjs", *(["--ahora"] if ahora else [])),
                               deadline, "deploy")
        except RuntimeError as exc:
            self.copiar_desglose(str(exc), deadline)
            raise
        if "DEPLOY_SKIP" in out and "DEPLOY_FAIL" not in out and "DEPLOY_OK" not in out:
            self.deploy_skip = True
            return
        report = self.copiar_desglose(out, deadline)
        if "DEPLOY_OK" not in out or "DEPLOY_FAIL" in out:
            raise RuntimeError("deploy sin DEPLOY_OK")
        self.desglose = report

    def copiar_desglose(self, out, deadline):
        report = re.search(r"desglose=(/state/logs/desglose-\d{4}-\d{2}-\d{2}-\d{4}\.log)(?:\s|$)", out)
        if report:
            try:
                self.process(self.docker(DEPLOYER, "cat", report[1]), deadline, "deploy")
            except Exception as exc:
                self.log(f"DEPLOY_ALERT no se pudo copiar {report[1]}: {exc}")
            return report[1]
        self.log("DEPLOY_ALERT resultado sin ruta de desglose")
        return None

    def deploy_ahora(self, deadline):
        self.deploy(deadline, ahora=True)

    def estado(self, deadline):
        if self.deploy_skip:
            self.log("PUBLICACION_SIN_CAMBIOS")
            return
        if not self.desglose:
            raise RuntimeError("sin desglose")
        # La ruta sólo se acepta desde el patrón estricto del resultado del deploy.
        # El lector devuelve 1 si el productor no entregó líneas PRODUCTO.
        read = self.docker(DEPLOYER, "cat", self.desglose)
        write = self.docker(WORKER, "python", "/app/tools/actualizar_publicacion.py", "--desglose", "-",
                            cwd="/app/worker", stdin=True)
        self.process(["sh", "-c", " ".join(read) + " | " + " ".join(write)], deadline, "estado")

    def chrome_barrido(self, deadline):
        """Antes del barrido: Chrome tiene que abrir y cerrar una pestaña. Si no, se reinicia y se espera."""
        chequeo = self.docker(CHROME_BARRIDO, "sh", "-c", CHROME_CHEQUEO)
        chequeo_cdp = self.docker(BARRIDO, "python", "-c", CHROME_CHEQUEO_CDP, cwd="/app")

        def sano():
            try:
                self.process(chequeo, min(deadline, self.clock() + 30), "chrome_barrido", emit=False)
                self.process(chequeo_cdp, min(deadline, self.clock() + CHROME_CHEQUEO_SEGUNDOS), "chrome_barrido", emit=False)
                return True
            except Exception:  # noqa: BLE001 — cualquier falla del chequeo cuenta como Chrome caído
                return False

        if sano():
            self.log("CHROME_BARRIDO_OK pestaña abierta y cerrada")
            return
        self.log(f"CHROME_BARRIDO_REINICIO {CHROME_BARRIDO} no abrió una pestaña; reinicio el contenedor")
        self.process(["docker", "restart", CHROME_BARRIDO], min(deadline, self.clock() + 60), "chrome_barrido")
        for intento in range(1, CHROME_ESPERAS + 1):
            self.sleep(3)
            if sano():
                self.log(f"CHROME_BARRIDO_OK tras el reinicio ({intento * 3} s)")
                return
        raise RuntimeError(f"CHROME_BARRIDO_FALLA sigue sin abrir pestañas {CHROME_ESPERAS * 3} s después del reinicio")

    def step(self, paso, timeout):
        self.step_start = self.clock()
        nombre = f"{self.bloque}:{paso}"
        record = dict(bloque=self.bloque, paso=nombre, inicio=self.stamp(), fin=None, segundos=0, estado="en_curso", motivo="")
        self.summary["pasos"].append(record)
        self.save()
        self.log(f"PASO_INICIO {nombre}")
        # El alta puede durar horas: cada paso tiene su plazo completo.
        # Deploy/estado conservan además su plazo aunque venciera el global.
        deadline = min(self.step_start + timeout, self.alta_deadline)
        buscar_env = None
        if self.bloque == "alta":
            deadline = min(deadline, self.alta_deadline)
            if paso == "buscar":
                cutoff = datetime.fromisoformat(self.fecha).replace(hour=BUSCAR_FIN_ART, tzinfo=ART)
                remaining = (cutoff - self.now().astimezone(ART)).total_seconds()
                if remaining <= BUSCAR_RESERVA:
                    record.update(estado="ok", motivo="plazo_buscar", fin=self.stamp(), segundos=0)
                    self.log("BUSCAR_FIN estado=pausado motivo=plazo_buscar")
                    self.save()
                    return
                deadline = min(deadline, self.clock() + remaining)
                buscar_env = {"BUSCAR_DEADLINE": str(cutoff.timestamp() - BUSCAR_RESERVA)}
        if self.bloque != "alta" and paso not in ("deploy", "estado"):
            deadline = min(self.deadline, deadline)
        try:
            if self.clock() >= deadline:
                raise TimeoutError("timeout global")
            if paso == "offers":
                self.process(self.docker(WORKER, "python", "-c", "import worker; worker.publicar_offers()",
                                         cwd="/app/worker"), deadline, paso)
            elif paso == "barrido_amazon":
                self.chrome_barrido(deadline)
                seconds = max(1, int(deadline - self.clock()))
                self.process(self.docker(BARRIDO, "timeout", "-s", "KILL", str(seconds), "python", "-m", "barrido",
                                         "--store", "US", "--output", BARRIDO_SALIDA, cwd="/app"), deadline, paso)
            elif paso == "barrido_ml":
                seconds = max(1, int(deadline - self.clock()))
                self.process(self.docker(BARRIDO, "timeout", "-s", "KILL", str(seconds), "python", "-m", "barrido",
                                         "--step", "ml-lookup", "--output", BARRIDO_SALIDA, cwd="/app"), deadline, paso)
            elif paso == "barrido_altas":
                seconds = max(1, int(deadline - self.clock()))
                self.process(self.docker(WORKER, "timeout", "-s", "KILL", str(seconds), "python",
                                         "/app/tools/barrido_a_altas.py", BARRIDO_SALIDA, cwd="/app/worker"), deadline, paso)
            elif paso == "mas_vendidos":
                seconds = max(1, int(deadline - self.clock()))
                self.ultima_salida = ""
                try:
                    self.process(self.docker(WORKER, "timeout", "-s", "KILL", str(seconds), "python",
                                             "/app/tools/actualizar_mas_vendidos.py", cwd="/app/worker"), deadline, paso)
                except RuntimeError as exc:
                    # Igual que el script: sin destacados nuevos no se toca la marca y la cadena sigue.
                    # Se mira la salida completa: el motivo resumido puede dejar afuera la marca (13/11).
                    if not str(exc).startswith("error (código 1)") or "MAS_VENDIDOS_FALLA" not in self.ultima_salida:
                        raise
                    record["motivo"] = "sin_destacados"
            elif paso == "chrome":
                env_timeout = max(1, int(deadline - self.clock()))
                extra = ["--pendientes"] if self.bloque == "alta" else []
                self.process(["env", f"PUBLICACION_MODO={self.bloque}", f"CADENA_TIMEOUT={env_timeout}", "sh", str(REPO / "tools/envio_ar_chrome.sh"), *extra],
                             deadline, paso)
            elif paso in ("buscar", "dudosos", "altas", "amazon", "ml", "fichas"):
                # El timeout dentro del contenedor mata el Python aunque muera docker exec en el host.
                seconds = max(1, int(deadline - self.clock()))
                scripts = {"buscar": "crecer_ahora", "dudosos": "dudosos_nvidia", "altas": "confirmar_altas"}
                script = [f"/app/tools/{scripts[paso]}.py"] if paso in scripts else ["/app/tools/refresh_ahora.py", paso]
                out = self.process(self.docker(WORKER, "timeout", "-s", "KILL", str(seconds), "python",
                                                    *script, cwd="/app/worker", env=buscar_env), deadline, paso)
                if paso == "altas":
                    m = re.search(r"ALTAS_OK promovidas=(\d+)", out or "")
                    self.promovidas = int(m[1]) if m else None
                    m = re.search(r"ALTAS_OK[^\n]*\bvencidos=(\d+)", out or "")
                    self.vencidos = int(m[1]) if m else None
            elif paso == "estado":
                self.estado(deadline)
            elif self.bloque == "alta":
                self.deploy_ahora(deadline)
            else:
                self.deploy(deadline)
            record["estado"] = "ok"
        except Exception as exc:
            record.update(estado="fail", motivo=str(exc))
            self.log(traceback.format_exc())
        finally:
            record.update(fin=self.stamp(), segundos=round(self.clock() - self.step_start, 1))
            self.log(f"PASO_{record['estado'].upper()} {nombre} {record['motivo']} {record['segundos']}s")
            self.save()

    def run(self):
        self.step_start = self.clock()
        try:
            self.process(self.docker(WORKER, "python", "/app/tools/actualizar_publicacion.py", "--verificar-estado",
                                     cwd="/app/worker"), min(self.clock() + ALTAS_TIMEOUT, self.alta_deadline), "estado_inicial")
        except Exception as exc:
            self.log(f"PUBLICACION_INICIO_ABORTADO {exc}")
            self.summary["fin"] = self.stamp()
            self.save()
            return 1
        self.promovidas = self.vencidos = None
        verificacion = (("offers", OFFERS_TIMEOUT), ("chrome", CHROME_TIMEOUT), ("amazon", AMAZON_TIMEOUT), ("ml", ML_TIMEOUT), ("fichas", ML_TIMEOUT),
                        ("deploy", DEPLOY_TIMEOUT), ("estado", ALTAS_TIMEOUT))
        # 10/11: «buscar» (crecer_ahora) queda para uso manual; el alta diaria es el barrido en tres pasos.
        alta = (("barrido_amazon", BARRIDO_AMAZON_TIMEOUT), ("barrido_ml", BARRIDO_ML_TIMEOUT),
                ("barrido_altas", BARRIDO_ALTAS_TIMEOUT), ("dudosos", AMAZON_TIMEOUT), ("chrome", CHROME_TIMEOUT),
                ("altas", ALTAS_TIMEOUT), ("amazon", AMAZON_TIMEOUT), ("ml", ML_TIMEOUT),
                ("mas_vendidos", MAS_VENDIDOS_TIMEOUT), ("deploy", DEPLOY_TIMEOUT), ("estado", ALTAS_TIMEOUT))
        verificacion_fallida = False
        for bloque, pasos in (("verificacion", verificacion), ("alta", alta)):
            self.bloque = bloque
            self.desglose = None
            self.deploy_skip = False
            # Cada bloque tiene su propio límite: una verificación agotada no impide el alta.
            if bloque == "alta":
                self.deadline = self.clock() + GLOBAL_TIMEOUT
            first = len(self.summary["pasos"])
            for paso, timeout in pasos:
                if self.now().astimezone(ART).date().isoformat() != self.fecha or self.clock() >= self.alta_deadline:
                    self.log(f"CADENA_FIN bloque={bloque} motivo=fin_dia_ART")
                    break
                if bloque == "alta" and paso == "deploy" and verificacion_fallida:
                    self.log("ALTA_SIN_DEPLOY verificacion_fallida")
                    break
                if bloque == "alta" and paso == "amazon" and self.promovidas == 0 and self.vencidos == 0:
                    self.log("ALTA sin altas promovidas ni no_revisar vencidos; termina el bloque")
                    break
                self.step(paso, timeout)
            records = self.summary["pasos"][first:]
            failed = sum(p["estado"] != "ok" for p in records)
            if bloque == "verificacion":
                verificacion_fallida = bool(failed)
            self.log(f"ETAPA_RESUMEN {bloque} pasos={len(records)} ok={len(records) - failed} fallidos={failed}")
        self.summary["fin"] = self.stamp()
        self.save()
        return int(any(p["estado"] != "ok" for p in self.summary["pasos"]))


def main(argv):
    argparse.ArgumentParser(description=__doc__).parse_args(argv)
    # Una única cadena usa Chrome y los archivos de publicación.
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "cadena.lock", "w") as lock:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX)
        return Cadena().run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
