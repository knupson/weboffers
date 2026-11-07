"""Eventos estructurados con hora ART en cada línea."""
from datetime import datetime, timedelta, timezone
import json

ART = timezone(timedelta(hours=-3))


def now_art():
    return datetime.now(ART)


def emit_event(event, **fields):
    print(f"{now_art().isoformat()} {event} " + json.dumps(fields, ensure_ascii=False, default=str), flush=True)
