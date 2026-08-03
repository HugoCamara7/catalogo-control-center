# Fase 3 - Ejecutar desde la solicitud

Base: `main` con Fase 1 y 2 aplicadas.

## Archivo a subir: 1

```
app_matrixify.py
```

## Lo que ya estaba (y no habia que construir)

**Ejecutar la carga usando el input guardado ya funcionaba.** En la pantalla de
carga completa existe un selector "Origen del input":

```
( ) Usar archivo de una solicitud     ( ) Subir archivo manualmente
```

Al elegir una solicitud, `archivo_de_solicitud()` recupera el Excel validado
desde los artefactos del ticket y lo entrega directo al motor de carga. No hay
que descargarlo ni volver a subirlo. El archivo original y sus versiones se
conservan intactos: solo se lee.

Piezas: `solicitudes_ejecutables()` y `archivo_de_solicitud()`, con 20 tests en
`scripts/test_carga_desde_solicitud.py`.

## Lo que faltaba: que hacer despues de ejecutar

Al terminar la sincronizacion no habia ninguna accion sobre la solicitud de
origen. Habia que volver a la bandeja de Solicitudes para cerrarla.

Se agrego `_render_acciones_solicitud_tras_carga()`, que aparece justo debajo del
panel de sincronizacion **solo si la carga salio de una solicitud** y solo para
operador (Digital) o administrador. Ofrece tres acciones y ninguna mas:

| Accion | Que hace |
|---|---|
| **Observar** | Devuelve la solicitud a la marca. Pide describir que corregir. |
| **Continuar después** | La deja en curso, sin cambiar la etapa. |
| **Completar carga** | La finaliza. Pide motivo. |

Observar y Completar exigen texto: queda en el historial del ticket y en la
auditoria. Completar usa `set_status_manual`, que ya se audita como
"Completar carga" desde la Fase 1.

No hay contadores ni porcentajes en este bloque: solo la etapa actual y las tres
acciones.

## Pruebas

Suite completa sin cambios:

| Test | Resultado |
|---|---|
| test_engines_audit.py | 45 OK |
| test_separadores_lista.py | 42 OK |
| test_engines_normalize.py | 38 OK |
| test_engines_ticket_flow.py | 29 OK |
| test_ticket_system.py | 28 OK |
| **test_carga_desde_solicitud.py** | **20 OK** |
| test_engines_excel_io.py | 18 OK |
| test_tipos_de_prenda.py | 13 OK |
| test_catalog_rules.py | OK |
| test_partial_maintenance_validations.py | OK |
| test_auth_accesos.py | 1 fallo + 1 error, iguales a antes |
| test_brand_commercial_input.py | falla, igual que antes |

## Velocidad

El bloque nuevo solo se dibuja si la carga vino de una solicitud, y lee el ticket
una vez. No agrega llamadas a Shopify ni a BigQuery.

## Lo que queda

- Fase 4: vista Brand simplificada, pantalla "Mis solicitudes" compacta e
  inventario de migracion.
