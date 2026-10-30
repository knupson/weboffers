---
name: Franquicia 400
description: Cada oferta pintada como la placa de un colectivo porteño, con la cuenta argentina enmarcada en filete.
colors:
  esmalte: "#141210"
  placa: "#1d1a17"
  placa-2: "#262220"
  linea: "#3a332d"
  sombra: "#0b0a09"
  crema: "#f4efe4"
  crema-2: "#cfc6b6"
  apagado: "#a39a8b"
  rojo: "#d7262b"
  rojo-hover: "#e83a3f"
  amarillo: "#f2c230"
  verde: "#1f8f4e"
  verde-claro: "#5cc489"
  celeste: "#6ec6f0"
typography:
  display:
    fontFamily: "Ultra, Rockwell Extra Bold, serif"
    fontSize: "clamp(48px, 4.8vw, 84px)"
    fontWeight: 400
    lineHeight: 1.02
    letterSpacing: "-0.01em"
  headline:
    fontFamily: "Ultra, Rockwell Extra Bold, serif"
    fontSize: "clamp(30px, 3.6vw, 46px)"
    fontWeight: 400
    lineHeight: 1.02
    letterSpacing: "-0.01em"
  figure:
    fontFamily: "Ultra, Rockwell Extra Bold, serif"
    fontSize: "clamp(32px, 7cqi, 48px)"
    fontWeight: 400
    lineHeight: 1.05
  title-page:
    fontFamily: "Archivo Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "clamp(28px, 3.4vw, 42px)"
    fontWeight: 800
    lineHeight: 1.1
    letterSpacing: "-0.02em"
  title:
    fontFamily: "Archivo Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 700
    lineHeight: 1.3
  lead:
    fontFamily: "Archivo Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1.55
  body:
    fontFamily: "Archivo Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Archivo Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 600
    lineHeight: 1.3
  fine:
    fontFamily: "Archivo Variable, ui-sans-serif, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.55
  button:
    fontFamily: "Ultra, Rockwell Extra Bold, serif"
    fontSize: "16px"
    fontWeight: 400
    lineHeight: 1
    letterSpacing: "0.01em"
rounded:
  placa: "18px"
  marco: "12px"
  campo: "10px"
  chapita: "8px"
spacing:
  gutter-sm: "16px"
  gutter-md: "32px"
  stack-sm: "8px"
  stack-md: "16px"
  grid: "20px"
  section-sm: "64px"
  section-md: "88px"
  container: "1240px"
components:
  button-primary:
    backgroundColor: "{colors.rojo}"
    textColor: "#ffffff"
    typography: "{typography.button}"
    rounded: "{rounded.campo}"
    padding: "0 20px"
    height: "46px"
  button-primary-hover:
    backgroundColor: "{colors.rojo-hover}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.crema}"
    rounded: "{rounded.campo}"
    padding: "0 20px"
    height: "46px"
  button-ghost-hover:
    backgroundColor: "{colors.placa-2}"
  chip:
    backgroundColor: "{colors.placa}"
    textColor: "{colors.crema-2}"
    typography: "{typography.label}"
    rounded: "{rounded.campo}"
    padding: "0 14px"
    height: "38px"
  chip-active:
    backgroundColor: "{colors.amarillo}"
    textColor: "{colors.esmalte}"
  input:
    backgroundColor: "{colors.esmalte}"
    textColor: "{colors.crema}"
    rounded: "{rounded.campo}"
    padding: "0 14px"
    height: "50px"
  search-cartel:
    backgroundColor: "{colors.crema}"
    textColor: "{colors.esmalte}"
    rounded: "14px"
    padding: "8px"
  card-placa:
    backgroundColor: "{colors.placa}"
    textColor: "{colors.crema}"
    rounded: "{rounded.placa}"
  badge-store:
    backgroundColor: "{colors.celeste}"
    textColor: "{colors.esmalte}"
    rounded: "{rounded.chapita}"
    padding: "0 8px"
    height: "26px"
---

# Design System: Franquicia 400

## Overview

**Creative North Star: "La placa del colectivo"**

