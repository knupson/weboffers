import datetime
import json

from tools import vigia_franquicia as v

ART = v.rf.ART
HOY = datetime.datetime(2026, 11, 5, 10, 0, tzinfo=ART)
PASOS = [f"verificacion:{p}" for p in ("offers", "chrome", "amazon", "ml", "fichas", "deploy", "estado")] + [
    f"alta:{p}" for p in ("barrido_amazon", "barrido_ml", "barrido_altas", "dudosos", "chrome", "altas")]
TODOS = "\n".join(v.CONTENEDORES)


def fake_sh(ps=TODOS, deployer=""):
    def sh(*cmd, timeout=30):
        if cmd[:2] == ("docker", "ps"):
            return 0, ps
        return 0, deployer
    return sh


def leer_ok(contenedor, ruta):
    if "ar-chrome" in ruta:
        return {"items": {"B1": {"ships": True, "free": True}}}
    return {"date": "2026-11-05"}


def bajar_ok(url):
    return json.dumps({"preciosDe": "2026-11-05", "publicados": 100})


def log(tmp_path, *lineas):
    (tmp_path / "worker-2026-11-05.log").write_text("\n".join(lineas) + "\n", encoding="utf-8")


def correr(tmp_path, **kw):
    (tmp_path / "cadena-2026-11-05.json").write_text(json.dumps({
        "fecha": "2026-11-05", "fin": "2026-11-05T05:00:00-03:00", "pasos": [{"paso": p, "estado": "ok"} for p in PASOS]
    }), encoding="utf-8")
    args = dict(cadena_dir=str(tmp_path), internet=lambda: True, sh=fake_sh(), leer=leer_ok, bajar=bajar_ok, logs_dir=str(tmp_path))
    args.update(kw)
    return v.chequeos(HOY, **args)


def test_todo_bien_no_avisa(tmp_path):
    log(tmp_path, "09:16:05 LATIDO worker")
    assert correr(tmp_path) == {}


def test_vigia_detecta_publicacion_alerta(tmp_path):
    log(tmp_path, "2026-11-05 09:16:05 PUBLICACION_ALERTA salieron=11 motivos=envio:11")
    problemas = correr(tmp_path)
    assert any(k.startswith("log:") and "PUBLICACION_ALERTA salieron=11" in texto
               for k, texto in problemas.items())


def test_sin_internet_es_lo_unico_que_se_reporta(tmp_path):
    assert list(correr(tmp_path, internet=lambda: False)) == ["internet"]


def test_contenedor_caido_y_fallas_del_log(tmp_path):
    log(tmp_path, "09:16:05 Falló la actualización de precios de Mercado Libre (ConnectionError).",
        *[f"09:2{i}:00 Mercado Libre: no se pudo consultar p{i} (HTTPError); se omite." for i in range(5)])
    p = correr(tmp_path, sh=fake_sh(ps="franquicia400-weboffers-worker-1"))
    assert any(k.startswith("contenedores:") for k in p)
    assert any(k.startswith("log:Falló") for k in p)
    assert "ml-fallas" in p


def test_latido_con_fecha_en_el_log(tmp_path):
    # Formato real desde el 05/11: «AAAA-MM-DD HH:MM:SS texto».
    log(tmp_path, "2026-11-05 09:16:05 LATIDO worker")
    assert "latido" not in correr(tmp_path)


def test_sin_latido_con_fecha_en_el_log(tmp_path):
    log(tmp_path, "2026-11-05 07:01:00 LATIDO worker")
    assert correr(tmp_path)["latido"] == "el worker no da señales desde las 07:01"


def test_worker_sin_latido(tmp_path):
    log(tmp_path, "07:01:00 Publicación completa: modo=offline, productos=241, cambios=True.")
    assert "latido" in correr(tmp_path)


def test_precios_viejos_y_sitio_bajo_minimo(tmp_path):
    log(tmp_path, "09:16:05 ok")
    p = correr(tmp_path, leer=lambda c, r: {"date": "2026-11-04"},
               bajar=lambda u: json.dumps({"preciosDe": "2026-11-05", "publicados": 82}))
    assert {"fresco:ml-prices.json", "fresco:amazon-prices.json"} <= set(p)
    # El mínimo lo avisa el control de las 7:30; el vigía no lo repite (06/11: llegaban dos WhatsApp).
    assert "sitio-minimo" not in p


