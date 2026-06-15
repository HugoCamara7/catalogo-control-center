# Entrega funcional - Catalogo Control Center

Fecha: 10/06/2026

## Objetivo

Aplicacion operativa para controlar catalogo Shopify por sitio/marca, generar archivos Matrixify, generar Centry completo y revisar KPIs de stock, creacion, visibilidad y bases comerciales.

## Alcance actual

- Login de acceso para usuarios autorizados.
- Seleccion de sitio activo y marcas permitidas.
- KPIs de catalogo con datos de Shopify, BigQuery y stock eComm.
- Generacion de Matrixify para carga completa y parcial.
- Generacion de Centry desde codigos modelo-color.
- Vista previa de Matrixify, Centry, observaciones y validaciones.
- Conexion con Shopify Admin API.
- Lectura de BigQuery como fuente maestra.
- Fallback de maestros estaticos embebidos para categorias, dimensiones y parametros Centry.

## Fuentes de datos

### BigQuery

Proyecto de ejecucion sugerido:

```toml
project_id = "forus-pe-shared-prod-ti"
location = "us-central1"
```

Maestro de productos:

```toml
table = "forus-analitica-prod-datalake.bronze.stg_pe_central_arti"
```

Stock:

```toml
stock_query = """
SELECT ...
FROM `forus-analitica-prod-datalake.bronze.stg_pe_central_stock_bi`
"""
```

Campos criticos esperados desde maestro:

- SKU interno variante: `CODINT_MA` o equivalente.
- Modelo-color: `COD MOD COL`, `Mod-Col`, `codmod_codcol` o construido desde modelo + color.
- Talla: `TALNUM_MA` o equivalente.
- Marca: `MARCA_MA` o equivalente.
- Precio: `Precio` o equivalente.
- Codigo de barras/EAN: `CodBarras`, `CODBAR_MA`, `EAN`, `EAN13`, `UPC`, `GTIN`, `codigo_barras` o equivalente.

La app detecta variantes de nombres para EAN/barcode, incluyendo columnas tipo `CODBAR_MA`, `EAN13_MA`, `codigo_barra_producto`, `UPC` y `GTIN`.

### Shopify

Configuracion por sitio en Streamlit secrets:

- `shop_domain`
- `admin_access_token`
- `api_version`

La app consulta productos, variantes, precios, inventario, imagenes, estado publicado y visibilidad.

### Maestros locales embebidos

Carpeta `data/`:

- `base_categorias_centry.xlsx`
- `centry_codex_categorias.xlsx`
- `dimensiones_productos.xlsx`
- `bodegas_ecomm.xlsx`
- `tipos_shopify.xlsx`
- `matrixify_modelo.xlsx`
- `arti.zip` como respaldo local

Archivo generado:

- `centry_static_masters.py`

## Reglas de negocio importantes

- El EAN es obligatorio para Centry. Si falta EAN, no se debe considerar listo.
- El EAN no es igual al SKU. SKU interno y codigo de barras son campos distintos.
- En vestuario y calzado no se debe usar talla `000`.
- En accesorios, si conviven `0`, `000` y `O/S`, se conserva `O/S`.
- No se deben cargar marcas que comienzan con `K` cuando correspondan a codigos internos no comerciales.
- Las fotos para Centry deben usar el formato original/marketplace utilizado para carga inicial, no la URL transformada de Shopify.
- Vendor, marca, tallas, precio, EAN y categorias deben completarse desde BigQuery/maestros, no manualmente.
- En carga parcial de Centry, el usuario sube codigos modelo-color faltantes y la app devuelve Excel Centry listo.
- En carga completa Matrixify, tambien debe generarse hoja Centry cuando aplique.

## Salidas esperadas

### Matrixify

Archivo Excel con hojas principales para carga Shopify/Matrixify, resumen, issues, advertencias y registros omitidos.

### Centry

Archivo Excel con todos los campos comerciales requeridos:

- Categoria
- Precio
- SKU del producto
- SKU de la variante
- Codigo de barra variante
- Color
- Talla
- Condicion
- Temporada
- Marca
- Dimensiones
- Imagenes
- Campos comerciales adicionales segun plantilla Centry

### Vistas previas

La app muestra:

- KPIs principales.
- Checklist comercial web.
- Vista previa Matrixify.
- Vista previa Centry.
- Observaciones y bloqueos.

## Archivos principales

- `app_matrixify.py`: interfaz Streamlit, login, KPIs, vistas, carga parcial/completa, Shopify API y BigQuery helpers.
- `generate_columbia_matrixify.py`: motor principal de generacion Matrixify/Centry.
- `shopify_api.py`: cliente Shopify Admin API.
- `centry_static_masters.py`: maestros Centry embebidos.
- `requirements.txt`: dependencias.
- `.streamlit/secrets.example.toml`: plantilla sin credenciales reales.
- `assets/brands/`: logos por marca.
- `scripts/`: utilitarios de conversion.

## Recomendacion para migracion a Power Apps

Separar en 4 capas:

1. Power Apps: interfaz, login, seleccion de sitio/marca, carga de archivos y botones.
2. Power Automate: orquestacion de procesos largos, generacion de Excel y envio de respuestas.
3. Azure Function o Cloud Run: ejecutar la logica Python actual de Matrixify/Centry.
4. Conectores: BigQuery, Shopify Admin API y almacenamiento de archivos.

No recomiendo rehacer toda la logica compleja dentro de Power Fx. La parte de normalizacion de tallas, EAN, categorias, Matrixify y Centry debe vivir como servicio Python para reducir riesgo.

## Variables/secretos que se deben migrar

- Credenciales de BigQuery o service account.
- Shopify Admin API token por sitio.
- Dominios Shopify por sitio.
- Version de API Shopify.
- Tabla BigQuery maestra.
- Query de stock.
- Parametros por marca/sitio.

## Validaciones antes de salir a produccion

- Probar carga Columbia en Columbia.pe.
- Probar Sorel, MHW y Patagonia en Rockford.pe validando vendor real.
- Probar Vans en Vans.pe.
- Probar carga parcial Centry con codigos modelo-color.
- Validar que EAN no salga vacio.
- Validar que no existan `#ND`.
- Validar precios y variantes Shopify.
- Validar que todas las variantes tengan SKU y barcode cuando aplique.
- Validar tallas y exclusion de `000`.
- Validar fotos con nombre real de marca.

