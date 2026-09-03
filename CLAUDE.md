# Catalog Control Center — contexto del proyecto

Documento de continuidad. Léelo completo antes de tocar código.

---

## 0. Reglas que no se negocian

1. **La fuente de verdad es GitHub, no ninguna carpeta local.**
   Repositorio: `HugoCamara7/catalogo-control-center` (público).
   Antes de construir nada, descarga `app_matrixify.py` de `main` y compara su
   hash con la copia local. En julio de 2026 se perdieron 371 líneas y 12
   funciones por trabajar sobre una carpeta de OneDrive desincronizada.

2. **Los datos de solicitudes viven en OTRO repositorio**, privado:
   `HugoCamara7/catalogo-control-center-data`, rama `catalog-tickets`,
   carpeta `catalog_tickets/`. No busques tickets en el repo del código.

3. **`inject_custom_css` es un f-string.** Toda llave del CSS va **doblada**
   (`{{` y `}}`). Con llaves simples, Python interpreta `{padding:10px}` como
   interpolación y la app revienta con `NameError: name 'padding' is not defined`.

4. **`run_app()` captura todas las excepciones** y las convierte en `st.error`.
   Una prueba que solo mire `at.exception` dirá "sin excepciones" con la app
   rota. Hay que comprobar también `at.error`.

5. **Nunca dejes una función sin llamador.** Ya pasó dos veces: se definió un
   panel y nunca se invocó. Verifica con AST antes de entregar.

6. **Se entrega por GitHub, no en ZIP.** Desde septiembre de 2026 el agente
   escribe directo en el repositorio: rama, commit, push, PR y merge a `main`.
   Ya no se arma ZIP para que el usuario suba los archivos a mano.

   `gh` está instalado y autenticado como `HugoCamara7` (scopes `repo`,
   `workflow`, `read:org`), con permiso ADMIN en los dos repositorios. **No
   está en el PATH del shell**; se invoca por ruta completa:

   ```
   %LOCALAPPDATA%\Microsoft\WinGet\Packages\GitHub.cli_Microsoft.Winget.Source_8wekyb3d8bbwe\bin\gh.exe
   ```

   Sacar el token guardado de Git Credential Manager para llamar a la API a
   mano **está bloqueado** por el clasificador de seguridad de Claude Code, y
   no hay que intentar rodearlo: para eso está `gh`.

   `git push` sí funciona por su cuenta (GCM tiene las credenciales), pero
   entregar significa **PR mergeado a `main`** — ver la sección 13.

---

## 1. Qué es

App Streamlit que convierte un Excel comercial en un catálogo Matrixify y lo
sincroniza con Shopify, para varios sitios de Forus Perú.

Sitios: Columbia.pe · Rockford.pe · HushPuppies.pe · Vans.pe (más Patagonia y
Sorel en configuración). Cada uno con su vendor, marcas permitidas y colores.

Fuentes de datos: **BigQuery** (maestro ARTI y stock), **Shopify Admin API**
(catálogo actual), y respaldos Excel en `data/`.

---

## 2. Arquitectura

```
app_matrixify.py        18.7xx lineas · 439 funciones · UI + routing + logica
├── engines/            motores sin Streamlit, testeables
│   ├── audit.py        535 lin · auditoria (2 backends, 45 pruebas)
│   ├── notify.py       700 lin · correo transaccional (80 pruebas)
│   ├── stock.py        215 lin · stock por Mod-Col (35 pruebas)
│   ├── metrics.py      190 lin · metricas por Mod-Col (26 pruebas)
│   ├── price_check.py  200 lin · validacion precio/stock (19 pruebas)
│   ├── ticket_flow.py  562 lin · 23 estados -> 5 visibles (55 pruebas)
│   └── storage_check.py 176 lin · diagnostico de persistencia
├── ticket_system.py    1.093 lin · maquina de estados, 2 stores, 28 pruebas
├── generate_columbia_matrixify.py  3.319 lin · motor de catalogo
├── shopify_api.py      1.421 lin · GraphQL Admin API
├── catalog_rules.py      632 lin · reglas de validacion
├── centry_static_masters.py 5.874 lin · datos estaticos (sin funciones)
└── catalog_engine.py / job_store.py / sync_worker.py / api_main.py
```

**Regla de arquitectura:** `engines/` nunca importa Streamlit. Verificado por
prueba. `generate_columbia_matrixify.py` importa `streamlit` dentro de una
función con `try/except` solo para leer secretos — es dependencia blanda y el
módulo carga sin Streamlit.

### Deuda conocida

`catalog_engine.py:7` hace `from app_matrixify import apply_full_product_updates`.
El worker de fondo (`sync_worker.py`, desplegado en Render) depende de la capa
de UI. Se arregla extrayendo `engines/shopify_sync.py` (~2.080 líneas).

### Funciones más grandes de `app_matrixify.py`

| Líneas | Función |
|---:|---|
| 2.987 | `inject_custom_css` (CSS embebido en f-string) |
| 1.190 | `main` (routing + carga completa + carga parcial en línea) |
| 449 | `build_catalog_kpis` |
| 422 | `build_shopify_update_preview` |
| 414 | `apply_full_product_updates` |
| 332 | `render_ticket_detail` |

---

## 3. Estados de solicitud

`ticket_system.py` define **23 estados internos** (19 originales + 4 del
cierre de carga por etapas, agosto 2026). Los 19 primeros no se tocaron: las
solicitudes históricas se leen sin migración.

`engines/ticket_flow.py` los traduce a **5 visibles**:

| Visible | Agrupa |
|---|---|
| Pendiente de revisión | draft, request_received, pending_assignment, assigned, digital_review, correction_received |
| Lista para ejecutar | load_approved, preparing_catalog, dry_run, ready_execute |
| En ejecución | loading, validating_results, sial_loaded, price_load_requested, price_stock_validation, ready_to_close |
| Finalizada | completed, completed_with_observations, rejected, canceled |
| Observada | observed, waiting_brand_correction, failed |

Los matices se conservan entre paréntesis: "Finalizada (rechazada)",
"En ejecución (esperando carga de precios)".

**Recorrido feliz** (una sola acción principal por estado):

```
pending_assignment → Aceptar carga    (atajo: tomar + revisar + aprobar)
digital_review     → Aprobar para carga
load_approved      → Ejecutar carga   (atajo: validación previa + ejecutar)
loading            → Finalizar solicitud
```

### 3 bis. Atajos (`flujo.ATAJOS`, septiembre 2026)

Un atajo ejecuta **varias acciones del flujo con un solo botón**. Existen
porque llegar de "recién llegada" a "cargando" pedía **cinco clics** repartidos
en dos pantallas —Tomar solicitud, Iniciar revisión, Aprobar para carga,
Ejecutar validación previa, Ejecutar carga— y **ninguno era una decisión
distinta de la anterior**: quien toma una solicitud para revisarla ya decidió
revisarla.

Y había un bug: **"Ejecutar carga" desde `load_approved` fallaba SIEMPRE** con
"Ejecuta y revisa el dry run antes de iniciar la carga". `start_load` exige el
dry run, y el botón que lo corría vivía solo en el panel de "Cargas
pendientes", en otra pantalla. Por eso `validacion_previa` (`run_dry_run`) es
ahora una acción del flujo: para que el atajo la pueda encadenar.

