# Estabilizacion tecnica 2026-06-15

Cambios aplicados para reducir parches superpuestos y mejorar robustez:

- Se eliminaron definiciones duplicadas muertas de `render_non_visible_combo_table`; queda una sola funcion activa.
- Se vectorizo el calculo de stock eComm para evitar `DataFrame.apply(axis=1)` sobre toda la tabla de stock.
- Se centralizo el casteo numerico de columnas de stock con `numeric_stock_series`.
- Se conserva la regla eComm: tiendas normales usan `stock_tiendas`; bodega `320` usa `stock_tiendas + stock_bodega`.
- Se mantiene la auditoria de bodegas y el filtro por bodegas configuradas del sitio.
- Se verifico que no existan funciones top-level duplicadas.
- Se verifico sintaxis/import de `app_matrixify.py`, `generate_columbia_matrixify.py` y `shopify_api.py`.
- Se valido con caso controlado que una bodega no configurada no cuenta y que `stock_bodega` no se duplica en tiendas.
