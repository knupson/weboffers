"""Registro compartido de productos por día (19/11, pedido de Alejandro).

La historia de las 12:30 (sticker a la ficha), el Reel de las 19:00 y la historia de las 20:00 (sticker a Telegram)
nunca repiten producto el mismo día. El lote de los lunes (lote_historias.py) reserva las dos historias de cada día;
el Reel (hacer_reel.py) excluye lo reservado para hoy y anota sus dos productos.

Archivo: productos-del-dia.json  {"AAAA-MM-DD": {"historia12": [slug], "reel19": [slug, slug], "historia20": [slug]}}
En la VM vive en /home/claude/reel/registro/productos-del-dia.json (hacer_reel_vm.sh monta la carpeta).
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import os
from pathlib import Path

TURNOS = ("historia12", "reel19", "historia20")
# En la VM se monta la carpeta registro/ (REGISTRO_DIA): os.replace no puede reemplazar un archivo montado suelto.
REGISTRO = Path(os.environ.get("REGISTRO_DIA") or Path(__file__).resolve().parent / "productos-del-dia.json")
GUARDAR_DIAS = 60


def leer(path: Path | None = None) -> dict:
    path = path or REGISTRO
    if not path.exists():
        return {}
    texto = path.read_text(encoding="utf-8").strip()
    return json.loads(texto) if texto else {}


def reservados(fecha: str, excepto: str | None = None, path: Path | None = None) -> set[str]:
    """Slugs ya tomados ese día por los otros turnos (el turno `excepto` no cuenta: se puede rehacer)."""
    dia = leer(path).get(fecha, {})
    return {slug for turno, slugs in dia.items() if turno != excepto for slug in slugs}


def reservar(fecha: str, turno: str, slugs: list[str], path: Path | None = None) -> None:
    """Anota los productos de un turno. Falla (ValueError) si repiten producto con otro turno del mismo día."""
    path = path or REGISTRO
    if turno not in TURNOS:
        raise ValueError(f"Turno desconocido: {turno} (válidos: {', '.join(TURNOS)})")
    if len(set(slugs)) != len(slugs):
        raise ValueError(f"{turno} {fecha}: productos repetidos dentro del turno: {slugs}")
    choque = reservados(fecha, excepto=turno, path=path) & set(slugs)
    if choque:
        raise ValueError(f"{turno} {fecha}: ya usados ese día por otro turno: {sorted(choque)}")
    datos = leer(path)
    datos.setdefault(fecha, {})[turno] = list(slugs)
    limite = (date.fromisoformat(fecha) - timedelta(days=GUARDAR_DIAS)).isoformat()
    datos = {f: d for f, d in sorted(datos.items()) if f >= limite}
    # Escritura atómica: el archivo está montado en el contenedor, se escribe al lado y se reemplaza.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
