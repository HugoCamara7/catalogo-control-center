# Qué subir y por qué

Paquete armado sobre `main` en `cddaea5`. Sube los archivos respetando las
carpetas. **`app_matrixify.py` va al final.**

| Archivo | Estado |
| --- | --- |
| `app_matrixify.py` | modificado |
| `scripts/test_centry_ean.py` | modificado |
| `scripts/test_fotos_png.py` | modificado |
| `scripts/test_fotos_png_masivo.py` | modificado |
| `scripts/test_centry_enriquecimiento.py` | nuevo |

---

## 1. Centry — causa raíz: el maestro se tiraba a la basura

`build_centry_arti_lookup` construía el índice del maestro SIAL/BigQuery y se
quedaba con **cuatro campos**: código de barras, talla, talla normalizada y
color. El ARTI trae además `NombreModelo`, `DescripcionWeb`, `Caracteristicas`,
`Material`, `Cuidado`, `TipoProducto`, `Categoria`, `SubCategoria`, `Genero`,
`Temporada`, `Tecnologia`, `Coleccion`, `Ocasion` y `Deporte`. Todo eso se
descartaba en el índice, así que el Centry salía con Nombre, Descripción,
Género, Tipo, Materiales, Cuidados y Temporada vacíos **teniendo el dato a
mano**.

### Etapa única de enriquecimiento

Se añadió `centry_enriquecer_fila`, que corre **una sola vez por variante, antes
de que se lea ningún campo**. Rellena la fila con lo que sabe el maestro **solo
donde Shopify no trae nada**: Shopify manda siempre, el maestro es el respaldo
obligatorio.

Lo escribe en los nombres de columna que los resolutores de Centry **ya leían**
(`Type`, `Genero`, `Material`, `Cuidados`, `Temporada`…), así que
`centry_gender`, `centry_material_from_row`, `centry_care_from_row` y compañía
empiezan a encontrar el dato sin cambiar una línea. No es un parche por campo:
es un solo punto.

### SKU y EAN

**SKU.** Una variante sin `Variant SKU` se descartaba con un `continue` a secas:
desaparecía del archivo y nadie se enteraba. Ahora se busca el `CODINT_MA` del
maestro por Mod-Col + talla; si aparece, la variante entra; si no, se reporta con
su talla en vez de desvanecerse.

**EAN.** Sobre lo del paquete anterior (paralelo, índice que no se pisa, SKU
normalizado, notación científica), ahora el maestro se consulta con el registro
completo, así que el EAN también se rescata por Mod-Col + talla cuando el SKU no
empareja. El orden es el pedido: input → Variant Barcode de Shopify → maestro por
SKU → maestro por Mod-Col + talla. Lo que no aparece queda como **PENDIENTE**,
nunca vacío en silencio.

### El nombre ya no puede ser el código

`title = first_non_empty(product_row.Title, key)` — el segundo argumento era el
**código modelo-color**, y Centry lo publicaba tal cual como nombre del producto.
`NombreModelo` estaba en el maestro y no se miraba. Ahora la cadena es Shopify →
`custom.nombre_corto` (Hush Puppies) → `NombreModelo` del maestro; si ninguna
fuente lo tiene, el nombre queda **vacío y avisado**, que es honesto y se puede
corregir.

### Otros arreglos concretos

- **Temporada**: salía `"Verano"` fijo para todo el catálogo. El maestro la trae
  y ahora se usa.
- **Hush Puppies**: `custom.nombre_corto` y `custom.descripcion_corta` entran a
  la cadena de Nombre y Descripción, y viajan en la fila intermedia.
- `Coleccion`, `Ocasion`, `Deporte`, `Categoria` y `SubCategoria` del maestro
  también llegan.

### Validación

`centry_validar_salida` revisa el **resultado**, no el proceso. Marca por
producto (no por variante: 80 tallas sin EAN son un problema, no ochenta):

