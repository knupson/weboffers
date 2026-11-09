"""Pruebas del estado de publicación y sus transiciones diarias."""
from copy import deepcopy
from datetime import datetime, timezone
import json

import pytest

import publicacion
from publicacion import (
    ALERTA_SALIDAS, NO_REVISAR_DIAS, REPUBLICACION_INTENTOS,
    cargar, guardar, motivo_estado, parse_desglose, transicion,
)


ASIN = "B0BZR9TMBJ"
TODAY = "2026-11-12"
CUENTAS = {"salieron": 0, "republicados": 0, "a_no_revisar": 0,
           "nuevos_publicados": 0}


def entrada(situacion, **cambios):
    return {"situacion": situacion, "desde": "2026-11-09", "hasta": None,
            "intentos": 0, "ultimoIntento": None, "motivo": "", "asin": ASIN,
            **cambios}


def test_constantes():
    assert (NO_REVISAR_DIAS, REPUBLICACION_INTENTOS, ALERTA_SALIDAS) == (7, 3, 10)


def test_vencido_no_se_renueva_en_verificacion():
    estado = {"vencido": entrada("no_revisar", hasta=TODAY)}
    nuevo, _ = transicion(estado, {"vencido": ("FILTRADO", "ml_hoy", ASIN),
                                  "sin_entrada": ("FILTRADO", "ml_hoy", ASIN)}, TODAY,
                          modo="verificacion")
    assert nuevo == estado


def test_alta_no_mueve_publicados_ni_republicacion():
    estado = {s: entrada(s) for s in ("publicado", "republicacion")}
    nuevo, _ = transicion(estado, {s: ("FILTRADO", "ml_hoy", ASIN) for s in estado},
                          TODAY, modo="alta")
    assert nuevo == estado


@pytest.mark.parametrize("salidas,congela", [(2, False), (3, True), (4, True)])
def test_falla_masiva_no_avanza_intentos(salidas, congela, capsys):
    estado = {f"p{i}": entrada("publicado") for i in range(4)}
    estado["reintento"] = entrada("republicacion", intentos=2)
    desglose = {f"p{i}": ("FILTRADO" if i < salidas else "PUBLICADO", "ml_hoy", ASIN)
               for i in range(4)}
    desglose["reintento"] = ("FILTRADO", "ml_hoy", ASIN)
    nuevo, _ = transicion(estado, desglose, TODAY, modo="verificacion")
    assert (nuevo == estado) == congela
    assert ("PUBLICACION_ALERTA_MASIVA" in capsys.readouterr().out) == congela


