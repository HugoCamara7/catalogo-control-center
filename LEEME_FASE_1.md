# Fase 1 - Estados simplificados, sin contadores, Completar carga

Base: `main` del 2026-08-03 (commit `eab94edf9`).

## Archivos a subir: 3

```
app_matrixify.py        estados unificados, sin contadores, Completar carga
engines/audit.py        audita la nueva accion + tapa secretos en texto libre
assets/app.css          RESTAURACION: en main es un JPEG, no CSS
```

## 1. El ticket ya no muestra contadores

Se quitaron de `_render_ticket_execution_summary`:

- "Productos / Procesados / Pendientes"
- "Correctos / Actualizados / Advertencias / Fallidos / Exito %"
- el calculo de porcentaje de avance

El ticket ahora dice **en que etapa esta la tarea**, y nada mas. El detalle
tecnico de la carga sigue existiendo en el panel de sincronizacion, que es donde
sirve. El boton "Descargar reporte final" se mantiene.

## 2. Una sola escalera de etapas

Habia **dos steppers distintos**: uno de seis pasos y otro de cuatro. La misma
solicitud se veia en una etapa distinta segun la pantalla. Ahora los dos salen
de `engines/ticket_flow`:

```
Pendiente de revisión -> Lista para ejecutar -> En ejecución -> Finalizada
                         (+ Observada, fuera de la linea)
```

`_ticket_workflow_step()` quedo sin uso y se elimino.

**No se toco la maquina de 19 estados internos.** Es la que codifica permisos por
rol y transiciones validas, y 57 tests dependen de ella. El motor conserva el
detalle; la pantalla muestra cinco etapas. Asi se simplifica sin romper reglas.

## 3. "Completar carga"

Reemplaza al panel "Cambiar estado manualmente" de la entrega anterior.

- Solo **operador (Digital) y administrador**.
- Se elige la etapa entre las cinco visibles, no entre 19 estados internos.
- **Exige motivo**, que queda en el historial y en la auditoria.
- El boton dice "Finalizar solicitud" cuando la etapa elegida es Finalizada, y
  "Actualizar etapa" en el resto.
- El ticket **no se mueve solo** por la cantidad procesada ni por el resultado
  tecnico del job: lo cierra una persona.

Cada etapa visible mapea a un estado interno y vuelve a mapear a si misma.
Verificado, 0 fallos:

| Etapa elegida | Estado interno | Vuelve a |
|---|---|---|
| Pendiente de revisión | digital_review | Pendiente de revisión |
| Lista para ejecutar | load_approved | Lista para ejecutar |
| En ejecución | loading | En ejecución |
| Observada | observed | Observada |
| Finalizada | completed | Finalizada |

## 4. Auditoria

`set_status_manual` no estaba en `ACCIONES_TICKET`, asi que **el cambio de etapa
no quedaba registrado**. Se agrego como "Completar carga".

Verificado que registra: accion, usuario, rol, solicitud, marca, etapa anterior,
etapa nueva, resultado y modulo. Y que **un intento sin permiso tambien se
registra**, con resultado "error".

### Secretos en texto libre

La sanitizacion ya tapaba tokens reales de GitHub y Shopify y claves privadas.
No tapaba pares `clave=valor` escritos dentro de un mensaje, que es como suelen
aparecer en un error. Ahora se tapa el valor y se conserva el resto:

```
antes:  fallo con password=Secreta123 al conectar
ahora:  fallo con password=[oculto] al conectar
```

Se comprobo que un Mod-Col normal (`20265-IKE`) no se toca.

## 5. assets/app.css estaba roto en main

En `main` ese archivo **es una imagen JPEG**, no CSS:

```
primeros bytes: ff d8 ff e0 ... 4a 46 49 46   ("JFIF")
tamano:         76.365 bytes = el de logo_vans.jpg
```

Se subio el logo de Vans encima de la hoja de estilos, en los commits del
2026-08-03 06:42 UTC que movieron los logos de `assets/brands/` a `assets/`.

Esto **rompe dos tests** de `test_auth_accesos.py`, que fallan con
`UnicodeDecodeError: byte 0xff en posicion 0`. Al restaurar el CSS bueno, esos
dos errores desaparecen.

Ojo: los logos quedaron duplicados en `assets/` y `assets/brands/`. Conviene
confirmar cual lee la app y borrar la copia que sobre.

## Pruebas

| Test | Resultado |
|---|---|
| test_engines_audit.py | 45 OK |
| test_separadores_lista.py | 42 OK |
| test_engines_normalize.py | 38 OK |
| test_engines_ticket_flow.py | 29 OK |
| test_ticket_system.py | 28 OK |
| test_carga_desde_solicitud.py | 20 OK |
| test_engines_excel_io.py | 18 OK |
| test_tipos_de_prenda.py | 13 OK |
| test_catalog_rules.py | OK |
| test_partial_maintenance_validations.py | OK |
| test_auth_accesos.py | 1 fallo + 1 error, **iguales a antes** |
| test_brand_commercial_input.py | falla, **igual que antes** |

Los dos que fallan son anteriores a esta fase: `test_auth_accesos` espera un
`auth_role_label` que no existe, y `test_brand_commercial_input` espera las hojas
`INPUT_COMERCIAL / GUIA / DICCIONARIO` de la version legacy del formato.

### Velocidad

Esta fase **quita** trabajo, no agrega: se dejaron de calcular porcentajes y
contadores en cada render del ticket. Tiempo de import del app medido tres
veces: 2,65 / 2,64 / 2,59 s, sin cambio respecto de antes.

## Lo que sigue

- Fase 2: pantalla de auditoria con filtros, buscador, paginacion de 30, detalle
  por usuario y export.
- Fase 3: ejecutar la carga desde la solicitud usando el input guardado.
- Fase 4: vista Brand simplificada, "Mis solicitudes" compacta e inventario de
  migracion.
