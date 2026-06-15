# Checklist go live

## Antes de publicar

- [ ] Revisar que `.streamlit/secrets.toml` no este en el repositorio.
- [ ] Confirmar `requirements.txt`.
- [ ] Confirmar que `data/` tenga los maestros actualizados.
- [ ] Confirmar credenciales Shopify por sitio.
- [ ] Confirmar credenciales BigQuery.

## Prueba funcional minima

- [ ] Cargar input Columbia.
- [ ] Cargar input Rockford.
- [ ] Generar Matrixify.
- [ ] Revisar que todas las variantes tengan `Variant SKU`.
- [ ] Revisar que productos nuevos tengan todas las tallas de BigQuery/ARTI.
- [ ] Revisar que productos existentes creen tallas faltantes.
- [ ] Revisar que Rockford `0/000/O/S` salga como `Talla Unica` cuando aplica.
- [ ] Revisar que Centry traiga EAN.
- [ ] Revisar que Centry/Sial traigan pesos y dimensiones.
- [ ] Revisar que `Caracteristicas` y `Tecnologias` no pasen de 45 palabras.
- [ ] Revisar que no aparezcan tildes danadas.
- [ ] Revisar que `Color` no muestre codigos tipo `S77`.

## Prueba Shopify API

- [ ] Producto nuevo: crea todas las variantes con SKU.
- [ ] Producto existente: actualiza SKU si la variante existe sin SKU.
- [ ] Producto existente: crea variantes faltantes.
- [ ] Verificacion posterior no muestra SKUs faltantes.
