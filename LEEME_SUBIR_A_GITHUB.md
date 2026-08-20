# Qué subir y por qué

Paquete armado sobre `main` en `bbf59b1` (20/08/2026 13:35 UTC).
Sube los archivos respetando las carpetas. **`app_matrixify.py` va al final.**

| Archivo | Estado |
| --- | --- |
| `app_matrixify.py` | modificado |
| `ticket_system.py` | modificado |
| `catalog_rules.py` | modificado |
| `generate_columbia_matrixify.py` | modificado |
| `engines/catalog_map.py` | modificado |
| `scripts/test_bandeja_solicitudes.py` | modificado |
| `scripts/test_bandeja_rendimiento.py` | nuevo |
| `scripts/test_centry_ean.py` | nuevo |
| `scripts/test_hush_nombre_descripcion_corta.py` | nuevo |
| `scripts/test_fotos_png_masivo.py` | nuevo |

---

## 1. Bandeja de solicitudes: se cerraba la sesión al pulsar una tarjeta

**Causa.** La tarjeta era un enlace de verdad:
`<a href="?ticket=CAT-2026-000031" target="_self">`. Eso no es un rerun de
Streamlit: el navegador **recarga la página entera**, Streamlit abre una sesión
nueva, `st.session_state` queda vacío y `require_login()` devuelve al login,
porque la autenticación vive solo en `session_state`.

**Corrección.** Lo que se pulsa ahora es un `st.button` real, invisible y
estirado sobre la tarjeta. Dispara un rerun normal y la sesión sigue viva. En
el HTML de la tarjeta ya no queda ningún enlace, y hay una prueba que lo vigila.

## 2. Bandeja: lentitud

**Causa.** `GitHubTicketStore.list_tickets()` bajaba el índice del directorio y
después **un archivo por solicitud, uno detrás de otro**. Con 31 solicitudes son
32 viajes HTTP encadenados. La pantalla llama a `list_tickets` **dos veces** por
rerun (una sin filtros para los KPIs, otra filtrada) más un `get_ticket` para el
detalle: **unas 65 peticiones en serie por cada clic**, incluso al marcar una
casilla.

**Corrección.**

- Las descargas van **en paralelo** (8 a la vez).
- La lista se **guarda 25 segundos** en una caché de módulo, y la invalida
  cualquier escritura (crear, actualizar o borrar). Vive en el módulo y no en la
  instancia porque el servicio se construye de nuevo en cada rerun.
- Botón **Actualizar** en la bandeja para forzar la lectura desde GitHub.
- `get_ticket` **nunca** sale de la caché: de ahí viene el `_revision` con el que
  se guarda, y servirlo viejo haría fallar cada guardado con "cambió en otra
  sesión".
- El control de duplicados al crear una solicitud **fuerza lectura fresca**, para
  no reabrir el problema que se corrigió en agosto.

## 3. Bandeja: se veía descuadrada

El marco de la tarjeta lo dibujaba el HTML y la casilla con la acción rápida se
subían a su sitio con `margin-top:-44px` y selectores que adivinaban la
estructura interna de Streamlit. En cuanto una tarjeta era más alta que otra, la
fila se descuadraba.

Ahora el marco lo dibuja un contenedor con clave (`tkcard-`), y el contenido, la
zona pulsable y la franja de abajo son hijos suyos por flujo normal. Sin
márgenes negativos. Medido en la app: las nueve tarjetas de la página quedan
todas en 197 px de alto. Además, marcar una casilla ya muestra la barra de lote
**al primer clic** (antes hacía falta un segundo clic).

## 4. Hush Puppies: `Nombre corto` y `Descripción corta`

Los dos metafields ya existían en el registro, pero lo que escribía la marca no
llegaba a Shopify por tres motivos:

1. **Las columnas no estaban en el input de Hush Puppies.** El validador arma la
   fila normalizada solo con `commercial_input_columns_for_brand`, así que una
   columna que no esté ahí no se lee, no se valida y no se ve en la vista previa.
2. **"Descripción corta" era alias de Características.** Estaba en la lista
   `features` de `catalog_rules.py` y en `FEATURE_COLUMNS` del motor: la frase de
   la PLP se publicaba como bullets del Body HTML y el metafield salía vacío.