Franquicia 400 pinta cada oferta como la placa de un colectivo porteño: el dato que importa (cuánto sale puesto en tu casa) va enmarcado en filete y a la vista. El suelo es esmalte negro casi cálido; encima, placas apenas más claras con bordes dobles amarillo y rojo y volutas pintadas en las esquinas. La paleta de filete (rojo bermellón, amarillo cromo, verde esmeralda, celeste) aparece como pintura sobre el esmalte, nunca como fondo de página.

La tipografía sigue la lógica del cartel de comercio: los títulos y las cifras grandes van en letra de filete, una slab pesada amarilla con sombreado en capas rojo y negro; todo lo que se lee de corrido va en Archivo, grotesca de imprenta con cifras tabulares. La densidad es la de una vidriera ordenada: grilla de placas de producto, cartelitos de categoría en fila con scroll horizontal y una pizarra de búsquedas.

La imaginería es propia y pintada (plates de filete generadas con Gemini, cada una con su sidecar `.json` de procedencia). Nunca representa un producto real con IA: cuando haya foto de producto, viene de Amazon y se muestra sobre blanco, contenida dentro del marco. El sitio no se parece a knunet.com ni a blackseam.knunet.com, por pedido explícito de marca.

**Key Characteristics:**
- Esmalte negro como suelo, placas tonales encima, sin superficies claras salvo el cartel de búsqueda.
- Bordes dobles amarillo y rojo hechos con `box-shadow: inset` anidado, más volutas pintadas en las cuatro esquinas.
- Letra de filete (Ultra) con sombreado en capas para títulos, precios y totales; Archivo para todo lo demás.
- Rojo reservado para la acción de compra y para el estado "pasaste la franquicia".
- Cifras siempre tabulares; la hora del dato se imprime junto al dato.

## Colors

Paleta de filete porteño sobre esmalte: cuatro pinturas saturadas, una crema para la letra y una escala corta de negros cálidos para las superficies.

### Primary
- **Rojo Bermellón** (`rojo`): el botón de compra ("Ver en Amazon", "Buscar"), el filo exterior del borde doble, la capa media del sombreado de la letra, la placa de total y el estado de exceso sobre USD 400 (tramo de cinta, medidor, anillo del pulgar). Hover sube a **Rojo Encendido** (`rojo-hover`).

### Secondary
- **Amarillo Cromo** (`amarillo`): color de la letra de filete, filo interior del borde doble, chip activo, enlaces de texto, foco (`outline` 2px), selección de texto, caret, la marca del borde de USD 400 en la cinta.

### Tertiary
- **Verde Esmeralda** (`verde`): tramo de la cinta y del medidor mientras el monto entra en la franquicia. Su versión clara, **Verde Hoja** (`verde-claro`), es el texto de estado "sin derechos" y de las notas OK.
- **Celeste Cielo** (`celeste`): dato vivo y secundario. Cotización MEP en el header, chapita de tienda (Amazon.com / .es) en las tarjetas, borde exterior de la pizarra de búsquedas, cifras del reglamento, foco dentro del cartel de búsqueda y del segmentado.

### Neutral
- **Esmalte Negro** (`esmalte`): fondo de página, fondo de campos de formulario y del segmentado, `theme-color`.
- **Placa** (`placa`) y **Placa Honda** (`placa-2`): superficies de tarjetas, cartelitos, pizarra y calculadora; `placa-2` es hover de filas y la columna de resultado de la calculadora.
- **Línea** (`linea`): bordes finos (1.5px inset), divisores de 1px, scrollbar.
- **Sombra de Letra** (`sombra`): la capa más profunda del sombreado de la letra de filete.
- **Crema** (`crema`): texto principal y fondo del cartel de búsqueda. **Crema Gastada** (`crema-2`): texto secundario, bajadas, nav inactivo. **Apagado** (`apagado`): notas al pie, metadatos, migas.

### Named Rules
**The Pintura sobre Esmalte Rule.** Las cuatro pinturas de filete se aplican como trazo, borde, letra o chapita sobre esmalte o placa. Ninguna cubre una sección entera; la única superficie pintada grande permitida es la placa de total en rojo.

**The Rojo Compra Rule.** El rojo relleno significa "comprá" o "te pasaste de USD 400". No se usa para decorar ni para enlaces secundarios, que van en amarillo o como botón fantasma.

