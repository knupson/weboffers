# Cuatro procesos separados para publicar (diseño, 09/11/2026)

## Por qué

Pedido de Alejandro, literal:

> «Deberian ser procesos distintos. Uno es el de reverificacion de lo publicado. Y otro es el de suma de nuevos productos»
> «Proceso1: Suma de nuevos productos. | Proceso2: Verificacion Diaria de productos PUBLICADOS. | Proceso3: Verificacion "manual" de productos dudosos.»
> «Tendriamos un 4 proceso que seria el analisis de de republicacion. Si falla sale del sitio y se analiza 3 dias.»
> «Si despues de 3 dias se descarta, pero podria volver algun dia a traves del proceso 1»
> Sobre los dudosos: «Podes decidirlo vos. Y si hay un caso mega excepcional en que sigue en duda me lo podes pasar»
> «el "Catalogo" no existe. hay 116 publicados, nada mas. … o esta publicado o no esta publicado.»
> Sobre la verificación diaria: «deberia ser facil y especifico, 1 consulta a cada plataforma».

Hoy (medido el 09/11 en `cadena-2026-11-09.log`) la cadena de las 03:30 reconsulta todo `catalog.json` + `catalog-auto.json`: entran 291 productos, Chrome releva 238, y 175 no terminan publicados (`estado.json`: 116). La verificación diaria hace trabajo sobre productos que no están en el sitio, y el alta de nuevos productos comparte la cadena (paso `altas`).

> «Los que no se publicaron es porque no cumplian las condiciones, y 100% no deberian estar en ningun catalogo mas que en uno que diga "No revisar por xx dias" para no estar loopeandolos todos los dias en el proceso 1. Los que alguna vez estuvieron publicados viven en el fluijo del proceso [4].»
> «Arranquemos con 7» (días de «no revisar»).

Medido el 09/11 (`desglose-*.log` del deployer, desde 07/11 03:53): de los 175 no publicados hoy, 5 estuvieron publicados alguna vez desde el 07/11 y 170 nunca.

> «Todos los script se tienen que correr 1 sola vez por dia. Se acaba lo de noctura, mañana, etc.»

## Una corrida por día

Una sola corrida diaria (cron 03:30, el horario actual de la cadena), encadenada, y cada script corre una vez:

1. Proceso 2 + 4: Chrome (publicados + republicación) → Amazon → ML → deploy → estado.
2. Proceso 1, búsqueda: alta de candidatos nuevos (`catalog_auto`, sin ventana 20:00–03:00 ni reintentos por hora).
3. Proceso 3: dudosos con NVIDIA.
4. Proceso 1, confirmación: Chrome (pendientes + «no revisar» vencidos) → altas → Amazon → ML → deploy → estado.

Se eliminan: los reintentos por hora del worker (Amazon desde 06:00, slots de ML, alta 20:00–03:00, fichas ML), la unidad `franquicia-tras-alta.path` y el bucle de 10 minutos del deployer (pasa a desplegar sólo cuando lo llama la corrida). Un paso que falla se reintenta dentro de la misma corrida (regla 5 de AGENTS.md), no en otra hora.
Queda fuera (decisión de Claude, no son procesos de publicación): las publicaciones de Telegram 12:00/20:00, Meta, los recordatorios y los vigías.

## Estados (lo único que ve Alejandro)

Un producto está **publicado** o **no publicado**. Internamente, un no publicado puede estar en una de estas situaciones; ninguna es visible ni se le reporta como «catálogo»:

| Situación interna | Qué proceso lo toca |
|---|---|
| Publicado | 2 |
| En republicación (salió hace ≤3 días) | 4 |
| Dudoso (par sin identificador fuerte) | 3 |
| Candidato / pendiente de envío | 1 |
| «No revisar» (falló en el 1 o venció el 4) por 7 días | ninguno; al vencer vuelve a ser candidato del 1 |