**El atajo REEMPLAZA los botones que cubre** (`claves_reemplazadas`). "Aceptar
carga" al lado de "Tomar solicitud" son dos botones para lo mismo y no hay
forma de saber cuál usar. Y **solo se ofrece si ahorra al menos un clic**: desde
`digital_review` queda un único paso, así que se muestra "Aprobar para carga" a
secas.

**El despacho está en `_ejecutar_accion_ticket`**, no en cada pantalla: mira si
la acción trae `pasos_resueltos` y deriva a `_ejecutar_atajo_ticket`. Así las
tres superficies (botón rápido de la tarjeta, acción masiva y barra del
detalle) heredan los atajos sin saber que existen — incluido el lote, así que
**"Aceptar carga (5)" deja cinco solicitudes listas de una vez**. Se mira la
CLAVE, no su valor: un atajo con la cadena vacía sigue siendo un atajo, y con
`if accion.get(...)` caía al camino de acción suelta y reventaba con `KeyError`
en `metodo`, que los atajos no tienen.

**Para en el primer paso que falle** y dice qué alcanzó a aplicar. La solicitud
queda en un estado intermedio válido, nunca a medias de una escritura. La
auditoría y los correos salen igual que si se hubieran pulsado los botones uno
a uno, porque reusa `_ejecutar_accion_ticket` paso por paso.

**La cadena de cierre NO se ataja, a propósito.** Ahí cada paso espera algo
real —que el Área de Producto cargue los precios, que la validación contra
Shopify no traiga bloqueos— y saltárselos es exactamente el error que se
corrigió en agosto de 2026. Además "Carga SIAL terminada" **necesita el archivo
SIAL**, que solo tiene la pantalla: encadenarla desde el motor mandaría el
correo al Área de Producto **sin adjunto**. Hay 4 pruebas que lo fijan, una de
ellas recorriendo los 23 estados.

**`queda_en` es un dato duplicado** de `TRANSITIONS`. Hay una prueba que
comprueba que cada destino declarado sea **alcanzable** en el grafo real —no un
salto único, porque varios métodos dan dos saltos internos (`run_dry_run` hace
aprobada → preparando → dry run → lista, y `record_job_result` pasa por
validando como `ROLE_SYSTEM`). Sin ella, alguien cambia una transición y el
atajo hace el primer paso, falla el segundo y la solicitud queda a medio
camino. Dos acciones quedan excluidas y anotadas por ser fallos
**preexistentes**: `reabrir` y `cancelar` desde estados sin entrada admin en
`TRANSITIONS`.

