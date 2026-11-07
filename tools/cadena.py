#!/usr/bin/env python3
"""Cadena nocturna del host: Chrome → altas → Amazon → ML → deployer.

Chrome releva catálogo y pendientes en una sola pasada. Altas corre en el worker
y promueve únicamente envío gratis a Argentina y precio USD 100–400 de hoy.
Cada paso arranca al terminar el anterior y queda en el log y JSON de la cadena.
"""
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
        # modo «tras-alta» (07/11): lo dispara el fin del alta nocturna; sólo pendientes, log propio y deploy --ahora.
        self.modo = modo
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
                    self.log(f"PASO_SIGUE {paso} {self.clock() - self.step_start:.1f}s")
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
            tail = " | ".join((stderr or stdout).splitlines()[-8:])
            reason = "timeout" if child.returncode == 124 else "timeout o SIGKILL" if child.returncode == 137 else "error"
            raise RuntimeError(f"{reason} (código {child.returncode}): {tail}")
        return stdout

    def deploy(self, deadline):
        since = self.now().astimezone(timezone.utc)
        marker = json.dumps(dict(fecha=self.fecha, fin=self.stamp()))
        code = "import pathlib,sys; p=pathlib.Path(sys.argv[1]); t=p.with_suffix('.tmp'); t.write_text(sys.argv[2]); t.replace(p)"
        self.process(["docker", "exec", WORKER, "python", "-c", code,
                      f"/app/output/cadena-{self.fecha}.json", marker], deadline, "deploy")
        while self.clock() < deadline:
            try:
                content = self.process(["docker", "exec", DEPLOYER, "cat",
                                        f"/state/logs/deployer-{self.fecha}.log"], deadline, "deploy", emit=False)
            except RuntimeError as exc:
                self.log(f"DEPLOY_ESPERA {exc}")
                content = ""
            for line in content.splitlines():
                parts = line.split(" ", 2)
                if len(parts) < 2 or parts[1] not in ("DEPLOY_OK", "DEPLOY_FAIL"):
                    continue
                try:
                    at = datetime.fromisoformat(parts[0].replace("Z", "+00:00"))
                except ValueError:
                    continue
                if at < since:
                    continue
                self.log(line)
                report = re.search(r"desglose=(\S+)", line)
                if report and re.fullmatch(r"/state/logs/desglose-\d{4}-\d{2}-\d{2}-\d{4}\.log", report[1]):
                    try:
                        self.process(["docker", "exec", DEPLOYER, "cat", report[1]], deadline, "deploy")
                    except Exception as exc:
                        self.log(f"DEPLOY_ALERT no se pudo copiar {report[1]}: {exc}")
                else:
                    self.log("DEPLOY_ALERT resultado sin ruta de desglose")
                if parts[1] == "DEPLOY_FAIL":
                    raise RuntimeError(line)
                return
            self.sleep(min(HEARTBEAT, max(0, deadline - self.clock())))
            self.log(f"PASO_SIGUE deploy {self.clock() - self.step_start:.1f}s")
        raise TimeoutError("timeout esperando DEPLOY_OK / DEPLOY_FAIL")

    def deploy_ahora(self, deadline):
        # El marcador cadena-AAAA-MM-DD.json despliega una sola vez por día: un segundo deploy va por --ahora.
        out = self.process(["docker", "exec", DEPLOYER, "node", "/app/deploy.mjs", "--ahora"], deadline, "deploy")
        if "DEPLOY_OK" not in out:
            raise RuntimeError("deploy --ahora sin DEPLOY_OK")
        report = re.search(r"desglose=(/state/logs/desglose-\d{4}-\d{2}-\d{2}-\d{4}\.log)", out)
        if report:
            self.process(["docker", "exec", DEPLOYER, "cat", report[1]], deadline, "deploy")

    def step(self, paso, timeout):
        self.step_start = self.clock()
        record = dict(paso=paso, inicio=self.stamp(), fin=None, segundos=0, estado="en_curso", motivo="")
        self.summary["pasos"].append(record)
        self.save()
        self.log(f"PASO_INICIO {paso}")
        deadline = min(self.deadline, self.step_start + timeout)
        try:
            if self.clock() >= deadline:
                raise TimeoutError("timeout global")
            if paso == "chrome":
                env_timeout = max(1, int(deadline - self.clock()))
                extra = ["--pendientes"] if self.modo == "tras-alta" else []
                self.process(["env", f"CADENA_TIMEOUT={env_timeout}", "sh", str(REPO / "tools/envio_ar_chrome.sh"), *extra],
                             deadline, paso)
            elif paso in ("altas", "amazon", "ml"):
                # El timeout dentro del contenedor mata el Python aunque muera docker exec en el host.
                seconds = max(1, int(deadline - self.clock()))
                script = ["/app/tools/confirmar_altas.py"] if paso == "altas" else ["/app/tools/refresh_ahora.py", paso]
                out = self.process(["docker", "exec", "-w", "/app/worker", WORKER,
                                    "timeout", "-s", "KILL", str(seconds), "python",
                                    *script], deadline, paso)
                if paso == "altas":
                    m = re.search(r"ALTAS_OK promovidas=(\d+)", out or "")
                    self.promovidas = int(m[1]) if m else None
            elif self.modo == "tras-alta":
                self.deploy_ahora(deadline)
            else:
                self.deploy(deadline)
            record["estado"] = "ok"
        except Exception as exc:
            record.update(estado="fail", motivo=str(exc))
            self.log(traceback.format_exc())
        finally:
            record.update(fin=self.stamp(), segundos=round(self.clock() - self.step_start, 1))
            self.log(f"PASO_{record['estado'].upper()} {paso} {record['segundos']}s {record['motivo']}")
            self.save()

    def run(self):
        self.promovidas = None
        for paso, timeout in (("chrome", CHROME_TIMEOUT), ("altas", ALTAS_TIMEOUT), ("amazon", AMAZON_TIMEOUT),
                              ("ml", ML_TIMEOUT), ("deploy", DEPLOY_TIMEOUT)):
            if self.modo == "tras-alta" and paso == "amazon" and self.promovidas == 0:
                self.log("TRAS_ALTA sin altas promovidas; no hace falta desplegar")
                break
            self.step(paso, timeout)
        self.summary["fin"] = self.stamp()
        self.save()
        return int(any(p["estado"] != "ok" for p in self.summary["pasos"]))


def main(argv):
    modo = "tras-alta" if "--tras-alta" in argv else "cadena"
    # Las dos cadenas usan el mismo Chrome y los mismos archivos: nunca corren juntas (la segunda espera).
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_DIR / "cadena.lock", "w") as lock:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX)
        return Cadena(modo=modo).run()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