def test_estado_corrupto_levanta_error(tmp_path):
    (tmp_path / "publicacion.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        cargar(tmp_path)


def test_parse_desglose():
    texto = """2026-11-09 07:10:38 PRODUCTO asus-tuf-gaming-vg27aq3a asin=B0BZR9TMBJ origen=repo FILTRADO envia_ar=ok(true) envio_gratis=FALLA(2026-11-09 gratis=false) verificado=ok(true) asin=ok(B0BZR9TMBJ) imagen=ok(/products/asus-tuf-gaming-vg27aq3a.webp) ml_presente=FALLA(ausente) ml_precio=FALLA(ausente) ml_hoy=FALLA(ausente $ausente) amazon_ars=FALLA(ausente) amazon_usd=FALLA(USD ausente) amazon_rango=FALLA(USD ausente) amazon_fuente=FALLA(ausente) amazon_hoy=FALLA(ausente)
2026-11-09 07:10:38 PRODUCTO sandisk-extreme-portable-ssd-1tb asin=B08GTYFC37 origen=repo PUBLICADO envia_ar=ok(true) envio_gratis=ok(2026-11-09 gratis=true) verificado=ok(true) asin=ok(B08GTYFC37) imagen=ok(/products/sandisk-extreme-portable-ssd-1tb.webp) ml_presente=ok(presente) ml_precio=ok(498000) ml_hoy=ok(2026-11-09 $498000) amazon_ars=ok(440000) amazon_usd=ok(USD 219.99) amazon_rango=ok(USD 219.99) amazon_fuente=ok(amazon) amazon_hoy=ok(2026-11-09)
2026-11-09 07:10:39 Resumen de la corrida
"""
    assert parse_desglose(texto) == {
        "asus-tuf-gaming-vg27aq3a": ("FILTRADO", "envio_gratis", ASIN),
        "sandisk-extreme-portable-ssd-1tb": ("PUBLICADO", "", "B08GTYFC37"),
    }


@pytest.mark.parametrize("anterior", [None, entrada("no_revisar", hasta=TODAY)])
@pytest.mark.parametrize("resultado", ["PUBLICADO", "FILTRADO"])
def test_candidato_o_no_revisar_vencido(anterior, resultado):
    estado = {} if anterior is None else {"producto": anterior}
    nuevo, cuentas = transicion(estado, {"producto": (resultado, "ml_hoy", ASIN)}, TODAY, modo="alta")
    publicado = resultado == "PUBLICADO"
    assert nuevo["producto"] == entrada(
        "publicado" if publicado else "no_revisar", desde=TODAY,
        hasta=None if publicado else "2026-11-19",
        motivo="" if publicado else "ml_hoy",
    )
    assert cuentas == {**CUENTAS, ("nuevos_publicados" if publicado else "a_no_revisar"): 1}


@pytest.mark.parametrize("resultado", ["PUBLICADO", "FILTRADO"])
def test_no_revisar_vigente_no_cambia(resultado):
    estado = {"producto": entrada("no_revisar", hasta="2026-11-13")}
    nuevo, cuentas = transicion(estado, {"producto": (resultado, "ml_hoy", ASIN)}, TODAY, modo="verificacion")
    assert nuevo == estado
    assert cuentas == CUENTAS


def test_publicado_que_cumple_no_cambia():
    estado = {"producto": entrada("publicado")}
    nuevo, cuentas = transicion(estado, {"producto": ("PUBLICADO", "", ASIN)}, TODAY, modo="verificacion")
    assert nuevo == estado
    assert cuentas == CUENTAS


def test_publicado_que_falla_va_a_republicacion():
    estado = {"producto": entrada("publicado"), "sano": entrada("publicado")}
    nuevo, cuentas = transicion(estado, {"producto": ("FILTRADO", "ml_hoy", ASIN)}, TODAY, modo="verificacion")
    assert nuevo["producto"] == entrada("republicacion", desde=TODAY, motivo="ml_hoy")
    assert cuentas == {**CUENTAS, "salieron": 1}
    repetido, cuentas = transicion(nuevo, {"producto": ("FILTRADO", "ml_hoy", ASIN)}, TODAY, modo="verificacion")
    assert repetido == nuevo
    assert cuentas == CUENTAS


def test_republicacion_que_cumple_se_publica():
    estado = {"producto": entrada("republicacion", intentos=2, ultimoIntento="2026-11-11")}
    nuevo, cuentas = transicion(estado, {"producto": ("PUBLICADO", "", ASIN)}, TODAY, modo="verificacion")
    assert nuevo["producto"] == entrada("publicado", desde=TODAY)
    assert cuentas == {**CUENTAS, "republicados": 1}


def test_tercer_fallo_va_a_no_revisar_7_dias():
    estado = {"producto": entrada("republicacion", intentos=2, ultimoIntento="2026-11-11")}
    nuevo, cuentas = transicion(estado, {"producto": ("FILTRADO", "ml_hoy", ASIN)}, TODAY, modo="verificacion")
    assert nuevo["producto"] == entrada("no_revisar", desde=TODAY,
                                         hasta="2026-11-19", intentos=3,
                                         ultimoIntento=TODAY, motivo="ml_hoy")
    assert cuentas == {**CUENTAS, "a_no_revisar": 1}


def test_un_intento_por_dia():
    estado = {"producto": entrada("republicacion")}
    desglose = {"producto": ("FILTRADO", "ml_hoy", ASIN)}
    nuevo, cuentas = transicion(estado, desglose, TODAY, modo="verificacion")
    assert nuevo["producto"] == entrada("republicacion", intentos=1,
                                         ultimoIntento=TODAY, motivo="ml_hoy")
    assert cuentas == CUENTAS
    repetido, cuentas = transicion(nuevo, desglose, TODAY, modo="verificacion")
    assert repetido == nuevo
    assert cuentas == CUENTAS


def test_ausentes_no_cambian_y_no_muta_entrada():
    estado = {"ausente": entrada("publicado"), "producto": entrada("republicacion")}
    original = deepcopy(estado)
    nuevo, _ = transicion(estado, {"producto": ("FILTRADO", "ml_hoy", ASIN)}, TODAY, modo="verificacion")
    assert estado == original
    assert nuevo["ausente"] == estado["ausente"]


@pytest.mark.parametrize("cantidad,alerta", [(10, False), (11, True), (116, True)])
def test_salida_hasta_la_mitad_va_a_republicacion_y_alerta(cantidad, alerta, capsys):
    estado = {f"producto-{i}": entrada("publicado") for i in range(cantidad)}
    desglose = {slug: ("FILTRADO", "ml_hoy", ASIN) for slug in estado}
    estado.update({f"sano-{i}": entrada("publicado") for i in range(cantidad)})
    nuevo, cuentas = transicion(estado, desglose, TODAY, modo="verificacion")
    assert len(nuevo) == cantidad * 2
    assert all(nuevo[slug]["situacion"] == "republicacion" for slug in desglose)
    assert cuentas == {**CUENTAS, "salieron": cantidad}
    assert ("PUBLICACION_ALERTA_SALIDAS" in capsys.readouterr().out) == alerta


@pytest.mark.parametrize("anterior,verificacion,alta", [
    (None, "no_publicado", None),
    (entrada("publicado"), None, "verificado_en_otro_proceso"),
    (entrada("republicacion"), None, "verificado_en_otro_proceso"),
    (entrada("no_revisar", hasta="2026-11-13"), "no_revisar", "no_revisar"),
    (entrada("no_revisar", hasta=TODAY), "no_publicado", None),
    (entrada("no_revisar", hasta="2026-11-11"), "no_publicado", None),
])
def test_motivo_estado_modos(anterior, verificacion, alta):
    estado = {} if anterior is None else {"producto": anterior}
    product = {"slug": "producto", "asin": ASIN}
    assert motivo_estado(product, estado, TODAY, "verificacion") == verificacion
    assert motivo_estado(product, estado, TODAY, "alta") == alta


def test_estado_ausente(tmp_path, capsys):
    with pytest.raises(ValueError, match="PUBLICACION_SIN_ESTADO"):
        cargar(tmp_path)
    assert "PUBLICACION_SIN_ESTADO" in capsys.readouterr().out
    (tmp_path / "publicacion.json").write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="PUBLICACION_ESTADO_INVALIDO"):
        cargar(tmp_path)
    assert "PUBLICACION_ESTADO_INVALIDO" in capsys.readouterr().out


