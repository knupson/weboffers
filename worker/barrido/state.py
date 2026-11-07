"""Páginas confirmadas como fuente de verdad; materialización atómica."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path


def write_atomic(path, value, *, text=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value if text else json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def acquire_run_lock(output):
    path = Path(output) / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink()


class State:
    def __init__(self, output, date, store):
        self.output, self.date, self.store = Path(output), date, store
        self.root = self.output / "state" / date / store
        self.root.mkdir(parents=True, exist_ok=True)

    def freeze(self, config):
        path = self.root / "context.json"
        if path.exists():
            old = json.loads(path.read_text(encoding="utf-8"))
            if old != config:
                raise ValueError("Configuración diaria incompatible: usá otro directorio output")
        else:
            write_atomic(path, config)

    def pages(self, category=None):
        paths = self.root.glob("pages/*/*.json") if category is None else (self.root / "pages" / category).glob("*.json")
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(paths)]

    def load_checkpoint(self, category):
        pages = sorted(self.pages(category), key=lambda p: p["page"])
        for expected, page in enumerate(pages, 1):
            if expected != page["page"]:
                raise ValueError(f"Hueco en páginas confirmadas: {category}/{expected}")
        if pages and pages[-1]["complete"]:
            return None
        return len(pages) + 1

    def commit_page(self, category, page, payload):
        path = self.root / "pages" / category / f"{page:06}.json"
        if path.exists():
            if json.loads(path.read_text(encoding="utf-8")) != payload:
                raise ValueError(f"Página inmutable ya confirmada: {category}/{page}")
        else:
            write_atomic(path, payload)
        write_atomic(self.root / "checkpoint.json", {"category": category, "next_page": None if payload["complete"] else page + 1})

    def materialize_jsonl(self):
        products = {}
        for page in self.pages():
            for row in page["products"]:
                key = row["id"]
                if key not in products:
                    products[key] = row
                else:
                    for source in row["provenance"]:
                        if source not in products[key]["provenance"]:
                            products[key]["provenance"].append(source)
        write_atomic(self.output / f"{self.store}-{self.date}.jsonl",
                     "".join(json.dumps(p, ensure_ascii=False, allow_nan=False) + "\n" for p in products.values()), text=True)
        return list(products.values())

    def reserve_variation(self, identity, limit):
        path = self.root / "variations.json"
        body = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if identity in body or len(body) >= limit:
            return False
        body[identity] = {"status": "pending", "value": None}
        write_atomic(path, body)
        return True

    def finish_variation(self, identity, **result):
        path = self.root / "variations.json"
        body = json.loads(path.read_text(encoding="utf-8"))
        body[identity] = result
        write_atomic(path, body)

    def variation(self, identity):
        path = self.root / "variations.json"
        body = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return body.get(identity, {}).get("value")


def write_summary(output, date, stores):
    path = Path(output) / f"resumen-{date}.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"date": date, "stores": {}}
    previous["stores"].update(stores)
    write_atomic(path, previous)


def context_key(context):
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()
