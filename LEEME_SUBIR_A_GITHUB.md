# Qué subir — repo `app-matrixify-columbia`

> ⚠️ **Este paquete va a `app-matrixify-columbia`**, que es el repo desde el que
> Streamlit despliega tu app (lo confirmé en la traza del error:
> `/mount/src/app-matrixify-columbia/`). **No** a `catalogo-control-center`.

**`app_matrixify.py` va al final.**

| Archivo | Carpeta | Estado |
| --- | --- | --- |
| `requirements.txt` | raíz | modificado |
| `scripts/test_dependencias.py` | `scripts` | **nuevo** |
| `scripts/test_centry_plantilla.py` | `scripts` | modificado |
| `app_matrixify.py` | raíz | modificado — **al final** |

---

## 1. El color solo salía en la primera variante

Matrixify escribe el **bloque de producto únicamente en la primera fila** de
cada producto; las filas de las demás tallas vienen con esos campos vacíos.
`forward_fill_product_block` existe justo para arrastrarlo hacia abajo…

…pero de las **diez** columnas de las que el motor puede leer el color, solo se
arrastraba **una** (`custom.color`), y no es la primera de la lista. El
resolutor mira antes `Color Web`, `Color`, `custom.color_forus`… así que en
cuanto el color venía por cualquiera de esas, la talla 38 salía con color y el
resto en blanco.

**Corregido:** las diez columnas viven ahora en una sola constante,
`CENTRY_COLUMNAS_COLOR`, que usan **las dos partes**: el resolutor para leer y
el arrastre para rellenar. No se pueden desincronizar — si mañana se agrega una
columna al resolutor, se arrastra sola.

Aplicado al **Centry** y a la **Carga Sial**, que tenía el mismo problema.

Comprobado con un Matrixify como el de verdad (bloque solo en la fila 1), una a
una con las diez columnas: **4/4 variantes con color** en todas.

## 2. `ModuleNotFoundError: No module named 'xlsxwriter'`

El motor de Excel se cambió de `openpyxl` a `xlsxwriter` para bajar el pico de
memoria, pero **la dependencia nunca se declaró**. En local funcionaba porque
venía instalada de arrastre; en el servidor no. Y el fallo salía **al final**,
después de calcular todo el catálogo.

**Corregido en tres niveles:**

1. `xlsxwriter>=3.1` en `requirements.txt` — la causa.
2. **Respaldo**: si un despliegue se queda sin la librería, cae a `openpyxl` en
   vez de reventar. Comprobado bloqueando el import: el Excel sale igual.
3. **`scripts/test_dependencias.py`** — recorre el código de producción, saca
   sus imports de terceros y falla si alguno no está declarado. Eso cubre la
   clase entera de fallo, no solo este caso.

> Después de subir, **reinicia la app en Streamlit Cloud** para que reinstale
> las dependencias.

---

## Pruebas

Batería completa: **40 archivos**, todos OK salvo `test_auth_accesos.py` y
`test_brand_commercial_input.py`, los dos que ya fallaban desde antes.

```bash
python scripts/test_dependencias.py
```

```bash
python scripts/test_centry_plantilla.py
```

39 pruebas, 4 nuevas para el color: que llegue a todas las variantes **venga de
la columna que venga**, que ninguna fila quede vacía, que la Carga Sial también
lo arrastre, y que el resolutor y el arrastre lean de la misma constante.

---

## Nota sobre los dos repos

`catalogo-control-center` se quedó **3 commits atrás**: no tiene las tallas de
Vans, la redirección de tipos ni el EAN de Rockford. `app-matrixify-columbia`
—el que corre— sí los tiene.

Dime si quieres que `catalogo-control-center` se mantenga sincronizado o si lo
damos por muerto, para no volver a mirar el repo equivocado.
