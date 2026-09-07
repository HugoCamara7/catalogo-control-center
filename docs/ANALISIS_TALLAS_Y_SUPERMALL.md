# Análisis: orden de tallas y carga de Supermall

Documento de análisis previo a la implementación. Fecha: septiembre 2026.
Base: commit `8b0dcce` de `main`.

Todo lo que aquí se afirma está **medido contra el código y contra datos
reales** (`data/arti.zip`, 653.431 filas del maestro ARTI), no supuesto. Donde
no pude medir algo lo digo.

---

# PARTE 1 — Orden de tallas

## 1.1 Cómo funciona hoy

Hay **tres** criterios de orden de tallas en el repositorio, y **dos**
normalizadores:

| Dónde | Qué hace | Quién lo usa |
|---|---|---|
| `generate_columbia_matrixify.size_sort_key` | letras (12 valores) → números → `N/N` → resto | la **Carga completa**: ordena las variantes antes de escribir el Matrixify |
| `app_matrixify.size_sort_key` | números → `SIZE_ORDER` (tabla de 4 escalas) → resto | KPIs, stock, vistas previas |
| `engines/normalize.size_sort_key` | copia muerta de la Fase 0 | nadie |

`app_matrixify` importa el de `generate_...` con el alias
`master_size_sort_key`, y el **Mantenedor de Tallas** usa ese
(`tallas_orden_clave`), que es lo correcto. Pero `app_matrixify.size_sort_key`
sigue existiendo y **no coincide** con el maestro en las tallas compuestas:
`S/M` está en el maestro entre `S` y `M`, y en el de la app cae al grupo
"desconocido".

El orden se aplica en tres momentos:

1. **Al armar el Matrixify** (`generate_columbia_matrixify.py:4185`):
   `variants.sort_values("__SIZE", key=size_sort_key)`. Se ordena por la talla
   **antes** de convertir de escala.
2. **Al escribir en Shopify** (`app_matrixify._reorder_product_sizes`):
   reordena las variantes con `productVariantsBulkReorder` y **verifica**
   releyendo.
3. **En el Mantenedor de Tallas** (`render_mantenedor_tallas`), para el
   catálogo ya cargado.

## 1.2 Por qué Columbia sale mal — causa raíz, medida

`size_sort_key` solo entiende tres formas: **letra** de una tabla de 12
valores, **número** puro, y **`número/número`**. Todo lo demás cae en el grupo
9 y se ordena **alfabéticamente**.

Columbia usa, en producción, seis formas más que ninguna de las tres cubre.
Medido sobre el maestro real: **361 de 15.690 modelo-color de Columbia**
(2,3 %) tienen al menos una talla que cae en el grupo 9.

| Forma | Ejemplo real | Cómo queda hoy | Cómo debería quedar |
|---|---|---|---|
| letra + largo | `2135771-2OO` | `L/R, M/R, S/R, XL/R, XS/R` | `XS/R, S/R, M/R, L/R, XL/R` |
| letra + copa | `2094731-TVR` | `L/6, L/8, M/6, M/8, S/ 6, S/ 8, XL/6...` | `S/6, S/8, M/6, M/8, L/6...` |
| número + largo | `2135811-5HD` | `10/R, 12/R, 2/R, 4/R, 6/R, 8/R` | `2/R, 4/R, 6/R, 8/R, 10/R, 12/R` |
| rango | `6180-BK0` | `35-38, 39-42, 43-46, 47-48` (bien **por casualidad**) | igual |
| infantil `NT` | `2075202-5WF` | `2T, 3T, 4T` (bien por casualidad) | igual |
| fecha de Excel | `1523741-3HS` | `18/24, 03-JUN, 06-DIC, DIC-18` | `3-6, 6-12, 12-18, 18/24` |

Las dos que salen bien "por casualidad" salen bien porque el orden alfabético
coincide con el numérico en ese caso concreto. Con `10T` o con `8-10` dejan de
coincidir. **No es una regla, es suerte.**

