"""Ingreso HTTP interno para la herramienta manual existente."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from urllib.parse import parse_qs, urlparse
from .config import Config, load_config
from .events import emit_event
from .runner import run_all


def handle_probe(params):
    store = params.get("country", "US").upper()
    if store not in ("US", "ES"):
        raise ValueError("country debe ser US o ES")
    categories = load_config()
    node = params.get("node")
    if node:
        categories["stores"][store]["nodes"] = [n for n in categories["stores"][store]["nodes"] if n["id"] == node]
        if not categories["stores"][store]["nodes"]:
            raise ValueError(f"Nodo no configurado: {node}")
    config = Config(min_usd=float(params.get("min_price", 100)), max_usd=float(params.get("max_price", 400)))
    result = run_all(categories, config, os.environ.get("BARRIDO_OUTPUT", "/app/output/barrido"), stores=[store], dry_run=True)
    return {"stores": result, "dry_run": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        emit_event("BARRIDO_HTTP_SERVER", mensaje=format % args)

    def do_GET(self):
        request = urlparse(self.path)
        try:
            if request.path == "/health":
                status, payload = 200, {"status": "ok"}
            elif request.path == "/barrido/probe":
                payload = handle_probe({k: v[0] for k, v in parse_qs(request.query).items()})
                status = 200 if all(s["status"] == "complete" for s in payload["stores"].values()) else 502
            else:
                status, payload = 404, {"error": "Ruta inexistente"}
        except Exception as exc:
            emit_event("BARRIDO_ERROR", tipo=type(exc).__name__, motivo=str(exc))
            status, payload = 400, {"error": str(exc), "type": type(exc).__name__}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    emit_event("BARRIDO_SERVIDOR", puerto=8002)
    HTTPServer(("0.0.0.0", 8002), Handler).serve_forever()


if __name__ == "__main__":
    main()
