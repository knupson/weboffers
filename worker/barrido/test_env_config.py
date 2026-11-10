"""10/11: tope de páginas y pausa configurables por variable de entorno."""
from unittest import mock

from barrido import __main__ as cli


def _args(monkeypatch, env, argv=()):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    captured = {}

    def fake_execute(args, config):
        captured.update(args=args, config=config)
        return 0

    with mock.patch.object(cli, "execute", fake_execute), mock.patch.object(cli, "observe_run") as run:
        run.return_value.__enter__.return_value = mock.Mock()
        cli.main(list(argv))
    return captured


def test_variables_de_entorno_fijan_tope_y_pausa(monkeypatch, tmp_path):
    got = _args(monkeypatch, {"BARRIDO_MAX_PAGINAS": "7", "BARRIDO_PAUSE": "3"}, ["--output", str(tmp_path)])
    assert got["args"].max_pages == 7
    assert got["config"].pause == 3


def test_la_opcion_manda_sobre_la_variable(monkeypatch, tmp_path):
    got = _args(monkeypatch, {"BARRIDO_MAX_PAGINAS": "7"}, ["--output", str(tmp_path), "--max-pages", "2"])
    assert got["args"].max_pages == 2


def test_sin_variables_quedan_los_valores_de_siempre(monkeypatch, tmp_path):
    monkeypatch.delenv("BARRIDO_MAX_PAGINAS", raising=False)
    monkeypatch.delenv("BARRIDO_PAUSE", raising=False)
    got = _args(monkeypatch, {}, ["--output", str(tmp_path)])
    assert got["args"].max_pages is None
    assert got["config"].pause == 5


def test_tope_de_paginas_no_es_falla():
    from .__main__ import tienda_ok
    assert tienda_ok({"status": "partial", "categories": {"1": {"paginas": 10}}})
    assert not tienda_ok({"status": "partial", "categories": {"1": {"status": "failed", "error": "CDP"}}})
    assert not tienda_ok({"status": "partial", "reason": "ubicacion_ar_no_confirmada", "categories": {}})
    assert not tienda_ok({"status": "partial", "error": "x", "categories": {}})
    assert not tienda_ok({"status": "failed"}) and tienda_ok({"status": "skipped"})
