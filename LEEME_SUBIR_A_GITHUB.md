# Que subir a GitHub

Espejo completo de `HugoCamara7/catalogo-control-center` rama `main`, descargado
el 2026-08-02 despues de tus commits de las 09:29 UTC, con lo que falta aplicado
encima.

## Hay que subir 2 archivos

```
app_matrixify.py                 (nombres restaurados + slugify con enie)
generate_columbia_matrixify.py   (tipos de prenda unificados + acentos)
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