No existe más una lista de «todo lo que alguna vez se cargó» que se reconsulte entera cada día. Un par que nunca llegó a publicarse no vive en ningún lado salvo en «no revisar» (con fecha de vencimiento y motivo).

## Proceso 1 — Suma de nuevos productos

- Lo que hoy hacen el alta nocturna (`worker/catalog_auto.py`, 20:00–03:00) y la confirmación de pendientes (paso `altas` de `tools/cadena.py`, `tools/confirmar_altas.py`).
- Un candidato se publica sólo con: precio del día en Amazon y en ML, envío gratis a AR confirmado hoy por Chrome, USD 100–400, identificador fuerte (o aprobado por el proceso 3). Lo que falla se descarta en el paso que lo detecta.
- Un candidato que falla cualquier requisito va a «no revisar» 7 días con el motivo; el proceso 1 no lo consulta mientras tanto. Al vencer, vuelve a ser candidato común. Lo mismo para los que vencen en el proceso 4. Cada reconsulta deja en el log si cumplió o no, para recalibrar los 7 días en 2 semanas (pedido del 09/11). Hoy `rejected_asins()` tiene su propia lógica de exclusión; se reemplaza o se alinea con esta.
- Los pares ya armados (foto, identificadores, fichas) de un producto en «no revisar» se conservan para no rearmarlos al volver.
- Corre separado del proceso 2: su propio horario, log y estado. Si el 1 falla, el 2 y el sitio siguen igual.
- La rama `feat/barrido` (22 commits fuera de `main`, búsqueda Amazon→ML) es otra fuente del proceso 1; integrarla queda fuera de este diseño.

## Proceso 2 — Verificación diaria de publicados

- Entrada: **sólo** los productos publicados en el último deploy (los `PUBLICADO` del último desglose, o el mismo criterio `isComparable` de `src/lib/data.ts`). Hoy: 116.
- Consultas por producto, una por plataforma:
  - Amazon EE. UU.: 1 página en Chrome (precio + envío a AR juntos; hoy ya es así, `envio_ar_chrome`).
  - Amazon ES (o lo que no pasa por Chrome): scraper; hoy son 2 pedidos (precio + servidor AR). Ver «Abierto».
  - Mercado Libre: 1 pedido `/products/{catalogId}/items` (`worker/ml_prices.py:96`).
- El que cumple todo sigue publicado con el precio de hoy. El que falla cualquier requisito sale del sitio en el deploy de ese día y pasa al proceso 4, con el motivo en el log.
- Encadenado: Chrome → Amazon → ML → deploy, cada paso al terminar el anterior (regla 6 de AGENTS.md). Mismo horario que la cadena actual (03:30) salvo que se mida otra cosa.
- Regla 4: si la cantidad publicada cae, el aviso de hoy sigue; además el log dice cuántos salieron y por qué.

## Proceso 3 — Verificación de dudosos

- Entrada: `altas-revision.json` (pares que el proceso 1 encontró sin identificador fuerte).
- Automático, una vez por día en la VM, con el modelo gratis de NVIDIA (Alejandro, 09/11: «Me inclino con automatico pero con nvidia»), no con Claude.
- Un script junta la evidencia: ficha completa de Amazon (`tools/recolectar_fichas.py`), ficha de ML (API), y arma la comparación campo por campo (marca, modelo, capacidad, color, variante, identificadores).
- Dos modelos distintos de NVIDIA juzgan cada par por separado y devuelven `aprobar|rechazar` + motivo en JSON. Si coinciden, el script ejecuta `tools/revisar_altas.py aprobar|rechazar --motivo`. Si no coinciden, o alguno no responde o devuelve algo inválido, el par queda en revisión y se le pasa a Alejandro por WhatsApp con la comparación (el caso «mega excepcional»). (Decisión de Claude.)
- Aprobado no es publicado: vuelve al proceso 1 y pasa los mismos requisitos del día.
- Requisito de infraestructura: la clave `NVIDIA_API_KEY` hoy está en el registro de Windows; hay que dejarla en el `.env` del worker en la VM (vence 2027-04-30, `NVIDIA_API_KEY_EXPIRES`).
- Cada decisión queda en el log con los dos votos y la evidencia usada.