**`tomar` solo sale en `pending_assignment`.** Estaba también en `draft` y
`request_received`, y `assign()` rechaza los dos ("La solicitud ya no está
disponible para asignación"): el botón se dibujaba y fallaba siempre. Un botón
que no puede funcionar es peor que no tener botón.

**Después de "Aceptar carga" la app va sola a Carga completa**
(`ir_a_carga_completa`), con la solicitud **ya elegida** en el selector. Aceptar
una carga y quedarse en la bandeja obliga a buscar el modo de carga en la barra
lateral; llegar a la pantalla correcta y tener que rebuscar la solicitud en una
lista es la mitad del mismo problema. Los dos valores que escribe son los
mismos que usan los botones del menú, o la barra lateral queda marcada en otra
opción — hay un test que lo fija.

**El selector de Carga completa ya no pregunta el origen.** Había un radio
"Origen del input" delante: sobraba, porque cuando hay solicitudes listas
usarlas es lo que se quiere hacer siempre. Las **aprobadas van primero**
(`ESTADOS_APROBADA_SIN_CARGAR`) y cada línea lleva su estado visible, porque la
lista mezcla aprobadas con cargas en curso y sin eso dos líneas idénticas
pueden ser una lista para ejecutar y una que ya se cargó. El marcador va en
TEXTO (`[APROBADA]` / `[EN CURSO]`), no en emoji. La carga a mano sigue
disponible: automática cuando la solicitud no tiene adjunto recuperable, y con
una casilla explícita para reemplazar el adjunto por un Excel corregido por
fuera.

**El stepper de 4 pasos mentía.** `render_stepper` calculaba el estado de cada
paso por el **índice**, no por `current_step`: el paso 2 decía siempre "OK" y el
3 siempre "Revisar". Con la pantalla recién abierta y sin un solo archivo
cargado, la barra afirmaba que BigQuery estaba resuelto y que había algo que
revisar. Hay 4 pruebas que leen el HTML dibujado.

**El panel de "Cargas pendientes" tenía su PROPIO juego de botones.**
`render_full_load_ticket_queue` dibujaba "Ejecutar validación previa" y "Marcar
carga iniciada" a mano, sin pasar por los atajos, así que ahí seguían
apareciendo los dos pasos sueltos que la bandeja ya había unificado. Ahora usa
`render_barra_acciones`, la misma de la bandeja: hay **un solo lugar** donde
cambiar el recorrido.

Solo para los estados **previos a la carga** (`ESTADOS_ANTES_DE_CARGAR`). De
`loading` en adelante manda el cierre por etapas, que **necesita el archivo
Carga SIAL** — y ese solo lo tiene la pantalla. Encadenarlo desde la barra
mandaría el correo al Área de Producto sin adjunto.

**`render_barra_acciones` y `render_acciones_con_comentario` llevan `prefijo`.**
En Carga completa la barra se dibuja **dos veces**: en "Cargas pendientes" y
después del análisis (`_render_acciones_solicitud_tras_carga`). Con la misma
solicitud en las dos —que es el caso normal, la eliges arriba y la cargas
abajo— las claves `accion_<clave>_<codigo>` serían idénticas y Streamlit corta
la pantalla con `StreamlitDuplicateElementKey`. La cola pasa `"cola_"`; las
demás superficies se quedan con el prefijo vacío. Hay un test que recorre las
claves y falla si a alguna le falta.

**El override manual ya no viene con "Finalizada" preseleccionada.**
`_render_completar_carga` usa `set_status_manual`, que salta la máquina de
transiciones **a propósito**: es el escape para un ticket que quedó atrasado.
Pero venía con "Finalizada" marcada por defecto, así que una solicitud recién
aprobada —sin cargar nada— ofrecía "Finalizar solicitud" listo para pulsar, y
eso cierra saltándose la carga entera y toda la cadena de precios. Ahora el
selector va con `index=None` y el botón deshabilitado hasta que se elija. **La
capacidad no se quitó**, solo deja de ser el valor por defecto, y el panel se
movió dentro de "Más opciones".

**Cierre de carga por etapas** (6 etapas, `flujo.ETAPAS_CARGA`):

```
loading                → Carga SIAL terminada      (acción SECUNDARIA)
sial_loaded            → Notificar a Producto
price_load_requested   → Precios cargados
price_stock_validation → (validar) → ready_to_close
ready_to_close         → Finalizar solicitud       → completed
```

**"Completada" SOLO se alcanza desde `ready_to_close`.** Antes se podía cerrar
en cuanto terminaba el SIAL, sin precios cargados ni validados: ese era el
error a corregir. `TRANSITIONS[ROLE_SYSTEM]` ya no permite
`sial_loaded/price_*` → `completed`, y `finalize_request()` lo comprueba otra
vez. Hay 5 pruebas que intentan cerrar antes de tiempo y esperan que falle.

"Carga SIAL terminada" es secundaria a propósito: si fuera principal
desplazaría a "Finalizar solicitud" y rompería el recorrido de quien no usa la
cadena. Hay un test que lo fija.

`flujo.seguimiento_carga(estado)` devuelve las 6 etapas con su situación
("hecha"/"actual"/"pendiente") como DATOS. `render_seguimiento_carga()` solo
las dibuja. No metas la cadena de etapas en una pantalla.

Hay un test que falla si algún estado de `ticket_system` queda sin mapear, y
otro que cuenta 23. Si agregas un estado, actualiza ambos.

---

## 4. Roles y accesos

| Rol | Ve |
|---|---|
| `admin` (Hugo, Luis) | todo, incluida Auditoría |
| `operator` | bandeja de solicitudes |
| `brand` / comercial | solo "Input comercial" y "Mis solicitudes" |

**Riesgo abierto:** `auth_access_scope()` devuelve `ROLE_ADMIN` **por defecto**
para cualquier usuario que no esté en ninguna lista. Los 8 comerciales están
protegidos por código en `COMMERCIAL_INPUT_ONLY_USERS`, pero cualquier usuario
nuevo en Secrets sin rol explícito entra como administrador.

Usuarios comerciales: comercial, alejandro.mosqueira, clara.gallastegui,
natalia.ludowieg, daniela.ballon, mario.biggio, nicolas.rodriguez,
alejandro.espinoza (todos `@forus.pe`).

---

## 5. Auditoría

`log_user_activity()` conserva su firma original y sus 8 campos. Se le
agregaron parámetros opcionales: `ticket`, `marca`, `estado_anterior`,
`estado_nuevo`, `resultado`.

Detrás está `engines/audit.py` con dos backends (`LocalAuditStore` efímero,
`GitHubAuditStore` persistente), saneado de secretos, filtros, paginación de
30, KPIs, resumen por usuario y exportación.

**Destinatarios de la marca:** `brand_notification_recipients()` resuelve por
asociación EXPLÍCITA en `[app_auth.brands]`. **No uses `auth_allowed_brands()`
para esto**: a los admin y a los 8 comerciales les devuelve *todas* las marcas,
así que les llegaría cada cambio de cada marca.

**La instrumentación es automática:** `AuditedTicketService` envuelve
`TicketService` e intercepta 14 acciones capturando estado anterior y nuevo.
No hay que recordar una llamada en cada punto. Los 22 `download_button` llevan
`on_click=log_descarga`.

Se registran 23 tipos de acción. Los intentos denegados por permisos también
quedan, con `resultado="error"`.

---

## 5 bis. Notificaciones por correo (agosto 2026)

`engines/notify.py`. Documento completo en `docs/MOTOR_NOTIFICACIONES.md`.

**Punto de enganche:** `TicketService` ya recibía el notificador por inyección
y ya llamaba a `notifier.notify()` en cada transición. Enchufando
`AdaptadorCorreoTickets` ahí, el correo sale desde las 18 pantallas sin tocar
ninguna. **No pongas lógica de correo en una pantalla.**

- Tres transportes: `smtp`, `graph` (Microsoft 365 sin SMTP AUTH) y `consola`.
  Sin sección `[notificaciones]` en Secrets cae a `consola` y no envía nada.
- **Mailchimp se evaluó y se descartó**: su producto transaccional es Mandrill,
  de pago aparte, y por la API de marketing una baja de marketing apagaría los
  avisos operativos de una persona. El razonamiento completo está en el doc.
- No duplica: si el estado no cambió no arma el mensaje, y hay clave de
  idempotencia con ventana de 5 minutos contra el historial de la solicitud.
- El envío va en un hilo aparte, como la auditoría: un viaje SMTP en el hilo
  de la pantalla dejaría el botón colgado justo al aprobar o finalizar. Para
  la cola se usa `motor.preparar()`, **nunca `motor.enviar()`**: con `enviar()`
  el aviso sale dos veces, una en línea y otra al desencolar.
- El correo al Área de Producto lleva **el archivo Carga SIAL adjunto**. El
  archivo se guarda como artefacto de la solicitud al pulsar "Carga SIAL
  terminada", no queda en la sesión. En el registro solo va el nombre: el
  registro se serializa dentro del ticket JSON.
- Ningún fallo de correo puede tumbar ni deshacer un cambio de estado.

**`assign()` no pasa por `_transition`**: cambia el estado a mano. Por eso
tiene su propio aviso de cambio de estado. Si agregas otro método que cambie
`ticket["status"]` sin `_transition`, tiene que hacer lo mismo o la marca no
se entera.

---

## 5 ter. Stock por Código Modelo-Color

`engines/stock.py`. El stock llega por variante, pero el producto que se
prende o apaga es el Modelo-Color.

**Consolida primero por talla y después por modelo.** Sumar filas contaba dos
veces la misma existencia cuando una talla venía repetida (dos SKU del maestro
que normalizan a la misma talla). Medido: un modelo con 2 SKU sobre la talla 8
daba 20 unidades y 2 tallas con stock; lo correcto es 10 unidades y 1 talla.

`build_catalog_kpis` usa el motor para `Stock_total`, `Tallas_BigQuery`,
`Tallas_con_stock` y `Debe estar visible`. El resto de la función no cambió.
El KPI **"Filas de talla repetidas"** muestra cuántas se consolidaron: si es
alto, el maestro está duplicando variantes.

---

## 5 quater. Status de carga de catálogos (septiembre 2026)

`engines/load_status.py` (sin Streamlit ni pandas) + `render_status_de_carga()`.
Pantalla propia en el menú, **al lado de KPIs de catálogo**.

Reemplaza el Excel `Status_Carga_Catalogo`, que se llenaba a mano casilla por
casilla y envejecía en cuanto alguien cargaba algo. Las mismas hojas, pero con
datos vivos y una columna que el Excel no tenía.

**Es la única pantalla que mira TODOS los sitios a la vez.** El resto de la app
trabaja sobre el sitio elegido en la barra lateral; aquí la pregunta es cuánto
se cargó en total y qué falta, y esa no se responde de a un sitio.

| De dónde sale | Qué responde |
|---|---|
| Solicitudes (`ticket_system`) | qué inyectaron las marcas |
| Catálogo real de cada sitio (Shopify) | qué se cargó de verdad |
| La resta | qué falta |

**Cargado ≠ visible.** Un producto puede existir en Shopify y no verlo nadie:
en borrador, o activo sin publicar en el canal Online Store. Por eso hay cuatro
estados web (`Prendido y visible`, `Activo sin publicar`, `Borrador`,
`Archivado`) y solo el primero cuenta como prendido. Si la tienda no expone el
canal, `Published Online Store` llega vacío: eso se reporta como "Activo sin
publicar", **nunca** se asume publicado.

**`Vendor` NO sirve para saber la marca.** En Shopify es el vendor del SITIO
(`rockfordpe`), el mismo para todas las marcas de esa tienda: contando por
vendor, Rockford.pe tendría una sola marca y Columbia, Patagonia y Sorel
desaparecerían. Manda el metacampo `custom.marca`, que se **agregó a la
consulta de `shopify_api.fetch_products`** para esto. Respaldo: los tags.

La unidad es el **Modelo-Color**, igual que en `engines/stock.py`. Se cuenta una
vez por sitio; en los totales por marca se deduplica entre sitios (si no,
Rockford sumaría 435 × 3 sitios).

Un sitio sin Shopify en Secrets o que devuelve error **no** se reporta como
catálogo vacío — eso se leería como "no han cargado nada". Su estado viaja
aparte y la pantalla avisa que sus productos no están contados.

**Las etiquetas llevan tilde; las CLAVES no.** `engines/load_status` no usa
tildes en ninguna clave. `render_status_de_carga` pedía `kpis["Marcas con
catálogo"]` con tilde y era un `KeyError` que tumbaba la pantalla entera en
producción. No lo atrapó nada porque las pruebas cubrían el motor y el armado
de tablas, pero **nadie tocaba la función que dibuja**. Hay un test que lee del
árbol las claves que pide la pantalla y falla si el motor no las devuelve.
Desde septiembre de 2026 ese test también mira los `kpis.get("...")`, no solo
los `kpis["..."]`: un `.get()` con la clave mal escrita **no revienta**,
devuelve `None` y el número o el aviso simplemente no aparece nunca. Es peor
que el `KeyError`, porque nadie se entera.

**Se cuenta por `clave_de_producto`, NUNCA por `Mod-Col` a secas.** El
`Mod-Col` sale del metacampo `custom.codigo_modelo_color`, y los productos
viejos no lo tienen. Todas las tablas contaban con `set()` sobre ese campo, así
que **todos** los productos sin metacampo compartían la misma llave — la cadena
vacía — y el conjunto los colapsaba en uno solo.

Medido: 7 productos, 4 sin metacampo → el KPI "Productos cargados" decía **4**
y la tabla "Prendido y visible", que cuenta filas, decía **7**. Dos números
distintos para lo mismo en la misma pantalla. Y en la resta era peor: con dos
productos sin metacampo, uno visible y uno en borrador, la cadena vacía quedaba
en el conjunto de cargados **y** en el de visibles, así que **"No visibles"
daba 0 con la mitad del catálogo apagado**.

`clave_de_producto` devuelve el Modelo-Color cuando lo hay y `handle:<handle>`
cuando no — con prefijo, para que un handle que se parezca a un código no pueda
chocar con uno real. `Mod-Col` se queda solo para MOSTRAR (vacío es la verdad);
`Clave` es para CONTAR. `_identidad(fila)` es el respaldo para filas armadas a
mano que traen solo `Mod-Col`.

No lo atrapó ninguna de las 28 pruebas porque el helper `producto()` del test
exige el código como primer argumento y **ningún caso pasaba uno vacío**: cero
cobertura de lo que más abunda en producción. Ahora hay 7 pruebas de eso, y una
que exige que el KPI de arriba y la tabla de abajo den el mismo número en
catálogos con y sin metacampo. Fallan las 7 con el código anterior.

**"Sin marca" no es una marca.** `Marcas con catalogo` la contaba, así que un
sitio con productos sin `custom.marca` reportaba una marca de más. Los KPIs
`Productos sin codigo Modelo-Color` y `Productos sin marca` existen para que la
pantalla avise por qué un total puede no cuadrar con el Excel de alguien, en
vez de dejar que lo descubra solo.

**Los sitios se leen EN PARALELO.** Eran seis crawls paginados de GraphQL
encadenados y el más lento marcaba el ritmo de la pantalla entera. Dentro del
hilo va **solo** `fetch_products`: `st.session_state` no se puede tocar desde
un hilo, así que la caché se consulta antes (`shopify_products_en_cache`) y se
escribe después (`guardar_shopify_products`), las dos en el hilo de la
pantalla. El orden de la tabla de sitios es el de `SITE_CONFIGS`, no el de
llegada: una tabla que se reordena en cada refresco no se puede comparar.

Todo se descarga en un solo Excel con las 9 hojas.

---

## 5 quinquies. Interfaz móvil (septiembre 2026)

Las 13 media queries que ya existían paran en 900–1100px: eso es tablet. En un
teléfono (360–430px) las rejillas de 4 y 6 columnas dejaban tarjetas de 60px,
con el número partido en tres líneas.

**Hay DOS bloques de CSS y el login no comparte el de la app.** `require_login()`
llama a `render_login_styles()` y **nunca** a `inject_custom_css`, así que las
reglas de móvil hay que ponerlas en los dos sitios. Por eso el botón "Ingresar"
se quedaba en 74×40 aunque la app ya estuviera arreglada. Hay un test que fija
esta separación.

Dos escalones, no uno: **640px** (todavía caben dos tarjetas por fila) y
**430px** (teléfono angosto).

- **`.kpi-card` trae `height:96px` FIJO.** Pisar solo `min-height` no hace nada.
  Ocho tarjetas de 96px son 800px de scroll antes de llegar a algo tocable.
- **El ancho lo limita `stElementContainer`**, no el botón ni su envoltorio: mide
  lo que el texto (74px). Un botón sin `use_container_width` no crece por más
  `width:100%` que lleve encima.
- **44px es el mínimo táctil** de Apple y Google; el login usa 46px.
- **16px en los inputs**: por debajo, Safari hace zoom al enfocar y deja el
  formulario a medio salir de la pantalla.
- Las pestañas ruedan en horizontal en vez de cortarse; las tablas ruedan dentro
  de su caja y no arrastran la página.
- Todo va dentro de un `@media`. Una regla suelta con `!important` se llevaría
  por delante el escritorio — hay un test que lo comprueba.

**Cada clase la gobierna UNA hoja.** `.ticket-*` es de `render_ticket_styles`.
Tenerla también en `inject_custom_css` con `!important` dejaba los KPI de la
bandeja en dos columnas cuando la hoja de Solicitudes pedía tres. Dos hojas
peleando por la misma clase no se ve hasta que alguien mide el DOM; hay un test
que lo impide.

**Columnas anidadas.** Una columna que CONTIENE otra fila de columnas tiene que
quedarse con el ancho entero. Sin eso, la bandeja partía la pantalla en dos y
los cinco filtros de adentro quedaban en 181px: uno por fila, con la mitad del
ancho vacía al lado. Las columnas angostas sí comparten fila (base 50%, mínimo
150px).

**La bandeja de Solicitudes es la pantalla que había que medir.** En 390px la
primera solicitud empezaba en **y=1138px** — 1,3 pantallas de scroll antes de
ver nada útil. Nada estaba roto: simplemente no se podía trabajar. Quedó en
**y=724px**, dentro de la primera pantalla. Se logró con la cabecera compacta
(Streamlit le pone su propio padding a los `h1` de markdown, y con el
sobretítulo oculto el hueco era más alto que el título), los seis KPI de a tres
por fila y los filtros de a dos.

**En el teléfono el menú TIENE que poder cerrarse.** En escritorio el menú es
un riel fijo de 360px, y para eso la app esconde todos los controles nativos
para plegarlo (`stSidebarCollapseButton`, `stExpandSidebarButton`,
`collapsedControl`) y lo clava con `transform:translateX(0) !important`.

En un teléfono de 390px eso deja un panel de 360px encima de la pantalla
entera, **sin ninguna forma de quitarlo**: el contenido queda debajo y no se
puede accionar nada. Medido: Streamlit ya marcaba `aria-expanded="false"` — para
él el menú estaba cerrado — y el CSS de la app lo forzaba a la vista igual.

En móvil se le devuelven las tres piezas: respetar `aria-expanded="false"`
(sale de pantalla), el botón para cerrarlo (estaba en 0×0) y el botón para
abrirlo (vive en la cabecera oculta; se saca de ahí y queda flotando sobre el
contenido). **Al devolver la cabecera vuelve el botón Deploy de Streamlit**, que
se queda encima y se come el toque: la cabecera va con `pointer-events:none` y
solo el botón de abrir recibe toques. Hay tests que fijan las tres piezas.

**Streamlit Cloud mete en la cabecera botones que en local NO existen** — el
lápiz de editar la app, Deploy, el menú de tres puntos. Con un selector amplio
(`stBaseButton-header`), el lápiz recibía los estilos del botón flotante,
quedaba exactamente encima del de abrir el menú y el toque se iba a la pantalla
de edición. Se nombra solo `stExpandSidebarButton`; el resto de la cabecera se
oculta uno por uno. **No se prueba en local: hay que simular esos botones.**

**`stToolbar` no se puede ocultar con `display:none`**: el botón de abrir el
menú vive DENTRO de ella. Medido, quedaba en 0×0 y no había forma de abrir el
menú. Se la deja existir con altura cero y sin toques.

**Un botón nuevo del menú lateral hay que registrarlo en CINCO listas de
selectores** (caja, contenedor del texto, `p`, `::before` y `:hover`) y darle su
dibujo de icono. Nada en el código lo obliga: "Status de carga" se agregó al
menú y salió sin icono y con otra tipografía, distinto de los otros cuatro. Hay
un test que recorre cada `sidebar_nav_button` y falla si le falta alguna.

**El menú lateral en móvil.** Se abre encima de todo y había que bajar dentro de
él para llegar a "Operaciones": las cuatro tarjetas de presentación (logo Forus,
usuario, sitio activo, marcas) se comían la pantalla. Compactadas, el menú
entero entra de una. La tarjeta de usuario se compacta en SU hoja
(`render_sidebar_account_card`), no en `inject_custom_css` — misma regla de un
dueño por clase.

Verificado con capturas reales (Chromium 390px, 360px y 1440px): sin desborde
horizontal en ninguno, y escritorio intacto.

---

## 5 sexies. Mantenedor de Videos (septiembre 2026)

`engines/video_media.py` (sin Streamlit) + `render_video_maintainer()`. Entra
como **una opción más de Carga parcial**, al lado de "Mantenedor Fotos PNG".

**Funciona igual que el mantenedor de fotos: el video YA ESTÁ en el bucket.**
Nadie sube un archivo desde la app. El usuario entrega un Excel con los códigos
y la app arma la dirección, la busca, la publica y la deja en la posición 2.

```
2044361-6RX  →  COLUMBIA/2044361_6RX_2.mp4
             →  https://ecom-imagenes.../COLUMBIA/2044361_6RX_2.mp4
             →  ficha del producto, posición 2
```

**El `_2` del nombre ES la posición en la galería.** No es un número de
versión: el video va inmediatamente después de la foto principal.

**Solo hay modo masivo.** Siempre un Excel, aunque lleve un solo código. Un
modo individual con Modelo y Color escritos a mano sería una segunda forma de
armar el mismo nombre, y las dos se separan sin que nadie lo note.

**Trabaja en DOS TIEMPOS, igual que el mantenedor de fotos.** Primero
`video_analizar_codigos()` revisa TODO el Excel **sin escribir nada** en
Shopify: qué productos existen, de qué carpeta sale cada video y cuáles están
de verdad en el bucket. Solo después, y con confirmación, se publica. Sin esto,
en una lista de 50 códigos se empieza a cargar y uno se entera a mitad de
camino de que 30 videos no estaban. Hay un test que lee la función y falla si
aparece cualquier mutación de Shopify dentro.

El análisis deja cada código en un estado: `Listo para cargar`,
`Sin video en el bucket`, `No está en Shopify` o `Sin confirmar`. **"Sin
confirmar" SÍ se publica**: el bucket contesta 403 a las consultas anónimas y
eso no es "no existe" — es el mismo detalle que en las fotos dejaba 310 vistas
en "Sin PNG".

La comprobación del bucket es `png_comprobar_url`, **la misma de las fotos**,
con un parámetro `tipos` nuevo. Su valor por defecto es `("image/",)`, así que
las fotos no cambian en nada; los videos pasan
`("video/", "application/octet-stream")` porque S3 devuelve octet-stream para
los mp4 a los que nadie les puso el tipo.

**Se procesa por BLOQUES**, con `png_bloques`, la misma función de las fotos:
cada bloque termina, **se guarda** y la barra avanza, así una lista larga no se
cae entera. `VIDEO_MODELOS_POR_BLOQUE` es 5 y no 20 como las fotos: allí cada
código son diez peticiones HEAD, aquí es bajar decenas de MB del bucket y
volver a subirlos a Shopify. Bloques más chicos guardan más seguido. Hay un
test que comprueba que el guardado esté DENTRO del bucle.

La lectura del Excel es `png_codigos_desde_excel`, **la misma** del mantenedor
de fotos: quita vacíos y repetidos y explica cada descarte. Las direcciones del
bucket salen de `png_urls_a_probar`, también la misma.

**La carpeta la manda la MARCA, no el sitio.** Rockford.pe vende Columbia,
Patagonia, Sorel y Mountain Hardwear: tomar la carpeta del sitio dejaría los
videos de cuatro marcas en `ROCKFORD/`. Se lee de `BRAND_IMAGE_FOLDERS`, el
mismo diccionario de las fotos — aquí **no se copia**, se importa.

La marca de cada código sale, en este orden: **columna Marca del Excel** (si
viene) → **metacampo `custom.marca` del producto** → marca elegida en pantalla.
El metacampo va antes que la pantalla porque es el dato de la propia ficha; el
selector de la barra lateral sería el mismo para las cuatro marcas de Rockford.

**Shopify no se baja el video solo.** Con una foto alcanza con darle la URL
pública y él la descarga; con un video **no**: `originalSource` de un media
VIDEO solo acepta el `resourceUrl` de un staged upload. Por eso la app hace de
intermediaria — baja el mp4 del bucket con `video_descargar_del_bucket()` y se
lo entrega a Shopify — igual que ya hace `_sync_product_photos_direct` con las
fotos. Para quien usa la pantalla es idéntico a las fotos: solo códigos.

Los tres viajes obligatorios:

1. `stagedUploadsCreate(resource: VIDEO)` — `fileSize` es **obligatorio** y el
   método es **POST multipart**, no PUT: el destino es una política firmada de
   Google Cloud Storage y exige que el campo `file` vaya el **último**, después
   de todos los parámetros firmados.
2. POST del archivo a ese destino.
3. `productCreateMedia(mediaContentType: VIDEO)`. **No `fileCreate`**: eso deja
   el mp4 en Contenido > Archivos y nunca aparece en la ficha del producto.

**Y un cuarto que no es opcional.** `productCreateMedia` siempre agrega el media
**al final** y no acepta posición. El video queda segundo con
`productReorderMedia`, que trabaja con **índices que empiezan en 0**: la
posición 2 que ve una persona es `newPosition: "1"`, en **texto**
(`UnsignedInt64`). Confundir las dos numeraciones deja el video tercero. El
reordenamiento devuelve un `job` asíncrono, así que se **relee** la galería
para comprobar dónde quedó. Si no quedó en la 2 se reporta como **fallo**:
publicado en la posición equivocada es el peor error silencioso posible.

**La espera de un video es larga a propósito.** `wait_media_statuses` (fotos,
6×3s) devolvería `PROCESSING` casi siempre; `wait_video_media_ready` va 20×6s.
Y `fetch_media_statuses` solo abre `... on MediaImage`: con un video devuelve
el nodo **sin `status`** y la espera cree que ya terminó. Por eso existe
`fetch_video_media_statuses`, que abre los dos fragmentos.

**La app NO escribe en el bucket.** Se evaluó y se descartó: hubo una versión
con `engines/s3_uploader.py` y boto3 que subía el mp4 desde la pantalla, pero
el flujo real es el de las fotos — el archivo lo deja otra persona en el bucket
y la app solo lo publica. No hay sección `[s3]` en Secrets ni boto3 en
`requirements.txt`, y hay pruebas que impiden que vuelvan por la puerta de
atrás.

**Nunca crea productos y nunca duplica videos.** Si el producto ya tiene uno se
avisa y solo se reemplaza cuando la persona marca la casilla; el anterior se
borra **antes** de crear el nuevo, para que la posición 2 quede libre.

Los **10 pasos** quedan registrados uno por uno con su estado (ok / aviso /
error) y su detalle técnico, por código: cuando algo falla se ve exactamente
dónde. Cada intento va a la auditoría, salga bien o mal.

**Scopes de Shopify:** `read_products`, `write_products`. `write_files` NO hace
falta: los videos van por `productCreateMedia` / `productReorderMedia`.

## 5 septies. Rendimiento: el peso de cada rerun (septiembre 2026)

Streamlit vuelve a ejecutar el script entero en cada clic, así que lo que
importa no es cuánto tarda un cálculo sino **cuántos bytes viajan por
interacción**. Medido, no supuesto.

**Lo que NO era el problema.** Rearmar el f-string de 130 KB de
`inject_custom_css` cuesta **0,12 ms**. Cachearlo no habría servido de nada, y
sacar el CSS a un archivo estático rompería las 33 pruebas de
`test_css_movil.py`, que lo leen del código. No se toca.

**Lo que sí era.** Los logos van embutidos como `data:` URI dentro del HTML, en
resolución de origen: `assets/brands/logo_columbia.png` es **3840×696** para
dibujarse a 138×54 px. Y el **mismo logo de marca se embute cuatro veces por
rerun**: dentro del CSS (`site_logo_src`), en la tarjeta de marca, en la de
Shopify y en la cabecera.

| Sitio | Antes | Ahora |
|---|---:|---:|
| Columbia.pe | 668 KB | **182 KB** |
| Vans.pe | 447 KB | **174 KB** |
| MountainHardwear.pe | 406 KB | **226 KB** |
| Patagonia.pe | 229 KB | **115 KB** |
| HushPuppies.pe | 337 KB | **216 KB** |
| Rockford.pe · Sorel.pe | 113 / 95 KB | sin cambio (ya eran chicos) |

`image_data_uri` reduce a `LOGO_ANCHO_MAXIMO` (480 px, margen para retina) y
cachea. Tres reglas que no son obvias:

1. **Solo se usa la versión reducida si de verdad pesa menos.** Re-codificar
   algo ya optimizado lo **engorda**: `shopify_logo.png` pasaba de 17 KB a
   **83 KB** en PNG. Reducir sin comparar habría hecho la app más lenta en
   varios sitios.
2. **El formato se elige, no se asume.** `logo_vans.jpg` (1600×730, JPEG) en
   PNG daba 99 KB y en JPEG da **31 KB**. Pero JPEG solo se usa en los modos de
   Pillow **sin canal alfa** (`RGB`, `L`): pasar a JPEG algo con transparencia
   le pone **fondo negro** al logo, y es un error que no revienta — la app sigue
   andando y el logo sale con un rectángulo negro detrás. `P` puede llevar
   transparencia en la paleta, así que va a PNG.
3. **El `stat` va FUERA de la caché.** La firma de la función cacheada lleva
   `(st_mtime_ns, st_size)` y no se usa dentro: está ahí para que reemplazar un
   logo en disco invalide la caché sola. Con el `stat` dentro habría que
   reiniciar la app para ver el logo nuevo.

Pillow **se declara en `requirements.txt`**. Llega por Streamlit, pero aquí se
importa directo. Si faltara, `_reducir_imagen` devuelve `None` y se usa el
original: la app no puede quedarse sin logos por eso.

`resolve_logo_path` también quedó cacheada: su último respaldo hace `iterdir()`
—un listado de directorio— y se llamaba cuatro veces por rerun para el mismo
logo.

**Los sitios del Status de carga se leen en paralelo** — ver la sección 5
quater.

### Los adjuntos se bajaban de GitHub en CADA rerun

**`st.download_button` exige los bytes POR ADELANTADO.** No acepta un callable,
así que cada rerun bajaba de GitHub el Excel del input **y** el de validación
aunque nadie pulsara el botón. Con la bandeja y Carga completa abiertas eran
**entre dos y cinco descargas por clic**, y la pantalla se quedaba en gris
esperando la red: eso era la lentitud que se sentía.

`artefacto_de_solicitud(_store, ruta)` lo cachea. Medido con 250 ms de latencia
por descarga: **5 clics pasaban de 5,01 s a 0,50 s**, y de 20 descargas a 2.

Cachear por ruta es correcto porque los adjuntos son **inmutables**: la ruta
lleva la solicitud, el número de versión y el tipo, y una versión nueva escribe
una ruta nueva.

`_store` empieza con guion bajo **a propósito**: así Streamlit no lo hashea y la
clave de caché es solo la ruta. Si el store entrara en la clave, cada rerun
crearía uno nuevo y la caché no serviría de nada. Hay un test que lo fija, y
otro que falla si alguien vuelve a poner `store.get_artifact(...)` en línea.

**Lo que NO era el problema, medido:** `get_ticket_service()` no está cacheado y
se llama 8 veces por rerun, pero construirlo cuesta **0,20 ms** — 2 ms en total.
Cachearlo no habría cambiado nada. La auditoría tampoco: ya sale en un hilo
aparte.

### Los archivos de `assets/` están CORRIDOS una posición

Verificado abriendo las imágenes. Los nueve `assets/logo_*` de la raíz tienen,
cada uno, el logo de la marca **anterior** en orden alfabético:
`assets/logo_vans.jpg` contiene el logo de **Sorel**, y `assets/logo_columbia.png`
son **2 bytes** (`\r\n`), ni siquiera una imagen.

**La app NO los usa**: `SITE_UI_CONFIG` apunta a `assets/brands/`, y ahí los
nueve están correctos (`assets/brands/logo_vans.jpg` sí es Vans). Son copias
muertas y mal nombradas — van a la lista de la sección 10, no son un bug
visible. No las borré porque eso es una decisión aparte.

---

## 5 septies. El flujo de carga, de punta a punta (septiembre 2026)

```
Subir Brand → Aceptar carga → Carga completa → Seleccionar aprobada
           → Leer archivo → Analizar input → Cerrar solicitud
```

Siete pasos y **el usuario solo interviene en cuatro**: aceptar la carga,
elegir la solicitud, analizar y cerrar. El resto son transiciones automáticas.

| Paso | Quién lo hace |
|---|---|
| Subir Brand | la marca, en Input comercial |
| Aceptar carga | **1 clic** — el atajo encadena tomar + revisar + aprobar |
| Carga completa | automático: `va_a: carga_completa` lleva a la pantalla |
| Seleccionar aprobada | **1 clic** — ya viene preseleccionada la recién aceptada |
| Leer archivo | automático: se lee el adjunto de la solicitud |
| Analizar input | **1 clic** |
| Cerrar solicitud | **1 clic** |

**El cierre NO puede estar detrás de la casilla de sincronización.**
`_render_acciones_solicitud_tras_carga()` estaba anidado tres niveles: dentro
de `if complete_source == "Shopify API"`, dentro de `if confirm_complete:` y
después del panel de sincronización. Con "Respaldo Excel", o sin marcar la
casilla, no había forma de cerrar la solicitud desde Carga completa y tocaba
volver a la bandeja. Ahora se dibuja una sola vez al terminar el análisis, y
hay un test que compara la sangría y falla si vuelve a quedar dentro del `if`.

**Pero cerrar sigue exigiendo que la carga se haya ejecutado.** La sección se
dibuja apenas termina el análisis, cuando la solicitud todavía está en "Lista
para ejecutar": ofrecer ahí "Completar carga" cerraría una solicitud que nunca
se cargó, que es exactamente el error corregido en agosto de 2026. Por eso hay
una guarda por estado:

- Estados de la cadena de cierre → `render_seguimiento_carga` + la cadena.
- `loading` → los cuatro botones de cierre.
- Cualquier otro → `render_barra_acciones`, que deriva de `engines/ticket_flow`
  lo que se puede hacer. Desde "Lista para ejecutar" eso es **"Ejecutar
  carga"**: el eslabón que faltaba entre analizar y cerrar.

No se escribió una segunda lista de botones: manda el mismo motor que la
bandeja, con sus pruebas.

---

## 5 octies. Vestidos, y por que una carga decia 21 bloqueos sin explicar ninguno (septiembre 2026)

Una carga de Rockford mostraba **una sola** observacion —"Tipo de prenda ·
Bloquea la carga · VESTIDOS"— y abajo "La solicitud no puede enviarse: existen
**21** registros bloqueados". Leido asi, Rockford no aceptaba vestidos. Eran
**tres** fallos distintos, y ninguno era ese.

**1. El diccionario no tenia vestidos.** Ni `vestido`, ni `vestidos`, ni
`dress`: `PRODUCT_TYPE_RULES` tenia 45 tipos y ninguno para la prenda. No era
una restriccion de la marca — `commercial_product_type_rules_for_brand` filtra
por **CATEGORIA**, nunca por tipo, y Rockford admite Vestuario. En cuanto el
tipo existe, lo aceptan las cuatro marcas de vestuario por igual.

Va con `size_guide_group: "TOPS"` explicito. Sin grupo, "vestido" no cae ni en
`bottom_markers` ni en `top_markers` de `resolve_size_guide`, el grupo queda
vacio y las guias de TOPS y BOTTOMS **empatan en prioridad 95**: la elegida
depende del orden de la lista, no del producto. Es el mismo hueco que arrastran
Sweater, Jean, Enterizo y Chaleco Polar del lote de agosto.

`falda` NO se toca: sigue siendo alias de **Short** por decision previa del
diccionario, y moverla es una decision de negocio aparte.

**2. La tarjeta roja era la del campo que no bloquea.** "Tipo de prenda" esta
en `VALIDACIONES_SOLO_AVISO` y **nunca** bloquea, pero la fila del reporte se
guardaba con el estado de la **FILA**, no de la observacion. Una fila bloqueada
por cualquier otra causa pintaba "Bloquea la carga" sobre un campo que solo
avisa. Ahora cada observacion viaja con su propio `bloquea` y el estado sale de
ahi.

**3. Las causas REALES de bloqueo no dejaban rastro.** Campo obligatorio vacio,
`PUBLICAR_*` sin SI/NO, Clase no permitida, Marca cruzada y Fecha invalida solo
escribian en `row_messages` —la columna "Mensaje" de la vista previa— y **no
generaban fila en `report_df`**. El panel "Que hay que revisar" solo sabia de
tipo de prenda, guia de tallas, separadores y descripcion: por eso 21 bloqueos
no se explicaban en ningun lado. Todas pasan ahora por `anotar()`, que escribe
el mensaje **y** la fila del reporte con su accion recomendada.

Ademas: las tarjetas que bloquean se dibujan **primero** (con el orden del
archivo, la unica visible sin bajar podia ser un aviso inofensivo), y el error
final **nombra los campos** que bloquean en vez de solo contar filas.

`scripts/test_tipos_vestido_y_bloqueos.py` (24 pruebas) fija las tres cosas; 20
de ellas fallan con el codigo anterior. Una recorre cada causa de bloqueo y
exige que ninguna fila bloqueada se quede sin explicacion en el reporte.

---

## 6. Ejecutar carga desde una solicitud

`ArchivoDeSolicitud(io.BytesIO)` expone `.name`, `.size` y `.seek()`, que es
todo lo que `read_uploaded_excel_cached()` necesita. Por eso **el motor de
carga no se tocó**: solo cambia el origen del archivo.

En Carga completa hay un selector "Origen del input": usar el archivo de una
solicitud (recuperado con `get_artifact`) o subirlo a mano. La carga manual se
conserva como respaldo para solicitudes viejas sin adjunto.

Hay un test que compara ambas rutas con `pd.testing.assert_frame_equal`, y otro
que verifica que sigue habiendo **un solo** `read_uploaded_excel_cached` y **un
solo** `build_columbia_matrixify`.

---

## 7. Cambios hechos (julio 2026)

| Fase | Qué |
|---|---|
| 0 | CSS a `assets/app.css`, 16 funciones muertas eliminadas (538 líneas) — **descartada** al volver a la base correcta de GitHub |
| A | `engines/audit.py`, `engines/storage_check.py`, panel de almacenamiento, inventario, guía de migración |
| B | Instrumentación automática (20 acciones), pantalla completa de Auditoría |
| C | `engines/ticket_flow.py` (19 → 5 estados) |
| D | Tokens CSS (267 colores → variables), acabado visual, ejecución directa, barra de acciones, términos al español |

**Métricas actuales:** 17.842 líneas · 383 funciones · **134 pruebas** en 7
archivos.

---

## 8. Pendientes

1. **Consolidar las pestañas del detalle.** Resumen / Productos / Archivo y
   validación / Actividad parten información que se lee mejor seguida.
   Reescribir `render_ticket_detail` (332 líneas).
2. **Quitar los botones antiguos de "Gestión interna".** `render_barra_acciones`
   ya cubre el flujo principal, pero conviven con los botones viejos, que
   manejan casos que la barra aún no cubre (observaciones por producto,
   validación previa, reintentos). Hay duplicación.
3. **Partir `main()`** (1.190 líneas) en páginas. Carga completa y carga
   parcial están incrustadas.
4. **Extraer `engines/shopify_sync.py`** y arreglar la inversión de
   `catalog_engine.py`.
5. **Borrar 5 archivos corrompidos de la raíz del repo** (ver sección 10).
6. **Limpiar `engines/normalize.py`, `engines/excel_io.py` y un archivo suelto
   llamado `engines`** que quedaron de la Fase 0 descartada. Nadie los importa.
7. **Rotar las credenciales del código.** `get_auth_users()` tiene un
   diccionario de usuarios y contraseñas como fallback, y está en un repo
   público.

---

## 9. Errores conocidos

**`test_brand_commercial_input.py` falla desde antes de estos cambios.**
Espera hojas `INPUT_COMERCIAL / GUIA / DICCIONARIO`; el código genera
`PARA_COMPLETAR / EJEMPLO / COMO_LLENAR`. El test está desactualizado, no la app.

**`TicketConflictError`.** `GitHubTicketStore.update_ticket` compara el sha del
blob contra `expected_revision`. Cuando el archivo cambió de verdad entre la
lectura y la escritura, salta. Ya no es un callejón sin salida: se muestra como
aviso con botón "Recargar solicitud". Confirmado que las escrituras de
auditoría **no** lo causan (usan el sha del blob, no el del commit).

**`IndexError: At least one sheet must be visible`.** openpyxl al guardar un
libro sin hojas. Se corrigió en `dataframe_to_excel_bytes` escribiendo una hoja
"Sin datos" cuando el diccionario llega vacío.

**Siblings: el tipo del metacampo lo manda la TIENDA, no el código.**
`theme.siblings` casi nunca tiene definición en Shopify: el tipo se le fija con
la primera escritura y después rechaza cualquier otro. Ni `engines/catalog_map`
ni la cabecera de Matrixify pueden saber cuál quedó. Por eso el mismo metacampo
entraba por un camino y fallaba por otro.

- La carga parcial mandaba `theme.siblings` y `custom.siblings` en la **misma**
  llamada a `metafieldsSet`. La mutación es todo o nada: un solo tipo que no
  coincidiera dejaba los **dos** sin escribir y la fila en ERROR.
- Ahora cada metacampo va en su propia llamada, con el tipo de la definición de
  la tienda, y si Shopify lo rechaza por tipo se lee el que exige del propio
  mensaje de error y se reintenta **una** vez. El tipo aceptado se recuerda por
  sesión (`_tipo_metafield_recordado`), así que el resto del grupo va directo.
- Los valores se eligen según el tipo que se termine usando: `gid://` para
  referencia, handles para texto. Mandar unos donde van los otros era la otra
  mitad del error.
- Un error que **no** habla de tipos (permisos, red) no se reintenta.
- La vista previa compara **conjuntos**, no texto: Shopify devuelve el JSON sin
  espacios y `json.dumps` lo escribe con `", "`. Comparando texto crudo, cada
  análisis proponía reescribir el catálogo entero aunque ya estuviera correcto.

**`apply_shopify_preview` usaba `brand_config`, que no recibe.** La rama de
tecnologías de la carga parcial levantaba `NameError` y dejaba la fila en ERROR
sin haber intentado escribir. El tipo y los logos se leen ahora de la propia
vista previa, que ya los trae.

**`inotify watch limit reached`** en Streamlit Cloud. Se resuelve con
`fileWatcherType = "none"` en `.streamlit/config.toml`.

**Dos `normalize_size` distintas conviven** — `engines/normalize.py` (Fase 0,
sin usar) y `generate_columbia_matrixify.py`. Difieren en 15 de 27 casos: la
segunda convierte tallas de calzado (`85` → `8.5`, `400` → `40`). Los datos
reales de ARTI (`TALNUM_MA`) vienen en formato ×10. **No unificar** sin decidir
antes qué flujo usa cuál.

---

## 10. Archivos corrompidos en el repositorio

Verificado por firma binaria. No los usa nadie; la app lee los originales de
`data/`.

| Ruta | Contenido real |
|---|---|
| `config.toml` (raíz) | JavaScript de `generate_catalog_input_template.mjs` |
| `download` | copia del `.gitignore` |
| `dimensiones_productos.xlsx` (raíz) | imagen WEBP |
| `matrixify_modelo.xlsx` (raíz) | imagen WEBP |
| `formato_input_catalog_control_center.xlsx` | texto plano |
| `assets/logo_*` (los 9 de la raíz) | el logo de la marca **anterior**; `logo_columbia.png` son 2 bytes |

Los `assets/logo_*` de la raíz están **corridos una posición** (verificado
abriendo las imágenes: `assets/logo_vans.jpg` es el logo de Sorel). La app no
los usa — lee de `assets/brands/`, donde los nueve son correctos. Ver la
sección 5 septies.

Históricamente, `.streamlit/config.toml` llegó a tener pegado el contenido de
`secrets.example.toml` (commit `542c3757`). Eso hacía que Streamlit rechazara
cada clave como "not a valid config option" y dejaba `st.secrets` vacío.
**Nunca pegar secretos en `config.toml`.**

---

## 11. Secretos

Van en Streamlit Cloud → Manage app → Settings → Secrets. Plantilla en
`.streamlit/secrets.example.toml`.

Secciones: `[bigquery]`, `[gcp_service_account]`, `[app_auth]`,
`[app_auth.users]`, `[app_auth.roles]`, `[shopify_sites.*]`, `[ticketing]`.

GitHub Actions usa sus propios secretos (Settings → Secrets → Actions):
`COLUMBIA_SHOP_DOMAIN`, `*_ADMIN_API_ACCESS_TOKEN`, `BIGQUERY_*`.

---

## 12. Cómo validar antes de entregar

```bash
python scripts/test_brand_commercial_input.py          # 6
python scripts/test_carga_desde_solicitud.py           # 28
python scripts/test_engines_audit.py                   # 45
python scripts/test_engines_metrics.py                 # 26
python scripts/test_engines_notify.py                  # 88
python scripts/test_engines_price_check.py             # 19
python scripts/test_engines_stock.py                   # 35
python scripts/test_engines_ticket_flow.py             # 55
python scripts/test_engines_load_status.py             # 37
python scripts/test_engines_video_media.py             # 106
python scripts/test_css_movil.py                       # 33
python scripts/test_rendimiento.py                     # 20
python scripts/test_bandeja_solicitudes.py             # 57
python scripts/test_partial_maintenance_validations.py # 6
python scripts/test_siblings_carga_completa.py         # 24
python scripts/test_siblings_referencias.py            # 14
python scripts/test_siblings_tipos.py                  # 20
python scripts/test_ticket_system.py                   # 28
python scripts/test_tipos_vestido_y_bloqueos.py       # 24
```

> `test_brand_commercial_input.py` y `test_auth_accesos.py` fallan desde antes
> de estos cambios. El segundo espera `auth_role_label`, que ya no existe.

Además, siempre:

- **Diff por AST** contra el commit base: cuántas funciones se agregaron,
  eliminaron y modificaron, y cuántas quedaron idénticas byte a byte.
- **Interpolaciones del f-string del CSS**: solo deben aparecer
  `config['primary_color']`, `config['accent_color']`, `site_logo_css`,
  `site_logo_src`, `site_label_css`. Cualquier otra significa llaves sin doblar.
- **Funciones sin llamador**: cero.
- **AppTest por sección** (KPIs, Input comercial, Solicitudes, Carga de
  catálogo, Auditoría) mirando `at.error`, no solo `at.exception`.
- **Arranque headless** de Streamlit, esperando HTTP 200.

---

## 13. Tono de trabajo con este usuario

Trabaja en español. Prefiere entregas completas y ya aplicadas en el
repositorio, no fragmentos para copiar ni ZIP para subir a mano (ver regla 6).
Valora que se le diga con claridad qué no se hizo y por qué, y que se distinga
un fallo propio de uno preexistente.

**El trabajo no está terminado hasta que está en GitHub.** No basta con dejarlo
en una rama o en un PR abierto: la app se despliega desde `main`, así que
mientras el cambio no esté mergeado el usuario redespliega y **no ve nada**.
Ya pasó con el Mantenedor de Videos: el PR quedó abierto esperando confirmación,
él actualizó la app y el módulo no aparecía. Entregar = commit + push + PR
mergeado a `main`, y decírselo.

Cuando pida algo que parezca arriesgado, hay que decírselo — pero si lo
reafirma, se hace.