Las de "fecha de Excel" son `3-6`, `6-12`, `12-18`, `28-8`, `4-5`, `10-12` que
Excel interpretó como fechas al exportar el maestro. Son **decodificables sin
ambigüedad**: el nombre del mes se sustituye por su número **en el mismo sitio
donde está** (`03-JUN` → `3-6`, `DIC-18` → `12-18`, `28-AGO` → `28-8`). El
orden del texto original se conserva, así que no hay que adivinar.

Hay además dos huecos menores:

- `S/ 8` (con espacio) y `S/8` son la misma talla y hoy son dos valores
  distintos: `normalize_size` colapsa espacios repetidos pero no los quita
  alrededor de la barra.
- `2XL`, `3XL`, `4XL` no están en la tabla de letras del maestro (sí en la de
  la app). Caterpillar y Under Armour los traen.

**Lo importante: esto NO afecta a las demás marcas.** Medido, productos con al
menos una talla no reconocida:

```
COLUMBIA            361 / 15.690     ROCKFORD          3 / 9.785
PATAGONIA            45 /  2.359     HUSH PUPPIES      2 / 14.581
MOUNTAIN HARDWEAR    86 /  1.534     VANS             17 /  1.350
```

Rockford y Hush Puppies —que son el grueso del catálogo— están prácticamente
limpios. Por eso el arreglo tiene que **añadir formas**, nunca cambiar el orden
de las que ya funcionan.

## 1.3 Vans: la guía está bien, el problema es dónde se aplica

Comparé el archivo `Guia_de_Tallas__Vans_2026.xlsx` que enviaste, fila a fila,
contra `engines/tallas_calzado.TABLA_VANS`. **Coinciden exactamente** en las 34
filas. Las únicas seis diferencias son las de `US Men` por debajo de 6.5, que
el código deriva a propósito del desfase de 1,5 de la propia tabla y lo
documenta. La tabla no hay que tocarla.

El problema son **tres cosas de aplicación**:

**a) La conversión depende de una bandera de SITIO, no de la marca.**
`display_size_for_site` convierte solo si `brand_config["tallas_calzado_pe"]`,
y esa bandera solo la tiene `vans`. Por lo tanto **Vans cargado en Supermall.pe
sale en US**. Ya está anotado como pendiente nº 8 en `CLAUDE.md`, y con
Supermall deja de ser teórico.

**b) Sin género, se convierte con la columna equivocada.** Un mismo número US
es dos tallas distintas: US 8 de hombre es PE 40.5 y de mujer es PE 38.5. Sin
género, `talla_pe` aplica `ESCALA_UNISEX = HOMBRE` y devuelve nota
`"ambigua"` — pero **nadie mira esa nota**: `display_size_for_site` la
descarta con `_nota`.

Tu ejemplo lo confirma: pides `5, 6, 7 → 35, 36, 37`, que es la columna de
**mujer** (`6→36`, `7→37`; `5.5→35`). Hoy, sin género, la app devuelve
`36.5, 38, 39` — la columna de hombre. Dos tallas y media de diferencia.

Y el género casi nunca está: `shopify_api.CAMPOS_PRODUCTO` **no lee el
metacampo `custom.genero`**, así que en el catálogo leído de Shopify el género
llega vacío siempre y solo queda el de BigQuery/ARTI o la heurística de texto.

**c) La conversión exige que el tipo de prenda esté en el diccionario.**
`es_calzado` pregunta a `engines/garment_types`. Medido:

```
"Zapatillas"          → Calzado ✔      "Zapatillas Urbanas" → sin clase ✘
"Sandalias"           → Calzado ✔      "Calzado"            → sin clase ✘
```

Un producto cuyo `Type` sea "Zapatillas Urbanas" **no se convierte**, en
silencio.

## 1.4 Dos fallos que dejan el Mantenedor de Tallas sin efecto

El Mantenedor de Tallas (septiembre 2026) es justo la herramienta que
arreglaría el catálogo ya cargado. **Hoy no funciona ninguna de sus dos
funciones.**

