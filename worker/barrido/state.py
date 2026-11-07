"""Páginas confirmadas como fuente de verdad; materialización atómica."""
from contextlib import contextmanager
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from .events import emit_event


def write_atomic(path, value, *, text=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(value if text else json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def pid_alive(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Acceso denegado no prueba que haya muerto.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def acquire_run_lock(output, max_run_hours=8):
    path = Path(output) / "run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    owner = dict(pid=os.getpid(), started_at=time.time(), token=uuid.uuid4().hex)
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                literal = path.read_text(encoding='utf-8')
                existing = json.loads(literal)
                if isinstance(existing, int):  # Lock anterior a pid+hora.
                    existing = dict(pid=existing, started_at=path.stat().st_mtime)
                stale = time.time() - existing['started_at'] > max_run_hours * 3600 or not pid_alive(existing['pid'])
            except FileNotFoundError:
                continue
            except (ValueError, KeyError, TypeError):
                # Puede estar recién creado y todavía sin escribir.
                stale = time.time() - path.stat().st_mtime > max_run_hours * 3600
            if not stale:
                raise
            emit_event('BARRIDO_LOCK_HUERFANO', lock=literal)
            if path.read_text(encoding='utf-8') == literal:
                path.unlink()
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(owner, stream)
        yield
    finally:
        if path.exists() and json.loads(path.read_text(encoding='utf-8')) == owner:
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
            # Los IDs conocidos cambian con el catálogo; los subconjuntos de nodos
            # comparten páginas, pero conservan una definición estable por nodo.
            old.pop('known', None)
            config = {k: v for k, v in config.items() if k != 'known'}
            old_definition, definition = old.get('definition'), config.get('definition')
            if old_definition is not None and definition is not None:
                old_nodes = {node['id']: node for node in old_definition['nodes']}
                nodes = {node['id']: node for node in definition['nodes']}
                if any(old_nodes[key] != nodes[key] for key in old_nodes.keys() & nodes.keys()):
                    raise ValueError('Configuración diaria incompatible: cambió un nodo')
                merged = {**old_definition, 'nodes': list({**old_nodes, **nodes}.values())}
                old = {**old, 'definition': {k: v for k, v in old_definition.items() if k != 'nodes'}}
                comparable = {**config, 'definition': {k: v for k, v in definition.items() if k != 'nodes'}}
            else:
                comparable, merged = config, None
            if old != comparable:
                raise ValueError("Configuración diaria incompatible: usá otro directorio output")
            write_atomic(path, {**config, **({'definition': merged} if merged is not None else {})})
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

    def materialize_jsonl(self, known=None):
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
        if known is not None:
            for row in products.values():
                row["known"] = row["id"] in known
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
