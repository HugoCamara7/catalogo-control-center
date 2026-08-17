# Qué subir — 2 archivos

Todo lo anterior ya está en `main` y verificado. Esto es solo el arreglo del
SKU de variante en Centry.

## Sube estos 2

| Archivo | Ruta |
|---|---|
| `app_matrixify.py` | raíz |
| `test_siblings_carga_completa.py` | `scripts/` |

## Qué pasaba

Al configurar `product_master_table` en Secrets, BigQuery empezó a devolver los
EAN. Y ahí se destapó un fallo que llevaba tiempo escondido:

```python
variant_centry_sku = barcode or variant_sku   # el EAN GANABA
```

El **EAN se metía en la columna "SKU de la variante"** y tapaba el código
interno del producto. Mientras BigQuery no devolvía códigos de barra daba igual,
porque `barcode` siempre venía vacío y caía al SKU. Al llegar el EAN, empezó a
ganar.

Corregido a `variant_sku or barcode`: manda el SKU, y el código de barras queda
solo como respaldo para una variante que no traiga SKU. El EAN sigue yendo a su
columna, `Código de barra variante (EAN/UPC/ISBN)`.

## Comprobado

Regenerado con tu input real y un ARTI con EAN en las 586 variantes:

| Columna | Valor |
|---|---|
| `SKU del producto` | `RK202011432-645` |
| `SKU de la variante` | `5455311` |
| `Código de barra variante (EAN/UPC/ISBN)` | `7790000000002` |

**0 de 450 filas** tienen el SKU igual al EAN (antes: las 450). En el Matrixify,
`Variant SKU` y `Variant Barcode` también salen separados.

Suite completa: 22 en verde, los mismos 2 preexistentes
(`test_auth_accesos`, `test_brand_commercial_input`). 3 pruebas nuevas.

## Recuerda

- El `product_master_table` va en **Secrets de Streamlit**, no en GitHub.
- Falta pegar el CSS de `docs/CSS_FICHA_PRODUCTO.md` en los temas de Hush
  Puppies y Rockford.