**Fallo 1 — el reordenamiento revienta.** `app_matrixify.py:24175` llama a
`orden_tallas._indice_de_opcion(...)`. Esa función se llama
`indice_de_opcion`, **sin guion bajo**. Es un `AttributeError` que no está
capturado en `tallas_aplicar_producto`: sube hasta `run_app`, que lo convierte
en `st.error` y **corta la pantalla a media tanda**. O sea que "Aplicar" falla
en el primer producto que necesite reordenarse.

**Fallo 2 — el cambio de escala se pierde al aplicarlo.**
`tallas_aplicar_producto` **replanifica** sobre el producto releído (correcto,
es la regla de no escribir sobre una lectura vieja), pero el plan que le llega
**no lleva el campo `Type`**: `orden_tallas.plan_de_producto` no lo incluye en
el diccionario que devuelve. Entonces `plan.get("Type", "")` es `""`,
`tallas_convertidor_para` corta en `if not tipo`, devuelve `None`, y el plan
fresco sale **sin cambio de escala**. Resultado: *"Ya estaba bien al releerlo.
No se escribió nada."* — y nunca se convierte nada.

Ninguna de las 34 pruebas de `test_mantenedor_tallas.py` lo atrapó porque
todas prueban el **motor**, y estos dos fallos están en el **pegamento** de la
pantalla.

**Fallo 3 (menor, en la carga completa).** `_reorder_product_sizes` calcula
`values_in_order` (líneas 12821-12822) y **no lo usa nunca**. Es código muerto,
pero señala una intención que quedó sin hacer: reordenar los **valores de la
opción**, no solo las variantes.

## 1.5 Solución propuesta (parte 1)

**A. Un solo motor de tallas: `engines/tallas.py`** (sin Streamlit, sin pandas).

Expone `descomponer(talla)` → una talla estructurada (familia + componentes
numéricos) y `clave_de_orden(talla)`. Cubre, cada una como una **familia con
su propio orden interno**:

```
letras       XXXS…4XL (con alias 2XL/3XL/4XL) y las combinadas XS/S, S/M, M/L, L/XL
números      5, 8.5, 38.5, 40
letra+largo  S/R, M/R, XL/T, MS, MT, LT   (letra primero, largo después)
letra+copa   S/6, M/8, XL/6
núm+largo    2/R, 10/R
núm/núm      32/10, 14/16, 18/24
rangos       35-38, 39-42, 8-10
infantil     2T, 3T, 4T · 3-6M, 12M, 18M, 24M · 10.5C, 1Y
talla única  O/S, ONE, OSFA, Talla Única  → siempre al final
```

Más un **decodificador de fechas de Excel** que devuelve `03-JUN` → `3-6`
sustituyendo el mes en su sitio.

Ese motor pasa a ser el **único** criterio: `generate_columbia_matrixify.
size_sort_key` y `app_matrixify.size_sort_key` delegan en él, y
`engines/orden_tallas` lo recibe inyectado como ya hace hoy. Se acaba la
divergencia de los tres criterios.

**B. La red de seguridad: prueba dorada contra el maestro real.**
`scripts/test_orden_tallas_reales.py` recorre **los ~70.000 modelo-color de
`data/arti.zip`**, arma la curva de cada uno y exige:

1. En todo producto cuyas tallas el criterio VIEJO ya reconocía (ninguna en el
   grupo 9), el orden nuevo es **byte a byte el mismo**. Esto es lo que
   garantiza que Rockford, Hush Puppies, Patagonia y el 97,7 % de Columbia no
   se muevan.
2. Los casos concretos de arriba salen en el orden correcto.

Sin esa prueba, cambiar `size_sort_key` es tocar la carga de todas las marcas a
ciegas.

**C. Las guías, como DATO y por marca+clase.** `engines/guias_tallas.py` con un
registro `{(MARCA, CLASE): tabla}`, cargable desde `data/guias_tallas.xlsx`
además de las tablas en código. `MARCAS_TALLA_PE` deja de ser una constante
escrita a mano y pasa a derivarse del registro: una guía nueva es una hoja
nueva, no un `if` nuevo.

