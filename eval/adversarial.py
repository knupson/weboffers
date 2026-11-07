"""Banco adversarial independiente, sin red y con la semántica de eval/h.py.

Uso: python -I -X utf8 eval/adversarial.py. Los tests consumen este mismo banco.
Los casos sintéticos prueban reglas de identidad, no la existencia comercial.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "worker"), str(ROOT)]


def case(label, title, name, model, brand, category, accept=False, expected_status=None, **attrs):
    return dict(label=label, title=title, name=name, brand=brand, category=category,
                accept=accept, expected_status=expected_status,
                attrs={"BRAND": brand, "MODEL": model, **attrs})


REPORTED_CASES = [
    case("reportado-core-stinger", "HyperX Cloud Stinger 2 Core Gaming Headset",
         "HyperX Cloud Stinger 2 Gaming Headset", "Cloud Stinger 2", "HyperX", "Headphones", expected_status="doubtful"),
    case("reportado-buds-core", "Samsung Galaxy Buds Core", "Samsung Galaxy Buds",
         "Galaxy Buds", "Samsung", "Headphones", expected_status="doubtful"),
    case("reportado-pack-camaras", "Blink Outdoor 4 camera 2-camera system", "Blink Outdoor 4 camera",
         "Outdoor 4", "Blink", "Cameras", expected_status="doubtful"),
    case("reportado-tipo-pebble", "Logitech Pebble Keyboard", "Logitech Pebble Mouse",
         "Pebble", "Logitech", "Components", expected_status="rejected"),
    case("reportado-ram-a16", "Galaxy A16 5G 4+128GB", "Galaxy A16 5G 128GB",
         "Galaxy A16", "Samsung", "Cell Phones", expected_status="doubtful"),
]


def build_cases():
    rows = []
    # Doce ediciones; un MPN compartido tampoco puede tapar la edición omitida.
    for edition in "core lite se fe neo go mini max pro plus ultra air".split():
        base = "Acme Orbit Q700"
        rows.append(case(f"edicion-{edition}-omitida", f"{base} {edition} Headset", f"{base} Headset",
                         "Q700", "Acme", "Headphones", ALPHANUMERIC_MODEL="Q700"))
        rows.append(case(f"edicion-{edition}-igual", f"{base} {edition} Headset Black",
                         f"Acme Auriculares Orbit Q700 {edition} Negro", "Q700", "Acme", "Headphones", True))
    # Cantidades antes/después del sustantivo, en ambos idiomas y sin «pack».
    packs = ["2-camera system", "2-pack", "pack x2", "kit de 2", "3 cámaras",
             "set of 2", "twin pack", "dúo", "pack de 2 unidades", "2 units"]
    for i, pack in enumerate(packs):
        n = 3 if pack == "3 cámaras" else 2
        rows.append(case(f"pack-{i}-omitido", f"Acme Vista C700 camera {pack}", "Acme Vista C700 camera",
                         "C700", "Acme", "Cameras"))
        rows.append(case(f"pack-{i}-igual", f"Acme Vista C700 camera {pack}",
                         f"Acme Vista C700 cámara paquete de {n}", "C700", "Acme", "Cameras", True))
    types = [("Keyboard", "Teclado", "Mouse", "Components"),
             ("Mouse", "Ratón", "Keyboard", "Components"),
             ("Headset", "Auriculares", "Earbuds", "Headphones"),
             ("Speaker", "Parlante", "Headset", "Speakers"),
             ("Webcam", "Cámara web", "Monitor", "Cameras"),
             ("Router", "Router", "Tablet", "Networking"),
             ("Phone", "Celular", "Tablet", "Cell Phones"),
             ("Watch", "Reloj", "Charger", "Smartwatches"),
             ("Case", "Funda", "Cable", "Components"),
             ("Controller", "Joystick", "Stand", "Gaming")]
    for i, (english, spanish, other, category) in enumerate(types):
        rows.append(case(f"tipo-{i}-distinto", f"Acme Orbit Q700 {english}", f"Acme Orbit Q700 {other}",
                         "Q700", "Acme", category))
        rows.append(case(f"tipo-{i}-traducido", f"Acme Orbit Q700 {english}", f"Acme Orbit Q700 {spanish}",
                         "Q700", "Acme", category, True))
    for i, category in enumerate(["Cell Phones", "Tablets"]):
        rows.extend([
            case(f"ram-{i}-omitida-ml", "Acme Orbit Q700 8+128GB", "Acme Orbit Q700 128GB",
                 "Q700", "Acme", category),
            case(f"ram-{i}-omitida-amazon", "Acme Orbit Q700 128GB", "Acme Orbit Q700 8GB RAM 128GB",
                 "Q700", "Acme", category),
            case(f"ram-{i}-atributo", "Acme Orbit Q700 8+128GB", "Acme Orbit Q700 128GB",
                 "Q700", "Acme", category, True, RAM_MEMORY="8 GB"),
            case(f"ram-{i}-texto", "Acme Orbit Q700 8+128GB", "Acme Orbit Q700 RAM 8GB 128GB",
                 "Q700", "Acme", category, True),
        ])
    rows.extend([
        case("disco-distinto", "Acme Orbit Q700 SSD 1TB", "Acme Orbit Q700 SSD 2TB", "Q700", "Acme", "Data Storage"),
        case("disco-omitido", "Acme Orbit Q700 SSD 1TB", "Acme Orbit Q700 SSD", "Q700", "Acme", "Data Storage"),
        case("disco-unidades", "Acme Orbit Q700 SSD 1TB", "Acme Orbit Q700 SSD 1000GB", "Q700", "Acme", "Data Storage", True),
        case("disco-region-color", "Acme Orbit Q700 SSD 1TB International Version Black",
             "Acme Orbit Q700 SSD 1000GB Negro", "Q700", "Acme", "Data Storage", True),
        case("generacion-distinta", "Acme Orbit Q700 Speaker 2nd Gen", "Acme Orbit Q700 Parlante 3ra generación",
             "Q700", "Acme", "Speakers"),
        case("generacion-omitida", "Acme Orbit Q700 Speaker 2nd Gen", "Acme Orbit Q700 Parlante",
             "Q700", "Acme", "Speakers"),
        case("generacion-traducida", "Acme Orbit Q700 Speaker 2nd Gen", "Acme Orbit Q700 Parlante generación 2",
             "Q700", "Acme", "Speakers", True),
        case("region-color", "Acme Orbit Q700 Speaker International Version White", "Acme Orbit Q700 Parlante Negro",
             "Q700", "Acme", "Speakers", True),
        case("pack-cantidades-distintas", "Acme C700 Camera 2-pack", "Acme C700 cámara pack x3", "C700", "Acme", "Cameras"),
        case("pack-inverso", "Acme C700 Camera pack x3", "Acme C700 cámara 2-pack", "C700", "Acme", "Cameras"),
        case("pack-ambiguo", "Acme C700 camera 2-pack pack x3", "Acme C700 cámara 2-pack pack x3", "C700", "Acme", "Cameras"),
        case("pack-unidad-omitida", "Acme C700 Camera 1-pack", "Acme C700 cámara", "C700", "Acme", "Cameras"),
        case("tipo-webcam-camara", "Acme C700 Webcam", "Acme C700 cámara", "C700", "Acme", "Cameras"),
        case("tipo-soporte-cargador", "Acme C700 Stand", "Acme C700 cargador", "C700", "Acme", "Components"),
        case("ram-atributo-distinto", "Acme Q700 8+128GB", "Acme Q700 128GB", "Q700", "Acme", "Tablets", RAM_MEMORY="4 GB"),
        case("ram-atributo-contradictorio", "Acme Q700 8+128GB", "Acme Q700 8GB RAM 128GB", "Q700", "Acme", "Cell Phones", RAM="4 GB"),
        case("disco-oculto-por-ram", "Acme Q700 8GB RAM 128GB", "Acme Q700 8GB RAM", "Q700", "Acme", "Tablets"),
        case("generacion-romana-distinta", "Acme Orbit II Headset", "Acme Orbit III Auriculares", "Orbit", "Acme", "Headphones"),
        case("pack-unidad-igual", "Acme C700 Camera 1-pack", "Acme C700 cámara kit de 1", "C700", "Acme", "Cameras", True),
        case("pack-repetido-coherente", "Acme C700 camera 2-pack pack x2", "Acme C700 cámara dúo", "C700", "Acme", "Cameras", True),
        case("camara-funcion-webcam", "Acme C700 Action Camera, Webcam, Voice Control", "Acme C700 cámara de acción", "C700", "Acme", "Cameras", True),
        case("tablet-componentes", "Acme Q700 4 Speakers 128GB", "Acme Q700 Tablet 128GB", "Q700", "Acme", "Tablets", True),
        case("cpu-core-nucleos", "Acme Q700 8-Core Desktop Processor", "Acme Q700 Procesador", "Q700", "Acme", "Components", True),
        case("tablet-octa-core", "Acme Q700 Octa Core Tablet 128GB", "Acme Q700 Tablet 128GB", "Q700", "Acme", "Tablets", True),
        case("soporte-traducido", "Acme Q700 Stand", "Acme Q700 soporte", "Q700", "Acme", "Components", True),
        case("cargador-traducido", "Acme Q700 Charger", "Acme Q700 cargador", "Q700", "Acme", "Chargers", True),
        case("cable-traducido", "Acme Q700 Cable", "Acme Q700 cable", "Q700", "Acme", "Components", True),
        case("earbuds-in-ear", "Acme Q700 Earbuds", "Acme Q700 auriculares in-ear", "Q700", "Acme", "Headphones", True),
        case("pack-tras-uso", "Acme C700 Camera for indoors, 2-camera system", "Acme C700 cámara", "C700", "Acme", "Cameras"),
        case("ram-solo-atributo-ml", "Acme Q700 128GB", "Acme Q700 128GB", "Q700", "Acme", "Tablets", RAM_MEMORY="8GB"),
        case("earbuds-auriculares", "Acme Q700 Earbuds", "Acme Q700 auriculares", "Q700", "Acme", "Headphones", True),
        case("tablet-categoria-inferida", "Acme Q700 Octa Core 4 Speakers 128GB", "Acme Q700 Tablet 128GB",
             "Q700", "Acme", "Acme Q700 Octa Core 4 Speakers 128GB", True),
        case("core-tras-generacion", "Acme Q700 2 Core Headset", "Acme Q700 2 Headset", "Q700", "Acme", "Headphones"),
        case("tipo-control-parlante", "Acme Q700 Control", "Acme Q700 parlante", "Q700", "Acme", "Gaming"),
        case("cpu-core-con-espacios", "Acme Q700 8 Core Desktop Processor", "Acme Q700 Procesador", "Q700", "Acme", "Components", True),
        case("control-traducido", "Acme Q700 Controller", "Acme Q700 control", "Q700", "Acme", "Gaming", True),
        case("pack-modelo-numerico-omitido", "Blink Outdoor 4 camera", "Blink Outdoor 4 camera 2-pack", "Outdoor 4", "Blink", "Cameras"),
        case("pack-modelo-numerico-igual", "Blink Outdoor 4 camera 2-camera system", "Blink Outdoor 4 cámara kit de 2",
             "Outdoor 4", "Blink", "Cameras", True),
        case("pack-solo-atributo", "Acme Q700 Router", "Acme Q700 Router", "Q700", "Acme", "Networking",
             ALPHANUMERIC_MODEL="Q700 3-PACK"),
        case("pack-confirmado-atributo", "Acme Q700 Router 2-pack", "Acme Q700 Router", "Q700", "Acme", "Networking", True,
             ALPHANUMERIC_MODEL="Q700 2-PACK"),
    ])
    return rows


CASES = build_cases()


def evaluate_case(row, evaluate=None):
    if evaluate is None:
        from tools.match_candidates import evaluate
    amazon = {"asin": "B1", "store": "US", "amazonTitle": row["title"], "brand": row["brand"],
              "amazonCategory": row["category"], "amazonPriceUsd": 100}
    candidate = {"minPrice": 157500, "itemId": "MLA1", "name": row["name"]}
    product = {"name": row["name"], "attributes": [
        {"id": key, "value_name": value} for key, value in row["attrs"].items()]}
    return evaluate(amazon, candidate, product, 1575)


def main():
    wrong = missed = 0
    print("Caso | Esperado | Resultado | Motivo")
    print("--- | --- | --- | ---")
    for row in REPORTED_CASES + CASES:
        status, reason, _ = evaluate_case(row)
        accepted = status == "accepted"
        wrong += accepted and not row["accept"]
        missed += not accepted and row["accept"]
        print(f"{row['label']} | {'aceptar' if row['accept'] else 'no aceptar'} | {status} | {reason}")
    print(f"NUEVOS: {len(CASES)}; deben aceptar: {sum(r['accept'] for r in CASES)}; "
          f"no deben aceptar: {sum(not r['accept'] for r in CASES)}")
    print(f"ACEPTADOS ERRÓNEOS: {wrong}; MISMOS NO ACEPTADOS: {missed}")
    return bool(wrong or missed)


if __name__ == "__main__":
    sys.exit(main())
