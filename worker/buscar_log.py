"""Diario durable de búsqueda. El JSONL es la fuente para reanudar, siempre en ART."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path

ART = timezone(timedelta(hours=-3))


def line(marker, **fields):
    stamp = datetime.now(ART).isoformat(timespec="seconds")
    print(f"{stamp} {marker} " + " ".join(f"{k}={v}" for k, v in fields.items()), flush=True)


class BuscarLog:
    def __init__(self, output, today=None):
        self.output = Path(output)
        self.today = today or datetime.now(ART).date().isoformat()
        self.path = self.output / f"buscar-{self.today}.jsonl"
        self.records = []
        if self.path.exists():
            # Un KILL puede dejar sólo la última línea incompleta. Truncarla antes
            # de anexar evita que se pegue al siguiente registro y lo invalide.
            with self.path.open("rb+") as handle:
                end = 0
                for raw in handle:
                    try:
                        record = json.loads(raw)
                    except (ValueError, UnicodeDecodeError):
                        if handle.read(1):
                            raise ValueError(f"Diario corrupto: {self.path}, byte {end}")
                        handle.seek(end)
                        handle.truncate()
                        handle.flush()
                        os.fsync(handle.fileno())
                        break
                    self.records.append(record)
                    end = handle.tell()
                else:
                    if end:
                        handle.seek(end - 1)
                        if handle.read(1) != b"\n":
                            handle.seek(end)
                            handle.write(b"\n")
                            handle.flush()
                            os.fsync(handle.fileno())

    def resolved(self, stage):
        return {r["id"]: r for r in self.records if r["stage"] == stage}

    def append(self, stage, identity, result, reason="", **data):
        record = dict(stage=stage, id=identity, result=result, reason=reason,
                      at=datetime.now(ART).isoformat(timespec="seconds"), **data)
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
        self.output.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        self.records.append(record)
        return record
