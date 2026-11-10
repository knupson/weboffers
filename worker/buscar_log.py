"""Diario durable de búsqueda; índices incrementales y reanudación en ART."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time

ART = timezone(timedelta(hours=-3))
RESUME_DAYS = 7  # Misma ventana que «no revisar»; hoy y los seis días anteriores.
OUTCOMES = {
    "ml": {"con_pares", "sin_pares", "sin_precio", "fuera_de_rango", "duplicado"},
    "amazon": {"con_pares", "sin_pares", "duplicado", "fuera_de_rango"},
    "match": {"accepted", "doubtful", "rejected"},
    "ficha_ml": {"ok"},
}


class BuscarStop(Exception):
    """Plazo cooperativo vencido; todo registro confirmado ya está en disco."""


def check_stop():
    deadline = os.getenv("BUSCAR_DEADLINE")
    if deadline and time.time() >= float(deadline):
        raise BuscarStop("plazo_buscar")


def line(marker, **fields):
    stamp = datetime.now(ART).isoformat(timespec="seconds")
    print(f"{stamp} {marker} " + " ".join(f"{k}={v}" for k, v in fields.items()), flush=True)


class BuscarLog:
    def __init__(self, output, today=None):
        self.output = Path(output)
        self.today = today or datetime.now(ART).date().isoformat()
        self.path = self.output / f"buscar-{self.today}.jsonl"
        self.records = []  # Sólo hoy: nunca reprocesar pares/precios de otro día.
        self.index = defaultdict(dict)
        self.counts = Counter()
        self.data = defaultdict(dict)
        self.waiting = defaultdict(set)
        self.parents = {}
        self.stop_reason = ""
        day = datetime.fromisoformat(self.today)
        for age in range(RESUME_DAYS - 1, -1, -1):
            path = self.output / f"buscar-{(day - timedelta(days=age)).date()}.jsonl"
            for record in self._read(path):
                if age == 0:
                    self.records.append(record)
                    self._index(record)
                elif record["stage"] in ("ml", "amazon", "match"):
                    self._index(record, historical=True)

    def _read(self, path):
        if not path.exists():
            return []
        raw = path.read_bytes()
        good, damaged = [], False
        for row in raw.splitlines():
            try:
                record = json.loads(row)
                if not isinstance(record, dict) or not all(k in record for k in ("stage", "id", "result")):
                    raise ValueError("registro inválido")
                good.append(record)
            except (ValueError, UnicodeDecodeError):
                damaged = True
        if damaged:
            backup = path.with_name(path.name + f".corrupto-{time.time_ns()}")
            path.replace(backup)
            line("BUSCAR_DIARIO", estado="recuperado", motivo="diario_corrupto", copia=backup)
        if damaged or (raw and not raw.endswith(b"\n")):
            # Sólo buscar escribe este diario bajo locked_refresh. Los ingresos
            # manuales no lo abren ni lo reparan mientras corre la cadena.
            repaired = path.with_suffix(".recuperado.tmp")
            with repaired.open("w", encoding="utf-8") as handle:
                for record in good:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            repaired.replace(path)
        return good

    def _index(self, record, historical=False):
        stage, identity, result = record["stage"], record["id"], record["result"]
        if not historical:
            self.counts[(stage, result)] += 1
        if stage in ("ml", "amazon") and result == "con_pares":
            pairs = record.get("pairs", []) if stage == "ml" else [record.get("product", {})]
            missing = {p["asin"] for p in pairs if p.get("asin") not in self.index["match"]}
            if missing:
                key = (stage, identity)
                if key in self.parents:
                    for asin in self.parents[key][1]:
                        self.waiting[asin].discard(key)
                self.parents[key] = (record, missing)
                for asin in missing:
                    self.waiting[asin].add(key)
                return
        if stage not in OUTCOMES or result in OUTCOMES[stage]:
            self.index[stage][identity] = record
            if stage == "ficha_ml":
                self.data[stage][identity] = record["product"]
            if stage == "match":
                for key in self.waiting.pop(identity, ()):
                    parent, missing = self.parents[key]
                    missing.discard(identity)
                    if not missing:
                        self.index[key[0]][key[1]] = parent
                        del self.parents[key]
        # Un transitorio no invalida una decisión definitiva anterior.

    def resolved(self, stage):
        return self.index[stage]

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
        self._index(record)
        return record