- SKU del producto / SKU de la variante vacíos
- EAN vacío
- Género, Categoría, Clase, Talla, Color, Marca vacíos
- Nombre o Descripción vacíos, y el nombre que es el código modelo-color
- Materiales / Composición / Cuidados sin dato en el listado
- **Valores fuera de la plantilla**, usando `valores_permitidos` y `valor_valido`
  de `engines/centry_map`, que ya leen la plantilla oficial. No se reescribió
  ninguna lista.

Sale en pantalla con su severidad (Bloqueante / Advertencia) y como hoja
**`Validacion Centry`** en el Excel, junto a `Centry`, `Carga Sial` y
`Revision Centry`. La hoja de revisión trae además dos resúmenes nuevos: de dónde
salió cada EAN y qué campos completó el maestro.

## 2. Fotos PNG — mismo flujo que Fotos Normales

**Por qué salían 310 "Sin PNG" y 0 encontradas.** La comprobación usaba
`url_is_image`, que consulta el bucket por la URL de validación
(`https://s3.amazonaws.com/<bucket>/...`). Ese host responde **403** a las
consultas anónimas — comprobado, y responde 403 igual para `.jpg` que para
`.png`. El código trataba ese 403 como "no existe". El mantenedor de fotos
normales nunca lo notó porque **no valida**: `VALIDATE_IMAGES = False`, genera las
URLs y deja que Shopify baje la imagen.

**Correcciones:**

1. `png_image_candidates` ahora llama a **`image_candidates`**, el mismo
   generador del mantenedor normal, y solo le cambia la extensión. Host, carpeta
   por marca, nomenclatura `MODELO_COLOR_n` y orden de vistas son los mismos por
   construcción, no por copia. Hay una prueba que compara las dos listas.
2. `png_comprobar_url` consulta **exactamente las URLs que usa la carga**:
   `png_urls_a_probar` parte de `_image_url_candidates`, la misma lista que arma
   `_download_image_bytes` justo antes de subir una foto, y añade el host
   alterno del bucket. Prueba HEAD y GET por rango, y distingue tres respuestas:
   existe, **404 = no existe** y **no se pudo comprobar**.
3. **Todo en paralelo.** Las comprobaciones salían una detrás de otra: 31
   modelos × 10 vistas × 2 extensiones son 620 viajes encadenados. El botón se
   quedaba colgado sin dar señales — eso era el "hago clic y no funciona".
   Medido con un bucket de 150 ms por consulta: **de 93 s a 6 s**.
4. **Se busca `.png` y `.jpeg`** (y `.jpg` si lo marcas), con un selector en
   pantalla. Cada vista prueba las extensiones en orden y gana la primera que
   exista, así que un mismo modelo puede salir con la vista 1 en `.png` y la 2
   en `.jpeg`. El nombre del archivo se compara sin extensión, así que una foto
   que el producto ya tiene se reconoce aunque esté guardada en otro formato.
5. **La descarga como prueba definitiva** (`_download_image_bytes`, que es
   literalmente lo que hace la carga al subir) quedó **solo para el modo de un
   código**, donde son 10 vistas. En una lista larga era una descarga completa
   por vista: ahí estaba el cuelgue.
6. Lo que aun así queda sin confirmar se ofrece igual para cargar: quien baja la
   imagen de verdad es Shopify. Y si alguna URL no existe, `_sync_product_photos_direct`
   **sube las que sí** y lo dice en el mensaje ("No se cargaron N de M URLs"),
   en vez de perder el producto entero.
7. Las vistas que el producto **ya tiene** ni se consultan: se resuelven por el
   nombre del archivo y ahorran una petición cada una.
8. El motor JPG **no se tocó**: sigue devolviendo solo `.jpg` y hay una prueba
   que lo comprueba.

**Flujo, en pocos pasos:** código o Excel → mismos links → hasta 10 vistas →
`.png` / `.jpeg` → validación → preview → confirmación → inyección.

- **Bloques de 20 modelo-colores**, el mismo tamaño que la sincronización de la
  carga parcial, tanto al buscar como al cargar. El resultado se guarda al cerrar
  cada bloque.
- **Antes de Shopify** se dice cuántos modelos y cuántas fotos se van a inyectar
  y en qué modo, y hay que confirmar.
