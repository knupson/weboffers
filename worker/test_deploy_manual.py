"""05/11: el despliegue manual lo hace el deployer de la VM (mismo camino que el automático).

Antes tools/deploy.sh compilaba en la PC con data/catalog.json y sin catalog-auto.json, y publicaba el sitio
sin las altas automáticas.
"""
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_deploy_manual_usa_el_deployer_de_la_vm():
    script = (RAIZ / "tools" / "deploy.sh").read_text(encoding="utf-8")
    assert "node /app/deploy.mjs --ahora" in script
    assert "npm run build" not in script and "wrangler" not in script


def test_deployer_acepta_ahora_por_el_mismo_deploy_once():
    deploy = (RAIZ / "worker" / "deployer" / "deploy.mjs").read_text(encoding="utf-8")
    assert "process.argv.includes('--ahora')" in deploy
    assert "main({ manual: process.argv.includes('--ahora') })" in deploy
    assert "(opts.deployFn ?? deployOnce)(now, { ...opts, manual: opts.manual ?? false })" in deploy
