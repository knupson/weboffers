# Procedencia del scraper

- Repositorio: https://github.com/omkarcloud/amazon-scraper
- Commit: `8ffd4f976c705d009ec06d8e4e3e15fc77e35cee`.
- Recuperado el 07/11/2026 por archivo ZIP de ese commit desde
  `https://codeload.github.com/omkarcloud/amazon-scraper/zip/8ffd4f976c705d009ec06d8e4e3e15fc77e35cee`.
- El clon con git falló: `schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS (0x8009030e)`.
- La copia temporal suministrada carecía de LICENSE, requirements.txt, schema_fields.py y
  scraper_errors.py. Se recuperaron los cuatro desde el archivo del commit; no quedan pendientes.
- Licencia MIT original conservada: Copyright (c) 2026 Chetan Jain.
- Sólo se copiaron los módulos de ejecución de amazon/, config.py, scraper_errors.py,
  schema_fields.py, LICENSE y requirements.txt.
  No se copiaron secretos, cachés, pruebas con red ni ejecutables del servidor original.

Se excluyeron test_endpoints.py, test_parsers.py y las capturas upstream de amazon/fixtures/;
el primero consulta la red si AMAZON_BASE está definido. La suite de esta entrega usa sólo fixtures
propios y bloquea tanto requests como curl_cffi durante sus tests.

`upstream-hashes.json` contiene SHA-256 de cada archivo original incluido. `local-hashes.json` contiene los
hashes finales de archivos modificados. Las diferencias locales son:

- amazon/fetch.py: observador optativo de cada request de curl, con método, ruta sin query,
  HTTP, segundos y error literal. Incluye calentamiento, cambios de ubicación e intersticiales.
  Sin observador conserva el comportamiento original. No registra headers, cookies ni credenciales.

Fuera del vendor: bootstrap fija salida directa, timeout y ubicación AR compartida, y reduce
RETRIES=0/BLOCK_RETRIES=1 para que el runner gobierne backoff y N sin multiplicar sesiones ocultas.
No se cambió el parser upstream; se conserva HTML de tarjetas en el adaptador y se amplían patrones ES
en amazon_shipping.py. No se llama al wrapper upstream que descubre filtros por cada página.

requirements.txt de este directorio es el original sin pins. ../requirements.txt fija las versiones
consultadas en los metadatos públicos de PyPI el 07/11/2026 para el servicio independiente.
