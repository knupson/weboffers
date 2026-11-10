# Fixtures

Todos son sintéticos y se escribieron el 07/11/2026 para comprobar contratos, no para afirmar
productos, precios o envíos reales. Los identificadores FIXTURE no se usan en ejecución.
dogs_503.html incorpora el mensaje literal medido y aportado por Alejandro.
Los selectores corresponden al parser upstream fijado; faltan capturas reales de aceptación en VM.

`observabilidad.log` es un ejemplo escrito a mano de una página con bloqueo dogs, rotación,
backoff y reintento. Los bytes y duraciones son datos sintéticos del escenario, no mediciones.
El lector de logs lo usa como contrato. Las pruebas de transporte usan `dogs_503.html`,
`us_search.html`, respuestas OAuth sintéticas y formularios captcha construidos dentro del test.