@pytest.mark.parametrize("contenido", ["[]", "null", '{"producto": {}}'])
def test_estado_invalido(tmp_path, capsys, contenido):
    (tmp_path / "publicacion.json").write_text(contenido, encoding="utf-8")
    with pytest.raises(ValueError, match="PUBLICACION_ESTADO_INVALIDO"):
        cargar(tmp_path)
    assert "PUBLICACION_ESTADO_INVALIDO" in capsys.readouterr().out


def test_guardar_y_cargar(tmp_path):
    estado = {"producto": entrada("no_revisar", hasta="2026-11-19", motivo="sin envío")}
    output = tmp_path / "salida"
    guardar(output, estado)
    assert json.loads((output / "publicacion.json").read_text(encoding="utf-8")) == estado
    assert cargar(output) == estado


def test_guardar_archivo_real_y_cargar(tmp_path):
    estado = {"producto": entrada("publicado")}
    guardar(tmp_path, estado)
    assert cargar(tmp_path) == estado


def test_log_usa_hora_art_en_host_utc(monkeypatch, capsys):
    class RelojUTC(datetime):
        @classmethod
        def now(cls, tz=None):
            instante = datetime(2026, 11, 12, 1, 30, tzinfo=timezone.utc)
            return instante.astimezone(tz) if tz else instante.replace(tzinfo=None)

    monkeypatch.setattr(publicacion, "datetime", RelojUTC)
    publicacion._log("PRUEBA")
    assert capsys.readouterr().out == "2026-11-11 22:30:00 PRUEBA\n"
