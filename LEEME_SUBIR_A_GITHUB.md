# Que subir a GitHub

Espejo completo de `HugoCamara7/catalogo-control-center` rama `main`, descargado
el 2026-08-02 despues de tus commits de las 09:29 UTC, con lo que falta aplicado
encima.

## Hay que subir 2 archivos

```
app_matrixify.py                 (nombres, enie, inventario en bloque, estado manual)
generate_columbia_matrixify.py   (tipos, subcategoria, acentos, WHERE del ARTI)
shopify_api.py                   (10 fotos, activacion en bloque, espera por costo)
ticket_system.py                 (reintento de guardado + cambio manual de estado)
```

Lo demas ya esta correcto en `main` y aqui queda igual. **No toques**
`catalog_rules.py` ni los tests: ya estan bien en tu repo.

---

## Problema 1: se revirtio el paquete de nombres

Hoy subiste dos paquetes seguidos:

| Commit | Hora UTC | Contenido |
|---|---|---|
| `118ae43c0` | 09:25 | mi entrega de nombres/handle/bullets (app `+16/-7`) |
| `88276e508` | 09:29 | tipos de prenda (app `+7/-16`, catalog_rules `+791/-632`) |
| `b1cb8d31d` | 09:29 | `scripts/test_tipos_de_prenda.py` |

El paquete de tipos de prenda venia armado sobre un `app_matrixify.py` anterior,
asi que su `+7/-16` **deshizo exactamente** el `+16/-7` del anterior. Por eso los
nombres dejaron de funcionar: `generate_columbia_matrixify.py` si quedo con los
cambios, pero `app_matrixify.py` volvio atras.

Nada de tipos de prenda se perdio: ese paquete solo cambiaba `catalog_rules.py`
y los tests; su `app_matrixify.py` era byte a byte identico al base.

**Solucion:** este `app_matrixify.py` vuelve a traer los 4 cambios:

1. Importa `MissingInputColumnError` y `split_pipe_items` del generador.
2. `_split_tags` delega en `split_pipe_items` en vez de tener su propia regla.
3. Al crear producto en Shopify ya no cae a `title=... or handle`: si el Title
   viene vacio, ese producto falla con mensaje claro en vez de crearse con el
   codigo modelo-color como nombre.
4. Captura `MissingInputColumnError` antes del `except Exception` generico.

---

## Problema 2: los tipos de prenda no se estaban leyendo

Las 24 reglas de `PRODUCT_TYPE_RULES` no llegaban a la carga. Dos causas:

**a) La carga lee otro diccionario.** `load_known_types()` leia solo
`data/tipos_shopify.xlsx` (54 tipos), nunca `catalog_rules.py`. Siete de tus 24
tipos no estaban en ese archivo: `Bolsos`, `Correas`, `Cremas renovadoras`,
`Interiores Termicos`, `Polerones`, `Ropas de Bano`, `Slip Ons`.

**b) Las tildes no cruzaban.** `catalog_rules` escribe `Interiores Termicos` y
`Ropas de Bano`; el input y el xlsx escriben `Interiores Termicos` con tilde y
`Ropas de Bano` con enie. `normalize_compare` pasa a mayusculas pero **no quita
acentos**, asi que las dos fuentes no se reconocian entre si.

Resultado: en el input de Patagonia, 4 tipos perfectamente validos se reportaban
como "tipo nuevo".

**Solucion en `generate_columbia_matrixify.py`:**

- `normalize_type_key()` (nueva): clave de comparacion sin acentos, usada tanto
  al armar el diccionario como al buscar el tipo del producto.
- `catalog_rule_type_names()` (nueva): lee `PRODUCT_TYPE_RULES` con import
  protegido, para no romper si `catalog_rules` no esta disponible.
- `load_known_types()` ahora **suma las dos fuentes**. El diccionario pasa de 54
  a 69 tipos y la fuente reportada es
  `data/tipos_shopify.xlsx + catalog_rules.PRODUCT_TYPE_RULES`.

