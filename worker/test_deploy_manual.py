"""El despliegue manual aborta ante cualquier descarga fallida, sin usar archivos locales."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("failed", ["ml-prices.json", "amazon-prices.json"])
def test_download_failure_aborts_before_build(tmp_path, failed):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    tools = tmp_path / "tools"
    tools.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    source = Path(__file__).resolve().parent.parent / "tools"
    shutil.copyfile(source / "deploy.sh", tools / "deploy.sh")
    for name in ("ml-prices.json", "amazon-prices.json"):
        (data / name).write_text("local anterior")
    hooks = tmp_path / "hooks.sh"
    hooks.write_text('''ssh() {
  case "$*" in *"$FAIL_FILE"*) return 1;; esac
  printf '%s' '{"date":"2026-11-05"}'
}
npm() { touch build-called; }
npx() { touch deploy-called; }
''')
    env = {**os.environ, "BASH_ENV": hooks.as_posix(), "FAIL_FILE": failed}
    result = subprocess.run([bash, str(tools / "deploy.sh")], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert "se aborta" in result.stderr
    assert not (tmp_path / "build-called").exists()
    assert not (tmp_path / "deploy-called").exists()
    assert all((data / name).read_text() == "local anterior" for name in ("ml-prices.json", "amazon-prices.json"))
