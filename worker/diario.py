"""Diario de consultas del día: una línea JSON por ítem consultado, escrita con flush+fsync al obtenerlo.

Pedido de Alejandro (09/11): «teniamos que tener log de todo para consultar» y no guardar sólo en memoria. Un KILL pierde
a lo sumo el ítem en curso; la corrida siguiente del mismo día lee el diario y saltea lo ya consultado.
El diario no es un archivo de precios: el deploy nunca lo lee, así que un diario a medias no puede publicarse.
"""
from contextlib import contextmanager
from datetime import date, timedelta
import json
import os
from pathlib import Path
import time


def ruta(prices_path, today):
    """Un diario por archivo de precios y por día: amazon-prices-diario-AAAA-MM-DD.jsonl."""
    return Path(prices_path).with_name(f"{Path(prices_path).stem}-diario-{today}.jsonl")


@contextmanager
def exclusivo(path):
    """Exclusión entre procesos sobre el diario (flock en Linux; en Windows, sólo para correr los tests)."""
    lock = Path(str(path) + ".lock")
    with lock.open("a+b") as archivo:
        if os.name == "posix":
            import fcntl
            fcntl.flock(archivo, fcntl.LOCK_EX)
        else:
            import msvcrt
            archivo.write(b"\0")
            archivo.flush()
            archivo.seek(0)
            while True:
                try:
                    msvcrt.locking(archivo.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        try:
            yield
        finally:
            if os.name == "posix":
                import fcntl
                fcntl.flock(archivo, fcntl.LOCK_UN)
            else:
                archivo.seek(0)
                msvcrt.locking(archivo.fileno(), msvcrt.LK_UNLCK, 1)


def anexar_linea(path, linea):
    """Agrega una línea reparando antes una cola truncada por un KILL.

    Si el archivo no termina en salto de línea, el último fragmento (escritura cortada) se recorta hasta el último
    salto; así el registro nuevo no se pega a un fragmento y se pierde junto con él. Todo bajo exclusión mutua."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with exclusivo(path):
        with path.open("a+b") as archivo:
            archivo.seek(0, os.SEEK_END)
            size = archivo.tell()
            if size:
                archivo.seek(size - 1)
                if archivo.read(1) != b"\n":
                    archivo.seek(0)
                    contenido = archivo.read()
                    archivo.truncate(contenido.rfind(b"\n") + 1)
            archivo.seek(0, os.SEEK_END)
            archivo.write(linea.encode("utf-8") + b"\n")
            archivo.flush()
            os.fsync(archivo.fileno())


def anotar(path, registro):
    """Agrega un registro y lo fuerza a disco antes de seguir con el ítem siguiente."""
    anexar_linea(path, json.dumps(registro, ensure_ascii=False, allow_nan=False))


def leer(path):
    """Registros válidos del diario; ignora una última línea truncada por un KILL y cualquier línea ilegible."""
    try:
        texto = Path(path).read_text(encoding="utf-8")
    except OSError:
        return []
    registros = []
    for linea in texto.splitlines():
        try:
            registro = json.loads(linea)
        except ValueError:
            continue
        if isinstance(registro, dict):
            registros.append(registro)
    return registros


def purgar(prices_path, today, dias=7):
    """Borra diarios de más de `dias` días (los archivos de otros días nunca se reutilizan)."""
    limite = (date.fromisoformat(today) - timedelta(days=dias)).isoformat()
    for viejo in Path(prices_path).parent.glob(f"{Path(prices_path).stem}-diario-*.jsonl*"):
        try:
            if viejo.name.rsplit("-diario-", 1)[1][:10] <= limite:
                viejo.unlink()
        except (IndexError, OSError):
            pass