Con esto, agregar un tipo a `catalog_rules.py` ya alcanza para que la carga lo
reconozca; no hay que editar tambien el xlsx.

---

## Problema 3: la enie y las tildes se perdian

Auditoria de los 8 normalizadores de texto de la app pasando valores reales
("Nino", "Bano", "Pantalon", "Pinguino"). Cuatro perdian letras.

**El peor: `slugify()` de `app_matrixify.py`.** Solo reemplazaba las secuencias
mojibake (`Ã±`, `Ã¡`...), nunca los caracteres reales. Resultado:

```
"Casaca Nino"  ->  casaca-ni-o      (perdia la enie)
"Ropas de Bano" ->  ropas-de-ba-o
"Ano"          ->  a-o
```

Se usa en la linea 1329 para armar el handle con vendor + title + style +
color, asi que cualquier producto infantil o de bano salia con el handle roto.

**Los otros tres** (`normalize_text` del generador, que arma los handles;
`normalize_header_key` y `normalize_header_loose_key`, que detectan columnas)
cubrian a/e/i/o/u y la enie con una lista escrita a mano, pero **no la
dieresis**: "Pinguino" perdia la u y quedaba "ping-ino".

**Solucion:** `fold_accents()` (nueva, en el generador) usa
`unicodedata.normalize("NFKD")` y quita las marcas diacriticas, en vez de una
lista que siempre se queda corta. Cubre tildes, dieresis, enie, cedilla y
acentos graves. No es un criterio inventado: `catalog_rules.py` ya lo hacia
asi, y ahora los tres modulos coinciden.

Se aplico a `normalize_text`, `normalize_header_key`,
`normalize_header_loose_key`, `normalize_type_key` y al `slugify` del app, que
ademas repara el mojibake antes de doblar los acentos.

**Extra:** `read_csv_any_encoding()` (nueva) para leer el ARTI probando
utf-8-sig, utf-8, cp1252 y latin-1. Los export del ERP a veces salen en cp1252
y pandas, que asume UTF-8, revienta o deja mojibake justo en las palabras con
tilde.

### Resultado de la auditoria

| Normalizador | Antes | Ahora |
|---|---|---|
| `app.slugify` | perdia en 18 de 20 casos | OK |
| `gen.normalize_text` (handles) | perdia la dieresis | OK |
| `gen.normalize_header_key` | perdia la dieresis | OK |
| `gen.normalize_header_loose_key` | perdia la dieresis | OK |
| `gen.normalize_type_key` | OK | OK |
| `cr.normalize_key` | OK | OK |
| `cr.slugify_catalog_value` | OK | OK |

Ejemplos ahora, y los dos slugificadores coinciden:

```
Casaca Nino Columbia  ->  casaca-nino-columbia
Ropas de Bano         ->  ropas-de-bano
Short Bano Nina       ->  short-bano-nina
Pinguino              ->  pinguino
```

### Las tildes se conservan donde deben

En la corrida de Patagonia, los acentos sobreviven el recorrido completo y el
Excel escrito y releido queda identico:

| Campo | Productos que conservan tilde/enie |
|---|---|
| Body HTML | 252 de 252 |
| Metafield materialidad | 250 de 252 |
| Tags | 44 de 252 |
| Title | 35 de 252 |
| Image Alt Text | 35 de 252 |

Y en los handles: 0 con caracteres raros, 0 con formato invalido, 0 con letras
perdidas. Mojibake residual (`Ã`, `Â`, `â€`) en Title, Body y materialidad: 0.

Tambien se reviso que ningun `open()`, `read_text()` ni `to_csv()` quede sin
codificacion declarada, y que los `json.dumps` que viajan a Shopify no escapen
las tildes.

---

## Problema 4: velocidad

### El WHERE del ARTI (la ganancia grande)