> **Falta la guía de Columbia.** En tu mensaje dices "las guías de tallas de
> Vans y Columbia", pero el adjunto trae **solo la de Vans** (una hoja `GUIA`).
> Sin la de Columbia no puedo construir su tabla de conversión. El orden de
> Columbia sí lo puedo arreglar entero sin ella —es un problema de formatos,
> no de escalas—; la conversión de escala de Columbia, no.

**D. La conversión decide por MARCA + CLASE, no por sitio.** Pasar la marca a
`display_size_for_site` (pendiente nº 8). La bandera de sitio se conserva como
respaldo para que nada regrese.

**E. El género deja de adivinarse.**
- Añadir `custom.genero` (y de paso `custom.color`, `custom.nombre_corto`,
  `custom.descripcion_corta`) a `shopify_api.CAMPOS_PRODUCTO` — **una sola vez**,
  como manda la sección 5 decies: lo usan las dos lecturas.
- Orden de resolución: metacampo → ARTI `Genero` → heurística de texto.
- Si sigue sin saberse: **no se convierte y se reporta**. Hoy se aplica la
  columna de hombre en silencio, que es exactamente el error de tu ejemplo.
  (Es una decisión tuya: ver 3.1.)

**F. Los tres fallos de 1.4**, arreglados con prueba que falle con el código
anterior:
- `_indice_de_opcion` → `indice_de_opcion`.
- `plan_de_producto` devuelve también `Type` y `Genero`, y
  `tallas_aplicar_producto` los propaga al replanificar.
- `_reorder_product_sizes`: quitar el código muerto o completar el
  reordenamiento de valores de opción.

---

# PARTE 2 — Carga de Supermall

## 2.1 Qué hay hoy

Supermall.pe ya es un sitio de primera clase en el modelo de la app: está en
`SITE_CONFIGS` con `es_espejo: True`, sus marcas se calculan como la unión de
las de los demás sitios, tiene cola SIAL propia y no recibe input comercial.

Y hay dos piezas que resuelven **los extremos** del problema:

- **La pestaña "Espejo de Supermall"** (`engines/espejo_supermall.py`) responde
  *qué falta*: resta el catálogo de Supermall al de los demás sitios y entrega
  la lista de códigos Modelo-Color.
- **El botón "Preparar esta carga para Supermall.pe"** hace la segunda pasada
  de una carga que **acabas de hacer**: cambia de sitio y deja la misma
  solicitud elegida.

## 2.2 El hueco, dicho sin rodeos

**Entre esos dos extremos no hay nada.** El espejo te da un Excel con,
pongamos, 4.000 códigos, y el texto de la pantalla dice *"se pega en Carga
parcial → Carga Sial"*. Pero esa pantalla:

1. **Solo produce la hoja Carga Sial.** No produce el Matrixify, que es lo que
   crea el producto en Shopify. Sin Matrixify no hay carga.
2. **Lee el catálogo de UN solo sitio: el activo.** Y si estás en Supermall,
   el catálogo activo es el de Supermall — donde esos productos, por
   definición, **no están**. `matrixify_desde_codigos_modelo_color` llama a
   `session_shopify_products(brand_config["site_key"])`, y de ahí sale
   `product_lookup`, que es de donde se toman título, descripción, tipo, tags,
   color y metacampos.

O sea: **la información existe** —está en Vans.pe, Rockford.pe, Columbia.pe—
pero el camino que la app ofrece **no la mira**. El producto saldría con lo
poco que tenga BigQuery/ARTI y con el resto vacío.

El otro camino, el botón de segunda pasada, solo sirve para lo que se acaba de
cargar: no hay input comercial para los miles de productos históricos.

**La conclusión del análisis es que no falta una pantalla: falta el paso de
CONSOLIDACIÓN entre "qué falta" y "generar la carga".**

## 2.3 Inventario: qué tenemos, de dónde, y qué falta

