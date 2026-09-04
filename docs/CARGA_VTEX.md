# Carga VTEX (manual)

Septiembre 2026. Motor: `engines/vtex_catalog.py`. Pantalla:
`render_vtex_export()` en `app_matrixify.py`, dentro de **Carga parcial**.

---

## 1. Qué resuelve

Forus vende también en VTEX (`supermallpe`). Ahí la carga **no va por API**: se
suben cuatro planillas a mano en el admin de VTEX. Armarlas a mano significa
copiar nombre, descripción, marca, categoría, tallas, EAN e imágenes producto
por producto, y sobre todo **buscar a mano el ID que VTEX ya le dio a cada
producto y a cada SKU**.

Esta pantalla arma las cuatro planillas a partir de los códigos Modelo-Color,
con los datos que la app ya tiene, y hace el cruce de IDs contra el catálogo
maestro que el usuario sube.

**La app no se conecta a VTEX.** Ni para leer ni para escribir. Genera archivos
y los deja listos para descargar. Hay una prueba que falla si aparece una
llamada HTTP dentro de la pantalla.

---

## 2. Por qué el catálogo maestro es obligatorio

VTEX identifica por **ID numérico**, no por referencia:

- una fila con `Product ID` en blanco **crea** un producto;
- una fila con el `Product ID` puesto **actualiza** el que ya existe.

Si las planillas se generaran sin mirar el maestro, todo producto que ya está
cargado se volvería a crear: otro ID, otra URL, otra ficha. El catálogo quedaría
partido en dos y no hay forma barata de deshacerlo.

Por eso el archivo **Products and SKUs** es obligatorio antes de generar nada, y
por eso la regla del motor es: **un ID que sale del maestro nunca se
reemplaza**.

---

## 3. El dato que hace todo esto posible

La referencia de producto de VTEX **es** el código Modelo-Color de la app:

```
Mod-Col                 HP102011307-251
Product reference code  HP102011307-251
```

Verificado contra la exportación real de supermallpe. No hay tabla de
equivalencias que mantener: se busca el código tal cual.

---

## 4. Cómo se emparejan los SKUs

En esta tienda el `SKU reference code` **es el propio `SKU ID`** (verificado:
coinciden en las 499 filas de la muestra). O sea que la referencia no sirve para
reconocer un SKU que todavía no está cargado — un ID que VTEX aún no asignó no
se puede adivinar.

El emparejamiento real es **por talla dentro del producto**: el maestro trae
`SKU name` = `TALLA 39`, y de ahí sale la talla.

```
producto existe  +  talla existe   -> se reutiliza el SKU ID
producto existe  +  talla no está  -> SKU nuevo (el caso de ampliar la curva)
producto no existe               -> producto nuevo y todos sus SKUs nuevos
```

Un SKU cuya referencia declarada apunta a **otro** producto no se reutiliza:
reutilizarlo lo movería de ficha. Se avisa y se trata como nuevo.

**La referencia de los SKUs nuevos es configurable** desde la pantalla. Por
defecto `{mod_col}-{talla}` → `HP102011307-251-46`. Campos disponibles:
`{mod_col}`, `{modelo}`, `{color}`, `{talla}`, `{ean}`. Es una decisión de
negocio: si el ERP va a escribir después la referencia numérica, conviene dejar
el patrón en `{ean}` o acordar otro.

---

## 5. Las cuatro planillas

Las columnas están copiadas **exactamente** de las exportaciones reales
(nombres, orden y tildes incluidas: VTEX empareja por cabecera). No se agrega ni
se quita ninguna.

| Archivo | Columnas | Una fila por |
|---|---:|---|
| `Products_and_SKUs.xlsx` | 50 | SKU (el producto se repite) |
| `Product_Specifications.xlsx` | 16 | producto × campo |
| `SKU_Specifications.xlsx` | 16 | SKU × campo (Talla y Color) |
| `Images.xlsx` | 12 | SKU × foto |

Se descargan juntas en `VTEX_CARGA_[fecha].zip`. **El orden de carga en VTEX
importa**: primero Products and SKUs (crea los IDs), después las otras tres.

La hoja generada deja **la primera fila en blanco y la cabecera en la segunda**,
igual que el archivo que VTEX entrega. Todo se escribe como TEXTO: un
`Product ID` que Excel guarde como número vuelve como `310669.0` y deja de
emparejar.

### Los cuatro salen del mismo plan

`construir_archivos()` recibe UN plan y arma las cuatro tablas de ahí. El
`Product ID` y el `SKU ID` que aparecen en una son literalmente el mismo objeto
que en las otras tres: no hay forma de que se desincronicen. Hay pruebas que lo
verifican fila por fila.

---

## 6. Los ID de campo NO se inventan

Las especificaciones de VTEX se cargan con el **ID del campo** (`24` = Género,
`28` = Talla), y esos IDs son **propios de cada cuenta**. Escribirlos en el
código sería exactamente el hardcodeo que hay que evitar.

Por eso las tres exportaciones opcionales del maestro son el **diccionario de la
tienda**: qué campos tiene cada categoría, de qué tipo son, y qué valores admite
un `Radio` o un `CheckBox` con su ID.

- Sin la exportación de **especificaciones de productos**, `Product_Specifications`
  sale vacío. A propósito.
- Sin la de **especificaciones de SKUs**, `SKU_Specifications` sale vacío (ahí
  van Talla y Color).
- La de **imágenes** sirve para saber qué SKUs ya tienen fotos.

