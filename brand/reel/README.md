# Plantilla Duelo

Desde la raíz del repo, generá el video y el texto del post con:

```powershell
python brand/reel/hacer_reel.py
```

Necesitás Python 3.13, las dependencias de `brand/reel`, ffmpeg en PATH y Piper con el modelo Daniela en las rutas indicadas en el script. Los dos archivos diarios de precios deben tener la fecha de hoy en Argentina; también se controla `checked` en cada precio. El catálogo aporta nombres, categorías y elegibilidad, nunca precios de respaldo.

El cálculo replica `estimateFromAmazon` y el redondeo de `mergeAmazonPrices`: MEP de DolarAPI, envío de USD 45 debajo de USD 100, franquicia de USD 400, derechos del 35% y tasa del 3% sobre el excedente, IVA del 21% y adicional de Amazon del 4%. Se aborta si falta la cotización. El conteo del cierre incluye los productos comparables de hoy, igual que el sitio.

`src/duelo.json` contiene todas las props editables. Inicialmente reproduce el contenido de Reel 1 y usa sus audios; el generador lo reemplaza con seis WAV medidos y subtítulos de 2 a 4 palabras. Los ganadores respetan el criterio del sitio y se eligen por ahorro porcentual, con foto local y sin repetir los últimos seis Reels. `historial.json` incluye Reel 1 y sólo agrega una entrada después de completar video, normalización y caption.

Salidas: `out/duelo-AAAA-MM-DD.mp4`, `out/duelo-AAAA-MM-DD-final.mp4` y `out/duelo-AAAA-MM-DD.txt`. `out/` y `node_modules/` están ignorados. Una nueva ejecución exitosa el mismo día reemplaza las salidas de esa fecha y cuenta como otro Reel en el historial.

Validación local:

```powershell
cd brand/reel
python -m unittest -v
npx tsc --noEmit
```

Las pruebas contrastan el cálculo con las funciones TypeScript originales y prueban el flujo con datos sintéticos y subprocesos simulados. Para revisar sólo la plantilla inicial sin precios actuales: `npx remotion render Duelo out/duelo-plantilla-prueba.mp4`. Ese video es una prueba con el contenido inicial; no es un relevamiento del día.
