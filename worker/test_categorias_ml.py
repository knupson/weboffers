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
