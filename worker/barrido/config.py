"""Configuración validada antes de adquirir datos."""
from dataclasses import dataclass
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class Config:
    min_usd: float = 100
    max_usd: float = 400
    pause: float = 5
    ml_pause: float = .3
    backoff: float = 30
    backoff_cap: float = 120
    consecutive_blocks: int = 3
    variation_limit: int = 20
    transient_retries: int = 3
    max_run_hours: float = 8
    unlocated_page_ratio: float = .5

    def __post_init__(self):
        for key, value in vars(self).items():
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Configuración inválida: {key}={value}")
        if not 0 < self.min_usd <= self.max_usd or self.consecutive_blocks < 1:
            raise ValueError("Rango o cantidad de bloqueos inválidos")
        if self.unlocated_page_ratio > 1 or self.max_run_hours <= 0 or self.transient_retries < 1 or int(self.transient_retries) != self.transient_retries:
            raise ValueError("Umbral, duración o reintentos inválidos")
        if int(self.consecutive_blocks) != self.consecutive_blocks or int(self.variation_limit) != self.variation_limit:
            raise ValueError("Bloqueos y variantes deben ser enteros")


def validate_categories(body):
    if body.get("version") != 1 or not isinstance(body.get("stores"), dict):
        raise ValueError("Categorías: se requiere version=1 y stores")
    for store, definition in body["stores"].items():
        if store not in ("US", "ES"):
            raise ValueError(f"Tienda inválida: {store}")
        seen = set()
        for node in definition["nodes"]:
            if not isinstance(node.get("id"), str) or not node["id"].isalnum() or not node.get("name") or node.get("kind") not in ("root", "leaf"):
                raise ValueError(f"Nodo inválido: {node}")
            if node["id"] in seen:
                raise ValueError(f"Nodo duplicado: {node['id']}")
            seen.add(node["id"])
        if not isinstance(definition.get("exclude", []), list):
            raise ValueError("exclude debe ser lista")
    return body


def load_config(path=None):
    return validate_categories(json.loads(Path(path or Path(__file__).with_name("categorias.json")).read_text(encoding="utf-8")))
