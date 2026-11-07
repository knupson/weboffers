"""Telemetría del barrido: un evento por línea, sin cuerpos ni credenciales."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import signal
import sys
import threading
import time
import traceback
from urllib.parse import parse_qsl, urlsplit, urljoin
from uuid import uuid4

ART = timezone(timedelta(hours=-3))
_runtime = None
_lock = threading.RLock()
_context = {}
_SAFE_PARAMS = {'rh', 'fs', 'low-price', 'high-price', 'page', 'k', 'q', 'status',
                'site_id', 'offset', 'limit', 'provider', 'actionSource', 'deviceType',
                'pageType', 'storeContext', 'language', 'node'}


def now_art():
    return datetime.now(ART)


def safe_text(value):
    text = str(value)
    text = re.sub(r'(?i)(bearer\s+)[^\s"\',}]+', r'\1[OCULTO]', text)
    text = re.sub(r'(?i)((?:access_token|client_secret|authorization|amzn-r|amzn|token|password|bm-verify)["\']?\s*[:=]\s*["\']?)[^\s&"\',}]+', r'\1[OCULTO]', text)
    return re.sub(r'(https?://)[^/@\s]+:[^/@\s]+@', r'\1[OCULTO]@', text)


def clean(value):
    if isinstance(value, dict):
        return {k: ('[OCULTO]' if re.search(r'(?i)token|secret|authorization|cookie|password|^amzn', k)
                    else clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return safe_text(value) if isinstance(value, str) else value


def set_context(**fields):
    with _lock:
        _context.update(fields)


def set_action(description):
    with _lock:
        if _runtime:
            _runtime.action, _runtime.action_started = description, _runtime.clock()


def emit_event(event, **fields):
    with _lock:
        stamp = now_art()
        body = clean({**_context, **fields})
        if _runtime:
            body = {**body, 'run_id': _runtime.run_id, 'pid': os.getpid()}
            _runtime.record(event, body)
        line = f'{stamp.isoformat()} {event} ' + json.dumps(body, ensure_ascii=False, default=str)
        if _runtime:
            path = _runtime.output.parent / 'logs' / f'barrido-{stamp.date()}.log'
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open('a', encoding='utf-8') as stream:
                    stream.write(line + '\n')
                    stream.flush()
            except OSError as exc:
                print(f'{stamp.isoformat()} BARRIDO_LOG_ERROR ' + json.dumps(
                    clean(dict(path=str(path), motivo=str(exc))), ensure_ascii=False), flush=True)
        try:
            print(line, flush=True)
        except BrokenPipeError:
            pass


class Runtime:
    def __init__(self, output, config, *, clock=time.monotonic):
        self.output, self.config, self.clock = Path(output), config, clock
        self.run_id = uuid4().hex
        self.started = self.progress = clock()
        self.action = 'iniciando'
        self.action_started = clock()
        self.pending_request = None
        self.result_status = 'complete'
        self.monitor_progress = True
        self.counters = dict(requests=0, requests_amazon=0, requests_ml=0, requests_other=0, products=0, eligible=0,
                             ml_candidates=0, comparisons=0, errors=0, blocks=0, queries=0)
        self.stop = threading.Event()

    def record(self, event, body):
        if event in ('BARRIDO_LATIDO', 'BARRIDO_SIN_AVANCE') or body.get('origen') == 'latido':
            return
        self.progress = self.clock()
        if event == 'BARRIDO_HTTP_INICIO':
            self.counters['requests'] += 1
            self.counters['requests_ml' if body.get('tienda') == 'ML' else
                          'requests_amazon' if body.get('tienda') in ('US', 'ES') else 'requests_other'] += 1
        if event in ('BARRIDO_ERROR', 'BARRIDO_ML_ERROR'):
            self.counters['errors'] += 1
        if event == 'BARRIDO_HTTP_FIN' and body.get('bloqueo'):
            self.counters['blocks'] += 1
        if event == 'BARRIDO_PAGINA_CONTADORES':
            self.counters['products'] += body['productos']
            self.counters['eligible'] += body['conservados']
        if event == 'BARRIDO_ML_BUSQUEDA':
            self.counters['queries'] += 1
        if event == 'BARRIDO_ML_PRODUCTO':
            self.counters['products'] += 1
            self.counters['eligible'] += int(body.get('eligible', False))
            self.counters['ml_candidates'] += body['candidatos']

    def snapshot(self):
        with _lock:
            return dict(**_context, run_id=self.run_id, pid=os.getpid(), hora=now_art().isoformat(),
                        accion=f'{self.action} ({int(self.clock() - self.action_started)} s)',
                        pedido_actual=self.pending_request,
                        observando_avance=self.monitor_progress,
                        segundos_accion=round(self.clock() - self.action_started, 3),
                        segundos_sin_avance=round(self.clock() - self.progress, 3),
                        contadores=dict(self.counters), stall_seconds=self.config.stall_seconds)

    def heartbeat(self):
        with _lock:
            body = self.snapshot()
            if self.monitor_progress:
                self.output.mkdir(parents=True, exist_ok=True)
                temporary = self.output / f'.latido-{self.run_id}.tmp'
                temporary.write_text(json.dumps(clean(body), ensure_ascii=False), encoding='utf-8')
                os.replace(temporary, self.output / 'latido.json')
            emit_event('BARRIDO_LATIDO', **body)
            if self.monitor_progress and body['segundos_sin_avance'] >= self.config.stall_seconds:
                frame = sys._current_frames().get(threading.main_thread().ident)
                emit_event('BARRIDO_SIN_AVANCE', **body,
                           stack_principal=''.join(traceback.format_stack(frame)) if frame else 'Hilo principal no disponible')

    def loop(self):
        while not self.stop.wait(60):
            try:
                self.heartbeat()
            except Exception:
                emit_event('BARRIDO_EXCEPCION', origen='latido', traceback=traceback.format_exc())


@contextmanager
def action(description):
    runtime = _runtime
    if runtime:
        with _lock:
            previous = runtime.action, runtime.action_started
            runtime.action, runtime.action_started = description, runtime.clock()
    try:
        yield
    finally:
        if runtime:
            with _lock:
                runtime.action, runtime.action_started = previous


def wait(seconds, reason, *, sleep=time.sleep):
    until = (now_art() + timedelta(seconds=seconds)).isoformat()
    emit_event('BARRIDO_ESPERA', segundos=seconds, motivo=reason, hasta=until)
    with action(f'durmiendo {reason} {seconds} s hasta {until}'):
        sleep(seconds)
    emit_event('BARRIDO_ESPERA_FIN', motivo=reason, segundos=seconds)


def http_call(call, method, url, *, store, session_id, located=None, attempt=1,
              block_reason=None, _redirects=0, **kwargs):
    """Envuelve el transporte real; no registra headers, payloads ni HTML."""
    parsed = urlsplit(url)
    params = dict(parse_qsl(parsed.query))
    params.update(kwargs.get('params') or {})
    params = {k: v if k in _SAFE_PARAMS else '[OCULTO]' for k, v in params.items()}
    fields = dict(request_id=uuid4().hex, tienda=store, metodo=method,
                  path=parsed.path, params=params, sesion=session_id,
                  intento=_context.get('intento', attempt), intento_transporte=attempt,
                  ubicacion_ar=located, status=None, bytes=0, ms=0, bloqueo=None)
    emit_event('BARRIDO_HTTP_INICIO', **fields)
    if _runtime:
        _runtime.pending_request = fields
    started = time.monotonic()
    follow = kwargs.pop('allow_redirects', True)
    try:
        with action('esperando HTTP'):
            response = call(method, url, allow_redirects=False, **kwargs)
    except BaseException as exc:
        emit_event('BARRIDO_HTTP_FIN', **{**fields, 'ms': round((time.monotonic() - started) * 1000, 3)},
                   error=safe_text(exc), tipo=type(exc).__name__)
        if _runtime:
            _runtime.pending_request = None
        raise
    reason = block_reason(response) if block_reason else ('HTTP ' + str(response.status_code) if response.status_code in (403, 429) else None)
    emit_event('BARRIDO_HTTP_FIN', **{**fields, 'status': response.status_code,
               'bytes': len(response.content), 'ms': round((time.monotonic() - started) * 1000, 3), 'bloqueo': reason})
    if _runtime:
        _runtime.pending_request = None
    if follow and response.status_code in (301, 302, 303, 307, 308) and response.headers.get('Location'):
        if _redirects >= 30:
            raise RuntimeError('Se superaron 30 redirecciones HTTP')
        target = urljoin(url, response.headers['Location'])
        kwargs.pop('params', None)
        if response.status_code == 303 and method.upper() != 'HEAD' or response.status_code in (301, 302) and method.upper() == 'POST':
            method = 'GET'
            kwargs.pop('data', None)
            kwargs.pop('json', None)
        if urlsplit(target).netloc != parsed.netloc:
            kwargs['headers'] = {k: v for k, v in (kwargs.get('headers') or {}).items()
                                 if k.lower() not in ('authorization', 'cookie')}
        emit_event('BARRIDO_REDIRECCION', motivo='respuesta_HTTP', status=response.status_code,
                   path=urlsplit(target).path, request_id=fields['request_id'])
        return http_call(call, method, target, store=store, session_id=session_id, located=located,
                         attempt=attempt, block_reason=block_reason, _redirects=_redirects + 1, **kwargs)
    return response


def vendor_observer(**fields):
    kind = fields.pop('event')
    if kind == 'request':
        return http_call(fields.pop('call'), fields.pop('method'), fields.pop('url'),
                         store=fields.pop('country'), session_id=fields.pop('session_id'), **fields)
    if kind == 'wait':
        return wait(fields['seconds'], fields['reason'])
    emit_event(kind, **fields)


@contextmanager
def stage(name, store):
    set_context(etapa=name, tienda=store, categoria=None, pagina=None, asin=None, intento=1)
    started = time.monotonic()
    before = dict(_runtime.counters) if _runtime else {}
    emit_event('BARRIDO_ETAPA_INICIO')
    if _runtime:
        _runtime.heartbeat()
    outcome = {'status': 'complete'}
    try:
        yield outcome
    except BaseException:
        outcome['status'] = 'interrumpida'
        raise
    finally:
        metrics = {k: v - before[k] for k, v in _runtime.counters.items()} if _runtime else {}
        emit_event('BARRIDO_ETAPA_FIN', duracion=time.monotonic() - started, estado=outcome['status'], **metrics)


@contextmanager
def observe_run(output, config, args):
    global _runtime
    if _runtime:
        yield _runtime
        return
    _context.clear()
    runtime = _runtime = Runtime(output, config)
    runtime.monitor_progress = not args.get('servidor', False)
    previous_signals = {}
    old_hook = sys.excepthook
    def exception_hook(kind, value, tb):
        emit_event('BARRIDO_EXCEPCION', traceback=''.join(traceback.format_exception(kind, value, tb)))
        old_hook(kind, value, tb)
    def interrupted(signum, frame):
        emit_event('BARRIDO_CORTADO', senal=signal.Signals(signum).name, estado=runtime.snapshot())
        raise SystemExit(128 + signum)
    sys.excepthook = exception_hook
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous_signals[sig] = signal.signal(sig, interrupted)
    thread = threading.Thread(target=runtime.loop, name='barrido-latido', daemon=True)
    identity = dict(version=os.environ.get('BARRIDO_VERSION', 'observabilidad-v1'),
                    commit=os.environ.get('BARRIDO_GIT_COMMIT', 'no_disponible'),
                    config_hash=hashlib.sha256(json.dumps(vars(config), sort_keys=True).encode()).hexdigest(),
                    args=args)
    status = 'complete'
    try:
        emit_event('BARRIDO_PROCESO_INICIO', **identity, config=vars(config))
        runtime.heartbeat()
        thread.start()
        yield runtime
    except BaseException:
        status = 'interrumpida'
        emit_event('BARRIDO_EXCEPCION', traceback=traceback.format_exc())
        raise
    finally:
        runtime.stop.set()
        if thread.ident:
            thread.join(timeout=2)
        emit_event('BARRIDO_PROCESO_FIN', **identity, estado=runtime.result_status if status == 'complete' else status,
                   estado_final=runtime.snapshot())
        sys.excepthook = old_hook
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
        _runtime = None
        _context.clear()


def observed(function):
    """Cubre tanto el CLI como el ingreso HTTP y los callers directos."""
    @wraps(function)
    def wrapper(*args, **kwargs):
        bound = inspect.signature(function).bind(*args, **kwargs)
        config, output = bound.arguments['config'], bound.arguments['output']
        with observe_run(output, config, {'funcion': function.__name__, **{k: v for k, v in bound.arguments.items()
                         if k in ('stores', 'date', 'dry_run', 'limit')}}) as runtime:
            previous_monitor = runtime.monitor_progress
            runtime.monitor_progress = True
            try:
                if function.__name__ == 'run_ml_lookup':
                    with stage('ml_lookup', 'ML') as outcome:
                        result = function(*args, **kwargs)
                        outcome['status'] = result['status']
                else:
                    result = function(*args, **kwargs)
            finally:
                runtime.monitor_progress = previous_monitor
            runtime.result_status = (result['status'] if 'status' in result else
                                    'complete' if all(v['status'] in ('complete', 'skipped') for v in result.values()) else 'partial')
            return result
    return wrapper


def store_stage(function):
    @wraps(function)
    def wrapper(store, *args, **kwargs):
        with stage('amazon_' + store.lower(), store) as outcome:
            result = function(store, *args, **kwargs)
            outcome['status'] = result['status']
            return result
    return wrapper


def comparison_metrics():
    """Tarea 10 completará comparisons; sin datos no se inventa una tasa."""
    if not _runtime or not _runtime.counters['comparisons']:
        return dict(comparaciones_por_consulta=None, comparaciones_por_minuto=None)
    counters = _runtime.counters
    return dict(comparaciones_por_consulta=counters['comparisons'] / counters['queries'] if counters['queries'] else None,
                comparaciones_por_minuto=counters['comparisons'] / max((_runtime.clock() - _runtime.started) / 60, .000001))
