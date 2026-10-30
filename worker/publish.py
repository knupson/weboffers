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
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


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
