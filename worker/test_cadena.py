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
    runner.step("amazon", 35)
    assert all(p["motivo"] == "timeout global" for p in runner.summary["pasos"])


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


PASOS = [f"verificacion:{p}" for p in ("offers", "chrome", "amazon", "ml", "fichas", "deploy", "estado")] + [
    f"alta:{p}" for p in ("barrido_amazon", "barrido_ml", "barrido_altas", "dudosos", "chrome", "altas", "amazon", "ml", "mas_vendidos", "deploy", "estado")]


def corrida(tmp_path, promovidas=1, vencidos=0, falla=None, sin_desglose=False, skip=False):
    reloj, comandos = Reloj(), []
    runner = None

    def popen(command, **kwargs):
        comandos.append(command)
        if "--verificar-estado" in command:
            return Hijo(reloj, out="PUBLICACION_ESTADO_OK\n")
        actual = runner.summary["pasos"][-1]
        runner.llamadas.append((actual["bloque"], command))
        assert actual["estado"] == "en_curso"
        if falla == (actual["bloque"], actual["paso"].split(":")[-1]):
            return Hijo(reloj, seconds=65, code=1, err="error simulado")
        if "/app/tools/confirmar_altas.py" in command:
            return Hijo(reloj, out=f"ALTAS_OK promovidas={promovidas} rechazadas=0 siguen_pendientes=0 vencidos={vencidos}\n")
        if "/app/deploy.mjs" in command:
            if skip:
                return Hijo(reloj, out="DEPLOY_SKIP sin cambios\n")
            ruta = f"/state/logs/desglose-2026-11-06-{'0330' if actual['bloque'] == 'verificacion' else '0430'}.log"
            return Hijo(reloj, out="DEPLOY_OK publicado" + ("" if sin_desglose else f" desglose={ruta}") + "\n")
        return Hijo(reloj)

    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    runner.llamadas = []
    code = runner.run()
    return runner, comandos, code


def test_orden_verificacion_y_despues_alta(tmp_path):
    runner, comandos, code = corrida(tmp_path)
    assert code == 0
    assert [p["paso"] for p in runner.summary["pasos"]] == PASOS
    assert [p["bloque"] for p in runner.summary["pasos"]] == ["verificacion"] * 7 + ["alta"] * 11
    assert runner.summary["fin"]
    barrido = next(i for i, c in enumerate(comandos) if c[-4:] == ["--store", "US", "--output", cadena.BARRIDO_SALIDA])
    assert cadena.CHROME_BARRIDO in comandos[barrido - 2]  # chequeo de pestaña de Chrome
    assert cadena.CHROME_CHEQUEO_CDP in comandos[barrido - 1]  # y conexión real de Playwright, justo antes del barrido
    assert comandos[barrido + 3][-1] == "/app/tools/dudosos_nvidia.py"
    chrome = [c for c in comandos if any("envio_ar_chrome.sh" in x for x in c)]
    assert "--pendientes" not in chrome[0] and chrome[1][-1] == "--pendientes"
    deploy = [c for c in comandos if "/app/deploy.mjs" in c]
    assert "--ahora" not in deploy[0] and deploy[1][-1] == "--ahora"


def test_cada_paso_una_vez(tmp_path):
    runner, comandos, code = corrida(tmp_path)
    pares = [(p["bloque"], p["paso"]) for p in runner.summary["pasos"]]
    assert len(pares) == len(set(pares)) == 18
    # Los dos deploy copian su desglose al log; el barrido suma 3 pasos y el chequeo de Chrome (10/11),
    # que desde el 11/11 son dos comandos: pestaña y conexión real de Playwright.
    # 13/11: más el paso de «Lo más vendido» antes del deploy del alta.
    assert len(comandos) == 23
    assert sum("/app/deploy.mjs" in c for c in comandos) == 2


