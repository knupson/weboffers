from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

import telegram


CATALOG = [
    {"slug": "sin-foto", "asin": "B000000001", "name": "Sin foto", "summary": "Resumen", "store": "US",
     "verified": True, "ml": {"price": 200000}, "amazonArs": 190000, "shipsToAr": {"freeShipping": True},
     "listPrice": {"amount": 150, "currency": "USD"}},
    {"slug": "con-foto", "asin": "B000000002", "name": "Con <foto>", "summary": "Resumen & más", "store": "ES",
     "verified": True, "verdict": "ml", "image": "/products/con-foto.webp",
     "ml": {"price": 300000, "checked": "2026-10-30"}, "amazonArs": 230000,
     "shipsToAr": {"freeShipping": True, "checked": "2026-10-30"}, "amazonSource": "amazon",
     "amazonUsd": 200, "amazonChecked": "2026-10-30"},
    {"slug": "solo-source-vencido", "asin": "B000000006", "name": "Source vencido", "summary": "X", "store": "US",
     "verified": True, "ml": {"price": 300000}, "amazonSource": "amazon", "amazonArs": None},
    {"slug": "sin-ml", "asin": "B000000003", "name": "Sin ML", "summary": "X", "store": "US",
     "verified": True, "amazonArs": 190000, "listPrice": {"amount": 150, "currency": "USD"}},
    {"slug": "sin-estimado", "asin": "B000000004", "name": "Sin estimado", "summary": "X", "store": "US",
     "verified": True, "ml": {"price": 100000}},
    {"slug": "sin-asin", "asin": "", "name": "Sin ASIN", "summary": "X", "store": "US",
     "verified": True, "ml": {"price": 100000}, "amazonArs": 190000, "listPrice": {"amount": 150, "currency": "USD"}},
    {"slug": "no-verificado", "asin": "B000000005", "name": "X", "summary": "X", "store": "US",
     "verified": False, "ml": {"price": 100000}, "amazonArs": 190000, "listPrice": {"amount": 150, "currency": "USD"}},
]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return noon_art().astimezone(tz)
    monkeypatch.setattr(telegram, "datetime", Clock)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "@canal")


def noon_art():
    return datetime(2026, 10, 30, 15, 30, tzinfo=timezone.utc)  # 12:30 en Argentina


def test_posts_photo_first_then_once_per_day(tmp_path, monkeypatch):
    post = Mock()
    post.return_value.raise_for_status = Mock()
    monkeypatch.setattr(telegram.requests, "post", post)
    state = tmp_path / "s.json"
    assert telegram.maybe_post(CATALOG, state, noon_art()) == "con-foto"
    url, = post.call_args.args
    assert url.endswith("/sendPhoto")
    data = post.call_args.kwargs["data"]
    assert data["photo"] == "https://ofertas.knunet.com/products/con-foto.jpg"
    assert "Con &lt;foto&gt;" in data["caption"] and "Amazon.es" in data["caption"]
    assert "USD" not in data["caption"] and "EUR" not in data["caption"]
    assert "utm_source=telegram" in data["caption"] and "comisión" in data["caption"]
    assert telegram.maybe_post(CATALOG, state, noon_art()) is None
    assert post.call_count == 1


def test_waits_until_noon_and_skips_non_comparable(tmp_path, monkeypatch):
    post = Mock()
    monkeypatch.setattr(telegram.requests, "post", post)
    early = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 9:00 en Argentina
    assert telegram.maybe_post(CATALOG, tmp_path / "s.json", early) is None
    # Sin foto no se publica: el único comparable es con-foto y el ciclo vuelve a empezar con él.
    assert telegram.pick(CATALOG, ["con-foto"])["slug"] == "con-foto"
    assert [p["slug"] for p in CATALOG if telegram.is_comparable(p)] == ["con-foto"]
    post.assert_not_called()


def test_does_nothing_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert telegram.maybe_post(CATALOG, tmp_path / "s.json", noon_art()) is None


