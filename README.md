# App Matrixify Multimarca

Aplicacion Streamlit para convertir un Excel input de productos a una salida Matrixify expandida por talla. El flujo esta organizado por sitio destino para conservar IDs desde el ultimo catalogo Matrixify de cada tienda.

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

Para probar conexion Shopify por sitio, agrega las credenciales en Secrets:

```toml
[shopify_sites.columbia]
shop_domain = "columbiape.myshopify.com"
client_id = "..."
client_secret = "..."
admin_access_token = "..."
api_version = "2026-04"
```

Repite la estructura para `rockford` y `hush_puppies`. Si `admin_access_token`
esta vacio, la app intentara obtener token con `client_id` y `client_secret`.

Tambien puedes agregar una lista de tipos/familias actuales de Shopify para que el archivo final avise si aparece un tipo nuevo:

```text
data/tipos_shopify.xlsx
```

Puede ser una sola columna con encabezado `Tipo`, `Familia`, `Prenda` o similar.

3. Ejecutar la app:

```powershell
streamlit run app_matrixify.py
```

4. Elegir sitio destino en el sidebar.

La app trae perfiles cerrados para:

- Columbia.pe: permite Columbia.
- Rockford.pe: permite Columbia, Rockford, Patagonia, Sorel y Mountain Hardwear.
- HushPuppies.pe: permite Hush Puppies, Hush Puppies Kids, Accesorios HP, Keds y Rockford.
- Vans.pe: permite Vans.

El vendor, dominio Sial, carpeta de fotos y marcas permitidas se definen por sitio en el codigo para evitar cargas cruzadas.

5. Cargar archivos:

- Excel input de productos.
- Ultimo catalogo Matrixify del sitio elegido. Es obligatorio para conservar Product ID y Variant ID, y evitar duplicados.

6. Presionar **Generar Matrixify** y descargar el Excel final.

## Actualizaciones puntuales

En el sidebar puedes cambiar **Tipo de operacion** a **Actualizacion puntual**.
Este modo genera archivos Matrixify livianos, solo con los campos necesarios:

- **Tags**: sube `Mod-Col` y `Tags`; permite agregar a los tags actuales o reemplazarlos.
- **Fotos 10 vistas**: usa el catalogo Matrixify y ARTI para generar URLs correctas por marca; permite reemplazar o mezclar fotos.
- **Siblings**: recalcula `Metafield: theme.siblings` con todos los handles que comparten el mismo codigo modelo.
- **Titulo**: sube `Mod-Col` y `Title`.
- **Body HTML / Material / Cuidado**: reconstruye desde input comercial o detecta Material/Cuidado mezclados en el catalogo.

## Logica actual

- Lee el ARTI desde BigQuery cuando existen secretos configurados.
- Si BigQuery no esta configurado, usa `data/arti.zip`, `data/arti.csv` o `data/arti.xlsx`.
- Hace match entre input y ARTI por `Mod-Col` o `COD MOD COL`.
- Usa tallas, SKUs, precios y codigos de barra desde ARTI.
- Omite variantes con talla `0`.
- Ordena tallas tipo `XS, S, M, L, XL, XXL`, tallas numericas y tallas reales.
- Filtra ARTI por las marcas permitidas del sitio cuando existe la columna `MARCA_MA`.
- Valida marcas del input si existe columna `Marca`, `Brand`, `Vendor` o similar.
- Valida que el catalogo Matrixify cargado tenga el vendor esperado del sitio cuando existe columna `Vendor`.
- Genera hojas de salida Matrixify, Carga Sial, resumen, revision, tipos nuevos y omitidos sin cambios.
- Usa vendor, dominio Sial y carpeta de fotos segun el sitio elegido.

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
