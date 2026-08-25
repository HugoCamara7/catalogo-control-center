# Qué subir y por qué

Paquete sobre `main` en `7675a4d`. **Es todo lo que te falta subir.**

**`app_matrixify.py` va al final.**

| Archivo | Carpeta en el repo | Estado |
| --- | --- | --- |
| `engines/tallas_calzado.py` | `engines` | **nuevo** |
| `engines/centry_map.py` | `engines` | modificado |
| `generate_columbia_matrixify.py` | raíz | modificado |
| `scripts/test_tallas_calzado_pe.py` | `scripts` | **nuevo** |
| `scripts/test_centry_plantilla.py` | `scripts` | modificado |
| `scripts/test_centry_ean.py` | `scripts` | modificado |
| `app_matrixify.py` | raíz | modificado — **al final** |

> Arrastra las carpetas `engines` y `scripts` enteras y GitHub respeta la ruta.

---

# PARTE 1 — Rockford: los EAN que estaban en la BD y no llegaban

Cuando el código **sí está en el maestro** y la columna sale vacía, el problema
no es el dato: es **cómo cruzan las claves**. Encontré tres desajustes más.

**1. La talla se escribe distinto en cada lado.** El maestro la guarda como
número y Shopify como texto, así que la misma talla llega como `38`, `038`,
`38.0` o ` 38 `. Se comparaba la cadena tal cual, así que no cruzaban y la
variante se quedaba sin EAN. Ahora hay una **clave de talla** que normaliza las
dos partes: las cuatro formas caen en la misma entrada.

**2. El SKU de Shopify a veces ES el código de barras.** Hubo cargas antiguas
que publicaron el EAN en la columna del SKU (era el viejo
`barcode or variant_sku`). Buscar "su" EAN por ese SKU no devuelve nada… porque
ese SKU ya era el EAN. Ahora hay un índice por código de barras y, si el SKU de
Shopify aparece ahí, se usa como EAN y se reporta así.

**3. El resumen mentía sobre el origen.** Todo salía etiquetado como
`Maestro (SKU)` aunque hubiera cruzado por Mod-Col + talla, así que el
diagnóstico apuntaba al sitio equivocado. Ahora dice por dónde cruzó de verdad.

## Y si aun así falta alguno, la hoja te dice por qué

`Revision Centry` trae ahora dos líneas nuevas que separan lo accionable:

> `12 variantes: la fila SI está en el maestro pero llegó sin código de barras.
> Ejemplos -> 5486079 (mod-col RK110021743-5ZV, talla 38); …`

> `4 variantes: el SKU no aparece en el maestro (ni por Mod-Col + talla).
> Ejemplos -> …`

> `El maestro trae 12.480 SKU y 9.310 pares Mod-Col+talla. Ejemplo de SKU del
> maestro: 5486079, 5486080, …`

Con eso se sabe **de un vistazo** si hay que arreglar el maestro (falta el
código) o el emparejamiento (la fila está pero no cruza). Antes un "EAN
faltante" no decía nada.

## Comprobado

Seis escenarios en los que el maestro **sí** tiene el código, cambiando solo
cómo está escrita la clave:

| Escenario | Antes | Ahora |
| --- | --- | --- |
| Todo coincide | 3/3 | 3/3 |
| Maestro con ceros a la izquierda | 3/3 | 3/3 |
| Talla `038` en el maestro | 0/3 | **3/3** |
| Talla `38.0` en el maestro | 0/3 | **3/3** |
| El SKU de Shopify era el EAN | 0/3 | **3/3** |
| No está en el maestro | 0/3 | 0/3 + motivo explicado |

---

# PARTE 2 — Tipos redirigidos al diccionario de Centry

El catálogo dice `Zapatillas`; la plantilla pide `Zapatillas urbanas`. Como no
coincidían, la columna salía **vacía** y con un aviso por producto, en todo el
calzado y en buena parte del vestuario.

**No hay tipos nuevos**: los mismos, redirigidos en `EQUIVALENCIAS_TIPO`
(`engines/centry_map.py`).

| Nuestro tipo | Falabella | MercadoLibre |
| --- | --- | --- |
| Zapatillas | Zapatillas urbanas | Zapatilla |
| Zapatos | Zapatos casuales | Zapatos casuales |
| Slip Ons | Zapatillas urbanas | Zapatillas urbanas |
| Suecos | Zuecos | Zuecos |
| Casacas | Casacas / Chaquetas | — |
| Cortavientos | Cortaviento | — |
| Polares | Polares / Polar | — |
| Polerones | Poleras | — |
| Leggings | Leggins / Leggings | — |
| Overol | Overoles | — |
| Chullos, Pasamontañas | — | Gorros |
| Cartucheras | Neceseres | Neceseres |

Cada entrada admite varios destinos y se usa el primero que esa columna acepte.
**La tabla nunca puede colar un valor inválido**: el diccionario de la plantilla
sigue decidiendo, y hay una prueba que lo comprueba.

**Y el mismo fallo que tenían los materiales**: `tipo_para_columnas` resolvía
bien la columna y tres líneas más abajo el motor escribía encima el tipo crudo,
que la puerta acababa vaciando. Nueve columnas corregidas.

Columnas con diccionario que salen llenas: Rockford calzado **6 → 8**, Vans
calzado **6 → 8**, Columbia vestuario **5 → 6**. Y desaparecen todos los avisos
de "se dejó vacía".

---

# PARTE 3 — Vans: tallas de calzado en PE

```
5   → 36.5     7.5 → 40      10   → 43      12  → 46
5.5 → 37       8   → 40.5    10.5 → 44      040 → 40
6   → 38       8.5 → 41      11   → 44.5    045 → 45
6.5 → 38.5     9   → 42      11.5 → 45
7   → 39       9.5 → 42.5
```

Solo calzado y solo Vans (bandera `tallas_calzado_pe` del sitio). El mismo
número US es otra talla según el género: un 8 de hombre es PE 40.5 y uno de
mujer 38.5.

**Tallas repetidas**: `7.5` y `040` son la misma talla física y al convertir
chocan. No se borra ninguna; sale avisado con los SKU.

## ⚠️ Pendiente de confirmar

**Los unisex.** Sin género uso **US Men** por defecto. Si Vans te los manda en
escala de mujer, se cambia una línea en `engines/tallas_calzado.py`:

```python
ESCALA_UNISEX = MUJER
```

---

## Pruebas

**Batería completa: 39 archivos**, todos OK salvo `test_auth_accesos.py` y
`test_brand_commercial_input.py`, los dos que ya fallaban desde antes.

```bash
python scripts/test_centry_ean.py
```

40 pruebas (9 nuevas): la clave de talla en sus cuatro formas, los tres
desajustes de Rockford, el SKU que era el EAN, que lo que no existe siga
marcado, y que el origen informado sea el real.

```bash
python scripts/test_centry_plantilla.py
```

35 pruebas (10 nuevas para la redirección de tipos).

```bash
python scripts/test_tallas_calzado_pe.py
```

38 pruebas: las 34 filas de la guía y el producto real de la tienda.
