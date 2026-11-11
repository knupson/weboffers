import pytest

from tools.identifier_gate import strong_identifier_match


def lego(model_name, ml_model, brand="LEGO", ml_brand="Lego", model_number="6590610"):
    return {"brand": brand, "mlBrand": ml_brand,
            "amazonIds": {"model_number": model_number, "upc": "673419425360", "model_name": model_name},
            "mlIds": {"MODEL": ml_model}, "amazonTitle": "LEGO 2024 set con 1500 piezas 43019"}


# Los 5 primeros: filas reales de altas-revision.json (11/11) frenadas por sin_identificador_fuerte.
# Los 2 últimos: model_name/MODEL reales de LEGO en dudoso_matcheo (75354 y 76473), por la barra y el texto extra.
@pytest.mark.parametrize("model_name,ml_model", [
    ("Soccer Ball 43019", "43019"),
    ("Icons 11384", "11384"),
    ("Notre-Dame de Paris 21061", "21061"),
    ("Back to the Future Time Machine 10300", "10300"),
    ("Technic 42231", "42231"),
    ("tbd Star Wars TM 75354 75354", "7/53/54"),  # mismo set repetido; la barra de ML no separa
    ("Hogwarts Castle: East Wing 76473", "76473 Harry Potter"),
])
def test_lego_set_en_model_name_coincide_con_model_de_ml(model_name, ml_model):
    assert strong_identifier_match(lego(model_name, ml_model))


@pytest.mark.parametrize("row", [
    lego("Soccer Ball 43019", "43019", ml_brand="Otra"),                  # marca de ML distinta
    lego("Soccer Ball 43019", "43019", brand="Generic"),                  # marca de Amazon distinta
    lego("Soccer Ball 43019", "43020"),                                   # otro set
    lego("Pack 43019 y 43020", "43019"),                                  # dos sets en Amazon
    lego("Soccer Ball", "43019"),                                         # el set sólo está en el título
    lego("Ninjago 71860", "6585680", model_number="6585680"),             # 7 dígitos: no es número de set
    lego("Set 2024", "2025"),                                             # años distintos no coinciden
    lego("Star Wars 2025", "2025"),                                       # el mismo año no es un set (revisor 11/11)
    lego("", ""),
])
def test_lego_no_aprueba_sin_set_unico_en_los_dos_lados(row):
    assert not strong_identifier_match(row)


def test_lego_ignora_el_ano_junto_al_set():
    assert strong_identifier_match(lego("LEGO Icons 2024 Edition 10300", "10300"))


def test_lego_con_codigos_de_barras_distintos_no_aprueba():
    row = lego("Soccer Ball 43019", "43019")
    row["mlIds"]["GTIN"] = "5702017999999"
    assert not strong_identifier_match(row)
    row["mlIds"]["GTIN"] = "0673419425360"  # el mismo UPC de Amazon con cero adelante: coincide
    assert strong_identifier_match(row)


def test_otras_marcas_siguen_exigiendo_letras_y_numeros():
    row = {"brand": "Acme", "mlBrand": "Acme", "amazonIds": {"model_name": "43019", "model_number": "43019"},
           "mlIds": {"MODEL": "43019"}}
    assert not strong_identifier_match(row)
