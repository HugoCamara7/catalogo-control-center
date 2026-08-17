# Qué subir — bandeja de solicitudes + SKU/EAN

## Archivos

| Archivo | Ruta | |
|---|---|---|
| `app_matrixify.py` | raíz | modificado |
| `engines/ticket_flow.py` | `engines/` | modificado |
| `scripts/test_bandeja_solicitudes.py` | `scripts/` | **nuevo** |
| `scripts/test_siblings_carga_completa.py` | `scripts/` | modificado |

---

## 1. Bandeja: menos clicks

**Tarjeta clickeable entera.** Cada tarjeta es un `<a href="?ticket=CODIGO">`;
Streamlit lee el parámetro y abre el detalle. **Se eliminó el selector "Abrir
solicitud"** que había debajo de la rejilla: obligaba a volver a elegir en una
lista el ticket que ya estabas viendo.

**9 por página + paginación.** Antes se cortaba en 12 con el aviso "usa los
filtros para acotar". Ahora hay `‹ Anterior · 1 2 3 · Siguiente ›`, con ventana
de 7 números cuando hay muchas páginas.

**Selección múltiple y acción masiva.** Casilla en cada tarjeta y una barra que
aparece al seleccionar: **Tomar N** (asigna todas las que estén libres) y
**Avanzar N** (ejecuta el siguiente paso de cada una, sea el que sea). El
resultado sale resumido: cuántas avanzaron y cuáles fallaron y por qué.

**Acción rápida por tarjeta.** Debajo de cada una, un botón con su siguiente
paso. Un click, sin abrir el detalle. Solo aparece cuando la acción se puede
hacer sin escribir nada; observar o cancelar siguen pidiendo comentario.

**Badges claros:** estado (con el color del borde), prioridad (rojo urgente,
ámbar alta), productos, antigüedad, `Vencida` si pasó el SLA, y responsable
(en gris cursiva si está sin asignar).

## 2. Estados: se acabó la duplicación

El detalle tenía **dos** juegos de controles para lo mismo: la barra de acciones
y, debajo, un bloque "Gestión interna" con *Iniciar revisión*, *Solicitar
corrección*, *Aprobar*, *Rechazar*, *Validar solicitud*, *Registrar carga
iniciada*, *Reintentar carga* y *Finalizar carga*. El mismo cambio de estado se
ofrecía en dos sitios, con reglas distintas.

**Ahora las transiciones viven solo en la barra de acciones**, que sale de
`engines/ticket_flow`. Un click por acción. Lo que exige comentario (observar,
reabrir, cancelar) queda plegado en "Otras acciones".

De "Gestión interna" solo sobrevive lo que no es una transición: prioridad y
reasignar, dentro de "Ajustes de la solicitud", y el botón de guardar aparece
solo si cambiaste el valor.

También se quitó la barra de 4 pasos que `render_barra_acciones` dibujaba: el
detalle ya pinta una arriba. Se apilaban dos, y tres cuando la carga estaba en
marcha.

## 3. El flujo que pediste

```
Tomar solicitud → Iniciar revisión → Aprobar para carga → Ejecutar carga → Completar carga
```

Un click cada uno, desde la tarjeta o desde el detalle. **Tomar asigna siempre
al usuario que pulsa.**

No se tocó la máquina de estados: los 19 estados internos y sus permisos siguen
igual, en `ticket_system`. Lo que cambió es cuántos clicks cuesta recorrerla.

## 4. Completar carga: manual de verdad

Estaba deshabilitado salvo que el job registrara productos procesados:

```python
has_verifiable_result = bool(saved_result) or processed_count > 0
disabled=not (close_confirmed and has_verifiable_result)
```

Además pedía elegir resultado, escribir comentario y marcar una casilla: cuatro
interacciones para cerrar.

Ahora es **un botón**, sin depender de cantidades ni del resultado automático
del job, y el `result` que se guarda ya no lleva `processed` ni `successful`.
La acción se llama **"Completar carga"**.

## Comprobado

- **La app levanta**: arranque headless real, `HTTP 200`, sin trazas en el log.
- Suite completa: **23 en verde**. Siguen fallando `test_auth_accesos` y
  `test_brand_commercial_input`, preexistentes y ya conocidos. Cero regresiones.
- `scripts/test_bandeja_solicitudes.py`: 16 pruebas nuevas — tarjeta como enlace,
  escapado del código en la URL, badges, la cadena de 5 pasos, que *Tomar* asigna
  a quien pulsa, que *Completar carga* no manda cantidades, que lo que pide
  comentario no se ofrece como atajo, y el reparto de 9 por página.
- Sin funciones huérfanas nuevas (las mismas 19 de antes).

## Lo que NO se tocó

- La máquina de estados de `ticket_system` ni los permisos por rol.
- La vista de marca: sigue con su barra compacta y sin controles de operación.
- El cierre desde "Carga de catálogo", que ya era manual.
