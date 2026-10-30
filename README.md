# FRANQUICIA 400 · KnuNet (`weboffers`)

Despachante digital de hardware, comparador técnico lado a lado y simulador aduanero para el régimen **Courier Internacional Privado hacia Argentina (Decreto 1065/2024 y RG ARCA 5617/2024: franquicia de USD 400 FOB exenta de derechos de importación y tasa estadística)** monetizado mediante **Amazon Associates EE.UU. (`amazon.com`) y España (`amazon.es`)**.

Dominio productivo objetivo: `https://ofertas.knunet.com`

---

## 1. Arquitectura y módulos incluidos

1. **Catálogo de Ofertas Auditadas (Amazon US y Amazon ES):**
   - Conexión en vivo a `dolarapi.com` para obtener las cotizaciones del **Dólar MEP (Bolsa)** y **Dólar Tarjeta**.
   - Cálculo de liquidación aduanera completa: Valor FOB, flete internacional AmazonGlobal, base CIF, derechos de importación (0% hasta USD 400 FOB; 35% sobre excedente), tasa estadística (0% hasta USD 400 FOB; 3% sobre excedente) e IVA Aduanero (10.5% para bienes de informática/capital o 21% régimen general).
   - Comparativa directa en Pesos Argentinos (ARS) frente al precio promedio minorista en tiendas locales y diferencia entre cancelar el resumen con USD MEP vs Dólar Tarjeta.
   - Fotografías reales de estudio alojadas localmente en `public/products/*.jpg` (sin hotlinking externo ni dependencias de stock genérico).
2. **Simulador de Liquidación Aduanera Courier (USD 400 FOB):**
   - Permite ingresar cualquier valor FOB y flete de Amazon, elegir alícuota de IVA (10.5% o 21%), visualizar el desglose completo de impuestos y ejecutar búsquedas en `Amazon.com` o `Amazon.es` con el tag de afiliado inyectado.
3. **Matriz Comparativa Lado a Lado (hasta 4 unidades):**
   - Comparación técnica y arancelaria simultánea con especificaciones de tensión eléctrica para Argentina (220V 50Hz / 110-240V), código NCM y acceso directo al despacho en Amazon.
4. **Sistema Visual Dual (Manifiesto Impreso / HUD Carbono):**
   - `Modo Manifiesto` (`#F2EFE9`, papel técnico aduanero) por defecto y `Modo HUD` (`#110C08`, carbono industrial KnuNet) con persistencia en `localStorage`.
   - Tipografías auto-hospedadas vía `@fontsource` (`Barlow`, `Barlow Condensed`, `Saira Stencil One`, `JetBrains Mono`) e iconografía técnica `@phosphor-icons/react`.
5. **Cumplimiento Normativo y Legal Integrado:**
   - Divulgación obligatoria del **Acuerdo Operativo de Amazon Associates (Sección 5)** visible en el primer pantallazo y en el pie de página.
   - Pliegos legales completos accesibles desde toda la interfaz: Política de Privacidad (Ley 25.326 Argentina + RGPD), Política de Cookies con panel configurable de consentimiento y Términos de Uso del Simulador.
6. **Worker Automatizado para Raspberry Pi 4 (`pi4-worker/`):**
   - Contenedor Docker liviano en Python (`arm64`) que consulta el Dólar MEP del día, calcula la liquidación de ofertas y las publica en un canal de Telegram con enlaces de afiliado.

---

## 2. Configuración de Amazon Associates y cobro en USD

1. **Cuenta receptora en EE.UU. (ACH):**
   - Configurá una cuenta receptora en EE.UU. (Routing Number y Account Number ACH) en plataformas como Wallbit, Takenos o Payoneer.
2. **Registro en Amazon Associates:**
   - Registrate en [Amazon Associates EE.UU.](https://affiliate-program.amazon.com/) y en [Amazon Afiliados España](https://afiliados.amazon.es/) declarando el dominio `https://ofertas.knunet.com`.
   - Completá el formulario fiscal digital **W-8BEN** (persona física residente fuera de EE.UU.) y configurá el cobro por depósito directo ACH.
   - Configurá tus Tracking IDs en [`src/config/affiliate.ts`](./src/config/affiliate.ts) o mediante las variables de entorno `VITE_AMAZON_US_TAG` y `VITE_AMAZON_ES_TAG`.

---

## 3. Comandos de desarrollo, activos de marca y despliegue

```bash
# Instalar dependencias
npm install

# Iniciar servidor local de desarrollo
npm run dev

# Regenerar kit de identidad de marca (SVG, ICO, PNG, OpenGraph 1200x630 y Brandboard)
node brand/generate-brand-assets.mjs

# Verificar tipos TypeScript y compilar versión de producción (dist/)
npx tsc --noEmit
npm run build

# Desplegar en Cloudflare Workers Static Assets
npx wrangler deploy
```
