"""Auditoría 09/11 (F-07, F-15, F-21, F-23): precios de Amazon y ML se guardan al obtenerlos y un corte se retoma el mismo día.

Sin mocks de las funciones bajo prueba: sólo la red (fetch_bulk, fetch_ar_shipping, fetch_items) y las pausas.
Cada bucle se corta a mitad con un BaseException (un KILL no lo atrapa ningún `except Exception`) y se vuelve a correr.
"""
from datetime import datetime, timezone
import json
from unittest.mock import Mock

import pytest
import requests

import amazon_prices
import diario
import ml_prices
import publicacion

HOY = "2026-10-30"
AFTER_SEVEN = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 09:00 ART


class Kill(BaseException):
    """Simula SIGKILL."""


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "verificacion")
    monkeypatch.setenv("AMAZON_SCRAPER_URL", "http://scraper:8000")
    monkeypatch.delenv("AMAZON_AR_URL", raising=False)
    monkeypatch.setattr(amazon_prices, "PAUSE_SECONDS", 0)
    monkeypatch.setattr(amazon_prices, "BACKOFF_SECONDS", 0)
    monkeypatch.setattr(amazon_prices, "_budget_path", None)
    monkeypatch.setenv("ML_CLIENT_ID", "id")
    monkeypatch.setenv("ML_CLIENT_SECRET", "secret")
    monkeypatch.setattr(ml_prices, "PAUSE_SECONDS", 0)


def ok_item(asin, amount=150.0):
    return {"asin": asin, "price": {"amount": amount, "currency": "USD"}, "availability": {"is_in_stock": True}}


def vacio(asin):
    return {"asin": asin, "price": None, "buybox": None, "availability": None}


def producto(n, **cambios):
    return {"slug": f"p{n}", "asin": f"B{n:03d}", "store": "US", "verified": True, "image": "/products/x.webp",
            "ml": {"price": 1000, "catalogId": f"MLA{n}"}, "shipsToAr": {"freeShipping": True, "checked": HOY}, **cambios}


def publicados(tmp_path, catalogo, modo="publicado"):
    publicacion.guardar(tmp_path, {p["slug"]: publicacion._entrada(modo, "2026-10-29", "", p["asin"]) for p in catalogo})


# ----------------------------------------------------------------------------------------- F-07 Amazon: precios

def test_precios_kill_a_mitad_conserva_lo_consultado_y_el_reintento_solo_pide_lo_que_falta(tmp_path, monkeypatch, capsys):
    productos = [producto(n) for n in range(12)]
    prices = tmp_path / "amazon-prices.json"
    pedidos, cortar = [], [True]

    def bulk(base, asins, store):
        pedidos.append(list(asins))
        if cortar[0] and len(pedidos) == 3:
            raise Kill()
        return {a: ok_item(a) for a in asins}

    monkeypatch.setattr(amazon_prices, "fetch_bulk", bulk)
    with pytest.raises(Kill):
        amazon_prices.prices_with_chrome("http://scraper", productos, HOY, prices)
    guardados = [r for r in diario.leer(diario.ruta(prices, HOY)) if r["t"] == "precio"]
    assert [r["slug"] for r in guardados] == [f"p{n}" for n in range(10)]  # los 2 del lote en curso son lo único perdido
    assert all(r["at"].endswith("-03:00") and r["item"]["checked"] == HOY for r in guardados)
    assert capsys.readouterr().out.count("AMAZON_PRODUCTO") == 10  # una línea por precio, al obtenerlo
    assert not prices.exists()  # nada a medias: el deploy sólo ve un archivo completo

    pedidos.clear()
    cortar[0] = False
    items, ok, missing = amazon_prices.prices_with_chrome("http://scraper", productos, HOY, prices)
    assert pedidos == [["B010", "B011"]]
    assert sorted(items) == sorted(p["slug"] for p in productos) and ok == 12 and missing == 0
    assert "source=diario" in capsys.readouterr().out


