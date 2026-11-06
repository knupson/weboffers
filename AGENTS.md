# Franquicia 400 (weboffers) — reglas para agentes (Claude Code, Codex y Gemini)

Fuente única de reglas para cualquier agente en este repo. `CLAUDE.md` la importa. Qué es el producto y qué no se puede mostrar: `PRODUCT.md`. Diseño: `DESIGN.md`. Spec: `docs/SPEC.md`.

## Idioma

Todo lo que lee Alejandro (el dueño) va en castellano rioplatense: respuestas, commits, docs y textos del sitio. En inglés quedan sólo el código, los comandos, las rutas y los identificadores.

## Reglas de negocio que ningún cambio puede romper

Las dijo Alejandro. Se chequean antes de cerrar cualquier cambio en el catálogo, los precios, la cadena o el deploy:

1. **Es un comparador:** un producto sin precio del día de los dos lados (Amazon y Mercado Libre) o sin envío a Argentina confirmado **no se publica**. No sale «con una nota»: no sale.
2. **Nunca se muestra información vieja ni inventada.** Si la corrida de hoy no llega, no se rellena con la de ayer. Los límites de antigüedad están en `PRODUCT.md`.
3. **Un error en producción se arregla ya**, sin esperar a la próxima corrida programada.
4. **Si cae la cantidad publicada, es un error hasta que se demuestre lo contrario** (pasar de 64 a 19 productos fue una falla). Al cerrar, comparar la cantidad de productos publicados antes y después.

## Errores y tareas de varios pasos (Alejandro, 2026-11-06)

Estas reglas salen de revisar 19 sesiones con quejas de este repo y de Blackseam. Los patrones que se repitieron: el mismo error vuelve a aparecer en otro lado, la causa se afirma sin mirar el log, un arreglo queda sin integrar y los pasos de una cadena no se encadenan. Cuando el mensaje reporta un error, el hook `~/.claude/scripts/protocolo-errores.mjs` recuerda estas reglas.

1. **Diagnóstico con skill:** ante un error, invocar `superpowers:systematic-debugging` antes de tocar código.
2. **Causa con evidencia:** la causa sale de un log o registro leído, citando la línea y la hora. Si el log no alcanza para saberlo, primero se agrega el log y después se arregla. Nada de números estimados.
3. **Alcance completo:** el mismo error se busca en todo el repo y en todas sus instancias (todos los productos, todas las pantallas, todos los pasos de la cadena), no sólo donde se vio. El cierre lo dice así: «busqué en N lugares, estaba en M».
4. **«Arreglado» quiere decir integrado y visible:** mergeado, desplegado si corresponde y verificado donde Alejandro lo vio (en `ofertas.knunet.com`, no sólo en los tests). Un arreglo que todavía no se integró se informa como «pendiente de integrar».
5. **Tareas de varios pasos:** al arrancar, armar la lista de pasos (TaskCreate/TodoWrite), cada uno con su criterio de «hecho». Si un paso falla, se lee el error, se corrige y se reintenta sin preguntar. Sólo si falla igual dos veces se frena y se avisa, con el error literal.
6. **Encadenado, no por horario:** cada paso automático arranca cuando termina el anterior, dentro del script, y cada línea de log lleva su hora. Nunca se le pasa a Alejandro un comando que el agente puede correr solo.