La consulta a BigQuery filtraba por marca pero **no por los productos del
input**. Para Rockford bajaba el maestro completo de las cinco marcas del sitio
y el filtro real ocurria despues, ya en memoria:

```python
arti = arti[arti["__KEY"].isin(wanted_keys)]   # tarde
```

Ahora los Mod-Col del input viajan hasta el propio WHERE, igual que ya se hacia
en `app_matrixify.py` linea 1148 para los codigos de barras. Se verifico con un
cliente de BigQuery simulado, para las dos formas de tabla que soporta el codigo:

```sql
-- tabla con la columna de mod-col directa
UPPER(CAST(`COD_MOD_COL` AS STRING)) IN UNNEST(@mod_cols)

-- tabla con modelo y color separados
UPPER(CONCAT(CAST(`codmod_ma` AS STRING), '-', CAST(`codcol_ma` AS STRING))) IN UNNEST(@mod_cols)
```

La lista va como parametro (`ArrayQueryParameter`), en mayusculas, sin repetidos
y sin vacios. Piezas nuevas: `_normalized_mod_cols()` y `mod_cols_from_input()`.
La clave de cache de sesion incluye un hash de la lista, asi que cambiar de
input vuelve a consultar en vez de devolver datos de otro archivo.

Si tienes una `query` propia configurada en secrets, ese camino queda como
estaba: no se le puede agregar el filtro sin saber como se llama la columna en
tu consulta.

### Lo demas que se optimizo

- **`clean()` y `clean_value()`**: camino rapido para texto. Se llaman ~163.000
  veces por corrida y cada llamada entraba a `pd.isna()`. Se verifico que el
  resultado no cambia para texto, vacio, None, NaN, NaT, int, float, listas,
  diccionarios y booleanos.
- **`lru_cache`** en `fold_accents`, `normalize_header_key` y
  `normalize_header_loose_key`: se llaman miles de veces con los mismos nombres
  de columna.
- **`_column_key_maps()`** (nueva): el mapa de columnas a su clave normalizada
  se calcula una vez por juego de columnas. Antes `row_alias_value` lo rearmaba
  en cada llamada, corriendo la normalizacion Unicode sobre todas las columnas.
- **`__TITLE` y `__HANDLE_COLOR`** se resuelven por columna, una vez por
  archivo, en vez de fila por fila.
- **`find_technology_column()`** salio del bucle de
  `fill_top_row_product_fields`. Esto ya estaba mal desde antes de esta entrega:
  se recalculaba una vez por producto.

### Resultado

Mismo input de 252 productos, corridas alternadas y descartando la primera:

| Version | Minimo | Mediana |
|---|---|---|
| main de julio | 6,50 s | 6,67 s |
| esta entrega | **5,15 s** | 5,19 s |

**21% mas rapido que julio**, y eso generando 42% mas contenido:

| | main de julio | esta entrega |
|---|---|---|
| Titles generados | 0 | 252 |
| Tags generados | 0 | 252 |
| Bullets del Body HTML | 504 | 3.094 |
| Textos alt de imagen | 252 | 2.520 |
| Caracteres de contenido | 410.008 | 583.928 |

El main de julio "terminaba antes" en parte porque dejaba el Title y los Tags
vacios y armaba un solo bullet.

Nota sobre las mediciones: los tiempos absolutos varian bastante segun la carga
de la maquina. Lo que vale es la relacion, medida alternando las dos versiones
en la misma corrida.


### Lectura del catalogo de Shopify

- **`media(first: 20)` paso a `media(first: 10)`.** El generador ya usaba
  `MAX_IMAGES_PER_PRODUCT = 10`, asi que pedir 20 traia el doble de datos por
  producto para descartar la mitad.