- **Durante**, la barra muestra bloque actual, avance y el modelo en curso.
- **Al terminar**, por modelo: encontradas, cargadas, ya existentes, sin PNG, sin
  confirmar, duplicadas y errores; más un Excel con *Resumen por modelo*,
  *Detalle por vista* y *Descartados*.
- Un error de carga de Shopify ya no se confunde con un fallo de búsqueda.


## 3. Centry Rockford — el EAN vacío y las tallas que faltaban

### Por qué el EAN salía vacío

El EAN de Rockford **no viene en el ARTI**: viene del **Maestro de Productos**,
que es otra tabla, y lo cruza `enrich_arti_barcodes_from_bigquery_table`. Ese
cruce tenía tres fallos, y los tres terminaban en la misma columna en blanco:

1. **Emparejaba por cadena exacta.** El ARTI trae el SKU como `5486079` y el
   maestro puede tenerlo como `0005486079` (ceros a la izquierda) o `5486079.0`
   (la columna leída como número). Ninguna de las tres formas coincide letra por
   letra con las otras, así que no emparejaba **ninguna**.
2. **El `WHERE` de BigQuery tenía el mismo problema.** Comparaba
   `CAST(sku AS STRING) IN UNNEST(@skus)`. Si los dos lados no coincidían
   exactamente, la consulta volvía **vacía** y no había nada que cruzar.
3. **Cualquier error se tragaba entero.** Un `except Exception: return result, ""`
   convertía un problema de permisos, una columna que no existe o una consulta
   inválida en "sin EAN", sin una sola pista.

**Corregido:** los SKU se normalizan con las mismas reglas en los dos lados —en
Python con `_claves_sku_para_cruce` y en SQL con `_sql_sku_normalizado`, que
quita decimales de relleno y ceros a la izquierda—, la consulta va **por tandas
de 5.000** (una lista enorme en un solo parámetro hace que BigQuery la rechace),
el código que llega se normaliza con `centry_normalizar_ean`, y **cualquier
fallo se reporta** en vez de desaparecer.

### Por qué faltaban tallas

El filtro de marca corría **antes** de acotar a los códigos pedidos, y las filas
que descartaba no dejaban rastro. Si el maestro escribe la marca distinto en
algunas filas —`ROCKFORD PERU` en vez de `ROCKFORD`—, esas tallas se caían y el
producto salía con menos de las que tiene, sin ningún aviso.

**Corregido:** primero se acota a los códigos pedidos y **después** se filtra por
marca, así se puede decir exactamente qué tallas de *esos* códigos se cayeron y
con qué marca venían.

### Lo que ahora se ve en `Revision Centry`

- `Base maestra` — de dónde salió el ARTI y qué pasó con el cruce de EAN
  (cuántos completó, cuántos siguen sin código, o el error exacto si falló).
- Una línea **por modelo-color** con el recuento: `6 tallas (38, 39, 40, 41, 42,
  43) · 4 con EAN en el maestro, 2 sin EAN`.
- Las tallas descartadas por marca, con la marca que traían y las permitidas.
- `Centry (resumen EAN)` — de qué fuente salió cada código.

Con eso, si vuelve a salir una columna vacía, la hoja dice por qué en la primera
línea en vez de haber que adivinar.

---

## Pruebas

Batería completa: **34 archivos**, todos OK salvo los dos que ya fallaban en
`main` antes de este paquete (`test_auth_accesos.py` y
`test_brand_commercial_input.py`).

```bash
python scripts/test_centry_enriquecimiento.py
```

```bash
python scripts/test_centry_ean.py
```

```bash
python scripts/test_fotos_png.py
```

```bash
python scripts/test_fotos_png_masivo.py
```

Además se levantó la app con `AppTest`: arranca sin excepciones y los dos
mantenedores (Centry y Fotos PNG, en sus dos modos) abren correctamente.
`test_fotos_png.py` pasó de 82 s a 0,03 s porque ya no sale a la red: se
sustituye `png_comprobar_url`, que es la única puerta.
