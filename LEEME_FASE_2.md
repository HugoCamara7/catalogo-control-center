# Fase 2 - Auditoria: cobertura de acciones

Base: `main` con la Fase 1 ya aplicada.

## Archivo a subir: 1

```
app_matrixify.py
```

## Lo que ya estaba (y no habia que rehacer)

La pantalla de auditoria **ya cumplia tu especificacion**. Es una vista completa,
no del sidebar, y ya tiene:

- KPIs, filtros por usuario, rol, accion, modulo y marca
- buscador y rango de fechas
- **paginacion de 30** registros
- detalle por accion
- **auditoria por usuario** (resumen de acciones, solicitudes, modulos y errores)
- descarga en **Excel y CSV**, de todos los registros filtrados y no solo la pagina

El servicio (`engines/audit.py`) ya tenia `query`, `paginate`, `kpis`,
`por_usuario` y `to_export_rows`, con 45 tests.

## Lo que faltaba de verdad: cobertura

Auditar la pantalla no sirve si las acciones no se registran. Se reviso una por
una contra tu lista y habia dos huecos.

### 1. La ejecucion de la carga no se registraba

Solo quedaba el "Iniciar carga" del ticket. La ejecucion real contra Shopify
—que es la que importa demostrar— no dejaba rastro.

Se agrego `_auditar_bloque_carga()`, que registra cada bloque ejecutado con:

```
accion    : Ejecutar bloque de carga
detalle   : <sitio> · bloque N · estado <estado del job>
modulo    : Carga de catalogo
marca     : la marca del sitio
resultado : "error" si el bloque dejo productos con error, "ok" si no
```

Se instrumentaron los dos puntos donde se ejecuta un bloque: el primero al crear
el proceso y los siguientes al continuar.

### 2. La validacion del input comercial no se registraba

Solo se auditaba el ticket que se creaba despues. Si alguien probaba un archivo
que nunca llegaba a solicitud, no quedaba nada.

Ahora al analizar un input comercial se registra:

```
accion    : Validar input comercial
detalle   : <nombre del archivo> · N observaciones bloqueantes
modulo    : Input comercial
marca     : la marca seleccionada
resultado : "error" si hay bloqueos, "ok" si no
```

## Cobertura actual, contra tu lista

| Accion pedida | Estado |
|---|---|
| Ingreso y cierre de sesion | ya estaba |
| Intento de acceso fallido | ya estaba |
| Navegacion entre modulos | ya estaba ("Acceso a modulo") |
| Crear o editar solicitudes | ya estaba (via AuditedTicketService) |
| Asignaciones | ya estaba |
| Cambios de estado | ya estaba, y en Fase 1 se sumo "Completar carga" |
| Archivos subidos y reemplazados | ya estaba (create_ticket, add_correction_version) |
| Archivos validados | **nuevo** |
| Archivos descargados | ya estaba ("Descargar archivo") |
| Ejecucion de cargas | **nuevo** |
| Errores | ya estaba en tickets; **nuevo** en carga e input |
| Acciones administrativas | ya estaba (prioridad, cancelar, rechazar) |

Los campos guardados son los que pediste: fecha, usuario, correo, rol, marca,
modulo, solicitud, accion y resultado.

## Secretos

La sanitizacion reforzada en Fase 1 aplica a todo lo nuevo: los detalles pasan
por `sanitize_value`, que tapa tokens reales, claves privadas y pares
`clave=valor` dentro de texto libre.

## Pruebas

Suite completa sin cambios: 45 de auditoria, 42 de separadores, 38 de normalize,
29 de flujo, 28 de tickets, 20, 18, 13 y dos mas. Los mismos 2 fallos anteriores
(`test_auth_accesos` espera un `auth_role_label` inexistente,
`test_brand_commercial_input` espera las hojas de la version legacy del formato).

## Velocidad

Se agregan dos registros por accion del usuario, no por producto: un bloque de
carga genera **un** evento, no uno por cada uno de los 20 productos. El registro
esta envuelto en try/except y nunca bloquea la carga.
