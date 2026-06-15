# Funcionalidad validada

## Variantes y SKU

- La app no envia variantes por API sin `Variant SKU`.
- Si Shopify tiene variantes existentes sin SKU, intenta actualizar el Inventory Item SKU.
- Si faltan tallas, genera variantes nuevas con SKU desde BigQuery/ARTI.
- Para producto nuevo, usa las tallas detectadas desde BigQuery/ARTI.

## Rockford

- `MOUNTAIN HARDWEAR` usa carpeta de fotos `MOUNTAINHARDWEAR`.
- Rockford permite `0/000/O/S` como talla unica cuando aplica.
- Se evita usar codigo de color como color visible.

## Centry

- EAN se toma desde BigQuery/ARTI cuando esta disponible.
- Pesos y dimensiones salen desde maestro de dimensiones o fallback por categoria.
- `Listado de caracteristicas` sale con etiquetas de negocio.
- Tildes y caracteres mojibake se reparan antes del preview y antes del Excel.
- `Color` usa nombre visible si existe (`Color Web`, `Nombre Color`, `DESC_COLOR`, etc.). No usa codigos tipo `S77`.

## Sial

- Pesos y dimensiones salen poblados.
- `Caracteristicas` y `Tecnologias` se limitan a 45 palabras.
- Tildes se reparan en preview/export.
