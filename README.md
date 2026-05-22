# Conversor Matrixify por Tallas

Aplicacion Streamlit para convertir un Excel input de productos a una salida Matrixify expandida por talla.

## Como usar

1. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

2. Configurar el maestro `arti`.

La app primero intenta leer el ARTI desde BigQuery. Para desarrollo local, crea:

```text
.streamlit/secrets.toml
```

Puedes copiar la estructura desde:

```text
.streamlit/secrets.example.toml
```

Si BigQuery no esta configurado, la app usa el respaldo local:

```text
data/arti.zip
```

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
- Opcional: descarga Matrixify reciente para conservar IDs y detectar productos sin cambios.

5. Presionar **Generar Matrixify** y descargar el Excel final.

## Logica actual

- Lee el ARTI desde BigQuery cuando existen secretos configurados.
- Si BigQuery no esta configurado, usa `data/arti.zip`, `data/arti.csv` o `data/arti.xlsx`.
- Hace match entre input y ARTI por `Mod-Col` o `COD MOD COL`.
- Usa tallas, SKUs, precios y codigos de barra desde ARTI.
- Omite variantes con talla `0`.
- Ordena tallas tipo `XS, S, M, L, XL, XXL`, tallas numericas y tallas reales.
- Genera hojas de salida Matrixify, Carga Sial, resumen, revision, tipos nuevos y omitidos sin cambios.

## Columnas requeridas en BigQuery

La tabla o query debe entregar estas columnas:

```text
CODINT_MA
COD MOD COL
Mod-Col
TALNUM_MA
MARCA_MA
Precio
CodBarras
```