3. **Una columna vacía se rellenaba con la descripción larga.** Se resolvía con
   `row_first_existing`, que devuelve el primer valor no vacío, y la lista
   terminaba en `Descripcion`. La PLP mostraba el párrafo entero.

**Corrección.** Las dos columnas entran al perfil de Hush Puppies, Hush Puppies
Kids y Accesorios HP: aparecen en la plantilla, en la guía, en el diccionario,
en la validación y en la vista previa. `Descripción corta` deja de ser alias de
Características. Y cuando el input **trae** la columna manda ella, aunque venga
vacía: un vacío no borra Shopify, pero tampoco se rellena con otra cosa. Las
marcas que no envían estos campos siguen derivándolos como antes.

Ruta completa comprobada: input → validación → vista previa → Matrixify →
metafields por API directa.

## 5. Centry: EAN que no llegaba

Cuatro causas, ninguna visible en el resultado:

1. **El maestro guardaba la fila equivocada.** `build_centry_arti_lookup` usaba
   `setdefault`. Como el maestro trae varias filas por SKU (una por bodega), si
   la primera venía sin `CodBarras` el SKU se quedaba sin EAN aunque otra fila
   del mismo SKU sí lo tuviera.
2. **El SKU no emparejaba por formato.** El maestro devuelve `12345` donde
   Shopify tiene `0012345`, o `12345.0` cuando Excel lo leyó como número. La
   comparación era por cadena exacta.
3. **El EAN llegaba roto y pasaba el control.** Excel guarda el código como
   número y lo devuelve como `7.79871E+12` o `7798712345678.0`. No es vacío, así
   que se colaba hasta Centry convertido en basura.
4. **Solo se miraban dos fuentes.** Era
   `first_non_empty(maestro, Variant Barcode)`: el EAN que venía en el propio
   input no se leía.

**Corrección.** Un resolutor por SKU/variante que recorre las fuentes en el orden
pedido —input → Variant Barcode de Shopify → maestro SIAL/BigQuery por SKU →
maestro por Mod-Col + talla— y normaliza el código venga de donde venga. Si no
aparece en ninguna, la variante queda marcada como **PENDIENTE** en la hoja
*Revisión Centry*, con el detalle de qué SKUs son. Y se agrega una línea de
resumen con **de dónde salió cada EAN**, que es lo que permite ver la causa: si
todos dicen PENDIENTE el maestro no llegó; si el maestro resuelve pocos, el
problema es el emparejamiento por SKU.

## 6. Mantenedor Fotos PNG: proceso masivo por Excel

En *Carga parcial → Mantenedor Fotos PNG* hay un selector nuevo: **Un código** o
**Excel con varios códigos**. Con Excel, la herramienta lee la columna
`Código Modelo Color` (acepta los alias habituales), quita vacíos y repetidos,
valida el formato **antes de tocar la red**, y busca las vistas de todos los
modelos con una barra de avance.

Muestra por modelo: vistas encontradas, cargadas, ya existentes, sin PNG,
duplicadas y errores; avisa de los códigos que no existen en Shopify; pide
confirmación antes de cargar; y deja descargar un Excel con tres hojas —
*Resumen por modelo*, *Detalle por vista* y *Descartados*.

**Sigue siendo un mantenedor independiente.** Reutiliza tal cual las piezas del
modo de un solo código, así que el tope de **10 vistas**, el orden, el alt text
(el handle) y el control de fotos repetidas son los mismos. **No se agregó PNG
al motor normal de imágenes**, que continúa buscando solo JPG/JPEG; hay una
prueba que lo comprueba.

---

## Pruebas

Batería completa: **32 archivos, todos OK**, salvo los dos que ya fallaban en
`main` antes de este paquete (`test_auth_accesos.py` y
`test_brand_commercial_input.py`; comprobado sobre `main` limpio).

Nuevos:

```bash
python scripts/test_bandeja_rendimiento.py
```

```bash
python scripts/test_centry_ean.py
```

```bash
python scripts/test_hush_nombre_descripcion_corta.py
```

```bash
python scripts/test_fotos_png_masivo.py
```

Además se levantó la app en local con solicitudes de prueba: pulsar una tarjeta
cambia el detalle **sin volver al login**, y el Mantenedor Fotos PNG abre sus dos
modos sin excepciones.
