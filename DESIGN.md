# DESIGN.md — Sistema Visual de FRANQUICIA 400 · KnuNet

## 1. Dirección Visual y Mundo
**Arquetipo:** *Despacho Aduanero & Laboratorio Técnico* (fusión de `industrial-brutalist-ui` Swiss Industrial Print / Tactical Telemetry + el sistema de señalética e ingeniería de `knunet.com`).

El sitio evita por completo los clichés de plantillas generadas por IA (fondos `slate-950` con texto en gradiente verde/cian, tarjetas redondeadas flotantes con sombra difusa, íconos de Lucide, emojis de fueguitos o banderas, y etiquetas `uppercase` en cada bloque). En su lugar, la interfaz se comporta como una **planilla técnica de despacho e inspección de hardware**: grilla ortogonal de `1px` vista a través de líneas divisorias (`gap: 1px`), esquinas a 90° (`border-radius: 0`), sellos de clasificación arancelaria en esténcil, números tabulares en tipografía condensada y monoespaciada, y fotografías reales de producto sobre placas limpias.

## 2. Paleta Dual (Modo Manifiesto / Modo HUD)
El sitio mantiene **Page Theme Lock** estricto en toda la página y ofrece conmutación instantánea entre dos sustratos coherentes con el universo KnuNet:

### Sustrato A — Modo Manifiesto (Swiss Industrial Print · Claro por defecto / configurable)
| Token | Valor | Rol | Contraste sobre `--bg` |
|---|---|---|---|
| `--bg` | `#F2EFE9` | Papel manifiesto sin blanquear | — |
| `--bg-alt` | `#E8E3D9` | Celda secundaria / cabecera de tabla | — |
| `--surface` | `#FAF8F4` | Placa de producto e inputs | — |
| `--line` | `#CEC8BA` | Grilla estructural 1px | — |
| `--line-strong` | `#181614` | Marco principal y separadores de bloque | 15.6:1 |
| `--ink` | `#141311` | Tinta carbón principal | 16.2:1 (AAA) |
| `--muted` | `#524D46` | Texto técnico secundario | 6.8:1 (AA+) |
| `--accent` | `#C83E0B` | Naranja precinto aduanero (CTAs, alertas, foco) | 5.1:1 (AA) |
| `--accent-hi` | `#E04812` | Hover de acción primaria | — |
| `--ok` | `#146338` | Verde arancel 0% / franquicia verificada | 6.4:1 (AA) |
| `--ok-bg` | `#E3F1E8` | Fondo de sello arancel 0% | — |

### Sustrato B — Modo HUD (Tactical Telemetry · KnuNet Dark)
| Token | Valor | Rol | Contraste sobre `--bg` |
|---|---|---|---|
| `--bg` | `#110C08` | Fondo CRT oscuro cálido (`knunet.com`) | — |
| `--bg-alt` | `#18110B` | Celda secundaria | — |
| `--surface` | `#1F160E` | Placa activa / panel | — |
| `--line` | `#33251A` | Grilla estructural 1px | — |
| `--line-strong` | `#4A3522` | Marco de módulo y separador fuerte | — |
| `--ink` | `#ECD9BD` | Fósforo hueso para lectura | 12.8:1 (AAA) |
| `--muted` | `#A88F70` | Texto secundario cálido | 5.6:1 (AA) |
| `--accent` | `#FFA82E` | Ámbar KnuNet principal | 8.9:1 (AAA) |
| `--accent-hi` | `#FFC06A` | Títulos y foco activo | 11.4:1 (AAA) |
| `--ok` | `#5CE08A` | Indicador de franquicia activa | 9.8:1 (AAA) |
| `--ok-bg` | `#13291B` | Fondo de sello arancel 0% | — |

## 3. Tipografía (100% Self-Hosted vía `@fontsource`)
- **Display & Titulares Estructurales (`--font-cond`):** `Barlow Condensed` (600, 700). Mayúsculas en cabeceras de módulo, `line-height: 0.94`, `letter-spacing: -0.01em`.
- **Sellos y Nomenclador (`--font-stencil`):** `Saira Stencil One` (400). Reservado para la marca (`F400`), códigos de sector y timbrados aduaneros (`ARCA · RG 5617`).
- **Cuerpo Editorial (`--font-sans`):** `Barlow` (400, 500, 600). Medida de lectura controlada (`60-72ch`), `line-height: 1.55`.
- **Telemetría, Precios y Fórmulas (`--font-mono`):** `JetBrains Mono` (400, 500, 700) con `font-variant-numeric: tabular-nums`. Todos los importes en USD, ARS, porcentajes de ahorro y códigos ASIN usan monoespaciada tabular.

## 4. Reglas de Grilla, Componentes y Anti-Slop
1. **Grilla de plano mecánico:** Contenedor máximo de `1240px`, grilla de 12 columnas y bloques modulares unidos por bordes de `1px solid var(--line)` (`border-radius: 0px`).
2. **Restricción de Eyebrows:** Máximo 1 rótulo de sector cada 3 secciones (`design-taste-frontend` §4.7). Los encabezados se sostienen por jerarquía tipográfica.
3. **Cero rayas largas (`—` / `–`) y cero emojis:** Prohibidos en todo el código y textos. Se usan íconos técnicos de `@phosphor-icons/react` con trazo consistente (`weight="bold"` o `"regular"`).
4. **Fotografía real de hardware:** Cada producto utiliza su imagen real de estudio servida localmente desde `/products/<id>.jpg` sobre placa limpia con código ASIN e indicador de tensión eléctrica.
5. **Movimiento (`emil-design-eng`):**
   - Curvas: `--ease-out: cubic-bezier(0.23, 1, 0.32, 1)`, `--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1)`, `--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1)`.
   - Transiciones de interfaz `<= 200ms` (color, borde, transformaciones sutiles).
   - Respuesta táctil `:active` con `transform: scale(0.98)`.
   - Miras esquineras (`::before`) en tarjetas técnicas sólo en dispositivos con puntero fino (`@media (hover: hover) and (pointer: fine)`).
   - Respeto total a `@media (prefers-reduced-motion: reduce)`.
