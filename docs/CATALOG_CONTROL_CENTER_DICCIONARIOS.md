# Eliminacion definitiva de solicitudes

## Comportamiento

- Solo `hugo.camara@forus.pe` y `luis.nunez@forus.pe` pueden eliminar solicitudes.
- La eliminacion requiere confirmacion y un motivo.
- El registro se elimina del almacenamiento persistente; no queda como `Cancelado`.
- La solicitud desaparece de la tabla, del selector y del detalle en el siguiente rerun.
- Registros cancelados creados por versiones anteriores se ocultan de la bandeja.

## Archivos para GitHub

- `app_matrixify.py`
- `ticket_system.py`

## Validacion

```text
python -m py_compile app_matrixify.py ticket_system.py scripts/test_ticket_system.py
python -m unittest scripts.test_ticket_system -v
```

Resultado validado: 28 pruebas correctas.
