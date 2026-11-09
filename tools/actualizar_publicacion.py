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
from requisitos import modo_actual


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
        nuevo, cuentas = publicacion.transicion(estado, desglose, today, modo_actual())
        publicacion.guardar(output, nuevo)
        motivos = Counter(datos[1] for slug, datos in desglose.items()
                          if estado.get(slug, {}).get("situacion") == "publicado" and datos[0] == "FILTRADO")
        for slug, item in nuevo.items():
            previo = estado.get(slug)
            if previo == item:
                continue
            antes = previo["situacion"] if previo else "ausente"
            despues = item["situacion"]
            log(f"PUBLICACION_CAMBIO {slug} {antes}->{despues} motivo={item['motivo']}")
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
    entrada = parser.add_mutually_exclusive_group(required=True)
    entrada.add_argument("--desglose", help="Archivo de desglose o - para leer stdin")
    entrada.add_argument("--verificar-estado", action="store_true", help="Valida el estado antes de arrancar la cadena")
    args = parser.parse_args()
    output = worker.resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent
    sys.stdout = worker.DailyLog(output / "logs", sys.stdout)
    sys.stderr = worker.DailyLog(output / "logs", sys.stderr)
    try:
        if args.verificar_estado:
            publicacion.cargar(output)
            log("PUBLICACION_ESTADO_OK")
            return 0
        texto = sys.stdin.read() if args.desglose == "-" else Path(args.desglose).read_text(encoding="utf-8")
        actualizar(texto, output)
    except (OSError, ValueError) as error:
        log(f"PUBLICACION_ERROR {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
