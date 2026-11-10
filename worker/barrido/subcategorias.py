"""Lee de Amazon las subcategorías de cada categoría raíz y arma un archivo de categorías hoja.

Los IDs salen de la página de cada categoría (bloque «Department» de /s?rh=n:<id>, vía
`amazon.search.category_tree`); nunca se inventan. No cambia `categorias.json`: escribe
un archivo aparte que se usa con `python -m barrido --categories <archivo>`.

Uso (dentro del contenedor del barrido, con PYTHONPATH=/src/worker):
    python -m barrido.subcategorias --store US --salida /app/output/subcategorias

Escribe en --salida:
- subcategorias-<marca>.log: un evento por línea con hora ART en milisegundos (cada pedido HTTP,
  cada espera y cada categoría con sus hijas).
- categorias-hojas-<marca>.json: mismo formato que categorias.json, con kind="leaf".
"""
import argparse
import json
import os
import time
import traceback
from datetime import datetime
from pathlib import Path

from .config import load_config, validate_categories
from .revisar_ocultos import ART, Bitacora, crear_observador

PAUSA_SEGUNDOS = float(os.environ.get("SUBCATEGORIAS_PAUSA_SEGUNDOS", "5"))


def hojas_de(arbol):
    """Hijas con ID numérico y nombre; las que no traen ID se informan pero no se usan."""
    buenas, sin_id = [], []
    for hija in arbol.get("children") or []:
        nodo, nombre = str(hija.get("node_id") or ""), (hija.get("name") or "").strip()
        (buenas if nodo.isalnum() and nodo and nombre else sin_id).append({"id": nodo, "name": nombre})
    return buenas, sin_id


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--store", choices=("US", "ES"), default="US")
    ap.add_argument("--categories", help="Archivo de categorías raíz; por defecto categorias.json")
    ap.add_argument("--salida", default="/app/output/subcategorias")
    args = ap.parse_args(argv)

    marca = datetime.now(ART).strftime("%Y-%m-%d-%H%M%S")
    salida = Path(args.salida)
    log = Bitacora(salida / f"subcategorias-{marca}.log")
    raices = [n for n in load_config(args.categories)["stores"][args.store]["nodes"] if n["kind"] == "root"]
    log("SUBCAT_INICIO", tienda=args.store, raices=len(raices), pausa_segundos=PAUSA_SEGUNDOS,
        proxy=bool(os.environ.get("BARRIDO_AMAZON_PROXY")))

    from .bootstrap import configure_transport
    contador = {"http": 0}
    configure_transport(observer=crear_observador(log, contador, "SUBCAT"))
    from amazon import search

    inicio, hojas, vistos, fallas = time.monotonic(), [], set(), []
    for i, raiz in enumerate(raices):
        if i:
            log("SUBCAT_ESPERA", motivo="pausa_entre_categorias", segundos=PAUSA_SEGUNDOS)
            time.sleep(PAUSA_SEGUNDOS)
        t0, antes = time.monotonic(), contador["http"]
        log("SUBCAT_RAIZ_INICIO", id=raiz["id"], nombre=raiz["name"])
        try:
            arbol = search.category_tree(raiz["id"], args.store)
            buenas, sin_id = hojas_de(arbol)
            # 10/11: los departamentos «-intl-ship» devuelven una sola hija que es el departamento común
            # (p. ej. Computers → 541966 Computers & Accessories): se baja a las hijas de esa, hasta 2 niveles.
            nivel = 1
            while len(buenas) == 1 and nivel < 3:
                unica = buenas[0]
                log("SUBCAT_BAJA_NIVEL", raiz=raiz["id"], hacia=unica["id"], nombre=unica["name"], nivel=nivel + 1)
                log("SUBCAT_ESPERA", motivo="pausa_entre_niveles", segundos=PAUSA_SEGUNDOS)
                time.sleep(PAUSA_SEGUNDOS)
                sub, sin_id_sub = hojas_de(search.category_tree(unica["id"], args.store))
                sin_id += sin_id_sub
                if not sub:
                    break
                buenas, nivel = sub, nivel + 1
            nuevas = [h for h in buenas if h["id"] not in vistos and h["id"] != raiz["id"]]
            for h in nuevas:
                vistos.add(h["id"])
                hojas.append({"id": h["id"], "name": h["name"], "kind": "leaf", "parent": raiz["id"]})
            if not buenas and raiz["id"] not in vistos:
                # Sin bloque «Department»: la categoría queda como raíz para no perder su cobertura.
                vistos.add(raiz["id"])
                hojas.append({"id": raiz["id"], "name": raiz["name"], "kind": "root", "parent": raiz["id"]})
                log("SUBCAT_SIN_HIJAS", id=raiz["id"], nombre=raiz["name"], motivo="sin_bloque_department", queda="raiz")
            log("SUBCAT_RAIZ_FIN", id=raiz["id"], nombre=raiz["name"], estado="ok", hijas=len(buenas),
                nuevas=len(nuevas), sin_id=[h["name"] for h in sin_id], productos=arbol.get("products_count"),
                seleccionada=arbol.get("name"), ms=round((time.monotonic() - t0) * 1000),
                pedidos_http=contador["http"] - antes, lista=[f"{h['id']}:{h['name']}" for h in buenas])
        except Exception as exc:
            fallas.append(raiz["id"])
            log("SUBCAT_RAIZ_FIN", id=raiz["id"], nombre=raiz["name"], estado="error",
                error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc(),
                ms=round((time.monotonic() - t0) * 1000), pedidos_http=contador["http"] - antes)

    archivo = salida / f"categorias-hojas-{marca}.json"
    cuerpo = {"version": 1, "stores": {args.store: {"nodes": [{k: h[k] for k in ("id", "name", "kind")} for h in hojas],
                                                    "exclude": []}},
              "origen": {h["id"]: h["parent"] for h in hojas}}
    validate_categories({k: v for k, v in cuerpo.items() if k != "origen"})
    archivo.write_text(json.dumps(cuerpo, ensure_ascii=False, indent=2), encoding="utf-8")
    log("SUBCAT_FIN", raices=len(raices), hojas=len(hojas), fallas=fallas, archivo=str(archivo),
        segundos=round(time.monotonic() - inicio, 1), pedidos_http=contador["http"])
    return 1 if fallas else 0


if __name__ == "__main__":
    raise SystemExit(main())
