#!/usr/bin/env python3
"""Marca «Lo más vendido esta semana» con los destacados de Mercado Libre de hoy (12/11).

La marca `hot` de data/catalog.json era del 02/11, cargada a mano y nunca renovada. Este script cruza el catálogo
(data/catalog.json + catalog-auto.json) con los destacados actuales de ML (/highlights/MLA/category/<cat>, las
mismas raíces que crecer_desde_ml) y escribe output/mas-vendidos.json; el deployer lo copia a data/ y el sitio
toma esa fecha como `hot`. Si no obtiene ningún destacado no escribe nada (nunca deja una marca vieja como nueva).

Dentro del worker:
  python /app/tools/actualizar_mas_vendidos.py
"""
from datetime import datetime
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "worker"))
sys.path.insert(0, str(HERE.parent))
import ml_prices  # noqa: E402
from publish import write_atomic  # noqa: E402


def log(text):
    print(f"{datetime.now(ml_prices.ART):%Y-%m-%d %H:%M:%S} {text}", flush=True)


def leer_lista(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{path} debe ser una lista de productos")
    return data


def calcular(catalogo, destacados):
    """Slugs del catálogo cuyo catalogId de ML está hoy entre los destacados."""
    return sorted({p["slug"] for p in catalogo
                   if isinstance(p, dict) and p.get("slug") and (p.get("ml") or {}).get("catalogId") in destacados})


def destacados_ml(fallas):
    from tools import crecer_desde_ml
    return crecer_desde_ml.mas_vendidos_ml(set(), failures=fallas)


def main(output=Path("/app/output"), repo_catalog=Path("/app/data/catalog.json"), obtener=destacados_ml, hoy=None):
    output = Path(output)
    hoy = hoy or datetime.now(ml_prices.ART).date().isoformat()
    fallas = []
    destacados = obtener(fallas)
    if not destacados:
        log(f"MAS_VENDIDOS_FALLA sin destacados de ML hoy (categorias_con_error={len(fallas)}); no se escribe nada")
        return 1
    catalogo = leer_lista(repo_catalog) + leer_lista(output / "catalog-auto.json")
    slugs = calcular(catalogo, destacados)
    write_atomic(output / "mas-vendidos.json", {"fecha": hoy, "slugs": slugs, "destacadosMl": len(destacados),
                                                "categoriasConError": len(fallas)})
    log(f"MAS_VENDIDOS_OK fecha={hoy} slugs={len(slugs)} destacados_ml={len(destacados)} "
        f"categorias_con_error={len(fallas)} {','.join(slugs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
