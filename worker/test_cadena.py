from datetime import datetime, timedelta
import json
import io
import subprocess
import pytest

from tools import cadena


class Reloj:
    segundos = 0

    def clock(self):
        return self.segundos

    def sleep(self, seconds):
        self.segundos += seconds

    def now(self):
        return datetime(2026, 11, 6, 3, 30, tzinfo=cadena.ART) + timedelta(seconds=self.segundos)


class Hijo:
    def __init__(self, reloj, seconds=1, code=0, out="", err=""):
        self.reloj, self.seconds, self.returncode = reloj, seconds, code
        self.out, self.err, self.killed = out, err, False
        self.stdout, self.stderr = io.StringIO(out), io.StringIO(err)

    def wait(self, timeout=None):
        if timeout is not None and self.seconds > timeout:
            self.seconds -= timeout
            self.reloj.sleep(timeout)
            raise subprocess.TimeoutExpired("simulado", timeout)
        self.reloj.sleep(self.seconds)
        self.seconds = 0
        return self.returncode

    def kill(self):
        self.killed, self.seconds = True, 0


def test_orden_continua_tras_falla_latido_y_resumen(tmp_path):
    reloj = Reloj()
    comandos = []

    def popen(command, **kwargs):
        comandos.append(command)
        resumen = json.loads((tmp_path / "cadena-2026-11-06.json").read_text())
        assert resumen["pasos"][-1]["estado"] == "en_curso"
        if command[-1] == "amazon":
            return Hijo(reloj, seconds=65, code=1, err="Traceback\nerror simulado")
        if "cat" in command:
            return Hijo(reloj, out=f"{reloj.now().isoformat()} DEPLOY_OK publicado\n")
        return Hijo(reloj)

    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    assert runner.run() == 1
    assert "envio_ar_chrome.sh" in comandos[0][-1]
    assert comandos[1][-1] == "/app/tools/confirmar_altas.py"
    assert [c[-1] for c in comandos[2:4]] == ["amazon", "ml"]
    assert "cadena-2026-11-06.json" in comandos[4][-2]
    resumen = json.loads((tmp_path / "cadena-2026-11-06.json").read_text())
    assert [p["paso"] for p in resumen["pasos"]] == ["chrome", "altas", "amazon", "ml", "deploy"]
    assert [p["estado"] for p in resumen["pasos"]] == ["ok", "ok", "fail", "ok", "ok"]
    assert resumen["fin"] and resumen["segundos"] == 70
    assert "error simulado" in resumen["pasos"][2]["motivo"]
    log = (tmp_path / "cadena-2026-11-06.log").read_text()
    assert "PASO_SIGUE amazon 30.0s" in log
    assert "PASO_SIGUE amazon 60.0s" in log
    assert all(line.startswith("2026-11-06 03:") for line in log.splitlines())


def test_timeout_mata_hijo_y_guarda_parcial(tmp_path, monkeypatch):
    reloj = Reloj()
    hijo = Hijo(reloj, seconds=1000, err="error antes del timeout")
    # El host real usa killpg; se verifica esa ruta sin matar un proceso real.
    hijo.pid = 12345
    monkeypatch.setattr(cadena.os, "killpg", lambda *a: hijo.kill(), raising=False)
    runner = cadena.Cadena(tmp_path, lambda *a, **kw: hijo, reloj.clock, reloj.now, reloj.sleep)
    runner.step("amazon", 35)
    assert hijo.killed
    paso = json.loads((tmp_path / "cadena-2026-11-06.json").read_text())["pasos"][0]
    assert paso["estado"] == "fail" and paso["motivo"].startswith("timeout")
    assert "error antes del timeout" in paso["motivo"]
    assert paso["segundos"] == 35
    assert "error antes del timeout" in (tmp_path / "cadena-2026-11-06.log").read_text()


def test_limite_global_no_lanza_nuevos_procesos(tmp_path):
    reloj = Reloj()
    runner = cadena.Cadena(tmp_path, lambda *a, **kw: (_ for _ in ()).throw(AssertionError()),
                           reloj.clock, reloj.now, reloj.sleep)
    runner.deadline = reloj.clock()
    assert runner.run() == 1
    assert all(p["motivo"] == "timeout global" for p in runner.summary["pasos"])


def test_deploy_ignora_resultado_anterior_y_registra_falla_actual(tmp_path):
    reloj = Reloj()
    calls = []

    def popen(command, **kw):
        calls.append(command)
        if "cat" in command:
            out = "2026-11-06T06:00:00Z DEPLOY_OK anterior\n"
            if len(calls) > 2:
                out += f"{reloj.now().isoformat()} DEPLOY_FAIL build\n"
            return Hijo(reloj, out=out)
        return Hijo(reloj)

    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    runner.step("deploy", 100)
    assert runner.summary["pasos"][0]["estado"] == "fail"
    assert "DEPLOY_FAIL build" in runner.summary["pasos"][0]["motivo"]


def test_bloqueo_compartido_impide_refresh_simultaneos(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from refresh_lock import locked_refresh

    dentro = threading.Event()
    liberar = threading.Event()
    segundo = threading.Event()

    @locked_refresh
    def refresh(catalog, path, primero):
        if primero:
            dentro.set()
            assert liberar.wait(5)
        else:
            segundo.set()

    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(refresh, [], tmp_path / "amazon-prices.json", True)
        assert dentro.wait(5)
        b = pool.submit(refresh, [], tmp_path / "amazon-prices.json", False)
        try:
            assert not segundo.wait(0.2)
        finally:
            liberar.set()
        a.result()
        b.result()
    assert segundo.is_set()


@pytest.mark.parametrize('status', ['OK', 'FAIL'])
def test_deploy_copia_el_desglose_exactamente_despues_del_resultado(tmp_path, status):
    reloj = Reloj()
    report_path = '/state/logs/desglose-2026-11-06-0330.log'
    report = '2026-11-06 03:30:00 PRODUCTO kindle asin=B0CFPJYX7P origen=repo PUBLICADO\n2026-11-06 03:30:00 TOTALES total=1 publicados=1 filtrados=0\n'
    calls = []
    def popen(command, **kw):
        calls.append(command)
        if command[-1] == report_path:
            return Hijo(reloj, out=report)
        if 'cat' in command:
            return Hijo(reloj, out=f'{reloj.now().isoformat()} DEPLOY_{status} prueba desglose={report_path}\n')
        return Hijo(reloj)
    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    runner.step('deploy', 100)
    text = (tmp_path / 'cadena-2026-11-06.log').read_text(encoding='utf-8')
    assert report in text
    assert text.index(f'DEPLOY_{status}') < text.index('PRODUCTO kindle') < text.index(f'PASO_{status}')
    assert calls[-1] == ['docker', 'exec', cadena.DEPLOYER, 'cat', report_path]
    assert runner.summary['pasos'][0]['estado'] == ('ok' if status == 'OK' else 'fail')
