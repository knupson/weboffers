from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
import ml_fichas

NOW = datetime(2026, 11, 7, 2, tzinfo=timezone.utc)  # Todavía es 06/11 en ART.
PRODUCT = {"slug": "sandisk", "name": "SanDisk Extreme 1 TB", "ml": {"catalogId": "MLA54977132"}}
BODY = {"name": "Disco Ssd Externo 1tb Sandisk Extreme", "attributes": [
    {"id": "CAPACITY", "name": "Capacidad", "value_name": "1 TB"},
    {"id": "MODEL", "name": "Modelo", "value_name": "SDSSDE61-1T00"},
    {"id": "GTIN", "name": "GTIN", "value_name": "123"},
    {"id": "PACKAGE_WIDTH", "name": "Ancho del paquete", "value_name": "10 cm"},
], "main_features": [{"text": "Unidad externa"}]}


@pytest.fixture
def api(monkeypatch):
    get = Mock(return_value=BODY)
    pause = Mock()
    monkeypatch.setattr(ml_fichas.ml_prices, "is_configured", lambda: True)
    monkeypatch.setattr(ml_fichas.ml_prices, "get_json", get)
    monkeypatch.setattr(ml_fichas.ml_prices, "pause", pause)
    return get, pause


def test_fetch_source_date_and_noise(tmp_path, api):
    path = tmp_path / "ml-fichas.json"
    ml_fichas.refresh([PRODUCT], path, NOW)
    item = json.loads(path.read_text())["items"]["MLA54977132"]
    assert item["fetched"] == "2026-11-06"
    assert item["attributes"] == [["Capacidad", "1 TB"], ["Modelo", "SDSSDE61-1T00"]]
    assert item["mainFeatures"] == ["Unidad externa"]
    api[0].assert_called_once_with("/products/MLA54977132")
    api[1].assert_called_once()


@pytest.mark.parametrize("age, calls", [(0, 0), (7, 0), (8, 1), (-1, 1)])
def test_cache_age(tmp_path, api, age, calls):
    from datetime import timedelta
    path = tmp_path / "ml-fichas.json"
    ml_fichas.refresh([PRODUCT], path, NOW)
    data = json.loads(path.read_text())
    data["items"]["MLA54977132"]["fetched"] = (NOW.astimezone(ml_fichas.ml_prices.ART).date() - timedelta(days=age)).isoformat()
    data["items"]["unrelated"] = {"name": "Conservada"}
    path.write_text(json.dumps(data))
    api[0].reset_mock()
    ml_fichas.refresh([PRODUCT], path, NOW)
    assert api[0].call_count == calls
    assert json.loads(path.read_text())["items"]["unrelated"]["name"] == "Conservada"


def test_exact_sandisk_conflict_and_cached_defense(tmp_path, api, capsys):
    body = {**BODY, "attributes": [
        {"id": "CAPACITY", "name": "Capacidad", "value_name": "4 TB"},
        {"id": "MODEL", "name": "Modelo", "value_name": "SDSSDE61-4T00"},
    ]}
    api[0].return_value = body
    path = tmp_path / "ml-fichas.json"
    ml_fichas.refresh([PRODUCT], path, NOW)
    assert json.loads(path.read_text())["items"] == {}
    assert "2026-11-06 23:00:00 FICHA_DESCARTADA sandisk CAPACITY" in capsys.readouterr().out
    path.write_text(json.dumps({"items": {"MLA54977132": {
        "fetched": "2026-11-06", "name": body["name"], "rawAttributes": body["attributes"],
        "attributes": [["Capacidad", "4 TB"]], "mainFeatures": ["4 TB"],
    }}}))
    api[0].reset_mock()
    ml_fichas.refresh([PRODUCT], path, NOW)
    api[0].assert_not_called()
    assert json.loads(path.read_text())["items"] == {}


def test_failure_continues_and_pauses(tmp_path, api):
    api[0].side_effect = [ValueError("respuesta inválida"), BODY]
    path = tmp_path / "ml-fichas.json"
    ml_fichas.refresh([PRODUCT, {**PRODUCT, "slug": "otro", "ml": {"catalogId": "MLA2"}}], path, NOW)
    assert list(json.loads(path.read_text())["items"]) == ["MLA2"]
    assert api[1].call_count == 2


def test_cached_copy_survives_failed_refetch(tmp_path, api):
    path = tmp_path / "ml-fichas.json"
    ml_fichas.refresh([PRODUCT], path, NOW)
    data = json.loads(path.read_text())
    data["items"]["MLA54977132"]["fetched"] = "2026-10-01"
    path.write_text(json.dumps(data))
    api[0].side_effect = ValueError("falló consulta")
    ml_fichas.refresh([PRODUCT], path, NOW)
    assert json.loads(path.read_text())["items"] == data["items"]


def test_conflict_casos_reales_del_07_11():
    def hoja(name, *attrs):
        return {"name": name, "rawAttributes": [{"id": i, "value_name": v} for i, v in attrs]}
    # Errores reales del catálogo de ML: se descartan.
    assert ml_fichas.conflict("WD Green SSD SATA 1TB", hoja("WesternDigital WD Green SSD 1 TB", ("CAPACITY", "2 TB")))
    # Falsos positivos vistos con datos reales: no se descartan.
    assert not ml_fichas.conflict("Xiaomi Redmi Pad 2 256GB", hoja("Xiaomi Redmi Pad 2 256 GB",
        ("INTERNAL_MEMORY", "256 GB"), ("MAX_MEMORY_SUPPORTED_CAPACITY", "2 TB")))
    assert not ml_fichas.conflict("ASUS Dual RTX 3050 6GB", hoja("Placa Asus Dual Rtx 3050 6gb",
        ("MEMORY_DATA_SPEED", "3 GB/s")))
    assert not ml_fichas.conflict("Samsung A37 5G 256GB", hoja("Samsung Galaxy A37 5G 256 GB",
        ("INTERNAL_MEMORY", "256 GB"), ("RAM", "8 GB")))
    # Con dos cantidades en el nombre, la RAM sí se contrasta.
    assert ml_fichas.conflict("Xiaomi Pad 2 128GB 4GB", hoja("Xiaomi Pad 2 128 GB 4 GB", ("RAM", "8 GB")))


def test_nombres_en_conflicto_descartan_aunque_el_atributo_coincida_con_uno():
    # Hallazgo del revisor (07/11): con la unión de nombres, 2TB contra 1TB pasaba.
    hoja = {"name": "SSD Samsung 980 1TB", "rawAttributes": [{"id": "INTERNAL_MEMORY", "value_name": "1 TB"}]}
    assert ml_fichas.conflict("SSD Samsung 980 2TB", hoja)
    assert not ml_fichas.conflict("SSD Samsung 980 1TB", hoja)