El mapeo campo → dato de la app está en `MAPEO_ESPECIFICACIONES_PRODUCTO` y
`MAPEO_ESPECIFICACIONES_SKU`, y empareja **por nombre**, sin tildes ni
mayúsculas. Un campo que la tienda no tenga simplemente no se emite.

**Un valor que no está en la lista del campo se avisa y no se emite.** Un Radio
con un valor que la tienda no conoce no se carga: eso hay que saberlo antes de
bajar el ZIP, no cuando VTEX rechace la fila.

---

## 7. De dónde sale cada dato

El orden no es casual: manda lo que el usuario escribe, después lo que está
publicado, y al final el maestro.

| Dato | Fuente |
|---|---|
| Nombre, descripción, tipo, marca, fotos, tallas publicadas | catálogo del sitio en Shopify (`session_shopify_products`) |
| Tallas, EAN, color, nombre de modelo | maestro ARTI / BigQuery (`session_arti_for_app`) |
| Medidas del paquete | `centry_lookup_dimensions` (el mismo de Centry) |
| Fotos por código | `image_candidates` (el mismo del motor de catálogo) |
| Departamento, categoría, marca **de VTEX** | el catálogo maestro |
| Cualquier cosa que se quiera forzar | columnas extra del Excel de códigos |

El Excel de códigos puede traer una sola columna, que es lo normal. Si además
trae `Categoría`, `Nombre`, `Color web`, `Género`, `Material`, `Composición`,
`Temporada` o `Marca`, esos valores **mandan**. Es la válvula de escape para un
producto cuya categoría de VTEX no se puede deducir del tipo de prenda de
Shopify.

**El departamento es una suposición, la categoría es el dato.** El departamento
se propone desde el género (Hombre / Mujer / Niños); si la categoría existe en
otro departamento del maestro, gana el maestro.

### Para un producto que YA existe no se reescribe nada

Por defecto un producto que ya está en VTEX se re-emite tal cual viene del
maestro. Reescribirle el nombre, la URL o la meta description a un producto
publicado le cambia el SEO sin que nadie lo haya pedido. La casilla
**"Actualizar los productos que ya existen"** lo permite, y aun así la
`Product URL` se conserva: VTEX le agrega un sufijo cuando la URL ya existe, así
que recalcularla no daría la misma.

Lo mismo con la categoría y la marca: si la app propone una distinta de la que
el producto tiene en VTEX, **gana VTEX** y se avisa. Cambiar la categoría movería
el producto de sitio en la web.

---

## 8. Validaciones

Los **errores** impiden generar los archivos. Los **avisos** se revisan y no
bloquean.

| Alerta | Nivel | Por qué |
|---|---|---|
| Código no encontrado | error | no hay datos con qué armar la fila |
| Producto sin categoría VTEX | error | VTEX no puede crear un producto sin categoría |
| Producto sin marca VTEX | error | igual: la marca es obligatoria y su ID sale del maestro |
| Producto sin nombre | error | — |
| SKU no encontrado (sin tallas) | error | un producto sin SKUs no se puede vender |
| Referencia duplicada en el maestro | error | la referencia apunta a dos Product ID; no se puede elegir por el usuario |
| Referencia de SKU repetida en la carga | error | dos SKUs distintos con la misma referencia |
| Código duplicado en la selección | aviso | se usa la primera aparición |
| Producto / SKU sin ID VTEX | aviso | es una creación, y hay que verla |
| Imagen faltante | aviso | el producto se carga sin fotos |
| Producto / SKU existente con información inconsistente | aviso | VTEX dice una cosa y la app otra; gana VTEX |
| Valor que no existe en la lista de la tienda | aviso | la especificación no se emite |

---

## 9. Rendimiento

El maestro de VTEX pasa de los 100 MB.

- Se lee con **openpyxl en modo `read_only`**, fila por fila, no con
  `pd.read_excel`, que cargaría las 50 columnas enteras en memoria incluidas las
  descripciones largas que aquí no se usan.
- El maestro indexado se **cachea** con `st.cache_resource`. El parámetro de los
  archivos va con guion bajo (`_archivos`), igual que `artefacto_de_solicitud`,
  para que Streamlit no intente hashear 100 MB en cada rerun y la clave sea solo
  la firma `(nombre, tamaño, file_id)`. Sin esto, cada clic de la pantalla
  volvería a leer el maestro entero.
- El maestro se guarda **partido en dos niveles** (producto y SKU) en vez de
  guardar la fila completa por SKU: las 23 columnas de producto se repiten en
  cada talla y un catálogo de 300.000 SKUs no cabe en memoria de otra forma.
- El cruce de códigos avanza por bloques con barra de progreso.
- Shopify y ARTI se leen **una vez cada uno**, antes del bucle. Pedir por código
  serían 2.000 viajes para 2.000 códigos.

---

## 10. Lo que NO hace

- No se conecta a VTEX.
- No toca nada de Shopify: la pantalla solo **lee** el catálogo del sitio.
- No modifica el flujo actual de Carga parcial ni de Carga completa. Entra como
  una opción más del selector, con corte temprano — el mismo patrón del
  Mantenedor de Videos.
- No inventa IDs de producto, de SKU, de campo, de marca ni de categoría.

---

## 11. Pruebas

```bash
python scripts/test_engines_vtex_catalog.py   # 60
```

Cubren la lectura (cabecera en la fila 2, cabeceras repetidas entre hojas,
columnas en otro orden, IDs que Excel devuelve como float), el mapeo de IDs, las
validaciones, la consistencia entre los cuatro archivos y el enganche con la
pantalla: que todo lo que la pantalla le pide al motor exista, que
`render_vtex_export` tenga llamador y que la opción esté en el menú de Carga
parcial.
