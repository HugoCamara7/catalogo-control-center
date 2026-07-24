# Catalog Control Center - Diccionarios y validaciones

## Diagnostico breve

La aplicacion ya tiene reglas valiosas para variantes, SKUs, fotos, metacampos, Body HTML y KPIs. El problema principal era que varias decisiones de negocio estaban repartidas entre `app_matrixify.py` y `generate_columbia_matrixify.py`, con alias de columnas y reglas similares escritas en mas de un lugar.

Eso provoca riesgos operativos:

- Un encabezado nuevo en ARTI o en el input puede no leerse y el sistema cae a valores genericos como el codigo modelo-color.
- La guia de talla puede quedar implicita o depender de una coincidencia incompleta.
- El Body HTML puede construirse con secciones mezcladas si el input no separa bien caracteristicas, materiales y cuidados.
- La exportacion de modelos no creados puede quedar incompleta aunque ARTI tenga la informacion con otro nombre de columna.

## Cambio aplicado

Se agrego `catalog_rules.py` como capa central sin dependencias de Streamlit ni Shopify. Esta capa permite:

- Centralizar alias de columnas.
- Normalizar tipos de prenda.
- Definir reglas base de guias de talla.
- Validar tallas invalidas antes de crear variantes.
- Definir columnas oficiales del input comercial.
- Sanitizar Body HTML de forma conservadora para reportes/preview.
- Devolver trazabilidad de decisiones: regla usada, estado y advertencias.

`app_matrixify.py` ahora consume estos alias para reforzar la lectura de ARTI y el Excel sugerido de modelos no creados.

## Archivos involucrados

- `catalog_rules.py`: reglas centrales, alias y validadores.
- `app_matrixify.py`: integracion segura de alias y trazabilidad en input sugerido.
- `generate_columbia_matrixify.py`: conserva la generacion principal actual de Matrixify, variantes y Body HTML.
- `scripts/generate_catalog_input_template.mjs`: genera el formato profesional de input comercial.

## Politica de variantes

- La fuente de verdad para variantes sigue siendo BigQuery/ARTI.
- No se inventan tallas.
- No se crean tallas invalidas como `K`, `0`, `000`, vacios o equivalentes.
- Accesorios no se fuerzan siempre a talla unica: si la fuente trae tallas validas, se respetan.
- Una variante sin SKU no debe enviarse a Shopify.

## Politica de input comercial

Los Brand Managers no deben completar campos tecnicos. El input comercial debe pedir principalmente informacion basica y comercial:

- Marca.
- Genero.
- Categoria o tipo de prenda, si aplica.
- Nombre comercial, descripcion, caracteristicas, materiales, cuidados y tecnologias cuando no existan en fuente maestra.
- Observaciones de negocio.

La app debe completar o sugerir los datos tecnicos desde ARTI, BigQuery y Shopify:

- SKU, EAN, talla, precio y stock.
- Codigo modelo, codigo color y codigo modelo-color cuando se pueda derivar.
- Guia de tallas.
- Tags sugeridos.
- Handle sugerido.

El handle es tecnico y se autogenera con esta formula:

`tipo de prenda + genero + marca + codigo modelo-color`

Ejemplo:

`casacas-mujer-columbia-2092991-nry`

## Politica de guias de talla

La decision debe considerar, como minimo:

1. Excepcion por producto o modelo-color, cuando exista.
2. Marca + categoria + genero.
3. Categoria + tipo de prenda.
4. Grupo de prenda: `TOPS` o `BOTTOMS`.
5. Sin asignacion automatica cuando no hay coincidencia confiable.

Para vestuario, el tipo de prenda define el grupo de guia:

- `TOPS`: casacas, polos, polerones, camisas, blusas, chalecos y prendas superiores.
- `BOTTOMS`: pantalones, shorts, bermudas, faldas, leggings, joggers y prendas inferiores.

Bloqueos obligatorios:

- Calzado no puede recibir guia de vestuario.
- Vestuario no puede recibir guia de calzado.
- Prenda superior no puede recibir guia `BOTTOMS`.
- Prenda inferior no puede recibir guia `TOPS`.
- Guia vacia no debe reemplazarse con una guia incorrecta.
- Caso ambiguo debe ir a revision.

## Politica de Body HTML

Estructura recomendada:

- Caracteristicas.
- Materiales.
- Cuidados.

Tecnologias no deben depender del Body HTML. Deben poblarse en metacampos:

- `custom.tecnologia` como `list.single_line_text_field`.
- `custom.logo` como `list.metaobject_reference`.

## Mantenimiento

Cuando negocio agregue un nuevo tipo de prenda, tecnologia, guia o alias:

1. Agregar la regla en `catalog_rules.py`.
2. Regenerar el Excel de input con `scripts/generate_catalog_input_template.mjs`.
3. Probar con input chico en modo preview.
4. Confirmar que no existan filas bloqueadas antes de sincronizar.

## Pruebas seguras

Las pruebas de `catalog_rules.py` no llaman Shopify. Validan reglas de datos antes de cualquier carga real.