### Fuentes disponibles hoy

| Fuente | Qué aporta | Cómo se lee |
|---|---|---|
| Shopify de los 6 sitios | título, descripción HTML, tipo, tags, vendor, marca, estado web, fotos, materialidad, tecnología, logo, siblings, variantes (SKU, EAN, precio, talla, color) | `cargar_catalogos_de_todos_los_sitios` — **ya los lee los 6, en paralelo** |
| BigQuery / maestro ARTI | SKU, curva de tallas, precio, código de barras, nombre, descripción web, características, material, cuidado, tipo, categoría, subcategoría, **género**, color, temporada, colección, ocasión, deporte, tecnología | `session_arti_for_app` |
| Bucket S3 de imágenes | fotos y videos, por carpeta de MARCA | `image_candidates` + `BRAND_IMAGE_FOLDERS` |
| Solicitudes | qué pidió cada marca y su Excel de input | `ticket_system` |

### Campo por campo, para la carga de Supermall

| Campo Supermall | Se obtiene | De dónde | Nota |
|---|---|---|---|
| Handle | ✅ automático | se genera del código/título | no se reutiliza el del origen: los handles son por tienda |
| Title | ✅ automático | Shopify origen → ARTI `NombreModelo` | |
| Body HTML | ✅ automático | Shopify origen → ARTI `DescripcionWeb` | |
| Vendor | ✅ automático | `supermallpe` (config del sitio) | |
| Type | ✅ automático | Shopify origen → ARTI `TipoProducto` → `SubCategoria` | debe estar en `garment_types` |
| Tags | ✅ automático | Shopify origen | |
| Variant SKU / EAN / precio | ✅ automático | ARTI | |
| Talla (Option1) | ⚠️ **transformación** | ARTI + conversión por marca | **depende de la parte 1** |
| Color (Option2) | ✅ automático | Shopify origen (`custom.color`) → ARTI `ColorNombre` | hoy `custom.color` **no se lee** |
| `custom.codigo_modelo_color` | ✅ automático | es la clave | |
| `custom.marca` | ✅ automático | ARTI `MARCA_MA` | manda esto, **no el Vendor** |
| `custom.genero` | ⚠️ **no se lee de Shopify** | ARTI `Genero` | hay que añadirlo a `CAMPOS_PRODUCTO` |
| `custom.materialidad`, `custom.tecnologia` | ✅ automático | Shopify origen → ARTI + `engines/enrich` | |
| `custom.nombre_corto`, `custom.descripcion_corta` | ⚠️ **no se leen de Shopify** | — | hay que añadirlos a `CAMPOS_PRODUCTO` |
| Fotos (`Image Src`) | ✅ automático | bucket S3 por marca | |
| Status / Published | ⚠️ **decisión** | — | ver 3.2 |
| `theme.siblings`, `custom.siblings` | ❌ **no trasladable** | — | son referencias a productos **de la tienda origen**; en Supermall apuntan a nada. Hay que reconstruirlos contra el catálogo de Supermall o dejarlos fuera |
| `custom.guia_de_tallas [page_reference]` | ❌ **no trasladable** | — | es la página de guía de tallas **de la tienda origen** |
| Bodega SIAL | ⚠️ **sin confirmar** | `sial_active_columns = "13"` | ya anotado en `CLAUDE.md` |
| Logo de Supermall | ❌ no existe | — | `assets/brands/logo_supermall.png` |

### Campos obligatorios (bloqueantes) para poder generar

Del análisis del generador y de las reglas ya existentes:

1. Código Modelo-Color (sin él no hay identidad; el espejo ya los aparta).
2. Al menos una variante con SKU **y** talla válida en ARTI.
3. Marca reconocida (siempre pasa: Supermall admite la unión).
4. Tipo de prenda reconocido por `garment_types` (si no, no hay clase, y sin
   clase no se sabe si convertir tallas).
5. Precio válido en al menos una variante (si no, `Published` sale `FALSE`).
6. Sin SKU duplicados y sin **colisión de tallas tras convertir** (dos US que
   caen en la misma PE — `orden_tallas` ya lo detecta y avisa).