def test_rejects_stale_amazon_source_after_amazon_price_expires(tmp_path):
    import json
    import ml_prices

    catalog = [
        {"slug": "vencido", "asin": "B000000009", "name": "Vencido", "summary": "X", "store": "US",
         "verified": True, "ml": {"price": 300000}, "shipsToAr": {"freeShipping": True}},
    ]
    ml_file = tmp_path / "ml-prices.json"
    # Actualización parcial de ML que conservó amazonSource="amazon" de un día previo
    ml_file.write_text(json.dumps({"date": "2026-10-30", "items": {
        "vencido": {"price": 290000, "verdict": "amazon", "amazonSource": "amazon"},
    }}), encoding="utf-8")
    amz_file = tmp_path / "amazon-prices.json"
    amz_file.write_text(json.dumps({"date": "2026-10-30", "items": {
        "vencido": {"amount": 150, "currency": "USD", "checked": "2026-10-20"},  # vencido (> 3 días)
    }}), encoding="utf-8")

    merged = ml_prices.merge(catalog, ml_file, amz_file, mep=1200.0, eur_usd=1.25, now=noon_art())
    assert merged[0]["amazonArs"] is None
    assert merged[0]["amazonSource"] is None
    assert telegram.is_comparable(merged[0]) is False


def test_posts_again_at_20_and_respects_old_state(tmp_path, monkeypatch):
    import json
    post = Mock()
    post.return_value.raise_for_status = Mock()
    monkeypatch.setattr(telegram.requests, "post", post)
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"lastDate": "2026-10-30", "posted": []}), encoding="utf-8")
    assert telegram.maybe_post(CATALOG, state, noon_art()) is None  # el de las 12 ya salió (estado viejo)
    night = datetime(2026, 10, 30, 23, 5, tzinfo=timezone.utc)  # 20:05 en Argentina
    assert telegram.maybe_post(CATALOG, state, night) == "con-foto"
    assert telegram.maybe_post(CATALOG, state, night) is None
    assert post.call_count == 1


def test_no_publica_sin_envio_gratis_confirmado():
    # 03/11: Telegram iba a publicar el Samsung T7 sin envío confirmado (REGLA 0).
    base = {**CATALOG[1], "shipsToAr": None}
    assert not telegram.is_comparable(base)
    assert not telegram.is_comparable({**base, "shipsToAr": {"freeShipping": False}})
    assert telegram.is_comparable({**base, "shipsToAr": {"freeShipping": True, "checked": "2026-10-30"}})


def test_envio_del_relevamiento_manda_sobre_el_catalogo(tmp_path):
    import json, worker
    path = tmp_path / "amazon-prices.json"
    path.write_text(json.dumps({"arShipping": {"a": {"ships": True, "free": False, "checked": "2026-11-03"},
                                               "b": {"ships": True, "free": True, "checked": "2026-11-03"}}}), encoding="utf-8")
    out = worker.with_ar_shipping([{"slug": "a", "shipsToAr": {"freeShipping": True}}, {"slug": "b"}, {"slug": "c"}], path,
                                 datetime(2026, 11, 3, 15, tzinfo=timezone.utc))
    assert [p.get("shipsToAr", {}).get("freeShipping") for p in out] == [False, True, None]
    assert out[1]["shipsToAr"]["checked"] == "2026-11-03"


@pytest.mark.parametrize("usd,expected", [(99.99, False), (100, True), (400, True), (400.01, False), (None, False)])
def test_rango_amazon(usd, expected):
    assert telegram.is_comparable({**CATALOG[1], "amazonUsd": usd}) is expected


@pytest.mark.parametrize("checked,expected", [("2026-10-16", True), ("2026-10-15", False),
                                            ("2026-10-31", False), (None, False), ("2026-02-30", False)])
def test_vigencia_envio(checked, expected):
    assert telegram.is_comparable({**CATALOG[1], "shipsToAr": {"freeShipping": True, "checked": checked}}) is expected


@pytest.mark.parametrize("change", [{"ml": {"price": 200000, "checked": "2026-10-29"}},
                                    {"amazonChecked": "2026-10-29"}, {"amazonSource": None}, {"shipsToArToday": False}])
def test_exige_precios_de_hoy_y_envio(change):
    assert not telegram.is_comparable({**CATALOG[1], **change})
