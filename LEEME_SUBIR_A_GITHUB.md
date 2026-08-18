# Qué subir — motor Centry por plantilla

| Archivo | Ruta | |
|---|---|---|
| `engines/centry_map.py` | `engines/` | **nuevo** |
| `data/plantilla_centry_productos.xlsx` | `data/` | **nuevo** |
| `scripts/test_centry_map.py` | `scripts/` | **nuevo** |
| `app_matrixify.py` | raíz | modificado |
| `engines/ticket_flow.py` | `engines/` | modificado (bandeja) |
| `scripts/test_bandeja_solicitudes.py` | `scripts/` | **nuevo** (bandeja) |
| `scripts/test_siblings_carga_completa.py` | `scripts/` | modificado |

La plantilla va al repo: es la **fuente de verdad**. Si Centry cambia columnas o
valores, reemplazas el Excel y no se toca Python.

## Nueva lógica

1. **El tipo pasa primero por el diccionario** (`engines/garment_types.py`).
   Si está, se usa el canónico y su clase. Si no está, **se acepta tal cual** y
   queda la advertencia. El producto nunca se descarta.
2. **Familia** por término dentro del tipo (calzado antes que vestuario, para
   que "zapatilla de running" no caiga en superior). La clase del diccionario es
   el respaldo.
3. **Columnas** = SIEMPRE + las de la familia + `COD MOD`, `COD COL`, `TALLA`,
   `Advertencias`. Sin familia salen solo SIEMPRE + la cola.
4. **Categoría** con `Marca|Tipo|Genero`; la marca concreta gana sobre `Todos`.
5. **Valores** contra el diccionario de cada columna, devolviendo la ortografía
   de la plantilla (`BAJA` → `Baja`).

## Categoría inteligente: siempre sale una

La tabla `Categorias` no cubre todas las combinaciones, y 124 filas salían sin
categoría. Ahora se resuelve en **cuatro pasos**, siempre avisando cuando no es
una coincidencia exacta:

1. **Exacta**: `Marca|Tipo|Género`, con la marca concreta por delante de `Todos`.
2. **Deducida del mismo tipo en otro género**: si `Polos / Hombre` es
   "Vestuario / Ropa Masculina / Poleras Manga Corta", entonces `Polos / Mujer`
   es "Vestuario / Ropa **Femenina** / Poleras Manga Corta". Traduce el segmento
   de género (`Calzados Masculinos` ↔ `Calzados Femeninos`, etc.). Una categoría
   sin segmento de género (Accesorios / Bolsos…) vale igual para todos.
3. **Genérica de su familia y género**, calculada **contando la propia tabla**,
   no escrita a mano: superior/Mujer → "Vestuario / Ropa Femenina",
   calzado/Hombre → "Calzados / Calzados Masculinos".
4. Si aun así no hay, queda pendiente con el motivo.

**No se cruza entre adulto e infantil.** Deducir `Cortavientos / Mujer` desde
`Niñas` daba "Vestuario / **Infantil** / Ropa Femenina", que no existe.

La **clase del diccionario** también entra: "Slip Ons" no coincide con ningún
término, pero el diccionario dice que es Calzado, y con eso ya resuelve.

| | antes | ahora |
|---|---|---|
| Filas sin categoría | 124 | **0** |
| Categoría llena | 450/450 | 450/450 |

De las 124 advertencias: 77 categorías deducidas y 47 genéricas. **Todas llevan
categoría**; la advertencia dice de dónde salió para poder revisarla.

## Shopify → BigQuery: ya funcionaba

Comprobado con un producto que **no está en Shopify**: la carga parcial lo arma
igual desde BigQuery/ARTI y avisa *"No existe en Shopify; se completó Centry con
BigQuery/ARTI"*. Si no está en ninguno, dice *"Código no encontrado en
BigQuery/ARTI"*. No hizo falta tocar nada.

## Inconsistencias encontradas en la plantilla

