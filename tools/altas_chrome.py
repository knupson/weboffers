"""Lista ASIN para Chrome y fusiona su relevamiento sin pisar los otros productos."""
import argparse
import io
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alta_state import read_json, update_state
from article_log import chrome_line
from catalog import load_catalog
from requisitos import motivo_total, modo_actual, resumen_etapa
import publicacion
from publish import write_atomic
from tools.confirmar_altas import chrome_today


def hora():
    """Hora ART para las líneas que salen por stderr sin DailyLog (regla 5 de AGENTS.md)."""
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=-3))).strftime("%Y-%m-%d %H:%M:%S")


def asin_list(catalog_path, output, pending_only=False):
    output = Path(output)
    pending = read_json(output / "altas-pendientes.json", [])
    estado = publicacion.cargar(output)
    today = hora()[:10]
    modo = modo_actual()
    catalog = load_catalog(catalog_path, output / "catalog-auto.json")
    if pending_only:
        catalog = [p for p in catalog if modo == "alta"
                   and (item := estado.get(p["slug"]))
                   and item["situacion"] == "no_revisar" and item["hasta"] <= today]
    slugs = {}
    salteos = {}
    otra_tienda = 0
    relevados = relevados_hoy(output, today)
    for entry in catalog + pending:
        if entry.get("store") != "US":
            # Chrome sólo releva Amazon US; España sigue a Amazon y ML sin pasar por acá (no es un salteo).
            otra_tienda += 1
            continue
        # 08/11: requisitos del catálogo (worker/requisitos.py), los mismos que exige el deploy.
        motivo = motivo_total(entry, estado, today, modo, stores=("US",))
        if motivo:
            salteos[entry.get("slug")] = motivo
            print(f"{hora()} CHROME_SALTEO slug={entry.get('slug')} asin={entry.get('asin')} motivo={motivo}",
                  file=sys.stderr, flush=True)
            continue
        if entry["asin"] in relevados:
            # F-06: un reintento del mismo día retoma donde quedó; lo que Chrome ya leyó hoy no se vuelve a pedir.
            salteos[entry.get("slug")] = "ya_relevado_hoy"
            print(f"{hora()} CHROME_SALTEO slug={entry.get('slug')} asin={entry.get('asin')} motivo=ya_relevado_hoy",
                  file=sys.stderr, flush=True)
            continue
        names = slugs.setdefault(entry["asin"], [])
        if entry["slug"] not in names:
            names.append(entry["slug"])
    print(f"{hora()} " + resumen_etapa("chrome", len(catalog + pending) - otra_tienda, salteos, a_relevar=len(slugs),
                                        otra_tienda_no_pasa_por_chrome=otra_tienda), file=sys.stderr, flush=True)
    return " ".join(asin + ":" + ",".join(names) for asin, names in slugs.items())


def relevados_hoy(output, today):
    """ASIN con evidencia literal de hoy (ships booleano) en ar-chrome-AAAA-MM-DD.json.

    Los que quedaron sin dato (captcha, página sin producto, error) se vuelven a pedir. CHROME_REHACER=1 relee todo."""
    if os.environ.get("CHROME_REHACER") == "1":
        return set()
    try:
        data = chrome_today(read_json(Path(output) / f"ar-chrome-{today}.json", {}), today)
    except (ValueError, TypeError):
        return set()
    return {asin for asin, item in data["items"].items()
            if isinstance(item, dict) and isinstance(item.get("ships"), bool)}


def snapshot_desde_parcial(texto):
    """Reconstruye el relevamiento desde el JSONL que envio_ar_chrome.py anota ASIN por ASIN.

    Ignora líneas truncadas (el KILL puede cortar la última). `generado` es la hora del último ASIN leído."""
    items, generado = {}, None
    for linea in texto.splitlines():
        try:
            registro = json.loads(linea)
        except ValueError:
            continue
        if not isinstance(registro, dict) or not registro.get("asin") or not isinstance(registro.get("item"), dict):
            continue
        items[registro["asin"]] = registro["item"]
        generado = registro.get("t") or generado
    return {"generado": generado, "items": items}


def merge_chrome(output, today, incoming):
    """Fusiona sólo la evidencia recibida; conserva los demás ASIN y metadatos."""
    output = Path(output)
    chrome_today(incoming, today)

    def merge():
        path = output / f"ar-chrome-{today}.json"
        previous = read_json(path, None)
        if previous is not None:
            chrome_today(previous, today)
        merged = {**(previous or {}), **incoming,
                  "items": {**((previous or {}).get("items") or {}), **incoming["items"]}}
        write_atomic(path, merged)
        return merged

    return update_state([], output / "ar-chrome.json", merge)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("accion", choices=("listar", "guardar"))
    parser.add_argument("--pendientes", action="store_true")
    parser.add_argument("--fecha")
    parser.add_argument("--jsonl", action="store_true",
                        help="stdin es el parcial JSONL de un relevamiento cortado, no el JSON final")
    args = parser.parse_args()
    output = Path("/app/output")
    if args.accion == "listar":
        print(asin_list("/app/data/catalog.json", output, args.pendientes))
    else:
        from worker import DailyLog
        if args.jsonl:
            data = snapshot_desde_parcial(sys.stdin.read())
            if not data["items"]:
                print("ENVIO_AR_CHROME_PARCIAL sin ASIN leídos; nada que guardar", flush=True)
                return
            print(f"ENVIO_AR_CHROME_PARCIAL se guardan {len(data['items'])} ASIN leídos antes del corte", flush=True)
        else:
            data = json.load(sys.stdin)
        # La fecha del archivo sale de cuándo terminó Chrome (ART), no de cuándo arrancó: una corrida que cruza la
        # medianoche no pierde el relevamiento (06/11, revisión). --fecha queda sólo como respaldo.
        from datetime import datetime
        from tools.confirmar_altas import ART
        fecha = datetime.fromisoformat(data["generado"]).astimezone(ART).date().isoformat() if data.get("generado") else args.fecha
        if fecha != args.fecha:
            print(f"ENVIO_AR_CHROME_AVISO el relevamiento terminó el {fecha} (arrancó el {args.fecha}); se guarda como {fecha}.", flush=True)
        merge_chrome(output, fecha, data)
        log = DailyLog(output / "logs", io.StringIO())
        entries = load_catalog("/app/data/catalog.json", output / "catalog-auto.json")
        entries += read_json(output / "altas-pendientes.json", [])
        for asin, item in data["items"].items():
            slugs = [p["slug"] for p in entries if p.get("asin") == asin]
            log.write(chrome_line(slugs, asin, item) + "\n")
        items = list(data["items"].values())
        print(f"ENVIO_AR_CHROME_OK productos={len(items)} segundos={data.get('segundos')} "
              f"envia={sum(x.get('ships') is True for x in items)} "
              f"gratis={sum(x.get('free') is True for x in items)} "
              f"no_envia={sum(x.get('ships') is False for x in items)} "
              f"sin_dato={sum(x.get('ships') is None for x in items)}", flush=True)


if __name__ == "__main__":
    main()
