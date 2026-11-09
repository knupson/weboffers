#!/usr/bin/env python3
"""Actualiza la situación de cada producto con el desglose del deploy."""
import argparse
from collections import Counter
from datetime import datetime
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
import alta_state
import publicacion


def log(mensaje):
    print(f"{datetime.now(publicacion.ART):%Y-%m-%d %H:%M:%S} {mensaje}", flush=True)


def actualizar(texto, output, today=None):
    """Lee y guarda bajo el mismo lock que la confirmación de altas."""
    desglose = publicacion.parse_desglose(texto)
    if not desglose:
        raise ValueError("El desglose no tiene ninguna línea PRODUCTO válida; el estado queda igual.")
    output = Path(output)
    today = today or datetime.now(publicacion.ART).date().isoformat()

    def operation():
        estado = publicacion.cargar(output)
        nuevo, cuentas = publicacion.transicion(estado, desglose, today)
        publicacion.guardar(output, nuevo)
        motivos = Counter()
        for slug, item in nuevo.items():
            previo = estado.get(slug)
            if previo == item:
                continue
            antes = previo["situacion"] if previo else "ausente"
            despues = item["situacion"]
            log(f"PUBLICACION_CAMBIO {slug} {antes}->{despues} motivo={item['motivo']}")
            if antes == "publicado" and despues == "republicacion":
                motivos[item["motivo"]] += 1
        if cuentas["salieron"] > publicacion.ALERTA_SALIDAS:
            detalle = ",".join(f"{motivo}:{cantidad}" for motivo, cantidad in sorted(motivos.items()))
            log(f"PUBLICACION_ALERTA salieron={cuentas['salieron']} motivos={detalle}")
        totales = Counter(item["situacion"] for item in nuevo.values())
        log(f"PUBLICACION_OK publicados={totales['publicado']} "
            f"republicacion={totales['republicacion']} no_revisar={totales['no_revisar']} "
            f"salieron={cuentas['salieron']} republicados={cuentas['republicados']}")
        return nuevo, cuentas

    return alta_state.update_state([], output / "altas.json", operation)


def main():
    import worker

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--desglose", required=True, help="Archivo de desglose o - para leer stdin")
    args = parser.parse_args()
    output = worker.resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent
    sys.stdout = worker.DailyLog(output / "logs", sys.stdout)
    sys.stderr = worker.DailyLog(output / "logs", sys.stderr)
    try:
        texto = sys.stdin.read() if args.desglose == "-" else Path(args.desglose).read_text(encoding="utf-8")
        actualizar(texto, output)
    except (OSError, ValueError) as error:
        log(f"PUBLICACION_ERROR {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
