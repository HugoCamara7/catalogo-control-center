# Actualización — 5 archivos

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
scripts/test_engines_catalog_map.py
LEEME_ESTE_PAQUETE.md
```

Respeta las carpetas: `engines/` dentro de `engines/`, `scripts/` dentro de
`scripts/`.

**No subas los otros 19.** Ya están bien y volver a subirlos solo añade
riesgo de pisar algo.

---

## Qué traen estos 5

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
python scripts/test_engines_catalog_map.py   # 70
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
