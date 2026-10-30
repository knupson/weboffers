from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

import telegram


CATALOG = [
    {"slug": "sin-foto", "name": "Sin foto", "summary": "Resumen", "store": "US", "verified": True},
    {"slug": "con-foto", "name": "Con <foto>", "summary": "Resumen & más", "store": "ES", "verified": True,
     "image": "/products/con-foto.webp"},
    {"slug": "no-verificado", "name": "X", "summary": "X", "store": "US", "verified": False},
]


@pytest.fixture(autouse=True)
def env(monkeypatch):
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
    assert "utm_source=telegram" in data["caption"] and "comisión" in data["caption"]
    assert telegram.maybe_post(CATALOG, state, noon_art()) is None
    assert post.call_count == 1


def test_waits_until_noon_and_skips_unverified(tmp_path, monkeypatch):
    post = Mock()
    monkeypatch.setattr(telegram.requests, "post", post)
    early = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 9:00 en Argentina
    assert telegram.maybe_post(CATALOG, tmp_path / "s.json", early) is None
    assert telegram.pick(CATALOG, ["con-foto"])["slug"] == "sin-foto"
    assert telegram.pick(CATALOG, ["con-foto", "sin-foto"])["slug"] == "con-foto"
    post.assert_not_called()


def test_does_nothing_without_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    assert telegram.maybe_post(CATALOG, tmp_path / "s.json", noon_art()) is None
