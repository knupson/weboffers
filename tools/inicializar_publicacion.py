#!/usr/bin/env python3
"""Inicializa la publicación con desgloses históricos concatenados por stdin."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import re
import sys
from zlib import crc32

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
import alta_state
import publicacion


def log(mensaje):
    print(f"{datetime.now(publicacion.ART):%Y-%m-%d %H:%M:%S} {mensaje}", flush=True)


def inicializar(texto, output, today=None, forzar=False):
    output = Path(output)
    hoy = date.fromisoformat(today) if today else datetime.now(publicacion.ART).date()

    def operation():
        if (output / "publicacion.json").exists() and not forzar:
            raise ValueError("publicacion.json ya existe; usá --forzar para reemplazarlo")
        bloques = []
        actual = None
        for linea in texto.splitlines():
            if linea.startswith("### "):
                match = re.search(r"desglose-(\d{4}-\d{2}-\d{2})-(\d{4})\.log$", linea.strip())
                if match is None:
                    raise ValueError("Cabecera de desglose inválida")
                fecha, hora = match.groups()
                datetime.strptime(fecha + hora, "%Y-%m-%d%H%M")
                actual = []
                bloques.append((fecha, hora, actual))
            elif actual is not None:
                actual.append(linea)
        if not bloques:
            raise ValueError("No hay bloques de desglose")
        bloques_ordenados = sorted(bloques, key=lambda b: b[:2])
        ultimos = publicacion.parse_desglose("\n".join(bloques_ordenados[-1][2]))
        publicados = {}
        for fecha, _, lineas in bloques_ordenados:
            for slug, datos in publicacion.parse_desglose("\n".join(lineas)).items():
                if datos[0] == "PUBLICADO":
                    publicados[slug] = date.fromisoformat(fecha)
        if not ultimos:
            raise ValueError("Los desgloses no tienen líneas PRODUCTO válidas")
        estado = {}
        for slug, (resultado, motivo, asin) in ultimos.items():
            desde = hoy
            hasta = None
            intentos = 0
            ultimo_intento = None
            if resultado == "PUBLICADO":
                situacion = "publicado"
                motivo = ""
            elif slug in publicados:
                desde = publicados[slug] + timedelta(days=1)
                intentos = max(0, (hoy - desde).days)
                if intentos >= publicacion.REPUBLICACION_INTENTOS:
                    situacion = "no_revisar"
                    desde = hoy
                    hasta = hoy + timedelta(days=publicacion.NO_REVISAR_DIAS)
                else:
                    situacion = "republicacion"
                ultimo_intento = hoy.isoformat() if intentos else None
            else:
                situacion = "no_revisar"
                hasta = hoy + timedelta(days=crc32(asin.encode("utf-8")) % 7 + 1)
            estado[slug] = {
                "situacion": situacion, "desde": desde.isoformat(),
                "hasta": hasta.isoformat() if hasta else None,
                "intentos": intentos, "ultimoIntento": ultimo_intento,
                "motivo": motivo, "asin": asin,
            }
        publicacion.guardar(output, estado)
        cuentas = Counter(item["situacion"] for item in estado.values())
        log(f"PUBLICACION_INICIAL publicados={cuentas['publicado']} "
            f"republicacion={cuentas['republicacion']} no_revisar={cuentas['no_revisar']}")
        return estado

    return alta_state.update_state([], output / "altas.json", operation)


def main():
    import worker

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hoy", type=date.fromisoformat)
    parser.add_argument("--forzar", action="store_true")
    args = parser.parse_args()
    output = worker.resolve_path(os.environ.get("OUTPUT_PATH", "output/offers.json")).parent
    try:
        inicializar(sys.stdin.read(), output,
                    args.hoy.isoformat() if args.hoy else None, args.forzar)
    except (OSError, ValueError) as error:
        log(f"PUBLICACION_ERROR {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
