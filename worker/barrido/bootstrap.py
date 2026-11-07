"""Carga única del paquete vendor sin mezclar otra instalación de amazon/config."""
import importlib
from pathlib import Path
import sys

VENDOR = Path(__file__).with_name("vendor").resolve()


def load_vendor():
    for name in ("amazon", "config", "scraper_errors", "schema_fields"):
        module = sys.modules.get(name)
        if module is not None and not Path(module.__file__).resolve().is_relative_to(VENDOR):
            raise RuntimeError(f"Importación incompatible: {name} desde {module.__file__}")
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    return importlib.import_module("amazon")


def configure_transport(observer=None):
    load_vendor()
    from amazon import fetch
    import config
    from amazon_shipping import apply_ar_location
    # Salida a Amazon: BARRIDO_AMAZON_PROXY (p. ej. socks5h://warp:1080, WARP de Cloudflare)
    # o directa por la IP de la VM. Medido 07/11: la IP de la VM recibe 503 en /s; por WARP pasa.
    import os
    proxy = os.environ.get("BARRIDO_AMAZON_PROXY") or None
    config.AMAZON_PROXY = proxy
    config.AMAZON_PROXY_COUNTRY = "any" if proxy else None
    config.AMAZON_EGRESS = "direct"
    fetch.RETRIES = 0
    # Por WARP el bloqueo es por sesión (07/11: de 3 pedidos, uno pasó al 1.º, otro al 2.º y otro
    # falló las 4 sesiones): hasta 4 sesiones nuevas por pedido, como el original. Directa: 1.
    fetch.BLOCK_RETRIES = 4 if proxy else 1
    fetch.OBSERVER = observer
    apply_ar_location()
    original = fetch.set_location
    def set_ar_once(sess, postal_code=None):
        from .events import emit_event
        if getattr(sess, 'ar_tried', False) or getattr(sess, 'located', None) == 'AR':
            emit_event('BARRIDO_UBICACION_OMITIDA', motivo='ya_intentada_o_confirmada',
                       sesion=getattr(sess, 'observation_id', None))
            return False
        if not sess.glow_token:
            emit_event('BARRIDO_UBICACION_OMITIDA', motivo='sin_token_glow',
                       sesion=getattr(sess, 'observation_id', None))
            return False
        sess.ar_tried = True
        emit_event('BARRIDO_UBICACION_INICIO', motivo='confirmar_destino_AR',
                   sesion=getattr(sess, 'observation_id', None), ubicacion_ar=False)
        try:
            confirmed = original(sess, postal_code)
            emit_event('BARRIDO_UBICACION_FIN', motivo='respuesta_cambio_destino', confirmado=confirmed,
                       sesion=getattr(sess, 'observation_id', None), ubicacion_ar=getattr(sess, 'located', None) == 'AR')
            if not confirmed:
                from .events import emit_event
                emit_event('BARRIDO_UBICACION_FALLIDA', motivo='Amazon no confirmó la ubicación AR')
            return confirmed
        except Exception as exc:
            emit_event('BARRIDO_UBICACION_FIN', motivo=str(exc), confirmado=False,
                       sesion=getattr(sess, 'observation_id', None), ubicacion_ar=False)
            from .events import emit_event
            emit_event('BARRIDO_UBICACION_FALLIDA', motivo=str(exc), tipo=type(exc).__name__)
            return False
    fetch.set_location = set_ar_once
    return fetch