- **Espera segun el costo real, no a ciegas.** Shopify cobra por costo de
  consulta con un balde que se recarga a ~50 puntos/segundo, e informa en cada
  respuesta cuanto queda y a que velocidad se recarga. El cliente dormia
  `1.5 * intento` sin mirar ese dato: a veces esperaba de mas, y a veces de
  menos y gastaba un reintento. Ahora `_throttle_wait_seconds()` calcula la
  espera justa. Si Shopify no manda el dato, se comporta como antes.

- **`ULTIMO_COSTO_GRAPHQL`** guarda el ultimo informe de costo, para poder ver
  si la lentitud viene de throttling y no de la red.

- **Tamano de pagina configurable.** Una pagina de 250 productos con sus
  variantes y fotos es una consulta muy cara. Se puede bajar desde Secrets:

  ```toml
  [shopify]
  products_page_size = 50
  ```

  Por defecto sigue en 250, asi que no cambia nada hasta que lo ajustes.

**Esto ultimo no esta medido contra tu tienda.** Es el unico cambio de esta
entrega que no pude verificar con datos reales: hace falta correr una carga y
mirar si el costo informado se acerca a cero.


### Activacion de inventario en sucursales (el cuello real)

Era, por cada producto:

- **1 consulta por variante** para ver en que sucursales estaba activa
- **1 mutacion por cada par (variante, sucursal)**

Con 10 tallas y 8 sucursales, ~90 llamadas por producto. Por 252 productos,
mas de 20.000 llamadas a la API. Dos cambios lo colapsan:

1. **Las sucursales activas ya vienen en la consulta del producto.**
   `fetch_product_options_and_variants` pedia `inventoryItem` pero no sus
   `inventoryLevels`, asi que despues se preguntaba variante por variante. Ahora
   llegan en la misma consulta que ya se hacia: **cero consultas extra**.

2. **`inventory_bulk_activate()` (nueva)**: usa
   `inventoryBulkToggleActivation`, la mutacion de Shopify que activa un
   inventory item en varias sucursales de una sola llamada. Una llamada por
   variante en vez de una por sucursal.

Medido con un cliente simulado, 10 variantes x 8 sucursales:

| | antes | ahora |
|---|---|---|
| Consultas por variante | 10 | **0** |
| Mutaciones | 80 | **10** |
| **Total de llamadas** | **90** | **10** |

**9 veces menos llamadas**, con el mismo reporte fila por sucursal (80 filas) y
los mismos estados OK / ACTIVO / ERROR / PENDIENTE.

Se verificaron los caminos de error:

- Error de permisos: corta de inmediato (8 filas, no 80) con el mensaje sobre
  `write_inventory`.
- Error normal en una variante: sigue con las demas (32 OK + 8 ERROR de 40).
- Tope `max_actions=20`: respeta el limite exacto (20 OK, 60 PENDIENTE).

Si `inventory_bulk_activate` no existiera (por ejemplo si se sube un
`shopify_api.py` viejo), vuelve solo al camino de a una sucursal por vez.

### Lo que no se toco, y por que

Queda el resto de la sincronizacion: crear el producto, publicarlo, las
variantes y las fotos. Eso sigue siendo una llamada por paso y por producto, y
es tiempo de red. Como el criterio es que siempre se actualice todo, procesa el
catalogo completo cada vez, por diseno.

La palanca que queda ahi es procesar varios productos en paralelo en vez de uno
por uno. No esta hecho: cambia el manejo de errores y el reporte de avance, y
preferi no mezclarlo con esta entrega. Ninguna de estas palancas es mas RAM.

---

## Problema 5: la subcategoria salia de otra fuente

`TYPE_COLUMNS` no incluia `Tipo de prenda`, que es como lo nombran los formatos
de input. Al no encontrar la columna, la variable quedaba vacia y el codigo caia
a buscar el tipo **en el ARTI**, que es otra fuente:

```
TYPE_COLUMNS encontraba en el input:  None
Columna real:                         'Tipo de prenda'
row_alias_value(TYPE_COLUMNS)   ->    ''      (vacio)
metafield custom.tipo           ->    'Polares'  (correcto)
```

