# Qué falta subir a GitHub — 2026-08-17

Comparado contra `main` en el commit `f7a864253` (tu último "Add files via
upload"). Ya subiste el paquete intermedio; esto es **solo lo que falta**.

Comprobado antes de armarlo: en esos 7 commits no subiste ningún cambio propio,
así que estos archivos no pisan nada tuyo. `scripts/test_body_html_top_row.py`
ya está idéntico en GitHub y por eso **no** viene en el ZIP.

## Archivos que cambiaron

| Archivo | Estado en GitHub |
|---|---|
| `app_matrixify.py` | reemplaza (le falta la propagación al grupo y el resolvedor por handle) |
| `generate_columbia_matrixify.py` | reemplaza (le falta la unión de siblings y el `strip_html`) |
| `shopify_api.py` | reemplaza (le falta `fetch_product_id_by_handle`) |
| `engines/storage_check.py` | reemplaza (le falta el reintento del 503) |
| `docs/CSS_FICHA_PRODUCTO.md` | **no existe** |
| `scripts/test_siblings_referencias.py` | reemplaza |
| `scripts/test_siblings_carga_completa.py` | **no existe** |
| `scripts/test_storage_check.py` | **no existe** |

`scripts/test_body_html_top_row.py` ya está bien subido: no viene en el ZIP.

---

## 1. Body HTML y metafields vacíos

Los 67 productos Rockford salían con las 450 filas correctas pero con el **Body
HTML, el Top Row y los ~20 metafields vacíos**. Al sincronizar, Shopify recibía
un solo metafield (`Marca`, que sale del respaldo `Vendor`) y ninguna
descripción.

El bloque de producto se escribe una sola vez, en la primera variante. En
Rockford las tallas cero se muestran como "Talla Única", ordenan primeras y se
quedaban con esa posición 1; después `final_variant_filter` las eliminaba —bien,
porque no corresponde talla única en calzado con tallas reales— y se llevaba la
descripción del producto entero. **136 filas borradas, 67 de 67 productos sin
descripción.** `Row #` empezaba en 3 en vez de 1: esa era la huella.

`spread_top_row_block` arrastra el bloque a todas las filas antes de filtrar y
`collapse_top_row_block` lo deja solo en la que sobreviva, renumerando `Row #` y
`Variant Position`. Ningún filtro, ni este ni uno futuro, puede volver a vaciarlo.

## 2. Valores en MAYÚSCULAS

`nombre_propio()` convierte a Nombre Propio **solo lo que viene entero en
mayúsculas**; si el texto ya trae minúsculas, la caja es deliberada y se respeta
(`Outgravity` queda igual).

`CUERO`→`Cuero`, `NO APLICA`→`No Aplica`, `MOCASÍN`→`Mocasín`,
`BOTAS DE CUERO`→`Botas de Cuero`, `GORE-TEX`→`Gore-Tex`.

No se tocan: `codigo_modelo_color` y `guia_de_tallas` (código y referencia),
`siblings` (handles), `nombre_corto` y `descripcion_corta` (prosa de la marca),
`marca`. En el Body HTML solo Materiales y Cuidados; Descripción y
Características quedan como las escribió la marca.

## 3. Siblings — ahora se recalculan en CADA carga completa

Eran **dos** problemas.

**a) Se borraban relaciones válidas.** `siblings_by_model` se calculaba solo con
el input, que trae únicamente los colores del día. Un modelo con tres colores
publicados que recibía uno nuevo terminaba con la relación reducida al nuevo.

Ahora `siblings_ya_publicados()` lee el catálogo de Shopify, agrupa por código de
modelo y **une** con lo que trae el input. Lee lista JSON, texto con comas y
descarta los `gid://`. Además rescata al producto cuyo `codigo_modelo_color` está
vacío, porque lo recoge de la lista de siblings de sus hermanos.

**b) Los productos ya publicados no se enteraban del color nuevo.** No venían en
el input, así que no se generaba fila para ellos.

Ahora la relación se trata como del **grupo**: la segunda pasada de
`apply_full_product_updates` escribe la misma lista en **todos** los miembros.
Cargando solo el color nuevo se actualizan los tres productos, tanto
`custom.siblings` (IDs) como `theme.siblings` (handles).

Cubre productos nuevos, existentes, colores agregados después y actualización de
relaciones. No borra relaciones válidas.

**c) `custom.siblings` es `list.product_reference`**, espera
`gid://shopify/Product/123`, no handles. Se agregó `fetch_product_id_by_handle`
en `shopify_api.py` y un resolvedor con caché de sesión que solo guarda aciertos
(un hermano que aún no existe tiene que poder resolverse cuando se cree). Hace
falta porque `apply_full_product_updates` recibe **un producto por llamada**.

## 4. Código Modelo Color vacío

