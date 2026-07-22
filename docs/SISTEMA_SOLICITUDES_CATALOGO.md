# Sistema interno de solicitudes de catalogo

## 1. Diagnostico de la arquitectura

Catalog Control Center mantiene Streamlit como interfaz y reutiliza la validacion
comercial existente. La carga de Shopify no se ejecuta desde una cuenta Brand.
El nuevo modulo agrega una capa de dominio independiente de Streamlit en
`ticket_system.py`, con persistencia intercambiable y adaptadores para efectos
externos.

Para desarrollo local se puede usar el backend de archivos. Para produccion
multiusuario se implemento `GitHubTicketStore`, que guarda tickets, versiones y
reportes en una rama privada dedicada y usa el SHA de GitHub como control de
concurrencia. No se usa SQLite como fuente productiva.

Las acciones de Shopify y correo quedan en mocks por seguridad. La interfaz de
jobs puede sustituirse por el worker o workflow actual sin cambiar el modelo del
ticket.

## 2. Roles y permisos

| Accion | Brand | Operador | Admin |
|---|---:|---:|---:|
| Descargar, validar y enviar input de su marca | Si | No | Si |
| Ver tickets de otras marcas | No | Solo autorizadas | Si |
| Corregir una solicitud observada | Si, propia | No | Si |
| Asignar o tomar solicitud | No | Si | Si |
| Reasignar responsable | No | No | Si |
| Observar, aprobar o rechazar | No | Si, asignada | Si |
| Ejecutar dry run y carga | No | Si, asignada | Si |
| Cambiar prioridad | No | No | Si |
| Ver auditoria completa | Solo propia | Autorizadas | Si |

Las marcas permitidas se leen desde `[app_auth.brands]`. Un Brand solo puede
crear y leer tickets propios de las marcas asignadas. Un operador puede leer las
marcas asignadas, pero no modificar un ticket tomado por otro operador. Admin
puede ver y reasignar todos los tickets.

## 3. Modelo de datos

Cada ticket conserva:

- Codigo `CAT-AAAA-000001`, solicitante, marca, sitios, tipo de carga y prioridad.
- Nombre, hash SHA-256 y version de plantilla del archivo validado.
- Totales de productos, modelo-color, variantes, nuevos, actualizados y bloqueos.
- Versiones inmutables del input y del reporte de validacion.
- Responsable, fecha limite configurable, estado y revision de concurrencia.
- Observaciones generales y estructuradas por producto/campo.
- Comentarios, notificaciones, dry run, Job ID, progreso y resultado final.
- Eventos de auditoria con usuario, fecha, accion, estado anterior y nuevo.

El duplicado se identifica por marca, hash, version de plantilla y tipo de carga.
Una correccion mantiene el mismo ticket, agrega una version y nunca sobreescribe
el archivo previamente revisado.

## 4. Flujo de estados

`Borrador -> Pendiente de revision -> Asignado -> En revision`

Desde revision:

- `Observado -> Corregido por Brand -> En revision`
- `Aprobado para cargar -> En carga -> Completado`
- `Aprobado para cargar -> En carga -> Completado con observaciones`
- `Aprobado para cargar -> En carga -> Fallido -> En carga` (reintento)
- `En revision -> Rechazado`

El boton de carga solo aparece despues de un dry run completado. El estado final
solo lo establece el resultado del adaptador de jobs, no un cambio manual libre.

## 5. Configuracion recomendada

Agregar a `.streamlit/secrets.toml` en Streamlit Cloud. No subir este contenido
al repositorio:

```toml
[app_auth.users]
"brand@forus.pe" = "CAMBIAR_PASSWORD"
"operador@forus.pe" = "CAMBIAR_PASSWORD"
"admin@forus.pe" = "CAMBIAR_PASSWORD"

[app_auth.roles]
"brand@forus.pe" = "brand"
"operador@forus.pe" = "operator"
"admin@forus.pe" = "admin"

[app_auth.brands]
"brand@forus.pe" = ["Columbia"]
"operador@forus.pe" = ["Columbia", "Rockford"]

[ticketing]
backend = "github"
repository = "ORGANIZACION/REPOSITORIO-PRIVADO"
token = "github_pat_REEMPLAZAR"
branch = "catalog-tickets"
prefix = "catalog_tickets"

[ticketing.sla_hours]
low = 120
normal = 72
high = 24
urgent = 8
```

