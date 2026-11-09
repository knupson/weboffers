"""Regresiones de F2, F5 y F6 con archivos reales y red simulada."""
from datetime import datetime
import json

import pytest

import amazon_prices
import ml_prices
import publicacion
from test_requisitos import producto
from tools import confirmar_altas, dudosos_nvidia, refresh_ahora, vigia_franquicia


TODAY = "2026-11-09"
NOW = datetime.fromisoformat(TODAY + "T04:00:00-03:00")


def save(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("con_precios_hoy", [True, False])
def test_alta_fusiona_precios_del_dia(tmp_path, monkeypatch, con_precios_hoy):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    publicacion.guardar(tmp_path, {"publicado": publicacion._entrada("publicado", TODAY, "", "PUBLICADO")})
    path = tmp_path / "amazon-prices.json"
    previo = {"date": TODAY if con_precios_hoy else "2026-11-08", "items": {
        "publicado": {"amount": 150, "checked": TODAY if con_precios_hoy else "2026-11-08"}},
        "missingReasons": {"fallido": "timeout"}, "run": {"faltan": {"total": 1, "motivos": {"timeout": 1}}}}
    save(path, previo)
    monkeypatch.setattr(amazon_prices, "scraper_url", lambda: "http://prueba")
    monkeypatch.setattr(amazon_prices, "refresh_ar_shipping", lambda *a, **k: {})
    monkeypatch.setattr(amazon_prices, "prices_with_chrome", lambda *a: ({"nuevo": {
        "amount": 200, "currency": "USD", "checked": TODAY}}, 1, 0))
    assert amazon_prices.maybe_refresh([producto("publicado"), producto("nuevo")], path, NOW, force=True)
    data = json.loads(path.read_text())
    assert data["date"] == TODAY
    assert set(data["items"]) == ({"publicado", "nuevo"} if con_precios_hoy else {"nuevo"})
    if con_precios_hoy:
        assert data["missingReasons"] == {"fallido": "timeout"}
        assert data["run"]["faltan"] == {"total": 1, "motivos": {"timeout": 1}}
    else:
        assert "fallido" not in data["missingReasons"]


def test_alta_ml_conserva_diagnosticos_de_verificacion(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    publicacion.guardar(tmp_path, {s: publicacion._entrada("publicado", TODAY, "", s.upper())
                                 for s in ("publicado", "fallido", "conflicto", "saltado")})
    path, amazon = tmp_path / "ml-prices.json", tmp_path / "amazon-prices.json"
    save(amazon, {"date": TODAY, "items": {s: {"amount": 200, "currency": "USD", "checked": TODAY}
                                            for s in ("publicado", "fallido", "conflicto", "saltado", "nuevo")}})
    save(path, {"date": TODAY, "slot": TODAY + "T04", "items": {"publicado": {"price": 300000, "checked": TODAY}},
                "failed": ["fallido"], "variantConflict": ["conflicto"], "absent": ["ausente"],
                "skipped": {"saltado": "sin_precio_amazon_hoy"}, "attempts": 1, "attemptHour": 3})
    consultados = []
    monkeypatch.setattr(ml_prices, "is_configured", lambda: True)
    def fetch(catalog_id):
        consultados.append(catalog_id)
        return [{"price": 250000, "id": "MLA123", "condition": "new"}]
    monkeypatch.setattr(ml_prices, "fetch_items", fetch)
    monkeypatch.setattr(ml_prices, "pause", lambda: None)
    catalog = [producto(s, ml={"catalogId": "MLA" + s.upper()})
               for s in ("publicado", "fallido", "conflicto", "saltado", "nuevo")]
    assert ml_prices.maybe_refresh(catalog, path, amazon, 1000, NOW, force=True)
    data = json.loads(path.read_text())
    assert set(data["items"]) == {"publicado", "nuevo"}
    assert data["failed"] == ["fallido"]
    assert data["variantConflict"] == ["conflicto"]
    assert data["absent"] == ["ausente"]
    assert data["skipped"] == {"saltado": "sin_precio_amazon_hoy"}
    assert consultados == ["MLANUEVO"]


@pytest.mark.parametrize("evidencia", [None, {"ships": None}, {"ships": True, "free": False},
                                     {"ships": True, "free": True, "precio": "$200"}])
def test_vencido_sin_chrome_hoy_vuelve_a_no_revisar(tmp_path, evidencia):
    catalog = tmp_path / "catalog.json"
    save(catalog, [producto("vencido", shipsToAr={"freeShipping": True, "checked": "2026-11-02"})])
    publicacion.guardar(tmp_path, {"vencido": publicacion._entrada("no_revisar", "2026-11-02", "ml_hoy", "VENCIDO")})
    if evidencia is not None:
        save(tmp_path / f"ar-chrome-{TODAY}.json", {"generado": TODAY + "T03:30:00-03:00", "items": {"VENCIDO": evidencia}})
    confirmar_altas.confirm(catalog, tmp_path, TODAY)
    item = publicacion.cargar(tmp_path)["vencido"]
    assert item["hasta"] == (TODAY if evidencia and evidencia.get("free") is True else "2026-11-16")


def test_vencidos_cuentan_es(tmp_path, capsys):
    catalog = tmp_path / "catalog.json"
    save(catalog, [producto("espana", store="ES")])
    publicacion.guardar(tmp_path, {"espana": publicacion._entrada("no_revisar", "2026-11-02", "ml_hoy", "ESPANA")})
    save(tmp_path / f"ar-chrome-{TODAY}.json", {"generado": TODAY + "T03:30:00-03:00", "items": {
        "ESPANA": {"ships": True, "free": True, "precio": "$200"}}})
    confirmar_altas.confirm(catalog, tmp_path, TODAY)
    assert "vencidos=1" in capsys.readouterr().out


def test_vencido_sin_chrome_se_excluye_aunque_haya_pendientes(tmp_path):
    catalog = tmp_path / "catalog.json"
    save(catalog, [producto("vencido", shipsToAr={"freeShipping": True, "checked": "2026-11-02"})])
    save(tmp_path / "altas-pendientes.json", [producto("pendiente")])
    publicacion.guardar(tmp_path, {"vencido": publicacion._entrada("no_revisar", "2026-11-02", "ml_hoy", "VENCIDO")})
    with pytest.raises(ValueError, match="No hay relevamiento"):
        confirmar_altas.confirm(catalog, tmp_path, TODAY)
    assert publicacion.cargar(tmp_path)["vencido"]["hasta"] == "2026-11-16"


def test_vencido_en_outofrange_se_reconsulta(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    path = tmp_path / "amazon-prices.json"
    publicacion.guardar(tmp_path, {"vencido": publicacion._entrada("no_revisar", "2026-11-02", "rango", "VENCIDO")})
    save(path, {"date": TODAY, "items": {}, "outOfRange": {"vencido": {"amount": 90}}})
    save(tmp_path / f"amazon-run-{TODAY}.json", {"passes": [{"fallas": [{"slug": "vencido", "motivo": "rango"}]}]})
    monkeypatch.setattr(amazon_prices, "prices_with_chrome", lambda *a: ({"vencido": {
        "amount": 200, "currency": "USD", "checked": TODAY}}, 1, 0))
    assert amazon_prices.price_new_products([producto("vencido")], path, NOW, "http://prueba")
    data = json.loads(path.read_text())
    assert data["items"]["vencido"]["amount"] == 200
    assert "vencido" not in data.get("outOfRange", {})


def test_dudosos_escribe_en_log_diario(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    def run(*args):
        dudosos_nvidia.log("DUDOSO_PARA_ALEJANDRO par=SINTETICO:MLA1")
        return 0
    monkeypatch.setattr(dudosos_nvidia, "run", run)
    with monkeypatch.context() as streams:
        streams.setattr(dudosos_nvidia.sys, "stdout", dudosos_nvidia.sys.stdout)
        streams.setattr(dudosos_nvidia.sys, "stderr", dudosos_nvidia.sys.stderr)
        assert dudosos_nvidia.main() == 0
    log = next((tmp_path / "logs").glob("worker-*.log")).read_text(encoding="utf-8")
    assert "DUDOSO_PARA_ALEJANDRO par=SINTETICO:MLA1" in log


def test_fichas_refresca_archivo_en_paso_diario(tmp_path, monkeypatch):
    worker = refresh_ahora.worker
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    publicacion.guardar(tmp_path, {})
    monkeypatch.setattr(worker, "load_catalog", lambda *a: [])
    monkeypatch.setattr(worker.rates, "get_rates", lambda: {})
    with monkeypatch.context() as streams:
        streams.setattr(refresh_ahora.sys, "stdout", refresh_ahora.sys.stdout)
        streams.setattr(refresh_ahora.sys, "stderr", refresh_ahora.sys.stderr)
        assert refresh_ahora.main("fichas") == 0
    assert json.loads((tmp_path / "ml-fichas.json").read_text())["items"] == {}


def test_fichas_solo_consulta_publicados_y_republicacion(tmp_path, monkeypatch):
    worker = refresh_ahora.worker
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    publicacion.guardar(tmp_path, {s: publicacion._entrada(s, TODAY, "", s.upper())
                                 for s in ("publicado", "republicacion", "no_revisar")})
    catalog = [producto(s, name=s, ml={"catalogId": s.upper()})
               for s in ("publicado", "republicacion", "no_revisar", "nuevo")]
    monkeypatch.setattr(worker, "load_catalog", lambda *a: catalog)
    monkeypatch.setattr(ml_prices, "is_configured", lambda: True)
    monkeypatch.setattr(ml_prices, "pause", lambda: None)
    monkeypatch.setattr(ml_prices, "get_json", lambda ruta: {"name": ruta.rsplit("/", 1)[-1], "attributes": []})
    with monkeypatch.context() as streams:
        streams.setattr(refresh_ahora.sys, "stdout", refresh_ahora.sys.stdout)
        streams.setattr(refresh_ahora.sys, "stderr", refresh_ahora.sys.stderr)
        assert refresh_ahora.main("fichas") == 0
    data = json.loads((tmp_path / "ml-fichas.json").read_text())
    assert set(data["items"]) == {"PUBLICADO", "REPUBLICACION"}


@pytest.mark.parametrize("fin", [None, TODAY + "T07:00:00-03:00"])
def test_vigia_no_alerta_con_cadena_en_curso(tmp_path, monkeypatch, fin):
    save(tmp_path / f"cadena-{TODAY}.json", {"fecha": TODAY, "fin": fin, "pasos": [
        {"paso": "verificacion:amazon", "estado": "en_curso"}]})
    if fin:
        monkeypatch.setattr(vigia_franquicia, "cadena_en_curso", lambda *a: True, raising=False)
    assert vigia_franquicia.chequear_cadena(TODAY, tmp_path) == {}


@pytest.mark.parametrize("marca", ["PUBLICACION_SIN_ESTADO", "PUBLICACION_ESTADO_INVALIDO",
                                  "PUBLICACION_ALERTA_MASIVA", "DEPLOY_ALERT caída brusca"])
def test_vigia_reconoce_marcas_finales(marca):
    assert vigia_franquicia.MARCAS_FALLA.search(f"2026-11-09 07:00:00 {marca}")