def test_deploy_fail_en_log_del_deployer(tmp_path):
    log(tmp_path, "09:16:05 ok")
    p = correr(tmp_path, sh=fake_sh(deployer="2026-11-05T10:00:26.716Z DEPLOY_FAIL build (exit 1)"))
    assert any(k.startswith("deploy:") for k in p)


def test_caida_brusca_avisa_desde_log_del_deployer(tmp_path):
    log(tmp_path, "2026-11-05 09:16:05 LATIDO worker")
    p = correr(tmp_path, sh=fake_sh(deployer="2026-11-05 09:00:00 DEPLOY_ALERT caída brusca de 116 a 20"))
    assert any(k.startswith("deploy:") and "caída brusca" in texto for k, texto in p.items())


def test_avisa_una_vez_y_reintenta_si_no_sale(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "ESTADO", str(tmp_path / "estado.json"))
    monkeypatch.setattr(v, "chequeos", lambda ahora: {"latido": "el worker no da señales"})
    enviados = []

    def falla(texto, etiqueta):
        raise SystemExit(1)

    v.main(HOY, enviar=falla)
    assert json.load(open(tmp_path / "estado.json", encoding="utf-8"))["pendientes"] == {"latido": "el worker no da señales"}
    v.main(HOY, enviar=lambda t, e: enviados.append(t))
    v.main(HOY, enviar=lambda t, e: enviados.append(t))
    assert len(enviados) == 1  # se reintentó y después no se repite


def test_avisa_cuando_vuelve_internet(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "ESTADO", str(tmp_path / "estado.json"))
    enviados = []
    monkeypatch.setattr(v, "chequeos", lambda ahora: {"internet": "sin internet"})
    v.main(HOY, enviar=lambda t, e: enviados.append(t))
    assert enviados == []
    monkeypatch.setattr(v, "chequeos", lambda ahora: {})
    v.main(HOY + datetime.timedelta(minutes=15), enviar=lambda t, e: enviados.append(t))
    assert len(enviados) == 1 and "sin internet desde" in enviados[0]


def test_mas_de_seis_problemas_se_mandan_en_tandas(tmp_path, monkeypatch):
    monkeypatch.setattr(v, "ESTADO", str(tmp_path / "estado.json"))
    monkeypatch.setattr(v, "chequeos", lambda ahora: {f"p{i}": f"problema {i}" for i in range(8)})
    enviados = []
    v.main(HOY, enviar=lambda t, e: enviados.append(t))
    v.main(HOY, enviar=lambda t, e: enviados.append(t))
    v.main(HOY, enviar=lambda t, e: enviados.append(t))
    assert len(enviados) == 2 and "problema 7" in enviados[1]


def test_un_chequeo_que_explota_se_reporta(tmp_path):
    def roto(contenedor, ruta):
        raise ValueError("json roto")
    log(tmp_path, "09:16:05 ok")
    p = correr(tmp_path, leer=roto, bajar=lambda u: (_ for _ in ()).throw(RuntimeError("x")))
    assert "fresco:ml-prices.json" in p


def test_avisa_si_no_corrio_el_relevamiento_con_chrome(tmp_path):
    log(tmp_path, "09:16:05 ok")
    p = correr(tmp_path, leer=lambda c, r: None if "ar-chrome" in r else {"date": "2026-11-05"})
    assert "envio-chrome" in p


def test_cadena_faltante_fallida_e_interrumpida(tmp_path):
    hoy = "2026-11-05"
    assert "cadena" in v.chequear_cadena(hoy, tmp_path)
    p = tmp_path / f"cadena-{hoy}.json"
    p.write_text(json.dumps({"fecha": hoy, "fin": hoy + "T05:00:00-03:00", "pasos": [
        *[{"paso": name, "estado": "ok"} for name in PASOS if name != "verificacion:deploy"],
        {"paso": "verificacion:amazon", "estado": "fail", "motivo": "timeout"},
        {"paso": "verificacion:ml", "estado": "en_curso"}]}), encoding="utf-8")
    problemas = v.chequear_cadena(hoy, tmp_path)
    assert set(problemas) == {"cadena:verificacion:amazon", "cadena:verificacion:ml", "cadena:verificacion:deploy"}
    assert problemas["cadena:verificacion:amazon"] == "la cadena de madrugada falló en verificacion:amazon (timeout)"
    assert "cadena" not in v.chequeos(HOY.replace(hour=5, minute=29), internet=lambda: True,
        sh=fake_sh(), leer=leer_ok, logs_dir=str(tmp_path), cadena_dir=str(tmp_path / "ausente"))
    assert "cadena" in v.chequeos(HOY.replace(hour=5, minute=30), internet=lambda: True,
        sh=fake_sh(), leer=leer_ok, logs_dir=str(tmp_path), cadena_dir=str(tmp_path / "ausente"))