## 2.4 Consolidación cuando el producto está en varias webs

Es la decisión de diseño central. Un mismo Mod-Col puede estar en Rockford.pe y
en Columbia.pe con **descripciones distintas**. Propongo:

- **Campo a campo, no sitio entero.** Se toma el primer valor no vacío según un
  orden de prioridad, por campo. Tomar "el sitio ganador" completo desperdicia
  el campo que solo tiene el otro.
- **Prioridad: el sitio propio de la marca primero.** Un producto Vans se toma
  de Vans.pe aunque también esté en Rockford.pe. Se deriva de
  `allowed_arti_brands`, no se escribe a mano.
- **Desempate: el sitio donde el producto está `Prendido y visible`**, y
  después el orden de `SITE_CONFIGS` (estable, comparable entre ejecuciones).
- **Se registra de dónde salió cada campo** en la hoja de revisión. Cuando un
  producto salga raro, la pregunta va a ser "¿de dónde sacó esa descripción?"
  y tiene que poder responderse sin abrir seis pestañas.

## 2.5 Flujo propuesto

```
1. Leer los 6 catálogos              → cargar_catalogos_de_todos_los_sitios   [YA EXISTE]
2. Restar lo que ya está en Supermall→ espejo.comparar / codigos_a_cargar     [YA EXISTE]
3. Consolidar por Mod-Col            → engines/carga_supermall.consolidar     [NUEVO]
4. Enriquecer con BigQuery/ARTI      → build_centry_matrixify_from_master     [YA EXISTE, +1 parámetro]
5. Convertir tallas por marca+clase  → engines/tallas + guias_tallas          [PARTE 1]
6. Validar (bloquea / avisa)         → engines/carga_supermall.validar        [NUEVO]
7. Generar                           → Matrixify Supermall
                                     + Carga Sial Supermall (get_sial_columns)[YA EXISTE]
                                     + Revisión                                [NUEVO]
8. Cargar                            → apply_full_product_updates / Actions   [YA EXISTE]
```

Los pasos 1, 2, 4, 7-parcial y 8 **ya están escritos y probados**. Lo nuevo son
3, 6 y el pegamento. Eso es lo que quiere decir "reutilizando la mayor cantidad
posible de lógica existente".

El único cambio en código existente es dar a
`matrixify_desde_codigos_modelo_color` un parámetro `productos_origen=None`:
sin él se comporta exactamente como hoy (catálogo del sitio activo); con él usa
el catálogo consolidado. **Un parámetro opcional, no una bifurcación.**

### Por bloques y en dos tiempos

Igual que los mantenedores de fotos, videos y tallas: primero se **analiza sin
escribir nada** y se muestra qué va a salir; después, con confirmación, se
genera y se carga **por bloques**, guardando el avance dentro del bucle. Con
4.000 códigos, una pasada única que se cae a la mitad no deja constancia de
nada.

### Memoria

Es la restricción real: 1 GB **por app**, compartido (sección 5 nonies). Seis
catálogos consolidados más el Matrixify de Supermall no pueden estar vivos a la
vez. El consolidado se guarda como **índice acotado** —solo los campos que la
carga usa, como ya hace `columnas_leidas_del_catalogo`— y el Matrixify se
genera por bloques de códigos, no de una vez. Hay que medirlo con
`scripts/test_memoria.py` **antes** de dar esto por bueno.

## 2.6 Archivos a tocar

**Nuevos**
```
engines/tallas.py                    motor único de orden y familias de talla
engines/guias_tallas.py              registro de guías por marca+clase
engines/carga_supermall.py           consolidación + validación (sin Streamlit)
scripts/test_orden_tallas_reales.py  prueba dorada contra data/arti.zip
scripts/test_carga_supermall.py      pruebas del motor nuevo
data/guias_tallas.xlsx               las guías como dato
```