**The Verde-Rojo de la Cinta Rule.** Todo indicador del umbral de franquicia es verde hasta USD 400, marcado en amarillo en el borde exacto y rojo después. Mismo código en la cinta del hero, el medidor de la calculadora y los textos de estado.

## Typography

**Display Font:** Ultra (con Rockwell Extra Bold, serif)
**Body Font:** Archivo Variable (con ui-sans-serif, system-ui, sans-serif)

**Character:** Ultra es la letra pintada a pincel del fileteador: slab gorda, amarilla, con sombra en capas. Archivo es la imprenta grotesca de los carteles de comercio, elegida por la legibilidad de cifras.

### Hierarchy
- **Display** (Ultra 400, `clamp(48px, 4.8vw, 84px)`, 1.02): el título del hero. Sombreado `0.04em` rojo y `0.08em` sombra.
- **Headline** (Ultra 400, `clamp(30px, 3.6vw, 46px)`, 1.02): títulos de sección y de páginas internas (éstas suben a `clamp(40px, 5.6vw, 72px)`). Sombreado `0.05em` / `0.09em`.
- **Figure** (Ultra 400, 22 a 48px según contexto): precios, totales en pesos, operadores de la fórmula, números de paso, cifras del reglamento, el logo del header.
- **Title Page** (Archivo 800, `clamp(28px, 3.4vw, 42px)`, 1.1, -0.02em): nombre del producto en la ficha. Es grotesca, no letra de filete: el nombre del producto es dato, no cartel.
- **Title** (Archivo 700, 17px, 1.3): nombre del producto en la tarjeta, recortado a dos líneas. Títulos de paso y de calculadora en 18px.
- **Lead** (Archivo 400, 19px, máx. 46ch): bajada del hero; 17px en cabeceras de sección y ficha (máx. 68ch / 60ch).
- **Body** (Archivo 400, 16px, 1.55): prosa en `crema-2`, máx. 68ch.
- **Label** (Archivo 600, 14px): chips, rótulos de campo, filas de desglose, enlaces de tarjeta.
- **Fine** (Archivo 400, 13px, `apagado`): divulgación de afiliado, aclaraciones de ilustración, metadatos.

### Named Rules
**The Letra de Filete Rule.** Ultra se usa sólo para títulos, cifras y el botón de compra, siempre en amarillo (o crema) y, en títulos y totales, con su sombreado en capas rojo y negro desplazado en `em`. Nunca para párrafos, rótulos ni chips.

**The Cifra Tabular Rule.** Todo número que cambia (cotización, precio, total, desglose) lleva `font-variant-numeric: tabular-nums`. La hora de la cotización se imprime junto al valor.

## Layout

Contenedor centrado de 1240px con margen lateral de 16px (32px desde 768px). Las secciones respiran 64px arriba y abajo (88px desde 768px); las cabeceras de sección son una pila de 12px con 32px hasta el contenido.

El hero es una grilla de dos columnas desde 1024px (`0.85fr / 1.15fr`, gap 40px): a la izquierda título, bajada y cartel de búsqueda; a la derecha la placa pintada con la calculadora rápida posicionada en su centro vacío por porcentajes (25% laterales, 27% arriba, 25% abajo). Debajo asoma una fila de cartelitos de categoría con `scroll-snap` horizontal (columnas mínimas de 150px).

Las tarjetas de producto usan `repeat(auto-fill, minmax(270px, 1fr))` con gap de 20px: cuatro columnas en escritorio, una en celular. La ficha de producto es `1.2fr / 1fr` desde 1024px con la caja de compra `sticky` a 92px. La calculadora es un contenedor con `container-type: inline-size` que pasa a dos columnas desde 720px de ancho propio. Header `sticky` de 68px (60px en celular) con fondo esmalte al 97% y `blur(10px)`.

## Elevation & Depth

El sistema es tonal y de borde, no de sombra flotante. La profundidad se arma con tres escalones de negro (esmalte, placa, placa honda) y con bordes pintados hechos de `box-shadow: inset` anidados. La única sombra ambiental es una caída suave bajo las tarjetas de producto y el brillo rojo bajo el botón de compra. El sombreado duro de la letra es parte del oficio del filete (letra sombreada a pincel), no una elevación de caja.

