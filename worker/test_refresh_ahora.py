import json
import re

import pytest

from tools import refresh_ahora


@pytest.mark.parametrize("paso", ["amazon", "ml"])
def test_refresh_forzado_con_dailylog_y_traceback(tmp_path, monkeypatch, paso):
    worker = refresh_ahora.worker
    monkeypatch.setenv("OUTPUT_PATH", str(tmp_path / "offers.json"))
    monkeypatch.setenv("AMAZON_PRICES_PATH", str(tmp_path / "amazon-prices.json"))
    monkeypatch.setenv("ML_PRICES_PATH", str(tmp_path / "ml-prices.json"))
    monkeypatch.setattr(worker, "load_catalog", lambda *a: [])
    monkeypatch.setattr(worker.rates, "get_rates", lambda: {})
    module = worker.amazon_prices if paso == "amazon" else worker.ml_prices

    def refresh(catalog, target, *args, **kwargs):
        assert kwargs["force"] is True
        target.write_text(json.dumps({"date": refresh_ahora.datetime.now(module.ART).date().isoformat(),
                                      "items": {"producto": {"amount": 150}}}))

    monkeypatch.setattr(module, "maybe_refresh", refresh)
    with monkeypatch.context() as streams:
        streams.setattr(refresh_ahora.sys, "stdout", refresh_ahora.sys.stdout)
        streams.setattr(refresh_ahora.sys, "stderr", refresh_ahora.sys.stderr)
        assert refresh_ahora.main(paso) == 0

    def fail(*a, **kw):
        raise RuntimeError("error simulado")

    monkeypatch.setattr(module, "maybe_refresh", fail)
    with monkeypatch.context() as streams:
        streams.setattr(refresh_ahora.sys, "stdout", refresh_ahora.sys.stdout)
        streams.setattr(refresh_ahora.sys, "stderr", refresh_ahora.sys.stderr)
        assert refresh_ahora.main(paso) == 1
    text = next((tmp_path / "logs").glob("worker-*.log")).read_text(encoding="utf-8")
    assert f"REFRESH_INICIO {paso}" in text and f"REFRESH_OK {paso}" in text
    assert f"REFRESH_FAIL {paso}" in text and "Traceback" in text and "error simulado" in text
    assert all(re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ", line) for line in text.splitlines())