Recomendaciones:

1. Crear previamente la rama privada `catalog-tickets`.
2. Usar un fine-grained PAT con acceso solo al repositorio privado y permiso
   `Contents: Read and write`.
3. Guardar el token solo en Secrets de Streamlit.
4. No reutilizar tokens de Shopify ni exponerlos a Brand.
5. Mantener el backend `local` exclusivamente para pruebas de una sola instancia.

Variables equivalentes opcionales:

- `CATALOG_TICKETS_BACKEND=github`
- `CATALOG_TICKETS_REPOSITORY=owner/repo`
- `CATALOG_TICKETS_GITHUB_TOKEN=...`

## 6. Manual Brand

1. Ingresar con una cuenta de rol `brand`.
2. Descargar el formato correspondiente a la marca autorizada.
3. Completar y subir el input en **Input comercial**.
4. Ejecutar la validacion y revisar el resumen, errores y vista previa.
5. Corregir todos los errores bloqueantes.
6. Confirmar que la informacion esta lista y seleccionar prioridad/comentario.
7. Presionar **Enviar solicitud de carga**.
8. Consultar el avance en **Mis solicitudes**.
9. Si el ticket queda observado, abrirlo, revisar cada observacion y subir una
   nueva version corregida.
10. Descargar la validacion o el reporte final desde el mismo ticket.

Brand nunca ve credenciales ni botones de carga Shopify.

## 7. Manual Operaciones

1. Ingresar con rol `operator` o `admin`.
2. Abrir **Solicitudes** y revisar KPIs, filtros y notificaciones.
3. Abrir un ticket, descargar el input validado y revisar advertencias/versiones.
4. Presionar **Asignarme** y luego **Iniciar revision**.
5. Aprobar o registrar observaciones por producto, campo, valor y recomendacion.
6. Cuando Brand corrija, revisar la nueva version sin perder la anterior.
7. Aprobar y ejecutar **Simulacion**.
8. Revisar el resultado del dry run y confirmar la carga.
9. Consultar Job ID, progreso y resultado. Si falla, reintentar solo desde el
   ticket autorizado.
10. Descargar el reporte final y consultar el historial de auditoria.

## 8. Integracion de jobs y correo

La entrega local usa `MockJobAdapter` y `MockNotificationAdapter`; por lo tanto no
dispara Shopify, email ni GitHub Actions reales. Para conectar la operacion:

- Implementar un adaptador con los metodos `dry_run(ticket)` y `start(ticket)`.
- El adaptador debe enviar `ticket.code`, version, rutas de artefactos y hash al
  worker/workflow actual, y devolver un Job ID idempotente.
- El worker debe informar progreso y resultado mediante `record_job_result`.
- El adaptador de correo debe implementar `send(event, ticket, recipients)` y
  usar secretos del proveedor, nunca datos visibles en la interfaz.

Los registros bloqueados no forman parte de una solicitud valida y no llegan al
adaptador de carga.

## 9. Pruebas y evidencia

Ejecutar:

```powershell
python -m py_compile app_matrixify.py ticket_system.py scripts/test_ticket_system.py
python scripts/test_ticket_system.py -q
```

La suite contiene 26 pruebas y cubre los 20 escenarios obligatorios, incluyendo
duplicados, acceso por marca, toma concurrente, correcciones versionadas,
aprobacion, dry run, ejecucion mock, reintento, notificaciones, auditoria,
persistencia y filtros.

## 10. Archivos de la entrega

- `app_matrixify.py`: autenticacion por roles, portal Brand, bandeja y detalle.
- `ticket_system.py`: dominio, estados, permisos, stores y adaptadores mock.
- `scripts/test_ticket_system.py`: suite funcional automatizada.
- `docs/SISTEMA_SOLICITUDES_CATALOGO.md`: configuracion y manual operativo.

No se realizo deploy, push, envio de correos ni carga real a Shopify.
