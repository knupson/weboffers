"""Voz en off es-AR por escena, mide duraciones y arma la pista de audio de cada Short."""
import asyncio, json, subprocess, sys
from pathlib import Path

import edge_tts

OUT = Path(sys.argv[1])
VOICE = "es-AR-TomasNeural"
END = "Hacé la cuenta con tu producto en ofertas punto knu net punto com."
GUIONES = {
    "1": [
        "¿Cuánto te sale traer algo de Amazon a Argentina? Hagamos la cuenta con la franquicia de cuatrocientos dólares.",
        "Si sale cien dólares, con el envío y el IVA te queda en unos doscientos cincuenta y seis mil pesos.",
        "Con doscientos dólares, cerca de cuatrocientos cuarenta y cinco mil.",
        "Con trescientos, unos seiscientos treinta y cinco mil.",
        "Y con cuatrocientos, el tope de la franquicia, alrededor de ochocientos veinticinco mil. Sin derechos de importación.",
        END,
    ],
    "2": [
        "¿Qué pasa si te pasás de los cuatrocientos dólares?",
        "Supongamos un producto de quinientos dólares, más cuarenta de envío. Te pasás por cien.",
        "Sólo esos cien pagan derechos y tasa de estadística. Después se suma el IVA: en total, seiscientos noventa y nueve dólares.",
        "Puesto en tu casa, al dólar MEP, más o menos un millón noventa y cinco mil pesos.",
        END,
    ],
    "3": [
        "¿Conviene comprar en Amazon España desde Argentina?",
        "Uno: cobra en euros. Lo pasamos a dólares con el euro y el dólar oficial.",
        "Dos: trae equipos de doscientos veinte voltios, ideales para cafeteras y freidoras.",
        "Tres: viene con enchufe europeo, así que necesitás un adaptador.",
        "Y la franquicia es la misma: hasta cuatrocientos dólares sin derechos.",
        END,
    ],
    "reel-1": [
        "¿Amazon o Mercado Libre? Depende del producto. Mirá estos dos.",
        "Los Skullcandy Crusher: en Mercado Libre, ochocientos sesenta y nueve mil. Traídos de Amazon, unos trescientos cincuenta mil. Gana Amazon.",
        "El joystick GameSir: noventa y siete mil en Mercado Libre, y ciento setenta mil de Amazon. Gana Mercado Libre: el envío se come la diferencia.",
        "Debajo de cien dólares, casi siempre conviene Mercado Libre. Arriba, vale la pena comparar.",
        "Comparamos noventa y siete productos con los precios de hoy. Link en la bio.",
    ],
}
SOLO = sys.argv[2:]  # versiones a generar (vacío = todas)
PAUSA = 0.6  # segundos de aire después de cada frase


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)]))


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = {}
    for v, frases in GUIONES.items():
        if SOLO and v not in SOLO:
            continue
        ms, parts = [], []
        for i, texto in enumerate(frases):
            mp3 = OUT / f"v{v}-{i}.mp3"
            await edge_tts.Communicate(texto, VOICE, rate="+6%").save(str(mp3))
            d = dur(mp3) + PAUSA
            ms.append(round(d * 1000))
            wav = OUT / f"v{v}-{i}.wav"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3), "-af", f"apad=whole_dur={d}", "-ar", "44100", "-ac", "2", str(wav)], check=True)
            parts.append(wav)
        lista = OUT / f"v{v}.txt"
        lista.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c:a", "pcm_s16le", str(OUT / f"voz-{v}.wav")], check=True)
        plan[v] = ms
    (OUT / "duraciones.json").write_text(json.dumps(plan), encoding="utf-8")
    print(json.dumps(plan))


asyncio.run(main())
