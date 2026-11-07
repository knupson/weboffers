# Entrega del barrido

Implementadas las tareas 1–9 y la validación local de 11. Pendiente de integrar (tarea 10),
build en VM y aceptación real A6. No se ejecutó deploy ni se modificaron datos publicados.
No se consultó la cantidad publicada en producción; comparar cobertura y cantidad antes de integrar.

Validación final, desde la raíz del worktree:

`python -m pytest worker -q -p no:cacheprovider`

Resultado: **812 passed in 5.88s**. Incluye worker/amazon-ar/test_ar_server.py.
Se aplicaron las variables de entorno locales documentadas en OPERACION.md. Sin red en los tests
del barrido y sin tests upstream que pudieran activarse contra un endpoint vivo.

No quedan LICENSE, requirements.txt, schema_fields.py ni scraper_errors.py pendientes de recuperar.
Docker no está disponible localmente: build y pruebas reales US/ES quedan pendientes en VM.
El bloqueo de búsqueda medido por Alejandro no se da por resuelto.

## Archivos modificados

- docs/barrido/SPEC.md: contrato completo, políticas y alcance posterior.
- tools/probar_scraper.py: ingreso al servicio nuevo, moneda/USD, errores completos y hora ART.
- worker/amazon-ar/ar_server.py: importa ubicación y parser compartidos; conserva exportaciones.
- worker/amazon-ar/Dockerfile: copia el módulo compartido desde contexto worker.
- worker/docker-compose.yml: contexto AR y servicio interno independiente.

## Archivos creados

- docs/barrido/{TAREAS,OPERACION,ENTREGA}.md.
- worker/amazon_shipping.py.
- worker/barrido/{__init__,config,models,bootstrap,shipping,currency,refinements,amazon_source,
  ml_source,state,events,runner,__main__,server}.py.
- worker/barrido/{categorias.json,requirements.txt,Dockerfile}.
- worker/barrido/{conftest,test_config,test_currency,test_refinements,test_shipping,
  test_amazon_source,test_vendor,test_state,test_ml_source,test_runner,test_acceptance}.py.
- worker/barrido/fixtures/{README.md,us_search.html,es_search.html,dogs_503.html,
  ml_highlights.json,ml_product.json,ml_items.json,variations.json}.
- worker/barrido/vendor/: módulos de ejecución del commit fijado, licencia, requisitos originales,
  UPSTREAM.md y manifiestos SHA-256. Única modificación de código upstream: amazon/fetch.py.
- worker/test_probar_scraper.py.

tools/cadena.py, worker/catalog_auto.py y worker/worker.py no tienen cambios.

## Commits propuestos, en orden

No se intentó escribir commits por la restricción del sandbox indicada para este worktree.
Trailer para cada mensaje: `Co-Authored-By: GPT-6 (Codex) <noreply@openai.com>`.

1. **Definí el contrato diario y la configuración del barrido**
   Archivos: docs/barrido/SPEC.md; worker/barrido/{__init__,config,models,test_config}.py;
   worker/barrido/categorias.json.
2. **Incorporá el scraper fijado con licencia y trazabilidad**
   Archivos: worker/barrido/vendor/; worker/barrido/{bootstrap,test_vendor}.py;
   worker/barrido/requirements.txt.
3. **Compartí la ubicación AR y la clasificación de envíos US y ES**
   Archivos: worker/amazon_shipping.py; worker/amazon-ar/{ar_server.py,Dockerfile};
   worker/barrido/{shipping,test_shipping}.py.
4. **Agregá adquisición diaria, reanudación y control de bloqueos**
   Archivos: worker/barrido/{currency,refinements,amazon_source,ml_source,state,events,runner,__main__}.py;
   worker/barrido/{conftest,test_currency,test_refinements,test_amazon_source,test_ml_source,
   test_state,test_runner,test_acceptance}.py; worker/barrido/fixtures/.
5. **Sumá el servicio interno, la prueba manual y la guía de operación**
   Archivos: worker/barrido/{Dockerfile,server.py}; worker/docker-compose.yml;
   tools/probar_scraper.py; worker/test_probar_scraper.py;
   docs/barrido/{TAREAS,OPERACION,ENTREGA}.md.

Los commits 2 y 3 preparan componentes; la verificación completa corresponde al conjunto final.
