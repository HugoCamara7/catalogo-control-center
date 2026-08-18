# Qué subir — bandeja de solicitudes + SKU/EAN

| Archivo | Ruta | |
|---|---|---|
| `app_matrixify.py` | raíz | modificado |
| `engines/ticket_flow.py` | `engines/` | modificado |
| `scripts/test_bandeja_solicitudes.py` | `scripts/` | **nuevo** |
| `scripts/test_siblings_carga_completa.py` | `scripts/` | modificado |

---

## 1. La tarjeta

**Clickeable entera.** Enlace estirado (`<a>` vacío en posición absoluta) sobre
la tarjeta. Se eliminó el selector "Abrir solicitud" que había debajo de la
rejilla.

**Casilla en la esquina inferior derecha.** La tarjeta reserva una franja de
46px abajo y el enlace deja de cubrirla, así que la casilla y la acción rápida
viven dentro de la tarjeta sin que el enlace les robe el click. Medido en el
navegador: casilla a **13px del borde derecho y 13px del inferior**.

**9 por página** con `‹ Anterior · 1 2 3 · Siguiente ›`.

**Badges:** estado, prioridad (rojo urgente, ámbar alta), productos,
antigüedad, `Vencida`, y responsable en gris cursiva si está sin asignar.

## 2. Selección múltiple: un botón por etapa

Al marcar varias sale una barra con **un botón por cada etapa alcanzable** y
cuántas seleccionadas pueden ir:

```
3 seleccionadas · 1 sin acción
[ Iniciar revisión (2) ]  [ Ejecutar carga (1) ]  [ Quitar ]
```

Cada botón aplica solo a las suyas. Los botones salen en el orden del recorrido,
incluida la cadena larga de cierre (SIAL → precios → validación → cierre).

## 3. Detalle simplificado

Tenía **tres desplegables seguidos** (*Otras acciones*, *Ajustes de la
solicitud*, *Eliminar solicitud*), la línea "Siguiente paso" y un aviso que
repetía el estado con otras palabras ("Asignada / La carga aún no se ha
ejecutado").

Ahora: **botón principal + un único desplegable "Más opciones"** con las
acciones que piden comentario, los ajustes de prioridad y responsable, y
eliminar. La línea "Siguiente paso" desapareció (el botón ya lo dice, y lleva el
mismo texto en su tooltip) y el aviso solo aparece cuando dice algo que la
insignia de estado y la barra de etapas no digan ya.

Antes de esto ya se había quitado el bloque "Gestión interna", que duplicaba
todas las transiciones (*Iniciar revisión*, *Aprobar*, *Rechazar*, *Validar*,
*Registrar carga*, *Finalizar*) con reglas distintas a las de la barra.

## 4. Completar carga: manual

Estaba deshabilitado salvo que el job registrara productos procesados, y pedía
elegir resultado + comentario + casilla de confirmación. Ahora es un botón, y el
resultado guardado ya no lleva `processed` ni `successful`.

## Comprobado en el navegador

No solo con pruebas: levanté la rejilla y la medí en el DOM.

| | |
|---|---|
| Tarjetas enteras, 3 por fila | sí, sin scroll horizontal |
| Casilla dentro de la tarjeta | sí, a 13px de las dos esquinas |
| Click en el cuerpo | `A.ticket-card-hit` → abre el ticket |
| Click en la casilla | la recibe la casilla, el enlace **no** la tapa |
| Click en el botón | lo recibe el botón, el enlace **no** lo tapa |
| Navegación | clic en la 3ª tarjeta → `?ticket=CAT-2026-000029` |

- **La app levanta**: arranque headless, `HTTP 200`, cero trazas.
- Suite: **23 en verde**; siguen fallando `test_auth_accesos` y
  `test_brand_commercial_input`, preexistentes. Cero regresiones.
- `scripts/test_bandeja_solicitudes.py`: **21 pruebas**. Una de ellas detectó
  que faltaban dos acciones de la cadena de precios en el orden del lote.
- Sin funciones huérfanas nuevas.

## Lo que NO se tocó

La máquina de estados de `ticket_system`, los permisos por rol y la vista de
marca. De `ticket_flow` solo cambió la etiqueta de una acción a "Completar
carga".