def test_umami_ip_avisa_si_cambio_la_ip_de_casa():
    def sh_env(valor):
        def sh(*cmd, timeout=30):
            return 0, f"PATH=/x\nIGNORE_IP={valor}\n"
        return sh
    assert v.chequear_umami_ip(sh_env("1.2.3.4"), ip=lambda: "1.2.3.4") == {}
    assert v.chequear_umami_ip(sh_env('"1.2.3.4"'), ip=lambda: "1.2.3.4") == {}
    assert v.chequear_umami_ip(sh_env("9.9.9.9,1.2.3.4"), ip=lambda: "1.2.3.4") == {}
    assert "umami-ip" in v.chequear_umami_ip(sh_env("9.9.9.9"), ip=lambda: "1.2.3.4")
    # Sin la variable, sin contenedor o sin poder averiguar la IP: no se avisa (no hay dato para comparar).
    assert v.chequear_umami_ip(lambda *c, timeout=30: (0, "PATH=/x\n"), ip=lambda: "1.2.3.4") == {}
    assert v.chequear_umami_ip(lambda *c, timeout=30: (1, ""), ip=lambda: "1.2.3.4") == {}
    def falla():
        raise OSError("sin red")
    assert v.chequear_umami_ip(sh_env("9.9.9.9"), ip=falla) == {}


def test_latido_ignora_otra_actividad_y_mantiene_75_minutos(tmp_path):
    log(tmp_path, "2026-11-05 08:45:00 LATIDO worker", "2026-11-05 09:59:00 Telegram ok")
    assert "latido" not in correr(tmp_path)
    log(tmp_path, "2026-11-05 08:44:59 LATIDO worker", "2026-11-05 09:59:00 Telegram ok")
    assert "latido" in correr(tmp_path)
    log(tmp_path, "2026-11-05 09:59:00 Telegram ok")
    assert "latido" in correr(tmp_path)


def test_alta_ok_no_oculta_falla_verificacion_y_controla_todos_los_pasos(tmp_path):
    for name in PASOS + [f"alta:{p}" for p in ("amazon", "ml", "deploy", "estado")]:
        steps = [{"paso": p, "estado": "fail" if p == name else "ok"} for p in
                 PASOS + [f"alta:{p}" for p in ("amazon", "ml", "deploy", "estado")]]
        (tmp_path / "cadena-2026-11-05.json").write_text(json.dumps({"fecha": "2026-11-05", "fin": "2026-11-05T05:00:00-03:00", "pasos": steps}))
        assert set(v.chequear_cadena("2026-11-05", tmp_path)) == {f"cadena:{name}"}


def test_motivo_de_cadena_largo_se_recorta_en_el_aviso(tmp_path):
    # 12/11: el motivo de alta:barrido_ml medía 11.222 caracteres y salió entero por WhatsApp.
    motivo = "error (código 1): BARRIDO_ML_ERROR RemoteDisconnected | " + "x" * 11_000
    steps = [{"paso": p, "estado": "ok"} for p in PASOS + [f"alta:{p}" for p in ("amazon", "ml", "deploy", "estado")]]
    steps.append({"paso": "alta:barrido_ml_extra", "estado": "fail", "motivo": motivo})
    (tmp_path / "cadena-2026-11-05.json").write_text(json.dumps({"fecha": "2026-11-05", "fin": "2026-11-05T05:00:00-03:00", "pasos": steps}))
    texto = v.chequear_cadena("2026-11-05", tmp_path)["cadena:alta:barrido_ml_extra"]
    assert "RemoteDisconnected" in texto
    assert len(texto) <= v.MOTIVO_MAX + len("la cadena de madrugada falló en alta:barrido_ml_extra ()")