- **`SIEMPRE` no trae diccionarios: trae 2 productos de ejemplo.** Tomarlas como
  valores permitidos habría rechazado todos los productos reales. Sus columnas
  son texto libre.
- **`Forma de la punta` está dos veces en Calzado**: la primera vacía. Se
  conserva la que trae el diccionario.
- **28 claves `(Marca, Tipo, Género)` con dos categorías.** Cuando una es más
  general se elige esa y se avisa; cuando están al mismo nivel (Guantes /
  Unisex Adultos, que duda entre Deporte Masculino y Femenino) **no se elige**.
- **29 combinaciones existen solo para Columbia o Bsoul y no tienen respaldo en
  `Todos`**: si otra marca trae ese tipo, queda sin categoría.
- Nombres inconsistentes entre hojas (`Genero` sin tilde en Accesorios, prefijos
  duplicados como `Tipo de cuello - Tipo de cuello -`). Se respetan tal cual
  porque Centry espera ese nombre exacto.

## Columnas: 98 → 90, sin duplicados ni basura

La primera versión añadía las columnas nuevas **encima** de la lista vieja en
vez de reemplazarla. Y la lista vieja estaba **con mojibake**: `CategorÃ­a`,
`GarantÃ­a`, `PerÃº`. Como esos nombres no coinciden con los de la plantilla,
cada columna salía **dos veces**: la rota y la buena. Más `cccc`,
`INFORMACIÓN ADICIONAL` y `Unnamed: 52`..`Unnamed: 56`.

Dos cambios:

1. **`CENTRY_COLUMNS` sale ahora de la plantilla**, no de listas escritas a mano
   (`_centry_columns_desde_plantilla`). Si no se puede leer el Excel, vuelve a
   las listas de antes para que la app siga funcionando.
2. **Se reparó el mojibake del archivo**: 170 líneas, 13 secuencias
   (`Ã³`→`ó`, `Ã­`→`í`, `Ãº`→`ú`…). Se respetaron los alias de **doble**
   codificación, que son intencionales para leer datos ya corruptos.

| | antes | ahora |
|---|---|---|
| Columnas Centry | 98 | **90** |
| Basura / duplicadas | 7 | **0** |

Comprobado que no se perdió dato al limpiar los nombres: `Nombre`, `Marca`,
`Descripcion`, `Listado de características`, `Garantía`, `Categoría`, `Talla`,
`Género`, `Estado` e `URL imagen principal` siguen en 450/450, y `Color` en 67,
igual que antes.

## Corrección del NameError

La primera versión reventaba la carga parcial:

```
NameError: name 'modelo_centry' is not defined
  build_centry_sial_from_matrixify, línea 4257
```

Al añadir las columnas clave, el reemplazo tocó **dos** funciones y las
variables solo se calculaban en una. Además esas cuatro columnas **no existen en
la hoja Sial**, que identifica con `Mod`/`Col`/`Tal`: sobraban ahí. Se quitaron
de `build_centry_sial_from_matrixify` y quedan solo en la hoja Centry.

Verificado ejecutando las tres rutas, no solo compilando:

| Función | |
|---|---|
| `build_centry_from_matrixify` (parcial, `only_codes`) | OK — 6 filas, 98 columnas |
| `build_centry_sial_from_matrixify` | OK — 450 filas, 48 columnas |
| `build_centry_from_matrixify` (completa) | OK — 450 filas, 98 columnas |

## Comprobado con tu carga real

450 filas Centry: `COD MOD`, `COD COL` y `TALLA` llenas en **450/450**, y 124
filas con advertencia explicando qué falta (la mayoría, tipos sin categoría en la
plantilla: Slip Ons, Zapatos, Zapatillas para Rockford).

- Suite: **24 en verde**; los 2 preexistentes de siempre. Cero regresiones.
- `scripts/test_centry_map.py`: 38 pruebas.
- App levanta headless con `HTTP 200`, cero trazas.