Esa variable alimenta dos cosas: la columna `Type` de Shopify y el metafield
`custom.sub_categoria`. Por eso `custom.tipo` salia bien (esa busqueda si lista
"Tipo de prenda") pero la subcategoria salia de otro lado.

**Solucion:** se agregan `Tipo de prenda`, `Tipo de Prenda` y `Tipo prenda` a
`TYPE_COLUMNS`, antes de `Categoria` para que el tipo mande sobre la clase.

Resultado sobre los 252 productos de Patagonia:

| Control | Resultado |
|---|---|
| `Type` vacio | 0 |
| `sub_categoria` vacia | 0 |
| `Type` igual a Tipo de prenda | 252 de 252 |
| `sub_categoria` igual a `custom.tipo` | 252 de 252 |

```
Mod-Col      Type          sub_categoria   categoria
20265-IKE    Polares       Polares         VESTUARIO
21218-N11    Pantalones    Pantalones      VESTUARIO
22397-ORH    Cuelleras     Cuelleras       ACCESORIOS
```

No regresion: Columbia, Hush Puppies y Vans siguen detectando la misma columna
que antes y dan 0 diferencias. Solo cambia Patagonia, que antes no encontraba
ninguna.

---

## Orden de tallas: verificado

Se probo metiendo las tallas **deliberadamente desordenadas** en 30 productos:

| Control | Resultado |
|---|---|
| Productos con tallas desordenadas | 0 de 30 |
| `XL S M L XS` revuelto | sale `XS S M L XL` |
| `36 30 38 32 34` revuelto | sale `30 32 34 36 38` |
| `Variant Position` consecutiva desde 1 | si |

Tambien se verifico `size_sort_key` con medias tallas de calzado
(`7 7.5 8 9 10 11.5`), tallas de nino (`2 4 6 8 10 12 14`) y `2XL` despues de
`XL`.

Hay dos redes: el orden se calcula al generar el Excel, y la sincronizacion
ejecuta ademas `product_variants_bulk_reorder` dentro de Shopify.

---

## Problema 6: el ticket quedaba trabado y no se podia finalizar

Dos sintomas que resultaron ser el mismo problema de fondo.

**"El ticket cambio en otra sesion. Recarga antes de continuar."**

Los tickets viven en GitHub (`backend = "github"`) y la revision que usa el
control de concurrencia es el **SHA del archivo**. Una sola accion encadena
varias escrituras y lecturas; por ejemplo `run_dry_run` hace tres escrituras y
dos lecturas seguidas. La API de contenidos de GitHub es eventualmente
consistente: una lectura hecha justo despues de una escritura puede devolver el
SHA anterior, y entonces la escritura siguiente sale con un SHA viejo.

`_save` no reintentaba: un solo SHA desfasado y el ticket quedaba trabado, sin
que nadie mas lo hubiera tocado. Por eso pasaba "a veces" y por eso reintentar
el mismo boton repetia la misma carrera.

**"La solicitud no esta lista para cargar" / no se podia cerrar**

Los botones de cierre (Finalizar carga, con observaciones, incidencia) solo
aparecen cuando el estado es `loading` o `validating`. Si la carga se ejecuto de
verdad en Shopify pero el ticket quedo atrasado en "Aprobada para carga", la
pantalla de cierre **no aparecia nunca** y no habia forma de finalizarlo.

### Solucion

- **`_save` reintenta** hasta 3 veces: relee la revision vigente y vuelve a
  guardar, con una espera corta entre intentos. Un conflicto real y persistente
  **sigue avisando** despues del tercer intento, no se oculta.
- **`set_status_manual()` (nueva)**: cambia el estado a mano, sin pasar por la
  maquina de transiciones. Solo operador o admin, exige un motivo, y queda en el
  historial como `status_changed_manual` con el usuario y el motivo. Graba
  `resolved_at` y `load_started_at` cuando corresponde.
