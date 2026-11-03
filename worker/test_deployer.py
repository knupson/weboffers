"""El deploy nunca reemplaza el sitio si faltan los precios del día."""

import json
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize("amazon", [None, {"date": "2026-11-03", "items": {}},
                                   {"date": "2026-11-02", "items": {"a": {"amount": 200}}}])
def test_deadline_without_prices_never_calls_deploy(tmp_path, amazon):
    ml_path = tmp_path / "ml-prices.json"
    amazon_path = tmp_path / "amazon-prices.json"
    ml_path.write_text(json.dumps({"date": "2026-11-03", "items": {"a": {"price": 1000}}}))
    if amazon is not None:
        amazon_path.write_text(json.dumps(amazon))
    module = (Path(__file__).parent / "deployer" / "deploy.mjs").resolve().as_uri()
    script = """
        const { deployWithRetry } = await import(process.argv[1]);
        const result = await deployWithRetry({
            outputFile: process.argv[2], amazonOutputFile: process.argv[3],
            nowFn: () => new Date('2026-11-03T14:00:00Z'),
            deployFn: async () => { throw new Error('No debe desplegar'); },
        });
        if (result !== 'fail') throw new Error(result);
    """
    # Evita que el guard del módulo lo tome como ejecución del daemon.
    result = subprocess.run(["node", "--input-type=module", "-e", script, module + "?test",
                             str(ml_path), str(amazon_path)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "DEPLOY_FAIL" in result.stdout
    assert "amazon-prices.json" in result.stdout
    assert "DEPLOY_OK" not in result.stdout
