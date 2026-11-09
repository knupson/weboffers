"""Salida atómica y aviso de cambios a Cloudflare."""

import hashlib
import json
import os
from pathlib import Path
import tempfile

import requests


def build_offers(generated_at, mode, rates, items):
    if mode not in ("api", "offline"):
        raise ValueError("El modo debe ser api u offline")
    fields = ("asin", "store", "title", "priceUsd", "priceFetchedAt", "imageUrl", "availability")
    return {"generatedAt": generated_at, "mode": mode, "rates": rates,
            "items": [{key: item.get(key) for key in fields} for item in items]}


def write_atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", suffix=".tmp",
                                         delete=False) as handle:
            temporary = handle.name
            json.dump(data, handle, ensure_ascii=False, allow_nan=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if path.name in {"ml-prices.json", "amazon-prices.json"} and path.parent.name != "historial":
            from datetime import date, timedelta
            day = date.fromisoformat(data["date"])
            history = path.parent / "historial"
            write_atomic(history / f"{day}-{path.name}", data)
            for old in history.glob("????-??-??-*-prices.json"):
                try:
                    if date.fromisoformat(old.name[:10]) <= day - timedelta(days=60):
                        old.unlink()
                except (ValueError, OSError):
                    pass
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def limpiar_temporales(directory, minutos=60):
    """Borra los `.nombre.XXXX.tmp` que dejó un write_atomic cortado por KILL (su `finally` no corre con SIGKILL).

    Sólo los de más de `minutos` minutos: una escritura en curso termina en milisegundos. Devuelve cuántos borró."""
    import time
    directory = Path(directory)
    limite = time.time() - minutos * 60
    borrados = 0
    for carpeta in (directory, directory / "historial", directory / "dudosos"):
        for viejo in carpeta.glob(".*.tmp"):
            try:
                if viejo.is_file() and viejo.stat().st_mtime < limite:
                    viejo.unlink()
                    borrados += 1
            except OSError:
                pass
    return borrados


def content_hash(payload):
    content = {key: value for key, value in payload.items() if key != "generatedAt"}
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def publish(path, payload, deploy_hook_url):
    try:
        with Path(path).open(encoding="utf-8") as handle:
            previous_hash = content_hash(json.load(handle))
    except (FileNotFoundError, ValueError, TypeError, AttributeError):
        previous_hash = None
    changed = content_hash(payload) != previous_hash
    write_atomic(path, payload)
    if changed and deploy_hook_url:
        response = requests.post(deploy_hook_url, timeout=30)
        response.raise_for_status()
    return changed
