"""Diario de consultas del día: una línea JSON por ítem consultado, escrita con flush+fsync al obtenerlo.

Pedido de Alejandro (09/11): «teniamos que tener log de todo para consultar» y no guardar sólo en memoria. Un KILL pierde
a lo sumo el ítem en curso; la corrida siguiente del mismo día lee el diario y saltea lo ya consultado.
El diario no es un archivo de precios: el deploy nunca lo lee, así que un diario a medias no puede publicarse.
"""
from datetime import date, timedelta
import json
import os
from pathlib import Path


def ruta(prices_path, today):
    """Un diario por archivo de precios y por día: amazon-prices-diario-AAAA-MM-DD.jsonl."""
    return Path(prices_path).with_name(f"{Path(prices_path).stem}-diario-{today}.jsonl")


def anotar(path, registro):
    """Agrega un registro y lo fuerza a disco antes de seguir con el ítem siguiente."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as archivo:
        archivo.write(json.dumps(registro, ensure_ascii=False, allow_nan=False) + "\n")
        archivo.flush()
        os.fsync(archivo.fileno())


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
    for viejo in Path(prices_path).parent.glob(f"{Path(prices_path).stem}-diario-*.jsonl"):
        try:
            if viejo.stem.rsplit("-diario-", 1)[1] <= limite:
                viejo.unlink()
        except (IndexError, OSError):
            pass
