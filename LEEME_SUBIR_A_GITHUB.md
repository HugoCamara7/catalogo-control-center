# Qué subir y por qué

Paquete sobre `main` en `f5399b0`. **Es todo lo que te falta subir**: el ajuste
de Centry contra la plantilla y la activación de Patagonia.pe.

Sube cada archivo a su carpeta. **`app_matrixify.py` va al final.**

| Archivo | Carpeta en el repo | Estado |
| --- | --- | --- |
| `generate_columbia_matrixify.py` | raíz | modificado |
| `engines/centry_map.py` | `engines` | modificado |
| `.streamlit/secrets.example.toml` | `.streamlit` | modificado |
| `scripts/test_centry_contaminacion.py` | `scripts` | modificado |
| `scripts/test_centry_plantilla.py` | `scripts` | **nuevo** |
| `scripts/test_sitio_patagonia.py` | `scripts` | **nuevo** |
| `app_matrixify.py` | raíz | modificado — **este al final** |

> Truco: arrastra la carpeta `engines` o `scripts` entera y GitHub respeta la
> ruta sola, sin tener que navegar.

---

# PARTE 1 — Patagonia.pe como sitio propio

Hasta ahora Patagonia era una **marca dentro de Rockford.pe**. Ahora es un
**sitio**, y la activación alcanza a todo porque casi todo se lee de una sola
entrada en `SITE_CONFIGS`.

**Qué queda activo:**

- Aparece en el **selector de sitio**: `Columbia.pe · Rockford.pe ·
  HushPuppies.pe · Patagonia.pe · Vans.pe`.
- **Fotos** en su carpeta del bucket (`/PATAGONIA`), tanto el motor JPG normal
  como el mantenedor PNG/JPEG.
- **Input comercial** con su columna `PUBLICAR_PATAGONIA_PE`, sus clases
  (Vestuario, Accesorios) y su plantilla.
- **Centry** completo: probado de punta a punta con 0 hallazgos bloqueantes,
  SKU y EAN por variante, género `Hombre` y guía `HombrevestuarioPatagonia`.
- **Carga SIAL** con su propia columna `Porduct Id - Patagonia.pe`.
- **Solicitudes**, KPIs y logo: ya funcionaban por marca, ahora también por
  sitio.

**Transición.** Patagonia sigue en `allowed_arti_brands` de Rockford.pe **a
propósito**: la plantilla trae las **dos** columnas de publicación
(`PUBLICAR_ROCKFORD_PE` y `PUBLICAR_PATAGONIA_PE`) y puedes decidir producto por
producto mientras dura el cambio. Cuando quieras cortar del todo, se quita
`"PATAGONIA"` de la lista de Rockford y listo.

**Tipos de prenda.** Un sitio nuevo no está en el diccionario por sitio, así que
cada tipo sale con su **nombre canónico** (`Casacas`, `Polares`...). Es el
comportamiento correcto: no se inventa una nomenclatura que Patagonia no ha
declarado. Si más adelante quiere nombres propios, se agregan a
`engines/garment_types.py`.

## ⚠️ Lo que tienes que hacer tú

**1. Las credenciales de Shopify.** En los *Secrets* de Streamlit, añade:

```toml
[shopify_sites.patagonia]
shop_domain = "patagoniape.myshopify.com"
client_id = "..."
client_secret = "..."
admin_access_token = "..."
api_version = "2026-04"
```

Sin esto el sitio aparece pero la API no conecta. El `shop_domain` que puse en
el ejemplo es una suposición por el patrón de las otras tiendas: **corrígelo con
el real**.

**2. Confirmar la bodega SIAL.** Puse `sial_active_columns = ["6", "13"]`,
heredado de Rockford, que es donde Patagonia se cargaba hasta ahora. Si opera en
otra bodega hay que cambiar ese código en `SITE_CONFIGS["patagonia"]`. **El resto
del sitio funciona igual**; sólo afecta a la hoja *Carga Sial*.

