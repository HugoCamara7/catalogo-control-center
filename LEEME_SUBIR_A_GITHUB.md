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