def test_precios_de_otro_dia_o_de_otro_asin_no_se_reutilizan(tmp_path, monkeypatch):
    prices = tmp_path / "amazon-prices.json"
    diario.anotar(diario.ruta(prices, HOY), {"t": "precio", "at": "x", "slug": "p0",
                                             "item": {"asin": "OTRO", "amount": 99.0, "currency": "USD", "checked": HOY}})
    diario.anotar(diario.ruta(prices, HOY), {"t": "precio", "at": "x", "slug": "p1",
                                             "item": {"asin": "B001", "amount": 99.0, "currency": "USD", "checked": "2026-10-29"}})
    pedidos = []
    monkeypatch.setattr(amazon_prices, "fetch_bulk", lambda base, asins, store: pedidos.extend(asins) or {a: ok_item(a) for a in asins})
    items, ok, _ = amazon_prices.prices_with_chrome("http://scraper", [producto(0), producto(1)], HOY, prices)
    assert pedidos == ["B000", "B001"] and ok == 2 and items["p0"]["amount"] == 150.0


def test_maybe_refresh_cortado_deja_el_archivo_anterior_y_el_reintento_termina_sin_repetir(tmp_path, monkeypatch):
    productos = [producto(n) for n in range(8)]
    publicados(tmp_path, productos)
    prices = tmp_path / "amazon-prices.json"
    prices.write_text(json.dumps({"date": "2026-10-29", "items": {}}), encoding="utf-8")
    pedidos, cortar = [], [True]

    def bulk(base, asins, store):
        pedidos.append(list(asins))
        if cortar[0] and len(pedidos) == 2:
            raise Kill()
        return {a: ok_item(a) for a in asins}

    monkeypatch.setattr(amazon_prices, "fetch_bulk", bulk)
    with pytest.raises(Kill):
        amazon_prices.maybe_refresh(productos, prices, AFTER_SEVEN)
    assert json.loads(prices.read_text())["date"] == "2026-10-29"  # sigue el de ayer: el deploy no ve nada a medias
    pedidos.clear()
    cortar[0] = False
    assert amazon_prices.maybe_refresh(productos, prices, AFTER_SEVEN)
    assert pedidos == [["B005", "B006", "B007"]]
    saved = json.loads(prices.read_text())
    assert saved["date"] == HOY and len(saved["items"]) == 8 and "completo" not in saved


# ----------------------------------------------------------------------------------------- F-07 Amazon: envío

