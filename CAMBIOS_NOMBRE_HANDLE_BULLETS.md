# Correccion de nombre de producto, handle, bullets y alt de imagenes

Base: `main` de `HugoCamara7/catalogo-control-center`
(`app_matrixify.py` sha256 `8ea14bc0...`, 17967 lineas).

Archivos que se reemplazan **completos**:

- `app_matrixify.py`
- `generate_columbia_matrixify.py`

---

## Causa raiz

El input de Patagonia trae la columna **`Nombre de Producto`** (con "de").
La lista `TITLE_COLUMNS` solo tenia `Nombre del Producto` (con "del") y
`Nombre Producto`. El comparador normaliza tildes, espacios y mayusculas,
pero no la preposicion:

```
Input real:          "Nombre de Producto"  ->  nombredeproducto
Alias mas parecido:  "Nombre del Producto" ->  nombredelproducto   NO coincide
```

Resultado: `title` quedaba vacio y de ahi salian los tres sintomas:

| Sintoma | Origen |
|---|---|
| Title = codigo modelo-color | `product_create(title=... or handle)` caia al handle, que era el slug del Mod-Col |
| Handle = solo el codigo | `normalize_handle` recibia vacio y devolvia solo el Mod-Col |
| Alt de imagen vacio | se armaba con el title vacio |

El separador `|` era un bug aparte: `html_list` cortaba por saltos de linea y
por vinetas, pero no por `|`, aunque el validador del Centro de Input ya le
pedia al usuario usar `|` "para que la app arme los bullets del Body HTML".

---

## Cambios en `generate_columbia_matrixify.py`

1. **`html_list`**: se agrega `|` como separador de bullets, junto a los saltos
   de linea y las vinetas que ya existian.

2. **`normalize_header_loose_key` (nueva)**: clave de comparacion que ademas
   ignora conectores (`de`, `del`, `la`, `el`, `los`, `las`, `y`, `the`, `of`).
   Se usa como tercer intento en `row_alias_value`, `row_first_existing` y
   `first_existing`, despues de la coincidencia exacta y la normalizada.
   Con esto `Nombre de Producto`, `Nombre del Producto` y `Nombre Producto`
   se reconocen como la misma columna en cualquier marca, sin declarar cada
   variante a mano.

3. **`TITLE_COLUMNS`**: se agregan `Nombre de Producto` y `Nombre de producto`
   **al final**, respetando el orden de prioridad original para no cambiar la
   columna elegida en marcas que ya traen `Title`.

4. **`HANDLE_COLOR_COLUMNS` (nueva)**: lista propia para el color del handle,
   que prefiere `Color web/filtro`. No se toca `COLOR_WEB_COLUMNS` porque ese
   valor alimenta los metafields de siblings de las marcas ya cargadas.

5. **`build_product_handle` (nueva)**: arma
   `nombre-producto-codigo-modelo-color-color` en formato handle (minusculas,
   sin tildes, sin caracteres especiales, separado por guiones). No repite un
   tramo que el nombre ya contenga.

6. **`build_image_alt_text` (nueva)**: devuelve
   `Nombre - 1; Nombre - 2; ...` con el mismo separador `; ` que usa
   `Image Src`, para que Matrixify empareje cada alt con su foto.

7. **`MissingInputColumnError` (nueva)**: si el input no trae ninguna columna
   de nombre, `build_columbia_matrixify` corta con un mensaje claro que lista
   las columnas encontradas. Ya no se usa el codigo modelo-color como reemplazo.

8. **Title por fila**: si la columna existe pero la celda esta vacia, se
   conserva el nombre que el producto ya tiene en Shopify y se deja una
   observacion. Si tampoco existe en Shopify, la fila se omite con su
   observacion. En ningun caso se usa el Mod-Col.

9. **`build_existing_lookup`**: ahora guarda tambien el `Title` del producto
   existente, necesario para el punto anterior.

## El separador `|` en todos los campos

Se reviso columna por columna cual usa `|` en el input de Patagonia y adonde va:

| Columna del input | Destino | Estado antes |
|---|---|---|
| Caracteristicas | Body HTML | roto: un solo bullet |
| Materiales | Body HTML | roto: un solo bullet |
| Materiales | metafield `custom.materialidad` | roto: texto crudo con `\|` |
| Tecnologia | metafield de tecnologia | **ya funcionaba** |
| Tags adicionales | columna `Tags` | roto: **llegaba vacio** |

10. **`split_pipe_items` (nueva)**: separador canonico del input comercial.
    `split_technology_items` ahora delega en el, asi que hay una sola regla.
    `_split_tags` de `app_matrixify.py` tambien delega, en vez de tener su copia.

11. **`TAG_COLUMNS`**: se agregan `Tags adicionales`, `Tags sugeridos`,
    `Tags extra` y `Etiquetas adicionales`. Antes ninguna coincidia y la
    columna `Tags` salia vacia; como el generador escribe
    `Tags Command: REPLACE`, eso **borraba los tags existentes** del producto.

12. **`format_tags` (nueva)**: convierte los tags al formato de Shopify
    (separados por `, `) y elimina repetidos. Se verifico contra un export real
    de Matrixify: 400 de 400 filas usan `, `, asi que ahora la salida coincide
    con el formato de Shopify en vez de diferir.

13. **`join_pipe_items` (nueva)**: aplana los items para los metafields de tipo
    `single_line_text_field`. Se aplica a `custom.materialidad`, que antes
    recibia el texto crudo con los `|` pegados al texto anterior.

14. **`protect_decimal_pipes` / `restore_decimal_pipes` (nuevas)**: en Materiales
    aparece `Cuerpo: 5|3-oz (150 g)`, donde el `|` **no es separador** sino una
    coma decimal. La aritmetica lo confirma: 150 g son 5.3 oz y 178 g son 6.3 oz.
    Pasa en **125 de las 252 filas**. Un `|` entre digitos ya no corta, ni en los
    bullets ni en los metafields. El caracter se conserva tal cual venia.

## Cambios en `app_matrixify.py`

15. **Creacion en Shopify**: se elimina el fallback `title=... or handle`. Si
    el Title viene vacio, ese producto falla con mensaje claro y queda en la
    tabla de errores del job, en vez de crearse con el codigo como nombre.

16. **Error de columna faltante**: se captura `MissingInputColumnError` antes
    del `except Exception` generico, para mostrar el mensaje limpio sin traceback.

---

## Validacion ejecutada

Corrida completa de `build_columbia_matrixify` sobre
`Input_Catalogo_PATAGONIA_20260731.xlsx`, sitio Rockford (Patagonia es una marca
de Rockford.pe; no existe un sitio `patagonia` en `SITE_CONFIGS`).

**252 productos generados de 252 filas de input:**

| Control | Resultado |
|---|---|
| Title vacio | 0 |
| Title igual al Mod-Col | 0 |
| Handle duplicado | 0 |
| Handle con formato invalido | 0 |
| Tags vacio | 0 |
| Tags con `\|` sin convertir | 0 |
| Materialidad vacia | 0 |
| Tecnologia vacia | 1 (la unica fila del input sin tecnologia) |
| Image Alt Text vacio | 0 |
| Body HTML sin bullets | 0 |
| Promedio de bullets por producto | 12.3 |

Ejemplos de salida real:

```
Title  : Pantalon Jogger Mujer Patagonia Happy Hike Studio
Handle : pantalon-jogger-mujer-patagonia-happy-hike-studio-21218-n11-negro
Tags   : Pantalones, Jogger, Active Essentials, Vestuario, Mujer,
         21218-N11, size-womens-bottoms
Tecno  : Fair Trade | HeiQ Pure | miDori bioSoft | NetPlus | Poliester Reciclado
Alt    : Pantalon Jogger Mujer Patagonia Happy Hike Studio - 1; ... - 2; ...
```

No regresion (misma columna detectada y mismos valores, antes vs despues):

| Archivo | Columna nombre | Title dif | Body dif | Tags dif |
|---|---|---|---|---|
| Catalogo Columbia Input 14-07-2026 | Title | 0 | 0 | 59 (solo espaciado) |
| Catalogo Hush Puppies 25-06-2026 | Title | 0 | 0 | 0 |
| Catalogo Active - Vans SP26 | Titulo | 0 | 0 | 0 |
| Carga Catalogo Clb 1 | Nombre del producto | 0 | 0 | 0 |
| Catalogo Columbia 06-05-2026 | (sin columna) | 0 | 0 | 0 |

