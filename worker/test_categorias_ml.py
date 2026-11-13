import pytest

from tools.categorias_ml import categoria_ml, categoria_ml_exacta


@pytest.mark.parametrize("domain,expected", [
    # Dominios leídos en fichas reales de ML (11/11).
    ("MLA-WRISTWATCHES", "Relojes"),
    ("MLA-HARD_DRIVES_AND_SSDS", "Almacenamiento"),
    ("MLA-DESKTOP_COMPUTER_POWER_SUPPLIES", "Componentes"),
    ("MLA-COMPUTER_MONITORS", "Monitores"),
    ("mla-wristwatches", "Relojes"),
    # Revisor 11/11: por subcadena estos caían en una categoría equivocada; exactos, no.
    ("MLA-BABY_MONITORS", ""),
    ("MLA-BLOOD_PRESSURE_MONITORS", ""),
    ("MLA-AIR_QUALITY_MONITORS", ""),
    ("MLA-MONITOR_ARMS", ""),
    ("MLA-STOPWATCHES", ""),
    ("MLA-WATCH_WINDERS", ""),
    ("MLA-WATCH_BANDS", ""),
    ("MLA-FOOD_PROCESSORS", ""),
    ("MLA-CAMERA_BACKPACKS", ""),
    ("MLA-NOTEBOOKS", ""),
    ("MLA-TONER_DRUMS", ""),
    (None, ""),
])
def test_categoria_ml_exacta(domain, expected):
    assert categoria_ml_exacta(domain) == expected


def test_categoria_ml_por_subcadena_sin_cambios():
    # La usan crecer_desde_ml y corregir_categorias: el movimiento de módulo (11/11) no cambia su comportamiento.
    assert categoria_ml("MLA-CELLPHONES") == "Celulares"
    assert categoria_ml("MLA-CAMERAS") == "Cámaras"
    assert categoria_ml(None) == ""


@pytest.mark.parametrize("domain,expected", [
    # 12/11: leídos en fichas reales de ML de altas-revision.json y del catálogo.
    ("MLA-HARD_DRIVES_AND_SSDS_ENCLOSURES", "Almacenamiento"),  # Synology DS223 (MLA2071000151), UGREEN DXP2800 (MLA52659246)
    ("MLA-COMBINED_TOOL_KITS", "Herramientas"),                 # Flexcut SK107 (MLA62738921)
    ("MLA-TOY_BUILDING_SETS", "Juguetes"),                      # LEGO 10327 (MLA30924256); 28 publicados en Juguetes
    # Sin categoría existente en el sitio: siguen en revisión.
    ("MLA-SNEAKERS", ""), ("MLA-BACKPACKS", "Mochilas"), ("MLA-LAPTOP_BRIEFCASES", "Mochilas"),
    ("MLA-BINOCULARS", ""), ("MLA-KNITTING_NEEDLES", ""),
    # 12/11 (Alejandro): Hogar y la categoría nueva Anteojos.
    ("MLA-DIGITAL_WEATHER_STATIONS", "Hogar"), ("MLA-GAS_DETECTORS", "Hogar"), ("MLA-SUNGLASSES", "Anteojos"),
    ("MLA-SURVEILLANCE_CAMERAS", "Cámaras"),  # Ubiquiti G5 (MLA47225060); los Ring de Hogar son del catálogo manual
    # 13/11 (Alejandro): llaves de impacto en Herramientas. Leído en la ficha de la Milwaukee 2962-20.
    ("MLA-ELECTRIC_SCREWDRIVERS_AND_IMPACT_WRENCHES", "Herramientas"),  # MLA44953790
])
def test_dominios_exactos_del_12_11(domain, expected):
    assert categoria_ml_exacta(domain) == expected
