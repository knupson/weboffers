"""08/11: las búsquedas en ML iban con el título de Amazon en inglés. Se traducen con el glosario."""
from barrido import ml_matching
from barrido.ml_matching import build_queries, translate_query

GLOSARIO = {"green": "verde", "bag": "cartera", "for": "-", "with": "-", "titanium": "titanio",
            "cutting": "picar", "board": "tabla", "knife": "cuchillo", "laptop": "notebook",
            "backpack": "mochila", "gaming": "=", "wireless": "inalambrico", "mouse": "mouse"}


def setup_function():
    ml_matching._glossary_cache = dict(GLOSARIO)


def test_traduce_palabra_por_palabra_y_saca_conectores():
    assert translate_query("Green Bag") == "verde cartera"
    assert translate_query("Titanium Cutting Board with Knife") == "titanio picar tabla cuchillo"


def test_conserva_marca_modelo_codigos_y_desconocidas():
    # Marca, códigos con dígitos y palabras fuera del glosario (nombres) quedan como están.
    assert translate_query("Timbuk2 Authority Laptop Backpack 2.0") == "Timbuk2 Authority notebook mochila 2.0"
    assert translate_query("Logitech G PRO X2 SUPERSTRIKE Wireless Gaming Mouse") == \
        "Logitech G PRO X2 SUPERSTRIKE inalambrico Gaming mouse"


def test_ninguna_consulta_lleva_palabras_traducibles_en_ingles():
    for titulo in ("Osprey Tropos Laptop Backpack, Black OS", "Plateful Titanium Cutting Board with Knife"):
        for consulta in build_queries(titulo):
            assert not {w.lower() for w in consulta.split()} & {"laptop", "backpack", "with", "titanium", "cutting", "board", "knife"}


def test_registra_palabras_sin_traduccion():
    ml_matching._untranslated.clear()
    translate_query("Plateful Titanium Pans")
    assert ml_matching._untranslated == {"plateful", "pans"}
