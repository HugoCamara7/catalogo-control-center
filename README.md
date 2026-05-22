# Conversor Matrixify por Tallas

Aplicacion Streamlit para convertir un Excel input de productos a una salida Matrixify expandida por talla.

## Como usar

1. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

2. Opcional: dejar fijo el maestro `arti`.

Si quieres que la app lea siempre el mismo maestro, pega tu archivo en:

```text
data/arti.xlsx
```

Si prefieres probar con distintos maestros, no pegues nada y sube el `arti` desde la pantalla de la app.

Tambien puedes agregar una lista de tipos/familias actuales de Shopify para que el archivo final avise si aparece un tipo nuevo:

```text
data/tipos_shopify.xlsx
```

Puede ser una sola columna con encabezado `Tipo`, `Familia`, `Prenda` o similar.

3. Ejecutar la app:

```powershell
streamlit run app_matrixify.py
```

4. Cargar archivos:

- Excel input de productos.
- Excel maestro `arti`, solo si no dejaste fijo `data/arti.xlsx`.

5. Presionar **Generar Matrixify** y descargar el Excel final.

## Logica actual

- Detecta columnas frecuentes como `estilo`, `modelo`, `codigo`, `sku`, `marca`, `descripcion`, `precio`, `color`, `talla`, `ean`.
- Hace match entre input y `arti` por estilo/modelo/codigo.
- Si encuentra el producto en `arti`, usa sus tallas, SKUs y codigos de barra.
- Si no encuentra match, usa las tallas de respaldo configuradas en pantalla.
- Ordena tallas tipo `XS, S, M, L, XL, XXL`, tallas numericas y tallas reales.
- Genera una hoja `Matrixify`, una hoja `Revision` y una hoja `Mapeo detectado`.

## Siguiente mejora recomendada

Cuando tengas un input real y el archivo `arti`, conviene ajustar el mapeo exacto de columnas Matrixify segun tu plantilla final de Shopify/Matrixify.