### Shadow Vocabulary
- **Borde de filete** (`inset 0 0 0 2px amarillo, inset 0 0 0 5px placa, inset 0 0 0 6px rojo`): tarjetas de producto, caja de compra, placa de "Cómo sacamos la cuenta".
- **Borde de pizarra** (`inset 0 0 0 2px celeste, inset 0 0 0 5px placa, inset 0 0 0 6px amarillo`): la pizarra de búsquedas curadas, para distinguirla de las placas de producto.
- **Hilo** (`inset 0 0 0 1.5px linea`): cartelitos, chips, campos, calculadora, pasos. Hover sube a `crema-2`; foco de campo a `2px amarillo`.
- **Caída de placa** (`0 14px 30px -18px rgb(0 0 0 / 0.8)`): sólo bajo la tarjeta de producto.
- **Esmalte del botón** (`inset 0 0 0 3px rojo, inset 0 0 0 4.5px crema, 0 6px 16px -8px rgb(215 38 43 / 0.6)`): filete crema interior y brillo rojo del botón de compra.
- **Anillos del cartel** (`0 0 0 3px esmalte, 0 0 0 5px amarillo, 0 0 0 7px esmalte, 0 0 0 9px rojo`): el buscador; el anillo amarillo pasa a celeste con `:focus-within`.
- **Sombreado de letra** (`text-shadow: 0.04em 0.04em 0 rojo, 0.08em 0.08em 0 sombra`): letra de filete.

### Named Rules
**The Borde Pintado Rule.** Un marco se dibuja con `box-shadow: inset` anidado (filete, separación del color de la placa, filete), nunca con `border` doble ni con imágenes de marco. Las volutas de esquina van aparte, como capa `::before`.

## Shapes

Esquinas generosas de chapa esmaltada: 18px (`placa`) para toda placa contenedora (tarjeta, pizarra, calculadora, pasos, cuenta), 12px (`marco`) para imágenes dentro de una placa, 10px (`campo`) para botones, campos, chips y la media de la tarjeta, 8px (`chapita`) para chapitas de marca y tienda y miniaturas. El cartel de búsqueda usa 14px. Los únicos círculos son el pulgar de la cinta. Las placas secundarias (tarjeta, pizarra, caja de compra, calculadora, cuenta) llevan cuatro volutas pintadas en las esquinas (`/art/esquina-*.webp`, 64px por defecto, 72px en calculadora, 88px en la cuenta) con `mix-blend-mode: lighten` sobre el negro.

## Components

### Buttons
Cartelito esmaltado: rojo, con filete crema interior y letra de filete.
- **Shape:** curva de campo (10px), alto 46px (40px `sm`, 56px `lg` a ancho completo).
- **Primary:** fondo `rojo`, texto blanco en Ultra 16px, padding horizontal 20px, ícono Phosphor de flecha a 16px.
- **Hover / Active:** fondo `rojo-hover` en 150ms con `--ease-out`; `:active` escala a 0.97 en 120ms.
- **Ghost:** transparente, texto `crema` en Archivo 700 15px, hilo `linea` de 1.5px; hover a `placa-2` con hilo `crema-2`. Para salidas secundarias (ofertas del día).
- **Link:** texto `amarillo` Archivo 600 con flecha, subrayado sólo en hover.

### Chips
- **Style:** filtros de categoría, 38px de alto, fondo `placa`, texto `crema-2` Archivo 600 14px, hilo `linea`, conteo al 65% de opacidad.
- **State:** `aria-pressed="true"` pasa a relleno `amarillo` con texto `esmalte` y sin hilo. Fila con scroll horizontal sin barra visible.

### Cards / Containers
- **Corner Style:** placa (18px), con media interna de 10px separada 10px del borde.
- **Background:** `placa`; media sobre negro puro con ilustración de filete de la categoría, o foto de Amazon `contain` sobre blanco con 16px de aire.
- **Shadow Strategy:** borde de filete + caída de placa; hover sube 3px en 200ms (anulado con `prefers-reduced-motion`).
- **Chapitas:** marca arriba a la izquierda (logo SVG en `crema` sobre esmalte al 86%), tienda arriba a la derecha en `celeste`.
- **Internal Padding:** 16px 18px; pie con botón de compra a todo el ancho y enlace amarillo "¿Cuánto me sale en pesos?". Toda la tarjeta es clickeable vía el `::after` del título.