Shopify rechaza el valor cuando el tipo no coincide con el de la definición, y la
ficha lo muestra en blanco. El tipo se adivinaba desde la cabecera de Matrixify
(que exporta `[id]`, que no es un tipo real) o desde la tabla interna.

Ahora se consulta la **definición real del metacampo en la tienda** y se usa ese
tipo. Una consulta por metacampo, cacheada. Si falla, decide la tabla interna
como antes.

## 5. HTML de la ficha — la causa NO está en la app

**Comprobado:** generando el mismo producto con las cuatro configuraciones de
marca, el Body HTML sale con el **mismo sha256 y los mismos 503 caracteres**.

```
columbia  sha=0eb3c51dee173556 len=503
hush_puppies  sha=0eb3c51dee173556 len=503
vans  sha=0eb3c51dee173556 len=503
rockford  sha=0eb3c51dee173556 len=503
```

El HTML no lleva estilos propios a propósito: `sanitize_body_html` elimina
cualquier `<style>` del cuerpo, y un `style=` en línea le ganaría al tema y
rompería Columbia y Vans, que hoy se ven bien. **La separación la pone el tema de
cada tienda.** Columbia y Vans ya estilan las clases `nweb__`; Hush Puppies y
Rockford no.

Por eso la corrección va en el tema de esas dos tiendas: **`docs/CSS_FICHA_PRODUCTO.md`**
trae el CSS listo para pegar, y las instrucciones. Columbia y Vans no se tocan.

**Y sí había un fallo en el código, latente:** `strip_html()` quitaba solo las
etiquetas, así que el contenido de un `<style>` heredado se colaba **como texto**
a la descripción corta, al bullet de Sial y a la columna Descripcion de Centry.
Corregido: ahora descarta `<style>` y `<script>` enteros. Si algún producto de
Hush Puppies tiene un body heredado con CSS, esto es parte de por qué se veía
raro.

## 6. "Almacenamiento sin persistir" por un 503 de GitHub

El diagnóstico decía "Respuesta 503: No server is currently available… Revisa el
token en Secrets". El token no tenía nada que ver: un rechazo de token es **401**.
El 503 es GitHub que no atendió, y **un solo hipo dejaba el banner en rojo**.

Ahora los códigos transitorios (`0`, `429`, `500`, `502`, `503`, `504`) se
reintentan 3 veces con espera creciente; `401` y `404` no. Si aun así falla, el
paso queda como **aviso** y el banner dice **"Almacenamiento por confirmar"**, que
es la verdad. El consejo apunta a `githubstatus.com`, no al token.

---

## Comprobado

Con tu input real (`Input_Catalogo_ROCKFORD_20260810 - calzado of.xlsx`) y el
ARTI reconstruido desde la hoja *Carga Sial*:

| | `main` hoy | con los arreglos |
|---|---|---|
| Filas / productos | 450 / 67 | 450 / 67 |
| Con Body HTML | **0** | **67** |
| Con Top Row | **0** | **67** |
| Metafields con valor | **0** | **1.072** |
| *Centry* con Descripción | **0** | **450** |
| `Row #` empieza en | 3 | 1 |

El conjunto de variantes **no cambia**: pares handle+SKU, tallas, Title, Vendor,
Type e Image Src salen idénticos.

Siblings, contra un Shopify simulado que rechaza handles igual que el real:

| | `main` hoy | con los arreglos |
|---|---|---|
| `custom.siblings` escritos | **0** | **1 por producto** |
| Valor | `["mocasin-…"]` ✗ | `["gid://shopify/Product/1000"]` ✓ |
| Color nuevo hereda publicados | no | **sí** |
| Publicados se actualizan | no | **sí, los 3** |

- Suite: **22 en verde**. Siguen fallando `test_auth_accesos` y
  `test_brand_commercial_input`, **preexistentes y ya conocidos** (esperan un
  `auth_role_label` y unas hojas legacy que no existen). Cero regresiones.
- 49 pruebas nuevas en cuatro archivos.
- Sin funciones huérfanas nuevas.

**Lo único que no se pudo probar contra la API real** es la escritura de
metafields y siblings: no tengo acceso a tu tienda. La lógica está cubierta con
pruebas contra un Shopify simulado; la confirmación final es tu primera
sincronización.

## Después de subir

1. Regenera el Matrixify de Rockford y sincroniza.
2. Pega el CSS de `docs/CSS_FICHA_PRODUCTO.md` en los temas de **Hush Puppies y
   Rockford solamente**.
3. Comprueba que Columbia y Vans siguen igual.

## Un hallazgo suelto

`matrixify_modelo.xlsx` de la raíz **no es un Excel: es una imagen WEBP**. El
bueno es `data/matrixify_modelo.xlsx`, que es el que usa el código
(`DEFAULT_MATRIXIFY_PATH`). El de la raíz no lo usa nadie y conviene borrarlo
antes de que alguien lo abra por error. Es el mismo tipo de accidente que ya pasó
con `assets/app.css`.
