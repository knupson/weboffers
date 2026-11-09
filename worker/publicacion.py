"""Estado de publicación, republicación y exclusión temporal por producto."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import re

import publish


NO_REVISAR_DIAS = 7
REPUBLICACION_INTENTOS = 3
ALERTA_SALIDAS = 10


def _log(mensaje: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {mensaje}")


def _validar(estado: dict) -> None:
    """Rechaza archivos que no tengan la forma del estado compartido."""
    if not isinstance(estado, dict):
        raise ValueError("El estado debe ser un objeto")
    for slug, item in estado.items():
        if not isinstance(slug, str) or not isinstance(item, dict):
            raise ValueError("Entrada de publicación inválida")
        if item["situacion"] not in {"publicado", "republicacion", "no_revisar"}:
            raise ValueError("Situación de publicación inválida")
        date.fromisoformat(item["desde"])
        for campo in ("hasta", "ultimoIntento"):
            if item[campo] is not None:
                date.fromisoformat(item[campo])
        if item["situacion"] == "no_revisar" and item["hasta"] is None:
            raise ValueError("Falta el vencimiento de no revisar")
        if type(item["intentos"]) is not int or item["intentos"] < 0:
            raise ValueError("Cantidad de intentos inválida")
        if not isinstance(item["motivo"], str) or not isinstance(item["asin"], str):
            raise ValueError("Motivo o ASIN inválido")


def cargar(output: Path) -> dict:
    try:
        estado = json.loads((Path(output) / "publicacion.json").read_text(encoding="utf-8"))
        _validar(estado)
        return estado
    except (OSError, ValueError, TypeError, KeyError) as error:
        _log(f"PUBLICACION_ESTADO_INVALIDO {error}")
        return {}


def guardar(output: Path, estado: dict) -> None:
    publish.write_atomic(Path(output) / "publicacion.json", estado)


def motivo_estado(product: dict, estado: dict, today: str, modo: str) -> str | None:
    if modo not in {"verificacion", "alta"}:
        raise ValueError("Modo de publicación inválido")
    item = estado.get(product["slug"])
    if item and item["situacion"] == "no_revisar" and item["hasta"] > today:
        return "no_revisar"
    publicado = item is not None and item["situacion"] in {"publicado", "republicacion"}
    if modo == "verificacion":
        return None if publicado else "no_publicado"
    return "verificado_en_otro_proceso" if publicado else None


def parse_desglose(texto: str) -> dict[str, tuple[str, str, str]]:
    """Conserva el primer requisito fallido y el ASIN original de cada línea."""
    desglose = {}
    for linea in texto.splitlines():
        match = re.search(
            r"\bPRODUCTO (\S+) asin=(\S+) origen=\S+ (PUBLICADO|FILTRADO)\b", linea
        )
        if match is None:
            continue
        slug, asin, resultado = match.groups()
        falla = re.search(r"\b(\w+)=FALLA\(", linea[match.end():])
        motivo = falla.group(1) if resultado == "FILTRADO" and falla else ""
        desglose[slug] = (resultado, motivo, asin)
    return desglose


def _entrada(situacion: str, today: str, motivo: str, asin: str) -> dict:
    return {
        "situacion": situacion, "desde": today,
        "hasta": ((date.fromisoformat(today) + timedelta(days=NO_REVISAR_DIAS)).isoformat()
                  if situacion == "no_revisar" else None),
        "intentos": 0, "ultimoIntento": None, "motivo": motivo, "asin": asin,
    }


def transicion(
    estado: dict, desglose: dict[str, tuple[str, str, str]], today: str,
) -> tuple[dict, dict]:
    nuevo = deepcopy(estado)
    cuentas = {"salieron": 0, "republicados": 0, "a_no_revisar": 0,
               "nuevos_publicados": 0}
    for slug, (resultado, motivo, asin) in desglose.items():
        item = nuevo.get(slug)
        situacion = item["situacion"] if item else None
        if situacion == "no_revisar" and item["hasta"] > today:
            continue
        if resultado == "PUBLICADO":
            if situacion == "publicado":
                continue
            nuevo[slug] = _entrada("publicado", today, "", asin)
            cuenta = "republicados" if situacion == "republicacion" else "nuevos_publicados"
            cuentas[cuenta] += 1
        elif resultado == "FILTRADO":
            if situacion == "publicado":
                nuevo[slug] = _entrada("republicacion", today, motivo, asin)
                cuentas["salieron"] += 1
            elif situacion == "republicacion":
                if item["desde"] == today or item["ultimoIntento"] == today:
                    continue
                item["intentos"] += 1
                item["ultimoIntento"] = today
                item["motivo"] = motivo
                if item["intentos"] >= REPUBLICACION_INTENTOS:
                    nuevo[slug] = {
                        **_entrada("no_revisar", today, motivo, asin),
                        "intentos": item["intentos"], "ultimoIntento": today,
                    }
                    cuentas["a_no_revisar"] += 1
            else:
                nuevo[slug] = _entrada("no_revisar", today, motivo, asin)
                cuentas["a_no_revisar"] += 1
    if cuentas["salieron"] > ALERTA_SALIDAS:
        _log(f"PUBLICACION_ALERTA_SALIDAS salieron={cuentas['salieron']}")
    return nuevo, cuentas