- **Panel "Cambiar estado manualmente"** en la pantalla de cargas pendientes,
  visible solo para operador y admin.

Verificado: recupera de 2 conflictos seguidos, avisa al tercero, el rol marca no
puede usarlo, y un estado inventado se rechaza. Los 28 tests de
`test_ticket_system.py` y los 29 de `test_engines_ticket_flow.py` siguen pasando.

**Sobre el trade-off:** al reintentar, tu cambio pisa lo que hubiera escrito el
otro. En el caso real el "otro" es tu propia escritura anterior que aun no se
veia, asi que es correcto. Si algun dia dos personas editan el mismo ticket a la
vez, ganaria la ultima.

---

## Queda pendiente (no lo toque)

Hay codigo huerfano alrededor del formato de input comercial, anterior a esta
entrega:

```
_build_brand_commercial_input_workbook_legacy()   <- SIN LLAMADOR
  └─ _commercial_values_rows()
      └─ commercial_product_type_rules_for_brand()
          └─ PRODUCT_TYPE_RULES
```

La version viva es `build_brand_commercial_input_workbook()` (linea 2339,
llamada en 2753) y arma las hojas `PARA_COMPLETAR / EJEMPLO / COMO_LLENAR`.
La legacy armaba `INPUT_COMERCIAL / GUIA / DICCIONARIO`, y era la hoja
DICCIONARIO la que listaba los tipos de prenda para el usuario.

Consecuencias:

- La plantilla que descarga la marca **no ofrece la lista de tipos**. La carga ya
  los reconoce (Problema 2 resuelto), pero el usuario no los ve al llenar.
- `scripts/test_brand_commercial_input.py` falla porque espera las hojas viejas.
  No es un fallo de esta entrega: falla igual en `main` limpio.

Si quieres, en una entrega aparte conecto los 24 tipos a la plantilla viva y
actualizo ese test. No lo hice ahora para no mezclarlo con esto.

---

## Validacion ejecutada sobre esta carpeta

| Test | Resultado |
|---|---|
| test_engines_audit.py | 45 OK |
| test_separadores_lista.py | 42 OK |
| test_engines_normalize.py | 38 OK |
| test_engines_ticket_flow.py | 29 OK |
| test_ticket_system.py | 28 OK |
| test_carga_desde_solicitud.py | 20 OK |
| test_engines_excel_io.py | 18 OK |
| **test_tipos_de_prenda.py** | **13 OK** |
| test_catalog_rules.py | OK |
| test_partial_maintenance_validations.py | OK |
| test_auth_accesos.py | falla, **igual en main limpio de hoy** |
| test_brand_commercial_input.py | falla, **igual en main limpio de hoy** |

Corrida completa sobre `Input_Catalogo_PATAGONIA_20260731.xlsx`, sitio Rockford:

| Control | Antes | Ahora |
|---|---|---|
| Productos generados | - | 252 de 252 |
| Title vacio | - | 0 |
| Handle duplicado | - | 0 |
| Tags vacio | 252 | 0 |
| Materialidad vacia | - | 0 |
| Image Alt Text vacio | - | 0 |
| Body sin bullets | 252 | 0 |
| **Avisos de tipo nuevo** | **4** | **0** |

## Antes de correr la carga completa

Cambian **1.956 URLs de producto** entre las cuatro marcas. Los productos no se
duplican (el emparejamiento va por el metafield `codigo_modelo_color` y se
conserva el `ID`, asi que Matrixify renombra), pero la URL publica si cambia.

**Confirma que Shopify tenga activada la creacion automatica de redirecciones**
antes de correr. Conviene empezar por Vans, que son 30 productos.

## Para la proxima

Si vas a subir dos paquetes seguidos, avisame antes de armar el segundo: lo
construyo sobre el resultado del primero y no se pisan.