def test_modo_viaja_en_el_entorno(tmp_path):
    runner, comandos, _ = corrida(tmp_path)
    for bloque, command in runner.llamadas:
        modo = f"PUBLICACION_MODO={bloque}"
        if command[0] == "docker":
            assert ["-e", modo] == command[2:4]
        elif command[0] == "env":
            assert modo in command
        else:
            assert command[:2] == ["sh", "-c"]
            assert command[2].count(f"-e {modo}") == 2


@pytest.mark.parametrize("remaining", [5400, 1000, 500])
def test_buscar_tiene_plazo_propio_sin_corte_interno(tmp_path, remaining):
    reloj = Reloj()
    commands = []
    def spawn(command, **kwargs):
        commands.append(command)
        return Hijo(reloj)
    runner = cadena.Cadena(tmp_path, spawn, reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.deadline = remaining
    runner.step("buscar", cadena.BUSCAR_TIMEOUT)
    command = commands[0]
    assert not any("CATALOG_AUTO_MAX_SECONDS" in arg for arg in command)
    assert command[command.index("timeout"):command.index("python")] == ["timeout", "-s", "KILL", str(int((reloj.now().replace(hour=20, minute=0, second=0) - reloj.now()).total_seconds()) + 1)]
    assert any(arg.startswith("BUSCAR_DEADLINE=") for arg in command)


@pytest.mark.parametrize("bloque", ["verificacion", "alta"])
def test_deploy_y_estado_conservan_plazo_completo(tmp_path, bloque):
    reloj = Reloj()
    commands = []
    def spawn(command, **kwargs):
        commands.append(command)
        return Hijo(reloj, seconds=70, out="DEPLOY_OK desglose=/state/logs/desglose-2026-11-06-0330.log\n")
    runner = cadena.Cadena(tmp_path, spawn, reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = bloque
    runner.deadline = 0
    runner.step("deploy", cadena.DEPLOY_TIMEOUT)
    runner.step("estado", cadena.ALTAS_TIMEOUT)
    assert [p["estado"] for p in runner.summary["pasos"]] == ["ok", "ok"]
    assert [p["segundos"] for p in runner.summary["pasos"]] == [140, 70]
    assert len(commands) == 3



def test_falla_verificacion_alta_corre_igual(tmp_path):
    runner, comandos, code = corrida(tmp_path, falla=("verificacion", "amazon"))
    assert code == 1
    assert [p["paso"] for p in runner.summary["pasos"]] == PASOS[:-2]
    assert all(p["estado"] == "ok" for p in runner.summary["pasos"][7:])
    log = (tmp_path / "cadena-2026-11-06.log").read_text(encoding="utf-8")
    assert "PASO_SIGUE verificacion:amazon 30.0s" in log and "PASO_SIGUE verificacion:amazon 60.0s" in log
    assert "ETAPA_RESUMEN verificacion" in log and "ETAPA_RESUMEN alta" in log
    assert all(line.startswith("2026-11-06 03:") for line in log.splitlines())


def test_alta_no_despliega_si_verificacion_fallo(tmp_path):
    runner, comandos, code = corrida(tmp_path, falla=("verificacion", "amazon"))
    assert code == 1
    alta = [p["paso"] for p in runner.summary["pasos"] if p["bloque"] == "alta"]
    assert alta == [f"alta:{p}" for p in ("barrido_amazon", "barrido_ml", "barrido_altas", "dudosos", "chrome", "altas", "amazon", "ml", "mas_vendidos")]
    assert not any("--ahora" in c for c in comandos)
    assert "ALTA_SIN_DEPLOY verificacion_fallida" in (tmp_path / "cadena-2026-11-06.log").read_text()


def test_sin_estado_no_arranca(tmp_path):
    reloj, comandos = Reloj(), []
    def popen(command, **kwargs):
        comandos.append(command)
        return Hijo(reloj, code=1, out="PUBLICACION_SIN_ESTADO falta publicacion.json\n")
    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    assert runner.run() == 1
    assert runner.summary["pasos"] == []
    assert len(comandos) == 1
    assert "--verificar-estado" in comandos[0]
    assert runner.summary["fin"]


def test_deploy_fallido_copia_desglose_aunque_haya_stderr(tmp_path):
    reloj, comandos = Reloj(), []
    ruta = "/state/logs/desglose-2026-11-06-0330.log"
    def popen(command, **kwargs):
        comandos.append(command)
        if "cat" in command:
            return Hijo(reloj, out="PRODUCTO prueba asin=BPRUEBA origen=repo FILTRADO\n")
        return Hijo(reloj, code=1, out=f"DEPLOY_FAIL prueba desglose={ruta}\n", err="advertencia de git\n")
    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    runner.step("deploy", 100)
    assert comandos[-1][-2:] == ["cat", ruta]
    assert "PRODUCTO prueba" in (tmp_path / "cadena-2026-11-06.log").read_text()


def test_fichas_se_ejecuta_una_vez_en_verificacion(tmp_path):
    runner, comandos, code = corrida(tmp_path)
    assert code == 0
    assert [p["paso"] for p in runner.summary["pasos"]].count("verificacion:fichas") == 1
    assert any(c[-2:] == ["/app/tools/refresh_ahora.py", "fichas"] for c in comandos)


def test_estado_recibe_el_desglose_del_deploy(tmp_path):
    _, comandos, code = corrida(tmp_path)
    assert code == 0
    estados = [c[2] for c in comandos if c[:2] == ["sh", "-c"]]
    for command, hora, modo in zip(estados, ["0330", "0430"], ["verificacion", "alta"]):
        assert command == (f"docker exec -e PUBLICACION_MODO={modo} {cadena.DEPLOYER} cat "
                           f"/state/logs/desglose-2026-11-06-{hora}.log | "
                           f"docker exec -i -e PUBLICACION_MODO={modo} -w /app/worker {cadena.WORKER} "
                           "python /app/tools/actualizar_publicacion.py --desglose -")


def test_estado_falla_sin_desglose(tmp_path):
    runner, _, code = corrida(tmp_path, sin_desglose=True)
    assert code == 1
    estados = [p for p in runner.summary["pasos"] if p["paso"].endswith(":estado")]
    assert len(estados) == 1
    assert all(p["estado"] == "fail" and p["motivo"] == "sin desglose" for p in estados)


@pytest.mark.parametrize("vencidos,esperados", [(0, PASOS[:13]), (1, PASOS)])
def test_sin_altas_promovidas_corta_solo_sin_vencidos(tmp_path, vencidos, esperados):
    runner, _, code = corrida(tmp_path, promovidas=0, vencidos=vencidos)
    assert code == 0
    assert [p["paso"] for p in runner.summary["pasos"]] == esperados


def test_timeout_del_bloque_no_impide_el_alta(tmp_path):
    reloj = Reloj()
    comandos = []
    def popen(command, **kwargs):
        comandos.append(command)
        return Hijo(reloj)
    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    runner.deadline = reloj.clock()
    assert runner.run() == 1
    assert all(p["motivo"] == "timeout global" for p in runner.summary["pasos"][:5])
    assert runner.summary["pasos"][5]["motivo"] == "deploy sin DEPLOY_OK"
    assert runner.summary["pasos"][6]["motivo"] == "sin desglose"
    assert any(cadena.BARRIDO in c for c in comandos)
    assert len(runner.summary["pasos"]) == 16  # 7 de verificación + 9 del alta hasta el deploy


def test_deploy_fallido_no_reutiliza_el_desglose_anterior(tmp_path):
    runner, comandos, code = corrida(tmp_path, falla=("alta", "deploy"))
    assert code == 1
    ultimo = runner.summary["pasos"][-1]
    assert ultimo["paso"] == "alta:estado" and ultimo["motivo"] == "sin desglose"
    assert len([c for c in comandos if c[:2] == ["sh", "-c"]]) == 1


@pytest.mark.parametrize("status", ["OK", "FAIL"])
def test_deploy_copia_el_desglose_exactamente_despues_del_resultado(tmp_path, status):
    reloj = Reloj()
    ruta = "/state/logs/desglose-2026-11-06-0330.log"
    informe = "2026-11-06 03:30:00 PRODUCTO kindle asin=B0CFPJYX7P origen=repo PUBLICADO\n"
    comandos = []
    def popen(command, **kwargs):
        comandos.append(command)
        if "cat" in command:
            return Hijo(reloj, out=informe)
        return Hijo(reloj, code=int(status == "FAIL"), out=f"DEPLOY_{status} prueba desglose={ruta}\n")
    runner = cadena.Cadena(tmp_path, popen, reloj.clock, reloj.now, reloj.sleep)
    runner.step("deploy", 100)
    texto = (tmp_path / "cadena-2026-11-06.log").read_text(encoding="utf-8")
    assert informe in texto
    assert texto.index(f"DEPLOY_{status}") < texto.index("PRODUCTO kindle") < texto.index(f"PASO_{status}")
    assert comandos[-1] == ["docker", "exec", "-e", "PUBLICACION_MODO=verificacion", cadena.DEPLOYER, "cat", ruta]
    assert runner.summary["pasos"][0]["estado"] == ("ok" if status == "OK" else "fail")


def test_segunda_corrida_mismo_dia_sin_cambios_termina_ok(tmp_path):
    assert corrida(tmp_path)[2] == 0
    runner, commands, code = corrida(tmp_path, skip=True)
    assert code == 0
    assert all(p["estado"] == "ok" for p in runner.summary["pasos"])
    assert not any(c[:2] == ["sh", "-c"] for c in commands)
    text = (tmp_path / "cadena-2026-11-06.log").read_text(encoding="utf-8")
    assert text.count("PUBLICACION_SIN_CAMBIOS") == 2
    assert "PASO_OK verificacion:estado" in text
    assert "PASO_OK alta:estado" in text


def test_offers_una_vez_antes_de_chrome(tmp_path):
    runner, commands, code = corrida(tmp_path)
    assert code == 0
    assert commands[1] == ["docker", "exec", "-e", "PUBLICACION_MODO=verificacion", "-w", "/app/worker",
                           cadena.WORKER, "python", "-c", "import worker; worker.publicar_offers()"]
    assert sum("import worker; worker.publicar_offers()" in c for c in commands) == 1


def test_rechaza_modo_retirado_antes_de_crear_log():
    with pytest.raises(SystemExit) as exc:
        cadena.main(["--tras-alta"])
    assert exc.value.code == 2


def test_barrido_chequea_chrome_y_lo_reinicia_si_no_abre_pestanas(tmp_path):
    # 10/11: tras un OOM /json/version respondía y el CDP no servía; la cadena reinicia el Chrome del barrido.
    reloj, comandos = Reloj(), []
    chequeos = iter([1, 1, 0])  # falla, falla tras reiniciar, después anda

    def spawn(command, **kwargs):
        comandos.append(command)
        if cadena.CHROME_BARRIDO in command and "sh" in command:
            return Hijo(reloj, code=next(chequeos))
        return Hijo(reloj)
    runner = cadena.Cadena(tmp_path, spawn, reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("barrido_amazon", cadena.BARRIDO_AMAZON_TIMEOUT)
    assert ["docker", "restart", cadena.CHROME_BARRIDO] in comandos
    barrido = comandos[-1]
    assert barrido[barrido.index(cadena.BARRIDO) + 1:][4:] == ["python", "-m", "barrido", "--store", "US",
                                                                "--output", cadena.BARRIDO_SALIDA]
    assert runner.summary["pasos"][-1]["estado"] == "ok"
    log = (tmp_path / "cadena-2026-11-06.log").read_text(encoding="utf-8")
    assert "CHROME_BARRIDO_REINICIO" in log and "CHROME_BARRIDO_OK tras el reinicio (6 s)" in log


def test_barrido_reinicia_chrome_si_abre_pestanas_pero_playwright_no_conecta(tmp_path):
    # 11/11: tras el OOM de 04:20:57 /json/new respondía pero connect_over_cdp vencía (6 de 6, 07:30).
    reloj, comandos = Reloj(), []
    cdp = iter([1, 0])  # Playwright no conecta; tras el reinicio sí

    def spawn(command, **kwargs):
        comandos.append(command)
        if cadena.CHROME_CHEQUEO_CDP in command:
            return Hijo(reloj, code=next(cdp))
        return Hijo(reloj)
    runner = cadena.Cadena(tmp_path, spawn, reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("barrido_amazon", cadena.BARRIDO_AMAZON_TIMEOUT)
    assert ["docker", "restart", cadena.CHROME_BARRIDO] in comandos
    assert runner.summary["pasos"][-1]["estado"] == "ok"
    log = (tmp_path / "cadena-2026-11-06.log").read_text(encoding="utf-8")
    assert "CHROME_BARRIDO_REINICIO" in log and "CHROME_BARRIDO_OK tras el reinicio (3 s)" in log


def test_barrido_no_arranca_si_chrome_no_vuelve(tmp_path):
    reloj, comandos = Reloj(), []

    def spawn(command, **kwargs):
        comandos.append(command)
        return Hijo(reloj, code=1 if cadena.CHROME_BARRIDO in command and "sh" in command else 0)
    runner = cadena.Cadena(tmp_path, spawn, reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("barrido_amazon", cadena.BARRIDO_AMAZON_TIMEOUT)
    paso = runner.summary["pasos"][-1]
    assert paso["estado"] == "fail" and "CHROME_BARRIDO_FALLA" in paso["motivo"]
    assert not any("barrido" in c and "-m" in c for c in comandos)


def test_pasos_ml_y_altas_del_barrido(tmp_path):
    reloj, comandos = Reloj(), []
    runner = cadena.Cadena(tmp_path, lambda command, **kw: comandos.append(command) or Hijo(reloj),
                           reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("barrido_ml", cadena.BARRIDO_ML_TIMEOUT)
    runner.step("barrido_altas", cadena.BARRIDO_ALTAS_TIMEOUT)
    assert comandos[0][-5:] == ["barrido", "--step", "ml-lookup", "--output", cadena.BARRIDO_SALIDA]
    assert cadena.BARRIDO in comandos[0]
    assert comandos[1][-2:] == ["/app/tools/barrido_a_altas.py", cadena.BARRIDO_SALIDA] and cadena.WORKER in comandos[1]



# 13/11: «Lo más vendido» se renueva en la cadena, justo antes del deploy del alta.
def test_mas_vendidos_corre_en_el_worker_justo_antes_del_deploy_del_alta(tmp_path):
    runner, comandos, code = corrida(tmp_path)
    assert code == 0
    alta = [p["paso"] for p in runner.summary["pasos"] if p["bloque"] == "alta"]
    assert alta.index("alta:mas_vendidos") == alta.index("alta:deploy") - 1
    mas = [c for c in comandos if "/app/tools/actualizar_mas_vendidos.py" in c]
    assert len(mas) == 1 and cadena.WORKER in mas[0]
    assert comandos[comandos.index(mas[0]) + 1][-2:] == ["/app/deploy.mjs", "--ahora"]


def test_mas_vendidos_sin_destacados_no_corta_la_cadena(tmp_path):
    reloj = Reloj()
    salida = "2026-11-13 07:12:28 MAS_VENDIDOS_FALLA sin destacados de ML hoy (categorias_con_error=3); no se escribe nada\n"
    runner = cadena.Cadena(tmp_path, lambda *a, **kw: Hijo(reloj, code=1, out=salida),
                           reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("mas_vendidos", cadena.MAS_VENDIDOS_TIMEOUT)
    paso = runner.summary["pasos"][0]
    assert paso["estado"] == "ok" and paso["motivo"] == "sin_destacados"
    assert "MAS_VENDIDOS_FALLA" in (tmp_path / "cadena-2026-11-06.log").read_text(encoding="utf-8")


def test_mas_vendidos_sin_destacados_con_lineas_de_timeout_sigue_siendo_ok(tmp_path):
    # Revisor, 13/11: con líneas «Timeout» antes, el motivo resumido dejaba afuera MAS_VENDIDOS_FALLA.
    reloj = Reloj()
    salida = "".join(
        f"2026-11-13T07:12:2{i}-03:00 BUSCAR_CATEGORIA id=MLA100{i} estado=error motivo=ConnectTimeoutError\n"
        for i in range(4)) + "2026-11-13 07:12:28 MAS_VENDIDOS_FALLA sin destacados de ML hoy (categorias_con_error=4); no se escribe nada\n"
    runner = cadena.Cadena(tmp_path, lambda *a, **kw: Hijo(reloj, code=1, out=salida),
                           reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("mas_vendidos", cadena.MAS_VENDIDOS_TIMEOUT)
    paso = runner.summary["pasos"][0]
    assert paso["estado"] == "ok" and paso["motivo"] == "sin_destacados"


def test_mas_vendidos_codigo_distinto_de_1_falla_aunque_haya_marca(tmp_path):
    reloj = Reloj()
    runner = cadena.Cadena(tmp_path, lambda *a, **kw: Hijo(reloj, code=137, out="MAS_VENDIDOS_FALLA x\n"),
                           reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("mas_vendidos", cadena.MAS_VENDIDOS_TIMEOUT)
    assert runner.summary["pasos"][0]["estado"] == "fail"


def test_mas_vendidos_con_error_real_falla_el_paso(tmp_path):
    reloj = Reloj()
    runner = cadena.Cadena(tmp_path, lambda *a, **kw: Hijo(reloj, code=1, err="Traceback\nValueError: catalogo roto\n"),
                           reloj.clock, reloj.now, reloj.sleep)
    runner.bloque = "alta"
    runner.step("mas_vendidos", cadena.MAS_VENDIDOS_TIMEOUT)
    paso = runner.summary["pasos"][0]
    assert paso["estado"] == "fail" and "catalogo roto" in paso["motivo"]


def test_mas_vendidos_falla_y_el_alta_igual_despliega(tmp_path):
    runner, comandos, code = corrida(tmp_path, falla=("alta", "mas_vendidos"))
    assert code == 1
    assert [p["paso"] for p in runner.summary["pasos"]] == PASOS
    assert any("--ahora" in c for c in comandos)

# 12/11: barrido_ml salió con código 1 por un solo BARRIDO_ML_ERROR y el motivo guardó las últimas 8 líneas
# crudas (BARRIDO_ML_SIN_TRADUCCION con 579 palabras, BARRIDO_PROCESO_FIN...): 11.222 caracteres por WhatsApp.
LINEA_ML_ERROR = ('2026-11-12T04:26:54.033798-03:00 BARRIDO_ML_ERROR {"etapa": "ml_lookup", "tienda": "ML", '
                  '"categoria": null, "pagina": 1, "asin": "B0FCFKQBSH", "intento": 1, "motivo": '
                  '"(\'Connection aborted.\', RemoteDisconnected(\'Remote end closed connection without response\'))", '
                  '"http": null, "run_id": "3d3506d13d504397941733cc3ad5b7e0", "pid": 88}')


def salida_ml_con_json_pesado():
    palabras = json.dumps({"etapa": "ml_lookup", "cantidad": 579, "palabras": [f"palabra{i}" for i in range(1200)]})
    cierre = json.dumps({"etapa": "ml_lookup", "estado": "partial", "errors": 1, "args": {"x": "y" * 3000}})
    return "\n".join([LINEA_ML_ERROR] + [f"2026-11-12T05:54:06-03:00 BARRIDO_DESCARTE {cierre}"] * 5 + [
        f"2026-11-12T05:54:09-03:00 BARRIDO_ML_SIN_TRADUCCION {palabras}",
        f"2026-11-12T05:54:09-03:00 BARRIDO_PROCESO_FIN {cierre}"]) + "\n"


def test_motivo_de_falla_prioriza_la_linea_de_error_y_tiene_tope(tmp_path):
    reloj = Reloj()
    salida = salida_ml_con_json_pesado()
    assert len(salida) > 10_000
    runner = cadena.Cadena(tmp_path, lambda command, **kw: Hijo(reloj, code=1, out=salida), reloj.clock, reloj.now, reloj.sleep)
    with pytest.raises(RuntimeError) as exc:
        runner.process(["python", "-m", "barrido"], 100, "barrido_ml")
    motivo = str(exc.value)
    assert motivo.startswith("error (código 1): ")
    assert "BARRIDO_ML_ERROR" in motivo and "RemoteDisconnected" in motivo and "B0FCFKQBSH" in motivo
    assert "SIN_TRADUCCION" not in motivo and "palabra1" not in motivo
    assert len(motivo) <= cadena.MOTIVO_MAX + len("error (código 1): ")


def test_motivo_sin_marcas_toma_ultimas_lineas_no_json_recortadas():
    lineas = ["arrancando", "x" * 2000, 'BARRIDO_OK {"a": "' + "b" * 3000 + '"}', "terminé sin marca"]
    motivo = cadena.resumen_salida(lineas)
    assert "terminé sin marca" in motivo and "bbbb" not in motivo
    assert len(motivo) <= cadena.MOTIVO_MAX


def test_motivo_de_traceback_muestra_la_excepcion_final():
    lineas = ["Traceback (most recent call last):", '  File "x.py", line 3, in <module>',
              "requests.exceptions.ConnectionError: HTTPConnectionPool(host='192.168.240.10', port=9222)"]
    assert "ConnectionError: HTTPConnectionPool" in cadena.resumen_salida(lineas)


def test_motivo_conserva_la_ruta_del_desglose(tmp_path):
    reloj = Reloj()
    ruta = "/state/logs/desglose-2026-11-06-0330.log"
    salida = salida_ml_con_json_pesado() + f"DEPLOY_FAIL prueba desglose={ruta}\n"
    runner = cadena.Cadena(tmp_path, lambda command, **kw: Hijo(reloj, code=1, out=salida), reloj.clock, reloj.now, reloj.sleep)
    with pytest.raises(RuntimeError) as exc:
        runner.process(["deploy"], 100, "deploy")
    assert f"desglose={ruta}" in str(exc.value)


def test_timeout_tambien_resume_la_salida(tmp_path, monkeypatch):
    reloj = Reloj()
    hijo = Hijo(reloj, seconds=1000, out=salida_ml_con_json_pesado())
    hijo.pid = 12345
    monkeypatch.setattr(cadena.os, "killpg", lambda *a: hijo.kill(), raising=False)
    runner = cadena.Cadena(tmp_path, lambda *a, **kw: hijo, reloj.clock, reloj.now, reloj.sleep)
    runner.step("amazon", 35)
    motivo = json.loads((tmp_path / "cadena-2026-11-06.json").read_text())["pasos"][0]["motivo"]
    assert motivo.startswith("timeout: ") and "RemoteDisconnected" in motivo
    assert len(motivo) <= cadena.MOTIVO_MAX + len("timeout: ")
