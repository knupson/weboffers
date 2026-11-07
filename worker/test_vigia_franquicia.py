import datetime
import json

from tools import vigia_franquicia as v

ART = v.rf.ART
HOY = datetime.datetime(2026, 11, 5, 10, 0, tzinfo=ART)
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
        "fecha": "2026-11-05", "pasos": [{"paso": p, "estado": "ok"} for p in ("chrome", "amazon", "ml", "deploy")]
    }), encoding="utf-8")
    args = dict(cadena_dir=str(tmp_path), internet=lambda: True, sh=fake_sh(), leer=leer_ok, bajar=bajar_ok, logs_dir=str(tmp_path))
    args.update(kw)
    return v.chequeos(HOY, **args)


def test_todo_bien_no_avisa(tmp_path):
    log(tmp_path, "09:16:05 Publicación completa: modo=offline, productos=241, cambios=True.")
    assert correr(tmp_path) == {}


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
    log(tmp_path, "2026-11-05 09:16:05 Publicación completa: modo=offline, productos=241, cambios=True.")
    assert "latido" not in correr(tmp_path)


def test_sin_latido_con_fecha_en_el_log(tmp_path):
    log(tmp_path, "2026-11-05 07:01:00 Publicación completa: modo=offline, productos=241, cambios=True.")
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
    p.write_text(json.dumps({"fecha": hoy, "pasos": [
        {"paso": "chrome", "estado": "ok"},
        {"paso": "amazon", "estado": "fail", "motivo": "timeout"},
        {"paso": "ml", "estado": "en_curso"}]}), encoding="utf-8")
    problemas = v.chequear_cadena(hoy, tmp_path)
    assert set(problemas) == {"cadena:amazon", "cadena:ml", "cadena:deploy"}
    assert problemas["cadena:amazon"] == "la cadena de madrugada falló en amazon (timeout)"
    assert "cadena" not in v.chequeos(HOY.replace(hour=5, minute=29), internet=lambda: True,
        sh=fake_sh(), leer=leer_ok, logs_dir=str(tmp_path), cadena_dir=str(tmp_path / "ausente"))
    assert "cadena" in v.chequeos(HOY.replace(hour=5, minute=30), internet=lambda: True,
        sh=fake_sh(), leer=leer_ok, logs_dir=str(tmp_path), cadena_dir=str(tmp_path / "ausente"))
