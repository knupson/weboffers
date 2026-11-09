"""Requisitos del catálogo que se conocen antes de consultar ninguna tienda (08/11).

Alejandro: «Cada elemento que no cumpla se tiene que filtrar en el mismo momento que vemos que no cumple».
Estos datos están en el catálogo, así que se miran en la primera etapa (Chrome) y en cada etapa siguiente:
un producto que no los cumple no se consulta en ningún lado y queda una línea con el motivo.
Son los mismos controles que aplica el deploy (src/lib/data.ts, comparableChecks): verificado, asin, imagen y ML.
"""
from collections import Counter


def motivo_catalogo(product, stores=("US", "ES")):
    """Primer requisito del catálogo que falla, o None si cumple todos."""
    if product.get("verified") is not True:
        return "sin_verificar"
    if not product.get("asin"):
        return "sin_asin"
    if not (product.get("ml") or {}).get("catalogId"):
        return "sin_ml"
    if not product.get("image"):
        return "sin_imagen"
    if product.get("store") not in stores:
        return "tienda_no_admitida"
    return None


def resumen_etapa(etapa, entran, salteados, **cuentas):
    """Una línea por etapa: cuántos entraron, cuántos se saltearon y por qué, y qué pasó con el resto."""
    motivos = Counter(salteados.values()) if isinstance(salteados, dict) else Counter(salteados)
    detalle = " ".join(f"{k}={v}" for k, v in cuentas.items())
    salteo = ",".join(f"{k}:{v}" for k, v in sorted(motivos.items())) or "ninguno"
    return (f"ETAPA_RESUMEN {etapa} entran={entran} salteados={sum(motivos.values())} "
            f"motivos_salteo={salteo} {detalle}").rstrip()
