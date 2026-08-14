# Actualización — 7 archivos

Agosto 2026. Sobre el commit `dc7290d91` de `main`.

**Ya subiste 19 de los 24 archivos el 12 de agosto.** Comparé uno por uno
contra GitHub: esos 19 están idénticos y **no hay que volver a tocarlos**.

Este paquete trae solo los **5 que cambiaron después**.

---

## Qué subir

```
app_matrixify.py
generate_columbia_matrixify.py
engines/catalog_map.py
engines/garment_types.py              ← nuevo
scripts/test_engines_catalog_map.py
scripts/test_engines_garment_types.py ← nuevo
scripts/test_tipo_de_prenda_por_sitio.py
LEEME_ESTE_PAQUETE.md
```

Respeta las carpetas: `engines/` dentro de `engines/`, `scripts/` dentro de
`scripts/`.

**No subas los otros 19.** Ya están bien y volver a subirlos solo añade
riesgo de pisar algo.

---

## Diccionario maestro de tipos

`engines/garment_types.py` está **generado desde tu Excel corregido**, no
transcrito a mano:

- **60 tipos canónicos**, 345 nombres reconocidos
- **Las 3 clases**: Vestuario (20), Calzado (11), Accesorios (29)
- **El nombre por sitio**, que no siempre es el canónico
- `Outdoor` **sigue sin reconocerse**, que es lo correcto: es una clase

Un tipo que un sitio no vende devuelve vacío en vez de forzar un nombre que esa
tienda no usa.

Al generarlo salió una ambigüedad de tu Excel: `cremas renovadoras` figuraba
como sinónimo de **Accesorios De Limpieza** y de **Crema renovadora** a la vez.
Se quedó en el primero. Si prefieres al revés, dímelo.

## Qué traen los demás

**Nombre Propio siempre** en Categoría, Subcategoría, Tipo de prenda, Clase,
Color, Color Forus, Grupo Color y Género — y también en los tags.

```
VESTUARIO  ->  Vestuario        LENTES DE SOL  ->  Lentes de Sol
vestuario  ->  Vestuario        NIÑO           ->  Niño
```

Los conectores quedan en minúscula, las tildes y la ñ se conservan, y los
códigos (`HP2020-SMV`, `IM5678-011`) no se tocan.

**El handle sigue todo en minúsculas**, sin tildes ni dobles guiones. Son dos
caminos distintos y no se pisan:

```
CHALECO POWDER LITE
  ├─ metafield ->  Chaleco Powder Lite
  └─ handle    ->  chaleco-powder-lite-im5678-011
```

**La clase se deriva del tipo en los tags.** El brand llena `Subcategoria`
(Chalecos), no `Categoria` (Vestuario). Leyendo solo el Excel, el tag
`Vestuario` no salía — uno de los que faltaban en Rockford. Ahora se deduce
del diccionario de tipos:

```
input:  Genero=Hombre · Subcategoria=Chalecos · Marca=Rockford
tags:   Hombre · Chalecos · Rockford · IM5678-011 · Vestuario
```

**Auditoría de metafields.** Los 25 que usa la app quedan cubiertos por el
registro central, sin tipos contradictorios. Se agregaron `custom.color`,
`custom.deporte` y `custom.logo`, y se unificó `custom.tecnologia`, que tenía
dos entradas con tipos distintos para la misma clave.

**`custom.sub_categoria` con guion bajo.** Esa es la clave real en Shopify;
escribir `custom.subcategoria` apuntaba a otro metafield.

**La vista del ticket, corregida.** Estilos en línea (no dependen de que
`app.css` cargue), sin números duplicados, y **una sola** barra de avance en
vez de tres apiladas.

---

## Después de subir

```bash
python scripts/test_engines_catalog_map.py     # 73
python scripts/test_engines_garment_types.py   # 19
```

Y en la app, abre una solicitud que esté en carga: el avance de 6 etapas debe
verse como tarjetas de colores, no como una lista suelta.

---

## Lo que sigue pendiente

- **Correos**: esperando que Renzo cree el registro en Entra y te pase
  `tenant_id`, `client_id` y el valor del secreto. Sin eso la app funciona
  igual y no envía nada.
- **Validar contra Shopify real**: todo esto está probado contra el código,
  no contra tu tienda. Carga un producto de prueba en Columbia, Vans,
  Rockford y Patagonia-en-Rockford.
- **Tres decisiones de criterio** del diccionario de tipos: `chaqueta` va hoy
  a Casacas, `falda` a Shorts y `cartera` a Bolsos. Dime si alguno debe ser
  su propio tipo.
