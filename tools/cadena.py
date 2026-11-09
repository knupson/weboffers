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
HEARTBEAT = 30
ART = timezone(timedelta(hours=-3))
LOG_DIR = Path("/home/claude/logs")
REPO = Path(__file__).resolve().parents[1]
WORKER = "franquicia400-weboffers-worker-1"
DEPLOYER = "franquicia400-weboffers-deployer-1"


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
                tail = " | ".join("".join(stderr_lines or stdout_lines).splitlines()[-8:])
                raise TimeoutError(f"timeout: {tail}" if tail else "timeout") from exc
            raise
        finally:
            for reader in readers:
                reader.join()
            child.stdout.close()
            child.stderr.close()
        stdout, stderr = "".join(stdout_lines), "".join(stderr_lines)
        if not emit and child.returncode:
            self.log(stdout)
            self.log(stderr)
        if child.returncode:
            tail = " | ".join((stderr + "\n" + stdout).splitlines()[-8:])
            # La ruta del desglose puede quedar fuera de las últimas líneas.
            report = re.search(r"desglose=\S+", stdout)
            if report and report[0] not in tail:
                tail += " | " + report[0]
            reason = "timeout" if child.returncode == 124 else "timeout o SIGKILL" if child.returncode == 137 else "error"
            raise RuntimeError(f"{reason} (código {child.returncode}): {tail}")
        return stdout

    def docker(self, container, *args, cwd=None, stdin=False):
        command = ["docker", "exec"]
        if stdin:
            command.append("-i")
        command += ["-e", f"PUBLICACION_MODO={self.bloque}"]
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

    def step(self, paso, timeout):
        self.step_start = self.clock()
        nombre = f"{self.bloque}:{paso}"
        record = dict(bloque=self.bloque, paso=nombre, inicio=self.stamp(), fin=None, segundos=0, estado="en_curso", motivo="")
        self.summary["pasos"].append(record)
        self.save()
        self.log(f"PASO_INICIO {nombre}")
        deadline = min(self.deadline, self.step_start + timeout)
        try:
            if self.clock() >= deadline:
                raise TimeoutError("timeout global")
            if paso == "offers":
                self.process(self.docker(WORKER, "python", "-c", "import worker; worker.publicar_offers()",
                                         cwd="/app/worker"), deadline, paso)
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
                                                    *script, cwd="/app/worker"), deadline, paso)
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
                                     cwd="/app/worker"), self.clock() + ALTAS_TIMEOUT, "estado_inicial")
        except Exception as exc:
            self.log(f"PUBLICACION_INICIO_ABORTADO {exc}")
            self.summary["fin"] = self.stamp()
            self.save()
            return 1
        self.promovidas = self.vencidos = None
        verificacion = (("offers", AMAZON_TIMEOUT), ("chrome", CHROME_TIMEOUT), ("amazon", AMAZON_TIMEOUT), ("ml", ML_TIMEOUT), ("fichas", ML_TIMEOUT),
                        ("deploy", DEPLOY_TIMEOUT), ("estado", ALTAS_TIMEOUT))
        alta = (("buscar", AMAZON_TIMEOUT), ("dudosos", AMAZON_TIMEOUT), ("chrome", CHROME_TIMEOUT),
                ("altas", ALTAS_TIMEOUT), ("amazon", AMAZON_TIMEOUT), ("ml", ML_TIMEOUT),
                ("deploy", DEPLOY_TIMEOUT), ("estado", ALTAS_TIMEOUT))
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
