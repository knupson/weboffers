"""10/11: la imagen del barrido copia sólo algunos módulos de worker/. ml_prices importaba diario, requisitos,
publicacion y amazon_prices, que no se copiaban, y barrido_ml falló en producción con ModuleNotFoundError
(los tests no lo vieron porque corren con todo worker/ en el PYTHONPATH)."""
import ast
import re
from pathlib import Path

WORKER = Path(__file__).resolve().parent.parent


def copiados():
    texto = (WORKER / "barrido" / "Dockerfile").read_text(encoding="utf-8")
    archivos = set()
    for linea in texto.splitlines():
        partes = linea.split()
        if partes[:1] == ["COPY"] and partes[-1] == "/app/":
            archivos.update(p[:-3] for p in partes[1:-1] if re.fullmatch(r"[a-z_]+\.py", p))
    return archivos


def imports_locales(modulo):
    arbol = ast.parse((WORKER / f"{modulo}.py").read_text(encoding="utf-8"))
    nombres = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.update(a.name.split(".")[0] for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            nombres.add(nodo.module.split(".")[0])
    return {n for n in nombres if (WORKER / f"{n}.py").exists()}


def imports_del_barrido():
    nombres = set()
    for archivo in (WORKER / "barrido").glob("*.py"):
        if archivo.name.startswith("test_"):
            continue
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            if isinstance(nodo, ast.Import):
                nombres.update(a.name.split(".")[0] for a in nodo.names)
            elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
                nombres.add(nodo.module.split(".")[0])
    return {n for n in nombres if (WORKER / f"{n}.py").exists()}


def test_dockerfile_copia_todos_los_modulos_que_importa_el_barrido():
    copia = copiados()
    pendientes, necesarios = list(imports_del_barrido()), set()
    while pendientes:
        modulo = pendientes.pop()
        if modulo in necesarios:
            continue
        necesarios.add(modulo)
        pendientes.extend(imports_locales(modulo))
    assert necesarios - copia == set(), f"Faltan en el COPY del Dockerfile: {sorted(necesarios - copia)}"
