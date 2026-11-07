"""Lectura local de telemetría; ejecutar dentro del mismo contenedor para consultar PID."""
import argparse
from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path

from .events import now_art


def read_events(path, since=None):
    with Path(path).open(encoding='utf-8') as stream:
        for number, line in enumerate(stream, 1):
            try:
                stamp, event, payload = line.split(' ', 2)
                timestamp = datetime.fromisoformat(stamp)
                body = json.loads(payload)
            except (ValueError, TypeError):
                yield dict(linea=number, evento='LOG_INCOMPLETO', literal=line.rstrip())
                continue
            if since and timestamp.strftime('%H:%M') < since:
                continue
            yield dict(hora=stamp, evento=event, datos=body, linea=number)


def process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def summarize(events, *, now=None, alive=process_alive):
    now = now or now_art()
    stages, errors, malformed = [], [], []
    requests, waits, discards = Counter(), Counter(), Counter()
    heartbeat = None
    heartbeats = {}
    runs = {}
    for event in events:
        name, body = event['evento'], event.get('datos', {})
        run_id = body.get('run_id')
        if name == 'LOG_INCOMPLETO':
            malformed.append(event)
            continue
        if name == 'BARRIDO_PROCESO_INICIO':
            runs[run_id] = dict(inicio=event['hora'], pid=body.get('pid'), finalizado=False)
        if name == 'BARRIDO_PROCESO_FIN':
            runs.setdefault(run_id, {})['finalizado'] = True
        if name in ('BARRIDO_ETAPA_INICIO', 'BARRIDO_ETAPA_FIN'):
            stages.append(dict(hora=event['hora'], evento=name, **body))
        if name == 'BARRIDO_HTTP_INICIO':
            requests[event['hora'][:16]] += 1
        if name == 'BARRIDO_ESPERA':
            waits[body['motivo']] += body['segundos']
        if name == 'BARRIDO_DESCARTE':
            discards[body['motivo']] += 1
        if ('ERROR' in name or 'BLOQUEADO' in name or name in ('BARRIDO_EXCEPCION', 'BARRIDO_CORTADO', 'BARRIDO_SIN_AVANCE')
                or name == 'BARRIDO_HTTP_FIN' and (body.get('bloqueo') or body.get('error') or (body.get('status') or 0) >= 400)):
            errors.append(event)
        if name == 'BARRIDO_LATIDO':
            heartbeat = dict(hora=event['hora'], **body)
            heartbeats[run_id] = heartbeat
    # El servidor ocioso puede seguir latiendo mientras otro PID adquiere datos.
    monitored = [b for b in heartbeats.values() if b.get('observando_avance', True)]
    active = [b for b in monitored if not runs.get(b.get('run_id'), {}).get('finalizado')]
    if active or monitored:
        heartbeat = max(active or monitored, key=lambda b: b['hora'])
    state = 'sin_latido'
    if heartbeat:
        age = max(0, (now - datetime.fromisoformat(heartbeat['hora'])).total_seconds())
        ended = runs.get(heartbeat.get('run_id'), {}).get('finalizado')
        living = alive(heartbeat['pid']) if not ended else False
        # Un PID puede reutilizarse después de un reinicio; el latido reciente es necesario.
        stalled = heartbeat.get('observando_avance', True) and heartbeat['segundos_sin_avance'] >= heartbeat.get('stall_seconds', 300)
        state = ('finalizado' if ended else 'no_vive' if living is False else
                 'latido_vencido_identidad_no_confirmada' if age > 120 else
                 'sin_permiso_para_verificar_pid' if living is None else
                 'vivo_sin_avance' if stalled else 'vivo')
    return dict(etapas=stages, pedidos_por_minuto=dict(requests), esperas_segundos_por_motivo=dict(waits),
                descartes_por_motivo=dict(discards), errores_y_bloqueos=errors,
                ultimo_latido=heartbeat, estado=state, corridas=runs, lineas_incompletas=malformed)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Resumen del log del barrido (hora ART)')
    parser.add_argument('--fecha', default=now_art().date().isoformat())
    parser.add_argument('--desde', help='Hora ART HH:MM, inclusive')
    parser.add_argument('--output', default=os.environ.get('BARRIDO_OUTPUT', '/app/output/barrido'))
    args = parser.parse_args(argv)
    try:
        datetime.strptime(args.fecha, '%Y-%m-%d')
        if args.desde:
            datetime.strptime(args.desde, '%H:%M')
            if len(args.desde) != 5:
                raise ValueError('Usá HH:MM')
        path = Path(args.output).parent / 'logs' / f'barrido-{args.fecha}.log'
        result = summarize(read_events(path, args.desde))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'No se pudo leer el log: {exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