**Modificados**
```
engines/tallas_calzado.py       pasa a leer del registro de guías
engines/orden_tallas.py         plan_de_producto devuelve Type y Genero
generate_columbia_matrixify.py  size_sort_key delega; display_size_for_site recibe marca
app_matrixify.py                size_sort_key delega; arreglo de los 3 fallos;
                                pantalla "Carga Supermall"; menú (5 listas de selectores)
shopify_api.py                  CAMPOS_PRODUCTO: +genero, +color, +nombre_corto, +descripcion_corta
CLAUDE.md                       sección nueva
```

---

# 3. Decisiones que necesito de ti

Son de negocio; el código las deja configurables pero alguien tiene que
elegir.

**3.1 — Talla de calzado sin género conocido.** Hoy se aplica la columna de
hombre en silencio (y por eso tu `5,6,7` sale `36.5, 38, 39`). Opciones:
(a) no convertir y reportarlo — mi recomendación; (b) convertir con hombre y
marcarlo en la revisión; (c) convertir con mujer.

**3.2 — Estado con el que nace un producto en Supermall.** ¿`Active` y
publicado en Online Store, o `Draft` para revisar antes? Mi recomendación:
publicado **solo si** está prendido y visible en al menos un sitio de origen y
tiene precio; el resto, borrador.

**3.3 — Precio en Supermall.** ¿El de BigQuery/ARTI (que es lo que usa la carga
completa) o el del sitio de origen? Recomiendo ARTI, por coherencia con el
resto de la app.

**3.4 — Prioridad de consolidación.** ¿Confirmas "el sitio propio de la marca
primero"?

**3.5 — Bodega SIAL de Supermall.** Sigue sin confirmar (`"13"`).

**3.6 — Siblings y guía de tallas.** ¿Se omiten en la primera versión (mi
recomendación: sí, y se arreglan después con un pase propio contra el catálogo
de Supermall ya cargado) o se intentan reconstruir desde el principio?

**3.7 — La guía de tallas de Columbia**, que no vino en el adjunto.

---

# 4. Riesgos

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Cambiar `size_sort_key` toca la carga de **todas** las marcas | alto | prueba dorada sobre los ~70.000 modelo-color reales: orden idéntico donde ya funcionaba |
| Convertir tallas con el género equivocado | alto — publica una talla que no es | no convertir sin género (3.1) + la nota `ambigua` deja de descartarse |
| Dos tallas US que caen en la misma PE | medio | `orden_tallas` ya lo detecta y no renombra ninguna; hay que propagarlo a la carga |
| Memoria al consolidar 6 catálogos + Matrixify | **alto** — tumba la app para todos | índice acotado + generación por bloques + `test_memoria.py` |
| Siblings y guía de tallas apuntando a la tienda origen | medio — enlaces rotos en la ficha | omitirlos en v1 (3.6) |
| `sial_tail_row` pone "Actualizar" en la columna de Supermall según el ID del **sitio que se carga** | medio | **preexistente**, ya anotado en `CLAUDE.md`. Supermall lo hace más visible. Es decisión de negocio: afecta la hoja de los cinco sitios |
| Añadir metacampos a `CAMPOS_PRODUCTO` encarece la lectura paginada | bajo | la lectura normal es bulk y no paga costo por consulta; el respaldo paginado sí, y hay que medirlo |
| `render_mantenedor_tallas` es la vía para arreglar lo ya cargado y **está roto** | alto | los tres fallos de 1.4, con pruebas que fallen con el código anterior |

---

# 5. Orden de trabajo propuesto

1. **Los tres fallos de 1.4** — son bugs vivos, van solos y con prueba propia.
2. **`engines/tallas.py` + prueba dorada** — arregla Columbia sin tocar el
   resto.
3. **Guías por marca+clase + género + marca en `display_size_for_site`** —
   arregla Vans, en la carga y en el mantenedor.
4. **`engines/carga_supermall.py` + pantalla** — con las decisiones de la
   sección 3 ya tomadas.

Los pasos 1 y 2 se pueden entregar y mergear a `main` sin esperar al 4.