---

# PARTE 2 — Centry contra la plantilla

## Por qué encontraba el material y lo dejaba vacío

Dos causas encadenadas.

**El motor se pisaba a sí mismo.** Los pares del Body (`Forro: 100% Poliéster`)
se volcaban en la fila con `**atributos_centry`, y **tres líneas más abajo**
`centry_apply_apparel_fields` escribía encima con `material`, que venía vacío
porque `centry_seccion_como_valor` rechaza a propósito el texto con etiquetas —y
la sección Materiales es justo eso—. El motor encontraba el dato, lo colocaba, y
lo borraba. Ese era el `atributos no aplicados: Forro: ...` con la columna en
blanco.

**Y "Forro" no tenía dónde ir.** En `ETIQUETAS_A_COLUMNA` sólo apuntaba a
columnas de **calzado**. En un cortavientos o un gorro esa columna no existe.
`Material exterior` directamente **no estaba en la tabla**.

**Corregido:** `centry_poner_si_vacio` (nada sobrescribe una columna con valor),
`material`/`composición` se recuperan de los pares del Body y llegan al *Listado
de características*, 11 etiquetas nuevas, y `atributos_desde_caracteristicas` va
en **dos pasadas** para que `Composición` conserve su columna y `Forro` la use
sólo si está libre.

## Por qué el SKU salía mal y el EAN vacío

`variant_centry_sku = variant_sku or barcode`. En sus dos versiones **un código
de barras podía acabar publicado como SKU de la variante**, y buscar el EAN de un
SKU que no existe no devuelve nada.

**Corregido:** el SKU es el SKU y nada más. Si la variante llega sin SKU se
rescata el `CODINT_MA` del maestro por Mod-Col + talla; si tampoco aparece, no
entra y se reporta. El EAN se busca **a nivel variante**: input → `Variant
Barcode` → maestro por SKU normalizado → maestro por Mod-Col + talla.

## Por qué había 850 hallazgos bloqueantes

El motor escribía el **valor crudo del catálogo** en columnas con diccionario
cerrado: `Niños`/`Unisex` donde la plantilla pide `Niño`/`Unisex adulto`,
`Zapatillas` donde pide `Zapatillas urbanas`. Centry los rechaza y la validación
los contaba uno por producto.

**Corregido en el origen:** `centry_gender_marketplace` traduce contra el
diccionario real (mirando la edad), y **`centry_depurar_valores_de_plantilla`**
es una puerta única — si el valor no está en el diccionario de su columna, no se
escribe; si está con otra ortografía, se guarda como lo escribe la plantilla. El
aviso sale **agrupado por columna**, no por producto.

Medido con seis productos de cinco marcas: **de 850 bloqueantes a 0**.

## Precio

Fuera del Centry: no bloquea, no es error, no genera advertencias. Se quitó la
tarjeta "Precio faltante" y el aviso por producto.

## Pantalla de validación

Resumen arriba **Listos | Con observaciones | Bloqueados**; sólo los bloqueantes
a la vista; las demás plegadas en `N observaciones no bloqueantes`, agrupadas por
campo y con el detalle debajo; la vista previa y las notas del proceso, también
plegadas.

---

## Pruebas

**Batería completa: 37 archivos**, todos OK salvo `test_auth_accesos.py` y
`test_brand_commercial_input.py`, los dos que ya fallaban antes de este trabajo.

Nuevos:

```bash
python scripts/test_sitio_patagonia.py
```

```bash
python scripts/test_centry_plantilla.py
```

25 pruebas para Patagonia (sitio, fotos, input, tipos, Centry, SIAL, y que no se
rompan los sitios que ya estaban) y 25 para la plantilla, sobre seis productos de
cinco marcas y las cuatro familias.

Además, con `AppTest`: la app arranca sin excepciones, el selector muestra los
cinco sitios y cambiar a **Patagonia.pe** y entrar a carga parcial no lanza nada.