def test_envio_kill_a_mitad_conserva_lo_relevado_y_el_reintento_no_lo_repite(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAZON_AR_URL", "http://ar")
    productos = [producto(n) for n in range(7)]
    prices = tmp_path / "amazon-prices.json"
    pedidos, cortar = [], [True]

    def envio(base, asins, store):
        pedidos.append(list(asins))
        if cortar[0] and len(pedidos) == 2:
            raise Kill()
        return {a: {"asin": a, "ships": True, "free": True} for a in asins}

    monkeypatch.setattr(amazon_prices, "fetch_ar_shipping", envio)
    items = {}
    with pytest.raises(Kill):
        amazon_prices.refresh_ar_shipping(productos, items, HOY, prices)
    guardados = [r for r in diario.leer(diario.ruta(prices, HOY)) if r["t"] == "envio"]
    assert [r["slug"] for r in guardados] == [f"p{n}" for n in range(5)]

    pedidos.clear()
    cortar[0] = False
    items = {}
    resumen = amazon_prices.refresh_ar_shipping(productos, items, HOY, prices)
    assert pedidos == [["B005", "B006"]]
    assert resumen == {"relevados": 7, "gratis": 7, "sin_dato": 0}
    assert all(items[f"p{n}"]["shipsToAr"] == {"ships": True, "free": True, "checked": HOY} for n in range(7))


# ----------------------------------------------------------------------------------------- F-21 Amazon: reintento en el paso

def test_falla_transitoria_se_reintenta_una_vez_en_el_mismo_paso(tmp_path, monkeypatch, capsys):
    productos = [producto(n) for n in range(6)]
    publicados(tmp_path, productos)
    prices = tmp_path / "amazon-prices.json"
    llamadas = []

    def bulk(base, asins, store):
        llamadas.append(list(asins))
        # El primer intento de B002 vuelve vacío (uno solo por lote: no llega al umbral de ráfaga); el reintento anda.
        return {a: (vacio(a) if a == "B002" and len(llamadas) == 1 else ok_item(a)) for a in asins}

    monkeypatch.setattr(amazon_prices, "fetch_bulk", bulk)
    assert amazon_prices.maybe_refresh(productos, prices, AFTER_SEVEN)
    assert llamadas == [["B000", "B001", "B002", "B003", "B004"], ["B005"], ["B002"]]
    saved = json.loads(prices.read_text())
    assert "p2" in saved["items"] and len(saved["items"]) == 6
    assert saved["run"]["reintentoInmediato"] == {"pendientes": 1, "recuperados": 1}
    assert saved["run"]["fallas"] == 1 and saved["run"]["ok"] == 6  # la primera pasada se cuenta como falló; lo recuperado suma
    assert saved["missingReasons"] == {} and "reintento inmediato, recuperados=1 de 1" in capsys.readouterr().out


def test_falla_que_no_es_transitoria_no_se_reintenta(tmp_path, monkeypatch):
    productos = [producto(n) for n in range(3)]
    publicados(tmp_path, productos)
    llamadas = []

    def bulk(base, asins, store):
        llamadas.append(list(asins))
        return {a: (ok_item(a) if a != "B001" else {**ok_item(a), "availability": {"is_in_stock": False}}) for a in asins}

    monkeypatch.setattr(amazon_prices, "fetch_bulk", bulk)
    amazon_prices.maybe_refresh(productos, tmp_path / "amazon-prices.json", AFTER_SEVEN)
    assert llamadas == [["B000", "B001", "B002"]]  # sin_stock es del producto, no de la consulta


# ----------------------------------------------------------------------------------------- F-15 archivos parciales

def test_alta_sin_archivo_de_hoy_marca_parcial_y_conserva_la_memoria(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    publicacion.guardar(tmp_path, {})
    nuevo = producto(1)
    original = amazon_prices.prices_with_chrome
    prices = tmp_path / "amazon-prices.json"
    ayer = {"date": "2026-10-29", "items": {"viejo": {"amount": 200.0, "currency": "USD", "checked": "2026-10-29"}},
            "arShipping": {"viejo": {"ships": True, "free": True, "checked": "2026-10-29"},
                           "vencido": {"ships": True, "free": True, "checked": "2026-09-01"}},
            "noArOffer": {"sin": "2026-10-28"}, "pace": {"pause_s": 20.0, "limpios": 1, "v": amazon_prices.PACE_VERSION},
            "outOfRange": {"caro": {"amount": 500.0, "currency": "USD"}}}
    prices.write_text(json.dumps(ayer), encoding="utf-8")
    monkeypatch.setattr(amazon_prices, "prices_with_chrome", lambda *a: (
        {"p1": {"asin": "B001", "amount": 150.0, "currency": "USD", "checked": HOY}}, 1, 0))
    local = AFTER_SEVEN.astimezone(amazon_prices.ART)
    assert amazon_prices.price_new_products([nuevo], prices, local, "http://scraper")
    saved = json.loads(prices.read_text())
    assert saved["date"] == HOY and saved["completo"] is False
    assert list(saved["items"]) == ["p1"]  # nunca datos viejos: nada de ayer en items
    assert list(saved["arShipping"]) == ["viejo"]  # la memoria vigente (14 días) se conserva; la vencida no
    assert saved["noArOffer"] == {"sin": "2026-10-28"} and saved["pace"]["pause_s"] == 20.0
    assert saved["outOfRange"] == {"caro": {"amount": 500.0, "currency": "USD"}}

    # La verificación del mismo día no toma ese archivo como corrida hecha: consulta todo y lo deja completo.
    monkeypatch.setattr(amazon_prices, "prices_with_chrome", original)
    monkeypatch.setenv("PUBLICACION_MODO", "verificacion")
    productos = [producto(n) for n in (7, 8)]
    publicados(tmp_path, productos)
    pedidos = []
    monkeypatch.setattr(amazon_prices, "fetch_bulk", lambda base, asins, store: pedidos.extend(asins) or {a: ok_item(a) for a in asins})
    assert amazon_prices.maybe_refresh(productos, prices, AFTER_SEVEN)
    assert pedidos == ["B007", "B008"]
    final = json.loads(prices.read_text())
    assert "completo" not in final and sorted(final["items"]) == ["p7", "p8"]


def catalogo_ml(*slugs):
    return [{"slug": s, "name": s, "store": "US", "verified": True, "verdict": "ml", "image": "/p.webp", "asin": "B0" + s,
             "ml": {"price": 500000, "catalogId": "MLA" + s}, "shipsToAr": {"freeShipping": True}} for s in slugs]


def amazon_de_hoy(tmp_path, slugs):
    if not (tmp_path / "publicacion.json").exists():
        publicacion.guardar(tmp_path, {})
    (tmp_path / "amazon-prices.json").write_text(json.dumps({"date": HOY, "items": {
        s: {"amount": 200.0, "currency": "USD", "checked": HOY} for s in slugs}}), encoding="utf-8")


# ----------------------------------------------------------------------------------------- F-23 ML

def test_ml_kill_a_mitad_conserva_lo_consultado_y_el_reintento_solo_pide_lo_que_falta(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    slugs = ["a", "b", "c", "d"]
    catalogo = catalogo_ml(*slugs)
    amazon_de_hoy(tmp_path, slugs)
    pedidos, cortar = [], [True]

    def items(catalog_id):
        pedidos.append(catalog_id)
        if cortar[0] and catalog_id == "MLAc":
            raise Kill()
        return [{"price": 400000, "condition": "new", "id": "MLA1", "permalink": "x"}] if catalog_id != "MLAb" else []

    monkeypatch.setattr(ml_prices, "fetch_items", items)
    monkeypatch.setattr(ml_prices, "cheapest_new", lambda found: (400000, "MLA1") if found else None)
    prices = tmp_path / "ml-prices.json"
    with pytest.raises(Kill):
        ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN)
    assert not prices.exists()
    guardados = diario.leer(diario.ruta(prices, HOY))
    assert [(r["slug"], r["estado"]) for r in guardados] == [("a", "ok"), ("b", "absent")]
    assert all(r["at"].endswith("-03:00") for r in guardados)
    assert capsys.readouterr().out.count("ML_PRODUCTO") == 2

    pedidos.clear()
    cortar[0] = False
    assert ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN)
    assert pedidos == ["MLAc", "MLAd"]
    saved = json.loads(prices.read_text())
    assert sorted(saved["items"]) == ["a", "c", "d"] and saved["absent"] == ["b"]
    assert "estado=ok motivo=ya_consultado_hoy" in capsys.readouterr().out


def test_ml_el_diario_de_otro_slot_no_se_reutiliza(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    catalogo = catalogo_ml("a")
    amazon_de_hoy(tmp_path, ["a"])
    prices = tmp_path / "ml-prices.json"
    diario.anotar(diario.ruta(prices, HOY), {"t": "consulta", "date": HOY, "slot": "2026-10-30T13", "at": "x", "slug": "a",
                                             "estado": "ok", "entry": {"catalogId": "MLAa", "price": 1, "checked": HOY}})
    pedidos = []
    monkeypatch.setattr(ml_prices, "fetch_items", lambda cid: pedidos.append(cid) or [{}])
    monkeypatch.setattr(ml_prices, "cheapest_new", lambda found: (400000, "MLA1"))
    ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN)
    assert pedidos == ["MLAa"]
    assert json.loads(prices.read_text())["items"]["a"]["price"] == 400000


# ----------------------------------------------------------------------------------------- F-21 ML

def test_ml_consulta_fallida_se_reintenta_una_vez_en_el_mismo_paso(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    catalogo = catalogo_ml("a", "b")
    amazon_de_hoy(tmp_path, ["a", "b"])
    llamadas = []

    def items(catalog_id):
        llamadas.append(catalog_id)
        if catalog_id == "MLAa" and llamadas.count("MLAa") == 1:
            raise requests.ConnectionError("sin red")
        return [{}]

    monkeypatch.setattr(ml_prices, "fetch_items", items)
    monkeypatch.setattr(ml_prices, "cheapest_new", lambda found: (400000, "MLA1"))
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN)
    assert llamadas == ["MLAa", "MLAb", "MLAa"]
    saved = json.loads(prices.read_text())
    assert sorted(saved["items"]) == ["a", "b"] and saved["failed"] == []
    assert "recuperado_en_reintento" in capsys.readouterr().out


def test_ml_si_el_reintento_tambien_falla_queda_en_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    amazon_de_hoy(tmp_path, ["a"])
    monkeypatch.setattr(ml_prices, "fetch_items", Mock(side_effect=requests.ConnectionError("sin red")))
    prices = tmp_path / "ml-prices.json"
    ml_prices.maybe_refresh(catalogo_ml("a"), prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN)
    assert ml_prices.fetch_items.call_count == 2
    saved = json.loads(prices.read_text())
    assert saved["failed"] == ["a"] and saved["items"] == {}
    assert diario.leer(diario.ruta(prices, HOY)) == []  # lo fallido no se anota como hecho


# ----------------------------------------------------------------------------------------- F-15 ML

def test_ml_alta_sin_archivo_de_hoy_marca_parcial_y_la_verificacion_lo_rehace(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    amazon_de_hoy(tmp_path, ["nuevo", "pub"])
    prices = tmp_path / "ml-prices.json"
    prices.write_text(json.dumps({"date": "2026-10-29", "slot": "2026-10-29T06", "items": {
        "pub": {"catalogId": "MLApub", "price": 1, "checked": "2026-10-29"}}}), encoding="utf-8")
    pedidos = []
    monkeypatch.setattr(ml_prices, "fetch_items", lambda cid: pedidos.append(cid) or [{}])
    monkeypatch.setattr(ml_prices, "cheapest_new", lambda found: (400000, "MLA1"))
    catalogo = catalogo_ml("nuevo", "pub")
    publicacion.guardar(tmp_path, {"pub": publicacion._entrada("publicado", "2026-10-29", "", "B0pub")})
    assert ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN)
    parcial = json.loads(prices.read_text())
    assert parcial["date"] == HOY and parcial["completo"] is False
    assert list(parcial["items"]) == ["nuevo"]  # sólo el producto del alta; nada de ayer
    assert pedidos == ["MLAnuevo"]

    # El mismo día la verificación no lo da por hecho: consulta sus productos y deja un archivo sin la marca.
    monkeypatch.setenv("PUBLICACION_MODO", "verificacion")
    pedidos.clear()
    assert ml_prices.maybe_refresh(catalogo, prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN)
    assert pedidos == ["MLApub"]
    final = json.loads(prices.read_text())
    assert "completo" not in final and list(final["items"]) == ["pub"]


def test_ml_alta_sobre_el_archivo_completo_de_hoy_no_lo_marca_parcial(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLICACION_MODO", "alta")
    amazon_de_hoy(tmp_path, ["nuevo", "pub"])
    prices = tmp_path / "ml-prices.json"
    prices.write_text(json.dumps({"date": HOY, "slot": "2026-10-30T06", "items": {
        "pub": {"catalogId": "MLApub", "price": 1, "checked": HOY}}}), encoding="utf-8")
    monkeypatch.setattr(ml_prices, "fetch_items", lambda cid: [{}])
    monkeypatch.setattr(ml_prices, "cheapest_new", lambda found: (400000, "MLA1"))
    publicacion.guardar(tmp_path, {"pub": publicacion._entrada("publicado", "2026-10-29", "", "B0pub")})
    ml_prices.maybe_refresh(catalogo_ml("nuevo", "pub"), prices, tmp_path / "amazon-prices.json", 1000.0, AFTER_SEVEN, force=True)
    saved = json.loads(prices.read_text())
    assert "completo" not in saved and sorted(saved["items"]) == ["nuevo", "pub"]