Las 59 diferencias de Columbia son solo el espacio despues de la coma
(`Gorros,Hiking` pasa a `Gorros, Hiking`): mismos tags, mismo orden. Se
comprobo contra un export real de Matrixify que Shopify usa `, ` en 400 de 400
filas, asi que la salida ahora **coincide** con el formato de Shopify en vez de
diferir, lo que reduce falsos "producto cambiado".

Tambien se verifico que la clave flexible no genere colisiones entre listas de
columnas distintas (las unicas coincidencias son entre las dos listas de color,
que se solapan por diseno).

---

## Impacto del handle nuevo, marca por marca

El handle se arma siempre con la estructura nueva, para **todas las marcas y
todos los sitios**. El `Handle` que traiga el input ya no manda: solo se usa
como respaldo si la fila no tiene nombre de producto.

| Input medido | Filas | Handles que cambian | Duplicados | Formato invalido |
|---|---|---|---|---|
| Patagonia 2026-07-31 | 252 | 252 | 0 | 0 |
| Columbia 2026-07-14 | 59 | 59 | 0 | 0 |
| Hush Puppies 2026-06-25 | 2.193 | 1.615 | 0 | 0 |
| Vans SP26 | 30 | 30 | 0 | 0 |
| **Total** | **2.534** | **1.956** | **0** | **0** |

Ejemplos del antes y despues:

```
Patagonia  antes: 20265-ike
           ahora: polar-mujer-patagonia-daily-snap-t-pullover-20265-ike-marron

Columbia   antes: gorro-columbia-mesh-1495921-ifg
           ahora: gorro-uniex-columbia-mesh-1495921-ifg-gris

H. Puppies antes: mocasines-mujer-natalia-hush-puppies-hp202011248963-smv
           ahora: mocasin-natalia-cuero-mujer-hp202011248963-smv-azul

Vans       antes: zapatillas-brooklyn-ls-vn000d7qb9m-gu8
           ahora: zapatillas-brooklyn-ls-vn000d7qb9m-gu8-negro
```

Para que Hush Puppies tomara el color se agregaron a `HANDLE_COLOR_COLUMNS` los
nombres en formato metafield (`Metafield: custom.color_forus [...]` y
`custom.grupo_color`), que es como los nombra su input. Solo 1 de sus 2.193
filas queda sin color.

## Dos cosas que debes saber

**1. Cambian 1.956 URLs de producto.** El generador escribe el `ID` de Shopify
en cada fila y `build_existing_lookup` busca el producto por el metafield
`codigo_modelo_color`, no por handle: por eso Matrixify **renombra** el producto
existente en lugar de duplicarlo, y no se pierden ventas ni reviews. Pero la URL
publica si cambia en los cuatro sitios. **Antes de correr la carga completa,
confirma que Shopify tenga activada la creacion automatica de redirecciones**,
o los enlaces existentes (Google, campanas, marketplaces) quedan en 404.
Conviene hacerlo primero en un sitio chico, como Vans (30 productos).

**2. El `5|3-oz` de Materiales queda tal cual.** No se corta por ese `|`, pero
tampoco se convierte a `5.3-oz` porque eso seria reescribir tu contenido. Los
numeros dicen que es un punto decimal (150 g = 5.3 oz, 178 g = 6.3 oz) y afecta
125 de 252 productos. Si quieres que se convierta a punto, es un cambio de una
linea: avisame y lo hago.

**3. Queda un punto fuera de este alcance.** El generador de **Centry**
(`build_centry_from_matrixify` en `app_matrixify.py`) todavia usa
`first_non_empty(product_row.get("Title"), key)`, es decir, cae al Mod-Col
cuando el producto no existe en Shopify. No lo toque porque Centry exige nombre
no vacio y cambiarlo sin revisar sus reglas puede invalidar el archivo. Si
quieres, lo corregimos aparte.