### Inputs / Fields
- **Style:** 50px de alto, fondo `esmalte`, texto `crema` Archivo 600 18px tabular, hilo `linea`, curva de campo. Prefijo de moneda absoluto a 14px.
- **Focus:** hilo pasa a `2px amarillo`, sin `outline`.
- **Segmentado:** pista `esmalte` con 4px de padding; opción elegida en relleno `amarillo` con texto `esmalte`; foco con `outline` celeste.
- **Notas:** error en fondo rojo oscuro con texto salmón; OK en verde oscuro con `verde-claro`.

### Navigation
Header `sticky` de 68px: logo en letra de filete a 22px a la izquierda, enlaces Archivo 500 15px en `crema-2` con hover a `crema` sobre `placa` y página actual en `amarillo`, y una pastilla con hilo que muestra el MEP en `celeste` con su hora (visible desde 960px). En celular baja a 60px, logo de 18px y oculta "Cómo funciona". El pie abre con un filete horizontal (2px amarillo arriba, 2px rojo abajo, 7px de alto).

### Cartel de búsqueda (signature)
Barra crema con texto esmalte, lupa, campo, selector de tienda sobre `#e6dfd0` y botón rojo, rodeada por anillos alternados esmalte, amarillo, esmalte, rojo. En celular se parte en dos filas.

### Cinta de la franquicia (signature)
Rango de USD 0 a 600 con pista de 10px: tramo `verde` hasta el borde, marca `amarillo` de 4px en USD 400 rotulada encima en Archivo 700 11px, resto en rojo oscuro. Pulgar crema de 26px con anillo amarillo que crece a 1.12 al arrastrar. Al cruzar el borde, tramo y anillo pasan a `rojo` y el estado cambia de verde a salmón. Vive en el centro vacío de la placa pintada del hero, con el monto en USD en crema y el total en pesos en amarillo sombreado.

### Pizarra de búsquedas
Placa con borde de pizarra (celeste y amarillo), filas de dos columnas desde 760px: miniatura de 64x48, rótulo Archivo 600 con la tienda debajo en `apagado`, flecha que se ilumina en amarillo y se corre 2px en diagonal al hover.

## Do's and Don'ts

### Do:
- **Do** apoyar todo sobre `esmalte` y levantar contenedores con `placa` / `placa-2`, nunca con superficies claras (salvo el cartel de búsqueda y la foto de producto sobre blanco).
- **Do** enmarcar las placas principales con el borde de filete inset (2px amarillo, 3px de placa, 1px rojo) y las volutas de esquina como capa `::before` con `mix-blend-mode: lighten`.
- **Do** escribir títulos, precios y totales en Ultra amarillo con su sombreado en capas desplazado en `em`.
- **Do** usar verde hasta USD 400, amarillo en el borde exacto y rojo después, en todo indicador de franquicia.
- **Do** animar sólo `transform`, `color`, `background-color` y `box-shadow` con `--ease-out` en 120 a 300ms, y anular los desplazamientos con `prefers-reduced-motion`.
- **Do** usar íconos Phosphor regular como SVG inline y logos de marca como SVG de un solo color.
- **Do** guardar cada raster pintado con su sidecar `.json` de procedencia (modelo, fecha, prompt, postproceso).

### Don't:
- **Don't** generar con IA imágenes que representen un producto real; la ilustración de filete es de categoría y se aclara como tal.
- **Don't** usar el rojo relleno fuera de la acción de compra, la placa de total o el estado de exceso.
- **Don't** usar Ultra para párrafos, rótulos, chips o nombres de producto.
- **Don't** dibujar marcos con `border` doble o con imágenes de marco completo; el marco es `box-shadow` inset y sólo las esquinas son pintura.
- **Don't** parecerse a knunet.com ni a blackseam.knunet.com: nada de HUD ámbar, sectores ni placas técnicas.
