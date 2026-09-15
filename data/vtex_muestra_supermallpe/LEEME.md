# Muestra del export de VTEX de Supermall.pe

Las cuatro planillas que exporta el admin de VTEX, con **500 filas por hoja** y
la estructura exacta del export real de septiembre de 2026: la primera fila en
blanco, las cabeceras en la segunda, y el archivo de especificaciones de
productos partido en **dos hojas** — VTEX corta por el límite de filas de Excel,
no por contenido, y las dos hojas no comparten ni un producto.

Es lo que usa `scripts/test_vtex_generator.py` para probar el generador contra
un archivo de verdad. Un juego de casos escrito a mano no sirve para esto:
prueba lo que a uno se le ocurre, y lo que rompe una carga es lo que no se le
ocurrió a nadie.

Lo que sale de aquí y no se puede inventar:

| Dato | De qué columna |
|---|---|
| Los Product ID y SKU ID que hay que **reusar** | `Product ID`, `SKU ID` |
| La identidad del producto | `Product reference code` = código Modelo-Color |
| El árbol de la tienda | `Department`/`Category` con sus IDs |
| Los IDs de marca | `Brand ID` |
| **El dominio de cada especificación** | `IDs de valores de campo` / `Valores de campo` |
| Las medidas de empaque por categoría | `Package weight/width/height/length` |

No lleva precios, ni stock, ni ningún dato de personas.