## Proceso 4 — Análisis de republicación

- Entrada: productos que el proceso 2 sacó del sitio. Se guarda la fecha de salida y el motivo.
- Durante los 3 días siguientes se consultan una vez por día con las mismas consultas del proceso 2 (pueden ir en la misma corrida, después de los publicados).
- Si un día cumple todo, se republica ese día (sin pasar por el proceso 1).
- Si al tercer día sigue fallando, se descarta. Puede volver sólo por el proceso 1.
- Arranque: los no publicados que figuran `PUBLICADO` en algún desglose (`/state/logs/desglose-*.log`, desde el 07/11; hoy 5) entran al proceso 4 con la fecha de su último `PUBLICADO`; si esa fecha ya pasó los 3 días, van directo a «no revisar». Los que nunca se publicaron (hoy 170) van a «no revisar» 7 días.

## Decisiones de Claude (tras la revisión del builder, 09/11)

- **Sin dato ≠ no cumple, pero el resultado es el mismo:** en el proceso 2, si Amazon/ML/Chrome no responden, se reintenta una vez dentro de la corrida; si sigue sin dato, el producto sale (regla 2: no hay precio de hoy y no se rellena con ayer) y entra al proceso 4. Si salen más de 10 en una corrida, aviso fuerte por WhatsApp con los motivos (regla 4), sin frenar el deploy.
- **Envío:** el proceso 2 mantiene la regla de `PRODUCT.md` (evidencia de envío gratis hasta 14 días, `ARSHIPPING_MAX_DAYS`). Sale si el relevamiento de hoy dice «no envía» o «envío pago»; si el relevamiento falla, sigue mientras la evidencia tenga ≤14 días. El proceso 1 sigue exigiendo Chrome del día.
- **`data/catalog.json`:** queda en git como depósito de pares armados (foto, textos, identificadores), no como lista a verificar. El estado nuevo (publicado / proceso 4 / no revisar, clave ASIN) manda y el deployer sólo construye lo publicado o lo que el proceso 4 republica. Sin commit que borre pares.
- Clave de «no revisar» y del proceso 4: el ASIN, alineado con `altas-rechazadas.json`; los 14 días actuales de `rejected_asins` pasan a 7 con vencimiento y motivo.
- Proceso 4: 3 consultas, desde el día siguiente a la salida.
- Los 170 iniciales vencen escalonados en los 7 días (por hash del ASIN) para no volver todos juntos.
- Un producto que vuelve de «no revisar» al proceso 1 sólo repite Chrome + precio ML, sin redescubrir.
- El proceso 1 despliega solo (`--ahora`, como el modo `tras-alta` de hoy). Chrome y `cadena.lock` siguen compartidos: los procesos se encolan, no corren en paralelo.

## No-objetivos

- No cambiar requisitos de publicación (`PRODUCT.md`, reglas 1–4 de AGENTS.md).
- No tocar el diseño del sitio.
- No integrar `feat/barrido` en este trabajo.

## Anti-objetivos (sería un fracaso aunque funcione)

- Publicar algo con precio o envío de un día anterior para «rellenar» el proceso 4.
- Que una falla del proceso 1 frene el proceso 2 (lo que pasó la noche del 08/11 con el `DEPLOY_FAIL`, aunque ahí no bajó el sitio).
- Hablarle a Alejandro de «catálogo».

## Abierto para el builder

- Dónde guardar el estado de publicados / republicación (archivo en `worker/output`, junto a `catalog-auto.json`) y cómo se lo pasa al deployer.
- Si el refresco horario del worker (`amazon_prices.maybe_refresh` desde las 06:00, `ml_prices` con slots) sigue existiendo o queda reemplazado por el proceso 2.
- Amazon ES: si se puede bajar a 1 pedido por producto; si no, dejar los 2 y loguearlo.
