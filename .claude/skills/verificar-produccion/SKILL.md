---
name: verificar-produccion
description: Verifica en ofertas.knunet.com que un cambio quedó integrado y visible — cantidad publicada antes/después, precios del día, sha desplegado vs main, y 3 fichas comparadas contra Amazon y Mercado Libre en Chrome. Usar ANTES de decir «arreglado» o «listo» en cualquier cambio de catálogo, precios, cadena o deploy, y cuando Alejandro pida verificar el sitio.
---

# Verificar producción (Franquicia 400)

Cumple la regla 4 de errores de `AGENTS.md` («arreglado = integrado y visible») y las reglas de negocio 2 y 4 (nada viejo; si cae la cantidad, es un error).

## 1. Antes del cambio: sacar la foto

```bash
node .claude/skills/verificar-produccion/verificar.mjs foto
```

Guarda `publicados` y el sha en `ultima-foto.json` (gitignored). Si te olvidaste, el control de caída sale como AVISO: decíselo a Alejandro, no lo des por bueno.

## 2. Después de integrar (push a main + deploy si toca el sitio)

```bash
node .claude/skills/verificar-produccion/verificar.mjs
```

Controla y dice OK / AVISO / FALLA:

| Control | FALLA si |
|---|---|
| Precios del día | `estado.json.preciosDe` ≠ hoy en hora de Buenos Aires |
| Sitemap = estado.json | la cantidad de fichas `/productos/<slug>/` difiere de `publicados` |
| Caída | `publicados` bajó respecto de la foto |
| Desplegado | el sha publicado ≠ `origin/main` **y** cambió algo del sitio (`src/`, `public/`, `data/`, config) |
| Fichas | alguna de las 3 al azar no tiene `data-prices-date` de hoy o le falta link de Amazon o ML |

`publicados` < 100 sale como AVISO (mínimo pedido por Alejandro).

Si hay FALLA: es un error de producción → se arregla ya (regla 3), con `superpowers:systematic-debugging` y la skill `logs-cadena` para citar el log.

Para desplegar a mano: `bash tools/deploy.sh` (corre el deployer de la VM; el código tiene que estar en main).

## 3. Comparación punta a punta en Chrome (no se saltea)

Los tests no alcanzaron el 31/10: hay que mirar la página real. Con Chrome «Tu Chrome» de la VM (deviceId `7a76cb96-794e-4733-893f-85d888eab3fa`), para cada una de las 3 fichas que imprimió el script:

1. Abrir la ficha y leer el precio de Amazon (USD y costo final) y el de Mercado Libre que muestra.
2. Abrir el link de Amazon: mismo producto, mismo precio en USD, envío a Argentina.
3. Abrir el link de Mercado Libre: mismo producto y precio en ARS.

Si Amazon muestra el intersticial «Continue shopping», apretarlo (autorizado 07/11). Si pide login, frenar y avisar.

## 4. Cierre

Reportar con datos leídos en esta corrida, con la hora del script:

- `publicados` antes → después (y de dónde sale cada número).
- sha publicado vs main.
- Las 3 fichas: precio página vs tienda, coincide o no.
- «Busqué en N lugares, estaba en M» si fue un arreglo.

Si algo quedó sin desplegar o sin mirar en Chrome: «pendiente de integrar» / «no verificado», nunca «arreglado».
