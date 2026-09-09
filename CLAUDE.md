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

5. **Ningún archivo del usuario se carga entero en memoria.** Se recorre en
   streaming y solo se conserva lo que se va a usar. Un lector nuevo se prueba
   con un archivo del TAMAÑO REAL, nunca con una muestra: en septiembre de 2026
   un lector probado con 500 filas pedía 2 GB con el archivo de verdad y tumbó
   la app. Streamlit Cloud da 1 GB **por app, no por usuario**. Lo vigila
   `scripts/test_memoria.py`.

6. **Nunca dejes una función sin llamador.** Ya pasó dos veces: se definió un
   panel y nunca se invocó. Verifica con AST antes de entregar.

7. **Se entrega por GitHub, no en ZIP.** Desde septiembre de 2026 el agente
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

Sitios: Columbia.pe · Rockford.pe · HushPuppies.pe · Vans.pe · Patagonia.pe y
**Supermall.pe**, que es el sitio ESPEJO y lleva el catálogo de todos (Sorel en
configuración). Cada uno con su vendor, marcas permitidas y colores.

Fuentes de datos: **BigQuery** (maestro ARTI y stock), **Shopify Admin API**
(catálogo actual), y respaldos Excel en `data/`.

---

## 2. Arquitectura

```
app_matrixify.py        25.6xx lineas · 595 funciones · UI + routing + logica
├── engines/            motores sin Streamlit, testeables
│   ├── audit.py        535 lin · auditoria (2 backends, 45 pruebas)
│   ├── notify.py       700 lin · correo transaccional (80 pruebas)
│   ├── stock.py        215 lin · stock por Mod-Col (35 pruebas)
│   ├── metrics.py      190 lin · metricas por Mod-Col (26 pruebas)
│   ├── price_check.py  200 lin · validacion precio/stock (19 pruebas)
│   ├── ticket_flow.py  562 lin · 23 estados -> 5 visibles (55 pruebas)
│   ├── load_status.py   diagnostico de carga de todos los sitios (37 pruebas)
│   ├── espejo_supermall.py  que le falta al espejo (35 pruebas)
│   ├── colecciones.py  colecciones por marca segun los tags (54 pruebas)
│   ├── garment_types.py  el UNICO diccionario de tipos (60 tipos, 523 nombres)
│   ├── orden_tallas.py  orden y escala de las tallas (34 pruebas)
│   ├── tallas_calzado.py conversion US -> PE con la guia oficial de Vans
│   └── storage_check.py 176 lin · diagnostico de persistencia
├── ticket_system.py    1.093 lin · maquina de estados, 2 stores, 28 pruebas
├── generate_columbia_matrixify.py  3.319 lin · motor de catalogo
├── shopify_api.py      2.382 lin · GraphQL Admin API (lectura masiva + paginada)
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

## 5 sexies bis. La carga manual a VTEX se retiró (septiembre 2026)

Supermall dejó VTEX y pasó a Shopify, así que la pantalla que armaba las cuatro
planillas para subirlas a mano dejó de tener sentido. Se borró entera:
`engines/vtex_catalog.py` (1.783 líneas), sus 90 pruebas, `docs/CARGA_VTEX.md`,
`data/vtex_diccionario_supermallpe.json` y las 1.000 líneas de pantalla que
vivían en `app_matrixify.py`.

Medido: el import de la app pasó de **0,72 s y 146 MB** a **0,57 s y 131 MB**.

Lo que **no** se tocó: las columnas `Sku - Supermall.pe` y
`Porduct Id - Supermall.pe` de la hoja **Carga Sial** siguen igual. Esas son del
Excel operativo que se manda, no de VTEX, y las sigue necesitando quien recibe
la carga.

Si Supermall vuelve a necesitar carga por planilla, esto está en el historial de
git; pero con Supermall en Shopify el camino es el normal de la app —un sitio
más en `SITE_CONFIGS`— y no una pantalla aparte.

---

## 5 sexies ter. Carga Sial por codigos Modelo-Color (septiembre 2026)

`build_sial_de_sitio_from_matrixify` + una opcion mas en Carga parcial,
**"Carga Sial"**, al lado de Centry. Se sube un Excel con codigos Modelo-Color
y devuelve la hoja Carga Sial lista para enviar. Nada mas: no escribe en
Shopify, hay un test que falla si aparece cualquier mutacion en la rama.

**Por que.** El Centry ya se pedia asi -codigos y Excel de vuelta- pero la
Carga Sial solo salia de una **carga completa**, que exige el input comercial
entero. Para diez modelos sueltos eso es armar toda la carga para llegar a una
hoja.

**Sale en el formato DEL SITIO, no en el de Centry.** El Excel de Centry ya
traia una hoja "Carga Sial", pero es la de Centry: cabecera `Mod/Col/Tal` y una
cola con `Nuevo o Actualizar (Rockford.pe)` y Supermall **escritos a mano**, o
sea la hoja equivocada en cuatro de los cinco sitios. La nueva usa
`get_sial_columns(brand_config)` y `sial_tail_row`, las mismas de la carga
completa, asi que Columbia recibe su cola y sus bodegas `4/13/6`, Vans la `103`
y Hush Puppies la `2/13`.

**Las dos hojas comparten el cuerpo.** Las 40 columnas del medio son identicas,
asi que se arman una sola vez en `_filas_sial_desde_matrixify`, que entrega
`(identidad, cuerpo)` por fila: la identidad es lo unico que cambia entre
formatos. Con dos funciones completas, el arreglo siguiente entra en una hoja y
se olvida en la otra -- es lo que ya pasa con las dos `normalize_size`. La cola
tambien se saco de `build_sial_row` a `sial_tail_row` por lo mismo: un sitio
nuevo se agrega en un solo lugar. Hay pruebas que comparan las dos hojas columna
a columna y que exigen que las dos llamen al nucleo.

**"Crear" o "Actualizar" es un dato de Shopify, no del Excel.** Un producto que
ya esta en la tienda sale como `Actualizar` con su `Porduct Id` en la columna de
**su** tienda; uno que no esta, como `Crear`. Por eso la opcion **exige Shopify
API** (con Respaldo Excel se corta con un aviso) y por eso el ID del producto
viaja ahora en el Matrixify que arma `build_centry_matrixify_from_master`: no es
columna Matrixify, viaja solo para esto.

**El tramo comun no esta escrito dos veces.** Centry y Carga Sial cruzan lo
mismo -- Shopify + BigQuery/ARTI para una lista de codigos -- y ese tramo es
`matrixify_desde_codigos_modelo_color`. Hay un test que exige que
`build_centry_matrixify_from_master` se llame en **un solo** lugar.

**Los codigos que no dejaron ninguna fila se avisan** (`sial_codigos_sin_filas`).
Pedir 50 y recibir 38 se ve igual de bien que recibir los 50 si nadie dice
cuales faltan. Un codigo de solo modelo cuenta como presente si salio cualquiera
de sus colores. El detalle -- codigo que no esta en el maestro, marca que el
sitio no carga, tallas descartadas -- va en la hoja **Revision Carga Sial**, la
misma que ya arma el Centry.

`scripts/test_carga_sial_parcial.py` (28 pruebas) fija todo esto.

---

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

## 5 nonies. Memoria: 1 GB por APP, no por usuario (septiembre 2026)

En septiembre de 2026 la app se cayó con *"Your app has gone over its resource
limits. It's using too much memory!"*. **Streamlit Community Cloud da 1 GB por
aplicación, no por sesión**: dos personas cargando a la vez comparten el mismo
contenedor. Cuando se pasa, el proceso muere sin traza y sin decir de qué.

No lo atrapó ninguna de las ~600 pruebas del repo, porque **ninguna miraba la
memoria**. `test_rendimiento.py` mide bytes por rerun, que es otra cosa.

Lo medido, y lo que se hizo con cada cosa:

| Qué | Antes | Ahora |
|---|---:|---:|
| DataFrames vivos tras una Carga completa | ~1.200 MB | **237 MB** |
| Importar la app (antes de que entre nadie) | 251 MB · 6,1 s | 180 MB · 0,7 s |

El lector del maestro de VTEX era el peor de los tres casos: hacía
`list(filas)` antes de indexar y pedía más de 2 GB con un archivo real. Ese
motor se retiró en septiembre de 2026 (sección 5 sexies bis), pero es de donde
sale la regla: **pasó las 62 pruebas del motor porque se probó con una muestra
de 500 filas**.

**`CENTRY_COLUMNS` se calculaba en tiempo de import.** Leía
`data/plantilla_centry_productos.xlsx` en CADA arranque solo para sacar los
nombres de columna: 5,5 s y ~35 MB, se usara Centry o no. Ahora es
`centry_columns()`, perezoso y memoizado. `app_matrixify.CENTRY_COLUMNS` sigue
existiendo con un `__getattr__` de módulo (PEP 562) para quien lo lea de fuera;
**los usos de dentro llaman a la función**, porque una búsqueda de global NO
pasa por `__getattr__`.

**Cuatro DataFrames de Carga completa salen de `session_state`.** Medido en una
carga de 40.000 filas: el respaldo del catálogo (330 MB), el maestro ARTI
(167 MB), el Centry (277 MB) y el Sial (191 MB). Quedaban residentes toda la
sesión aunque nadie los estuviera usando.

| Qué | Dónde vive ahora | Por qué |
|---|---|---|
| Respaldo del catálogo · ARTI | disco (`outputs/sesion/*.pkl`) | solo sirven para reanalizar sin volver a leer Shopify y BigQuery |
| Sial | disco + 100 filas y dos conteos en sesión | se necesita ENTERO en un solo momento: el adjunto del cierre |
| Centry | resumen en sesión, nada más | solo se usa para dibujar su pestaña |
| Matrixify | **se queda** (224 MB) | lo necesita la sincronización con Shopify |

Lo que queda vivo son **237 MB**; con los 180 del arranque, 417 MB de 1.024, o
sea sitio para dos o tres personas a la vez. La primera versión de este arreglo
dejaba 731 MB y se publicó como "430 MB", que era una cuenta mal hecha.

**El Centry es el caso interesante.** `render_centry_preview` se dibuja dentro
de una pestaña, y Streamlit ejecuta el contenido de TODAS las pestañas en cada
rerun: para sacar sus números recorría el Centry entero, así que el DataFrame
tenía que seguir vivo. Ahora `resumen_centry_para_pantalla` calcula los siete
números UNA vez, al analizar, y en sesión queda eso más 120 filas de muestra.
Mismos números en pantalla, tres órdenes de magnitud menos de memoria.

**Del Sial se guardan los CONTEOS aparte** (`complete_sial_filas`,
`complete_sial_modelos`), porque el panel de cierre los dibuja en cada rerun y
leer 191 MB de disco para contar filas es peor que el problema original.

**Si el disco no es escribible, todo se queda en la sesión.** Cuesta memoria,
pero perder el respaldo del catálogo obliga a releer Shopify y BigQuery en cada
clic, y perder el Sial deja el correo al Área de Producto **sin adjunto**, que
es el error de agosto de 2026. La corrección manda sobre el ahorro.

Los `.pkl` **se borran al limpiar**: si no, cada carga deja otro de cientos de
MB en el contenedor.

**Cuidado con lo que se lee en cada rerun.** El primer intento de este arreglo
dejó la condición que decide si hay datos cargados (`data_ready`) LEYENDO los
dos temporales de disco. Esa condición se evalúa en cada clic: eran 500 MB de
disco por interacción y, si la escritura había fallado, el `else` volvía a leer
Shopify y BigQuery. Se sintió como "no carga y está lentísimo", y fue una
regresión de un día. Ahora la condición solo comprueba que los archivos ESTÉN,
y los DataFrames se leen únicamente dentro del análisis. Hay cinco pruebas que
lo fijan.

**`render_centry_preview` hacía `centry_df.copy()`** y ahí solo se lee. Eran
277 MB duplicados en cada rerun que dibujara esa pestaña.

**`sys.getsizeof` de un DataFrame miente**: devuelve el tamaño del envoltorio, y
un df de 250 MB reportaba 130 bytes. Hay que usar `memory_usage(deep=True)`. El
panel de memoria (Auditoría → "Memoria de la app") lo usa para decir qué se está
comiendo la RAM, y `memoria_del_proceso()` lee `/proc/self/statm`, que en Linux
es exacto y no necesita `psutil`.

### La regla, y lo que la hace cumplir

> Ningún archivo del usuario se materializa entero en memoria: se recorre en
> streaming y solo se conserva lo que se va a usar.
> Un lector nuevo se prueba con un archivo del **tamaño real**, nunca con una
> muestra.

`scripts/test_memoria.py` (10 pruebas) es lo que impide que esto vuelva. Genera
un maestro sintético de 300.000 filas, corre cada medición **en un subproceso**
—el pico de RSS es del proceso entero, medir varias cosas en el mismo intérprete
las mezclaría— y falla si se pasa del presupuesto: 220 MB el import, 300 MB leer
el maestro. Una de las pruebas comprueba que guardar el maestro **sin** acotar
sigue siendo caro: si eso deja de serlo, la prueba ya no está midiendo nada.

**Lo que NO se hizo, y por qué.** Mover el trabajo pesado a `sync_worker.py` /
`api_main.py` (que ya están en Render) es la solución de fondo: Streamlit
reejecuta el script en cada clic y un catálogo de 300.000 SKUs nunca va a estar
cómodo en `session_state`. Es un proyecto de varios días y está anotado en
Pendientes, no descartado.

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

## 5 decies. La lectura del catálogo de Shopify (septiembre 2026)

La queja era literal: *"antes ponía a cargar en Vans 1000 productos y sí me
dejó, cargó todo; ahora ni termina de leerlo"*. No estaba roto: estaba pagando
el **costo de consulta** de Shopify.

`fetch_products` pedía 250 productos por página, cada uno con
`variants(first: 100)` y `media(first: 10)`. Eso a Shopify le cuesta unos **430
puntos por producto** —una variante son cuatro objetos (la variante, sus
`selectedOptions`, su `image` y su `inventoryItem`)— y el **máximo de una sola
consulta son 1.000 puntos**. Con esa consulta la única forma de que entre es
bajar `products_page_size` a dos o tres productos; y entonces un catálogo de
3.000 productos son **mil viajes**, cada uno pagando además espera de balde: el
balde se recarga a 50 puntos por segundo. Son horas.

**Ahora la lectura normal es una bulk operation.** No paga costo por consulta:
se le entrega la consulta a Shopify, la corre de su lado y deja el catálogo
entero en un JSONL. Un catálogo que tardaba horas se lee en minutos.

Lo que hay que saber para no romperlo:

- **Los campos se escriben UNA vez** (`CAMPOS_PRODUCTO`, `CAMPOS_MEDIA`,
  `CAMPOS_VARIANTE`) y los usan las dos lecturas. Si una trajera un campo que
  la otra no, el catálogo cambiaría según por dónde se leyó — es exactamente lo
  que ya se paga con las dos `normalize_size`. Hay un test que lo fija.
- **Una bulk operation no admite variables ni argumentos de paginación.** Nada
  de `first:`, `after:` ni `$publicationId`: el id de la publicación va escrito
  DENTRO de la consulta. Hay un test que falla si vuelve a aparecer alguno.
- **El JSONL trae una línea por objeto.** Las variantes y las fotos vienen
  aparte con `__parentId`, y hay que volver a armarlas. **No se asume que el
  hijo venga después del padre**: se guardan aparte y se cuelgan al final.
- **El archivo va a DISCO, no a memoria**, y el reensamblado va soltando los
  nodos (`productos.pop`) a medida que arma los registros: sin eso el catálogo
  queda dos veces en RAM, y son cientos de MB. Es la regla de la sección 5
  nonies.
- **La paginada sigue existiendo, de respaldo.** Shopify admite **una sola**
  bulk operation por app y tienda a la vez: si dos personas leen el mismo sitio
  a la vez, la segunda no puede quedarse sin catálogo. Cualquier fallo de la
  masiva —ya hay una corriendo, la tienda la rechaza, el token no la permite—
  cae a la paginada y lo dice. Se puede apagar del todo con
  `bulk_products = "no"` en Secrets.
- **`variants_page_size` es nuevo** y solo afecta a la paginada. Por defecto
  sigue pidiendo 100 variantes, o sea que el respaldo es exactamente lo de
  antes.

**El catálogo se guarda en DISCO, no solo en la sesión.** Antes vivía únicamente
en `st.session_state`: un reinicio del contenedor, o una persona nueva, volvían
a pagar la lectura entera. Ahora `outputs/sesion/catalogo_<sitio>.pkl` la
conserva 2 horas. Se descarta solo si es de otra tienda o de otra versión de la
API —devolver el catálogo de Rockford cuando se pidió el de Vans sería peor que
no tener caché, porque es el dato que decide si un producto se **crea** o se
**actualiza**.

Y por eso mismo **la caché se ve**: `render_catalogo_leido` dice cuándo se leyó
y trae al lado el botón **"Volver a leer"**, que borra la de sesión **y la de
disco**. Una caché invisible sobre el dato que decide crear/actualizar es una
trampa.

**La lectura ahora cuenta por dónde va.** Un spinner mudo durante minutos se lee
como "se colgó". El aviso sale del propio motor (`progreso`), que es el que sabe
si está esperando a que Shopify prepare la lectura o bajando páginas; la
pantalla solo lo dibuja. El aviso **nunca** puede tumbar la lectura: va dentro
de `_avisar`, con su `try`.

`scripts/test_lectura_catalogo.py` (27 pruebas) fija todo esto, con un Shopify
falso: no sale a la red.

---

## 5 undecies. Supermall.pe: el sitio espejo (septiembre 2026)

`engines/espejo_supermall.py` (sin Streamlit ni pandas) + la pestaña **"Espejo
de Supermall"** dentro de Status de carga + el botón **"Preparar esta carga
para Supermall.pe"** al final de Carga completa.

Supermall dejó VTEX y pasó a Shopify (sección 5 sexies bis), y **lleva el
catálogo de TODOS los sitios**, no el de una marca. O sea: es Rockford.pe
llevado al extremo, y el modelo de la app ya servía — un sitio más en
`SITE_CONFIGS`.

**Sus marcas NO están escritas a mano.** Son la unión de las de todos los demás
sitios, calculada justo debajo de `SITE_CONFIGS`. Con una lista fija, una marca
nueva en cualquier sitio se cargaría ahí y Supermall la rechazaría por "marca no
permitida" hasta que alguien se acordara de venir a este archivo. Supermall
existe justo para no depender de que alguien se acuerde.

**No recibe input comercial.** `sites_for_commercial_brand` salta los sitios con
`es_espejo`: si entrara, la plantilla del input le pondría a cada marca una
columna `PUBLICAR_SUPERMALL_PE` que no decide nada, y una casilla que no hace
nada es peor que no tenerla.

### El espejo: la resta, no la costumbre

Mantener Supermall al día "acordándose de cargar también allí" falla el día que
alguien tiene prisa, y nadie se entera hasta que un producto lleva meses sin
salir. La pestaña responde por la resta:

```
lo que hay en cualquier sitio  -  lo que hay en Supermall  =  lo que falta
```

- **Vive DENTRO de Status de carga**, no en pantalla propia. Es la única
  pantalla que ya tiene todos los sitios leídos (sección 5 quater); darle
  pantalla propia costaría leer los seis otra vez.
- **No vuelve a escribir cómo se lee un producto de Shopify.** La marca, el
  estado web y sobre todo la identidad salen de `engines/load_status`. Dos
  lectores del mismo producto se separan sin que nadie lo note.
- **Se cuenta por `clave_de_producto`**, igual que el Status de carga: con
  `set()` sobre el Mod-Col, todos los productos sin metacampo comparten la
  cadena vacía y el conjunto los colapsa en uno.
- **Cargado no es lo mismo que visible.** Lo que está en Supermall pero en
  borrador o sin publicar sale como "Cargados sin publicar" y **no** entra en la
  lista de códigos a cargar: recargarlo le reescribiría la ficha sin que nadie
  lo pida. Eso se publica, no se carga.
- **Un producto sin código Modelo-Color no se puede espejar por código** y se
  cuenta aparte. La carga se pide por lista de códigos y el suyo no existe;
  mezclarlo con "falta" dejaría la lista con huecos que nadie explica.
- **Destino ausente ≠ destino vacío.** Si el catálogo de Supermall no se pudo
  leer, todo saldría como "falta" y eso se leería como "hay que cargar el
  catálogo entero". Con el destino sin leer la pestaña avisa y no compara.
- Un producto que está en tres sitios cuenta **una** vez, y la fila dice en
  cuáles está.

### El segundo destino: dos pasadas, no una escritura doble

Al terminar una Carga completa aparece **"Preparar esta carga para
Supermall.pe"**: cambia el sitio activo y deja la **misma solicitud** ya elegida
en el selector de Carga completa. Es el mismo mecanismo de `ir_a_carga_completa`
que ya se usa después de "Aceptar carga".

**Son dos pasadas encadenadas y eso es a propósito.** Cada pasada arma su PROPIO
Matrixify, porque el catálogo contra el que se decide *crear* o *actualizar* es
el de la tienda destino y los `Product Id` de Vans.pe no valen en Supermall.pe.
Tener los dos vivos a la vez son ~450 MB medidos de los 1.024 que Streamlit
Cloud da **por app** (sección 5 nonies): con dos personas cargando, el
contenedor se muere. Encadenadas solo hay un Matrixify vivo cada vez. Hay un
test que falla si aparece un `build_columbia_matrixify` dentro de esa función.

**Es la misma solicitud, no una copia.** `_ticket_matches_active_site` deja pasar
las solicitudes de cualquier sitio cuando el destino es el espejo. Sin eso
habría que duplicar el ticket, y serían dos tickets para una sola decisión.

**El cambio de sitio va por `site_picker_pendiente`.** Escribir `site_picker`
después de que el `selectbox` existe levanta `StreamlitAPIException`, y el botón
vive en el área principal, que se dibuja **después** de la barra lateral. La
barra lo consume justo antes de instanciar el selector. Hay un test que
comprueba el orden.

### Lo que hay que confirmar todavía

Tres datos de negocio que el código deja configurables y con un valor por
defecto razonable, pero que nadie ha confirmado:

1. **La bodega SIAL** (`sial_active_columns`). Quedó en `"13"`, que es la que
   comparten cuatro de los cinco sitios. Si Supermall despacha desde otra, se
   cambia ahí y ya.
2. **Las tallas de calzado.** Vans.pe publica en tallas PE con
   `tallas_calzado_pe`; Supermall quedó **sin** la bandera, o sea en tallas de
   origen. Es una bandera de SITIO, no de marca, así que hoy no se puede tener
   Vans en PE y el resto en origen dentro del mismo sitio.
3. **El logo.** No hay `assets/brands/logo_supermall.png`; hasta que lo haya, la
   barra lateral dibuja la insignia de dos letras.

Y un fallo **preexistente** que Supermall hace más visible: `sial_tail_row` pone
"Crear"/"Actualizar" en TODAS las columnas `Nuevo o Actualizar (...)` con el
`existing_id` del sitio que se está cargando. O sea que en una carga de Vans, la
columna de Supermall dice "Actualizar" si el producto existe en **Vans**. Ya era
así para Columbia; no se tocó aquí porque cambiarlo afecta la hoja de los cinco
sitios y es una decisión de negocio.

`scripts/test_espejo_supermall.py` (35 pruebas) fija todo esto.

---

## 5 duodecies. Mantenedor de Tallas: orden y escala (septiembre 2026)

`engines/orden_tallas.py` (sin Streamlit ni pandas) + `render_mantenedor_tallas()`.
Entra como **una opción más de Carga parcial**, al lado del Mantenedor de Videos.

Dos cosas que se ven en la ficha y que **solo se arreglaban al CREAR** el
producto, o sea nunca para el catálogo que ya está cargado:

1. **El orden.** Una curva ampliada después deja la 44 entre la 38 y la 39. La
   Carga completa ordena al crear (`_reorder_product_sizes`), pero nadie vuelve
   a mirarlo.
2. **La escala.** Vans entrega el calzado en **US** y la tienda lo publica en
   **PE/EU** (41, 42...). Lo cargado antes de esa regla sigue diciendo "8".

### El fallo que destapó: las medias tallas quedaban al final

`size_sort_key` miraba `SIZE_ORDER` ANTES que el número. Como esa tabla **no
tiene medias tallas**, las conocidas caían en el grupo 0 y las medias en el 1,
que va detrás: una curva de calzado PE quedaba

```
36, 39, 42, 38.5, 40.5, 44.5
```

Ordenar los números por su valor no pierde nada, porque `SIZE_ORDER` ya tenía el
mismo número en dos escalas (el "40" de vestuario y el "40" europeo) y cuál
ganaba dependía de cuál se asignara último. Las de letra siguen saliendo por su
escala. Hay dos pruebas que lo fijan, y una que exige que los dos criterios de
orden de la app coincidan en los números.

### Lo que hay que saber para no romperlo

- **El análisis es GRATIS y no escribe nada.** Sale del catálogo que la app ya
  tiene leído (`fetch_products` trae las variantes en su orden y con sus
  opciones), así que revisar el sitio entero no cuesta un viaje extra. Los
  viajes se pagan solo por lo que hay que arreglar. Hay un test que falla si
  aparece cualquier mutación dentro del análisis.
- **Antes de escribir se RELEE el producto** y se replanifica sobre eso. El plan
  salió del catálogo cacheado y entre el análisis y el arreglo alguien pudo
  tocarlo; escribir sobre una lectura vieja es como se duplican productos. Si al
  releerlo ya estaba bien, no se escribe nada.
- **Primero renombrar, después ordenar.** Ordenar primero dejaría las etiquetas
  nuevas en las posiciones viejas. Hay un test que compara las posiciones.
- **El orden se VERIFICA releyendo.** Quedar mal ordenado sin que nadie lo diga
  es el peor error silencioso — el mismo criterio que el video en la posición 2.
- **Se renombra el VALOR de la opción** (`product_option_update`), no la opción
  de cada variante. Un solo cambio alcanza a todas las variantes que lo usan;
  variante por variante dejaría dos con el mismo valor a medio camino y Shopify
  rechaza el duplicado. No toca SKU, precios ni inventario.
- **Dos tallas que caen en la misma PE no se renombran.** Serían dos valores
  iguales en la misma opción. No se elige cuál sobra: se avisa.
- **Un producto con más de una opción (Talla y Color) NO se reordena.** Las
  variantes van en matriz y reordenarlas solo por talla las mezclaría. La
  escala sí se cambia, que es un renombre y no mueve nada de sitio.
- **El motor no trae su propia tabla ni su propio criterio de orden**: los dos
  se le **inyectan**, para que sean exactamente los mismos que usa la Carga
  completa (`master_size_sort_key` y `engines/tallas_calzado`). Un segundo
  criterio se separa del primero sin que nadie lo note.
- Se procesa **por bloques** de 10 con `png_bloques`, la misma de fotos y
  videos, y se guarda dentro del bucle.

### La escala va por MARCA, no por sitio

`tallas_calzado_pe` es una bandera del SITIO, y alcanzaba mientras Vans vivía
solo en Vans.pe. Con **Supermall.pe** —que lleva Vans, Columbia y Hush Puppies
en la misma tienda— una bandera de sitio convertiría todo el calzado del sitio o
nada. El mantenedor decide con `orden_tallas.MARCAS_TALLA_PE`, y solo sobre
**calzado**: en vestuario una talla "12" es de niño, no un US 12.

**La carga sigue usando la bandera de sitio.** No se cambió porque
`display_size_for_site` no recibe la marca y pasársela toca a todos sus
llamadores. En la práctica no hace falta: se carga y después se pasa el
mantenedor, que es justamente para lo que existe. Queda anotado en Pendientes.

`scripts/test_mantenedor_tallas.py` (34 pruebas) fija todo esto, incluida la
conversión contra la guía oficial de Vans.

---

## 5 terdecies. La pantalla duplicada, y el analisis 2,4 veces mas rapido (septiembre 2026)

### La pantalla se dibujaba dos veces

Al pulsar **Analizar input** aparecia media pantalla DUPLICADA: la vista previa,
el panel de accion y el checklist otra vez debajo, la copia vieja en gris,
durante todo el analisis.

**Regresion mia**, del aviso de progreso de la lectura del catalogo.
`leer_catalogo_del_sitio` creaba su propio `st.empty()`, y esa funcion solo se
llama en la rama que LEE. O sea: el hueco existia en unos reruns y no en otros.
Eso cambia la **forma del arbol de elementos** entre un rerun y el siguiente:
Streamlit deja de poder reemplazar el bloque de abajo en su sitio y lo **agrega**
debajo del viejo.

Reproducido con Chromium sobre un repro minimo de 20 lineas —una rama que crea
un `st.empty()`, un bloque de columnas y un trabajo lento—:

```
hueco creado DENTRO de la rama:  el bloque aparece 2 veces durante el trabajo
hueco creado SIEMPRE:            1 vez
```

Un `st.empty()` **vaciado sigue ocupando su nodo** en el arbol: `.empty()` borra
el contenido, no el hueco.

Ahora el hueco lo crea el LLAMADOR, antes de decidir si toca leer, y se le pasa.
Sin `aviso` no se dibuja avance, pero **nunca** se crea un hueco condicional.
Hay tres pruebas que lo fijan, una de ellas comparando la sangria para que el
hueco no vuelva a caer dentro de una rama.

> Regla general: **no crees elementos de Streamlit dentro de una rama que no se
> ejecuta siempre, si despues hay contenido que tarda.** No falla, se duplica.

### El analisis: 79 s a 33 s, con la misma salida

Medido con cProfile sobre 1.000 productos, 10.000 filas de ARTI y un catalogo de
33.000 filas. Lo que quedaba despues del arreglo del bucle cuadratico:

| | |
|---|---:|
| antes | **79,1 s** |
| el catalogo se corta una vez, no una por producto | 63,5 s |
| el bucle recorre dicts y no `Series` | 38,2 s |
| el indice acotado a lo que la carga usa | **32,6 s** |

Las tres cosas, y por que:

1. **`filas_por_handle`**: el catalogo pasa a `{handle: [fila como dict]}` en UNA
   pasada. Antes cada producto hacia `matrixify_df.loc[lista]`, y pandas
   reindexa las 107 columnas y las materializa: mil cortes.
2. **El bucle recorre dicts.** `iterrows()` crea un `Series` por fila y entonces
   **cada `.get()` pasa por el indice de pandas**: en el perfil eran 1,58
   millones de accesos y 20 segundos. Igual el maestro ARTI, que ademas se
   barria entero (`arti[arti["__KEY"] == key]`) una vez por producto.
3. **`claves_de_fila`**: varias funciones leian las columnas de la fila con
   `getattr(row, "index")`. Con un dict eso devuelve `[]` **sin fallar**, o sea
   que el respaldo por nombre normalizado dejaba de encontrar la columna y el
   campo salia vacio. Es el peor tipo de error, el que no revienta. Hay una
   prueba que exige que "Descripción " se encuentre pidiendo "Descripcion", en
   `Series` y en dict.

**La salida es IDENTICA.** Comparadas las 6 hojas (Matrixify, resumen,
observaciones, tipos nuevos, omitidos y Sial) en tres sitios, antes y despues:
misma forma y mismos valores.

**Y no se pago con memoria.** Guardar el catalogo entero como dicts costaba
**82 MB** medidos para un catalogo de 28 MB, y eso crece con la tienda mientras
el contenedor sigue dando 1 GB POR APP. Por eso el indice se acota a **los
handles que la carga toca** (1.000 de 3.000) y a **las columnas que se leen de
verdad** (46 de 98, via `columnas_leidas_del_catalogo`): **18 MB**. Lo vigila
`scripts/test_memoria.py`, con las columnas REALES del export — con un juego de
metacampos inventado el numero no se parece al de produccion.

Si alguien agrega una lectura de una columna nueva del catalogo, tiene que
agregarla a `columnas_leidas_del_catalogo` o llegara vacia. Hay una prueba que
exige que esten todas las de `comparable_columns`: si faltara una,
`product_is_unchanged` dejaria de compararla y un producto que SI cambio se
reportaria como omitido.

---

## 5 quaterdecies. El ticket se bajaba de GitHub en cada clic (septiembre 2026)

`get_ticket` **no esta cacheada, y es a proposito**: de ahi sale el `_revision`
con el que se guarda, y servirlo de una copia vieja haria fallar cada guardado
con "cambio en otra sesion".

Pero eso no justifica pagar el viaje **para pintar un titulo**. Tres pantallas
lo pedian solo para DIBUJAR, y las tres se redibujan en cada rerun:

- `_render_acciones_solicitud_tras_carga` (Carga completa, tras el analisis)
- `render_full_load_ticket_queue` (el panel de Cargas pendientes)
- `render_ticket_detail` (el detalle de la bandeja)

O sea **tres viajes a la API de GitHub por cada clic**. Medido con 250 ms de
latencia —lo que tarda desde Streamlit Cloud—: **0,75 s por clic** que no
hacian nada.

`ticket_para_pantalla` lo saca de la **bandeja, que ya esta cacheada** (25 s) y
que **toda escritura invalida** (`invalidate_cache` en create/update/delete).
Es el mismo dato sin el viaje, y despues de cualquier accion la siguiente
lectura ya es fresca. Si el ticket no esta en la bandeja —va filtrada por rol,
y una solicitud recien creada puede no aparecer— cae a `get_ticket`, o la
pantalla se quedaria vacia. Si la bandeja falla, tambien.

**Para ESCRIBIR se sigue usando `get_ticket`.** `_adjuntar_matrixify_antes_de_cargar`
lo hace asi y hay un test que lo exige: ahi el `_revision` tiene que venir de
GitHub.

### "Subir el input a mano" soltaba la solicitud

El aviso decia *"La carga quedará asociada a CAT-..."* y el codigo hacia
`pop("carga_desde_solicitud")` en la linea de al lado. Las dos consecuencias
eran silenciosas:

- `recordar_matrixify_de_carga` recibia el codigo vacio y **no apuntaba nada**,
  asi que el Matrixify no se adjuntaba a la solicitud y **la carga por GitHub
  Actions se quedaba sin archivo que cargar**.
- `_render_acciones_solicitud_tras_carga` corta cuando no hay codigo: al
  terminar el analisis **desaparecian los botones de cierre**.

Ahora la solicitud se conserva y solo cambia el archivo, que es lo que el aviso
prometia. Una carga que de verdad no sale de ninguna solicitud sigue soltandola.

### La cadena de la carga por Actions, para no volver a dudar

```
elegir solicitud   -> carga_desde_solicitud = CAT-...
Analizar input     -> recordar_matrixify_de_carga (ruta del Excel + claves)
Ejecutar carga     -> _ejecutar_accion_ticket ve metodo == "start_load"
                      -> _adjuntar_matrixify_antes_de_cargar -> attach_matrixify
                      -> start_load() -> jobs.start(ticket) -> workflow_dispatch
```

**Sin solicitud no hay carga remota**: el job cuelga del ticket, y un archivo
subido suelto no tiene donde colgarse. Ese caso se queda con la sincronizacion
por bloques de la propia pantalla. Y sin `[carga_remota]` en Secrets,
`get_job_adapter` cae al `MockJobAdapter` y tampoco dispara nada — eso se ve en
**Auditoría → "¿La carga sobrevive al cierre de sesión?"**.

---

## 5 quindecies. La carga se encadena sola, y la auditoria se puede limpiar (septiembre 2026)

### "¿Por que la sincronizacion es por bloques? deberia ser completa"

Los bloques **nunca fueron un limite**: la opcion "Todos pendientes" ya existia
en el selector. Pero era la **ultima de seis** y el valor por defecto era **50**,
asi que la carga completa estaba ahi y no la encontraba nadie: se veia como que
la app solo sabia cargar de 50 en 50.

Y lo que de verdad molestaba tampoco eran los bloques: era **pulsar "Continuar
siguiente bloque" veinte veces**.

Dos cambios:

- **"Todos pendientes" va primera y por defecto.** Los tamanos chicos siguen
  ahi, que sirven para reintentar una tanda concreta.
- **"Cargar todo sin parar"**: se pulsa UNA vez y la pantalla encadena los
  bloques sola, con el avance a la vista y un boton para parar.

Los bloques **se quedan**, y por lo mismo de siempre: cada uno que termina queda
guardado, asi que si la pestana se refresca o la app se reinicia a mitad de
1.000 productos se retoma donde iba en vez de empezar de cero. La red no es el
problema; tener que empujarla a mano si lo era.

Tres detalles que no son obvios:

- **El boton de parar se dibuja ANTES de procesar el bloque.** Durante el bloque
  el script sigue corriendo, y lo que venga detras todavia no existe en
  pantalla: dibujado despues, no se veria nunca y no habria forma de detenerlo.
- **La bandera se limpia en el `on_click`**, que corre antes del cuerpo del
  script en el rerun siguiente. Con un `if boton:` habria que acertar el hueco
  entre bloques.
- **El bucle termina siempre**, porque `process_sync_job_next_block` saca el
  producto de `pending_keys` aunque falle (pasa a `error_keys`). Aun asi hay una
  guarda: si un bloque no mueve el contador, se para. Un bucle infinito que
  ademas escribe en Shopify no es un bucle infinito cualquiera.
- **No hay `while`**: se encadena con `st.rerun()`. Un bucle dentro del mismo
  rerun bloquearia la pantalla entera y no se podria ni parar ni ver el avance.

**Y ojo:** con `[carga_remota]` configurado, "Ejecutar carga" desde una
solicitud ya la manda a un runner de GitHub Actions y **no hace falta este panel
para nada**. El panel es el camino local, para cuando la carga no sale de una
solicitud. Conviven dos formas de cargar y eso confunde — esta anotado en
Pendientes.

### Limpiar el historico de auditoria

El registro se guarda **un archivo por mes** en el repositorio de datos, y no
habia forma de limpiarlo: crecia sin techo. Ahora hay un panel en
**Auditoría → "Limpiar histórico de auditoría"**.

Limpiar es **borrar meses enteros**, que es como esta guardado: no hay forma de
que quede a medias ni de borrar "la accion de alguien" por separado.

Tres cosas que no son negociables:

- **El mes en curso nunca se ofrece.** Se estaria borrando lo que se acaba de
  registrar, incluida la propia limpieza.
- **Se conservan los ultimos 12 meses completos** por defecto (ajustable de 1 a
  36). Esto es una limpieza, no un borron: el registro existe para mirar atras.
- **La limpieza queda REGISTRADA**, con quien la hizo y que meses se llevo. Un
  borrado que no deja rastro convierte la auditoria en un adorno: el registro no
  podria explicar por que le falta un tramo.

Un mes que falla no corta la limpieza de los demas: se reporta y se sigue. Un
borrado a medias que corta en seco deja sin saber que alcanzo a irse. Y con
almacen efimero (sin `[auditoria]` en Secrets) el panel lo dice y no ofrece
nada: ahi el registro ya se pierde solo.

`scripts/test_sincronizacion_y_limpieza.py` (19 pruebas) fija las dos cosas.

---

## 5 nonies. La carga sigue con la sesión cerrada (septiembre 2026)

`engines/carga_remota.py` (sin Streamlit) + `scripts/worker_carga_shopify.py` +
`.github/workflows/carga-shopify.yml`.

**El problema:** la carga corría DENTRO del proceso de Streamlit. Cuando el
navegador se desconecta —la PC se apaga, se cae el wifi, se cierra la pestaña—
Streamlit corta la sesión y el script deja de avanzar a mitad del catálogo.

El panel "Sincronización recuperable por bloques" parecía resolverlo y no lo
hacía: **no avanza solo** (alguien tiene que pulsar "Continuar siguiente
bloque") y guarda el avance en `outputs/sync_jobs/`, que es disco del
contenedor de Streamlit Cloud y está en `.gitignore`. Un reinicio del
contenedor borra el avance, no solo la sesión.

Ahora la ejecuta un runner de GitHub Actions: una máquina que no es la del
usuario. El avance vive en el repositorio **privado** de datos, en
`catalog_tickets/catalog_jobs/`, al lado de las solicitudes.

**El punto de enganche YA EXISTÍA.** `TicketService` recibe el adaptador de
jobs por inyección y `start_load()` ya llamaba a `self.jobs.start(ticket)`,
guardando el resultado en `ticket["job"]`. Como el ticket se persiste en
GitHub, **el identificador del job sobrevive al cierre de sesión sin tocar la
máquina de estados**. Es la misma historia que el motor de notificaciones:
enchufando `AdaptadorCargaActions` ahí, las tres superficies que ejecutan
cargas lo heredan sin saber que existe. Hasta ahora había un `MockJobAdapter`
devolviendo un id falso.

**El ticket guarda solo el puntero**, no el avance. Con los pendientes y los
resultados dentro, cada escritura de la solicitud arrastraría el catálogo
entero y el JSON crecería sin techo.

**El Matrixify tiene que estar en el repositorio antes de disparar.** El runner
no puede leer `st.session_state`. `attach_matrixify` lo sube como adjunto de la
solicitud, y el enganche está en **`_ejecutar_accion_ticket`**, no en cada
pantalla: así los atajos y las tres superficies lo heredan. No reescribe si el
contenido no cambió —cada escritura es un commit— y solo se guarda la
REFERENCIA al DataFrame en la sesión: el Excel se arma una sola vez, al pulsar.

**Reanudable de verdad.** El avance se publica **dentro** del bucle, después de
cada bloque de 20. Guardando solo al final, un runner que muere a los 40
minutos no deja constancia de nada y el próximo intento recarga todo. Al
reanudar, las claves salen del **Excel**, no de la lista guardada: si el
adjunto se reemplazó por una versión corregida, la lista vieja cargaría
productos que ya no están en el archivo.

**Quedarse sin tiempo NO es terminar.** El tope del runner son 6 h; el worker
corta a los 330 min y deja el job en `queued` con sus pendientes. Marcarlo
completado con productos sin cargar es exactamente el error corregido en agosto
de 2026. Hay pruebas que lo fijan.

**Los logs de Actions son PÚBLICOS.** El workflow vive en el repositorio
público a propósito: ahí los minutos son gratis e ilimitados (en un repositorio
privado serían 2.000 al mes en el plan Free). La contrapartida es que cualquiera
puede leer el log de una ejecución; GitHub solo enmascara los secretos
declarados. Por eso:

- El worker imprime **solo** contadores, número de bloque y códigos Modelo-Color.
- Todo pasa por `_decir()`, que llama a `texto_publico()`. Hay un test AST que
  falla si aparece un `print()` fuera de ahí.
- El detalle de cada error va al registro del job, en el repositorio privado.
- El resultado **no** se sube como `upload-artifact`: eso sería publicar el
  catálogo. Va al repositorio de datos.

**`concurrency` por sitio, con `cancel-in-progress: false`.** Dos runners
cargando el mismo sitio se pisan en Shopify y chocan con el sha del repositorio
de datos —el mismo `TicketConflictError` de la sección 9—. Cancelar la primera
dejaría el catálogo a medias; como el job es reanudable, esperar no cuesta
trabajo repetido.

**Ojo con Hush Puppies.** `catalog_engine._env_name` arma la variable desde el
`site_key`, y el suyo es `hush_puppies` → `HUSH_PUPPIES_SHOP_DOMAIN`. El secreto
guardado se llama `HUSHPUPPIES_SHOP_DOMAIN`, sin el guion. El workflow los mapea;
sin eso Hush Puppies falla con "faltan credenciales" y nada más. Hay un test que
recorre los cinco sitios.

**Sin `[carga_remota]` en Secrets no cambia nada.** `get_job_adapter()` cae al
`MockJobAdapter` de siempre y la carga se sigue haciendo a mano por bloques.
Misma regla que el motor de correo, que sin `[notificaciones]` cae a consola.
El token **no** es el de `[ticketing]`: aquel es de contenidos sobre el
repositorio privado, y disparar un workflow necesita **Actions: write** sobre el
repositorio del código.

**Un fallo al disparar no tumba la solicitud.** `start()` nunca levanta:
devuelve un job en `not_dispatched` con el motivo, y la pantalla lo dice y
ofrece revisar. Misma regla que los correos.

**El dry run sigue siendo local.** Mandarlo a un runner solo agregaría cola a un
paso que hoy es inmediato y que no llama a Shopify.

**El Matrixify NO se queda en la sesión.** `recordar_matrixify_de_carga`
guarda la **ruta** del Excel que la pantalla ya escribió en disco para el botón
de descarga —su primera hoja es `Products`, que es la que lee el worker— y las
claves Modelo-Color, que son cadenas. Guardar el DataFrame en
`st.session_state` lo **fijaría hasta cerrar la sesión**: `build_columbia_matrixify`
no está cacheada, así que hoy se reconstruye en cada rerun y se libera solo. Es
el mismo error que se corrigió bajando los DataFrames gigantes a disco, y el
contenedor da 1 GB **por app**, compartido. Tampoco se arma un Excel nuevo al
pulsar: duplicaría en memoria justo en el peor momento. Hay 4 pruebas que lo
fijan y fallan con el código anterior.

Si el contenedor se reinicia entre el análisis y el clic, el archivo de disco
desaparece. En ese caso, **si la solicitud ya tiene un Matrixify adjunto** de un
intento anterior se sigue con ese: cortar ahí convertiría un reintento legítimo
en un callejón sin salida.

**Deuda que NO se pagó aquí:** el worker importa `app_matrixify` para reusar
`process_sync_job_next_block` —que ya tiene pruebas y está en producción—, así
que arrastra Streamlit al runner. Es la deuda de la sección 2 (extraer
`engines/shopify_sync.py`). Escribir aquí un segundo motor de carga sería tener
dos que se separan sin que nadie lo note, como las dos `normalize_size`.

## 5 sexdecies. El diccionario de tallas, y la escala por marca (septiembre 2026)

`engines/tallas.py` (sin Streamlit ni pandas) + `engines/guias_tallas.py`.

### El orden lo decidian TRES criterios y ninguno entendia a Columbia

Habia un `size_sort_key` en `generate_columbia_matrixify`, otro en
`app_matrixify` y una copia muerta en `engines/normalize`. Los tres entendian lo
mismo: **letra** de una tabla de doce, **numero** puro y **`numero/numero`**.
Todo lo demas caia en un cajon que se ordenaba **alfabeticamente**.

Medido sobre `data/arti.zip` -653.431 filas, ~94.000 modelo-color-, eso dejaba
**361 de los 15.690 modelo-color de Columbia** con la curva desordenada:

```
L/R, M/R, S/R, XL/R, XS/R      ->  XS/R, S/R, M/R, L/R, XL/R
10/R, 12/R, 2/R, 4/R, 6/R      ->  2/R, 4/R, 6/R, 8/R, 10/R, 12/R
L/6, L/8, M/6, M/8, S/ 8       ->  S/ 6, S/ 8, M/6, M/8, L/6, L/8
18/24, 03-JUN, 06-DIC, DIC-18  ->  03-JUN, 06-DIC, DIC-18, 18/24
```

Las de tipo `03-JUN` son `3-6` que Excel convirtio en fecha al exportar el
maestro. Se decodifican sustituyendo el mes por su numero **en el sitio donde
esta**: `DIC-18` da `12-18`. No hay que adivinar cual de los dos era el mes,
porque el texto conserva la posicion.

**La regla que hace que esto se pueda tocar sin miedo:** las familias 0, 1 y 2
de `engines/tallas` son **exactamente** las tres del criterio viejo, con los
mismos indices, y las formas nuevas van en familias >= 3, o sea siempre despues.
Consecuencia: en cualquier producto cuyas tallas el criterio viejo ya reconocia
todas, el orden nuevo es **identico**. Eso es lo que garantiza que Rockford (3
productos afectados de 9.785), Hush Puppies (2 de 14.581) y el 97,7 % de
Columbia no se muevan.

`scripts/test_orden_tallas_reales.py` lo comprueba recorriendo **los ~94.000
modelo-color del maestro real**. Un juego de casos escritos a mano no sirve para
esto: prueba lo que a uno se le ocurre, y lo que rompe una carga es lo que no se
le ocurrio a nadie. Es la misma leccion del lector de VTEX, que paso sus 62
pruebas porque se probo con una muestra de 500 filas.

**Si agregas una familia, va con numero >= 3 y con su caso en esa prueba.** La
cobertura paso del 97,7 % al 99,66 % de los modelo-color; lo que queda sin
reconocer se **reporta** (`tallas.no_reconocidas`) en vez de ordenarse por texto
en silencio. `O/S` se queda en la escala de letras en 99, donde estaba: sacarlo
a familia propia cambiaria el orden de los productos que lo mezclan con numeros
-PARFOIS tiene varios- y ahi hoy va primero.

### La escala de calzado son DOS datos, no un booleano

`tallas_calzado_pe` era una bandera del SITIO, y alcanzaba mientras Vans vivia
solo en Vans.pe. Con Supermall.pe un booleano solo sabe decir "todo el calzado
del sitio" o "nada", y las dos respuestas son falsas. Medido:

| Marca | mod-col en US | mod-col en PE | con las DOS |
|---|---:|---:|---:|
| Hush Puppies | 2.752 | 8.165 | **36** |
| Columbia | **2.794** | 0 | 0 |
| Rockford | 328 | 2.078 | **8** |
| Vans | 151 | 790 | **8** |
| Keds | 335 | 0 | 0 |
| Sorel | 201 | 0 | 0 |

**Columbia, Keds y Sorel entregan TODO su calzado en US** (`BM3003-EW7` es la
curva `70...130`, o sea US 7 a 13), asi que **Columbia.pe publica hoy su calzado
en tallas US**. Y hay 52 modelo-color con las dos escalas dentro del mismo
producto: `HP10201118-742` publica `60...110` y `390...450` a la vez.

Por eso el dato se parte:

- **`escala_calzado`, por SITIO**: que ve el comprador. `supermall` y `vans` en
  `"PE"`, el resto en `"origen"`. `tallas_calzado_pe` se conserva como respaldo.
- **`engines/guias_tallas`, por MARCA + CLASE**: como se traduce esa talla. Una
  guia nueva entra como **tabla** (`registrar_tabla`), no como `if`.

**Sin guia de la marca, o sin genero, NO se convierte**: se devuelve la talla de
origen y se avisa en la hoja de **Revision**. **La carga no se detiene por
esto** - parar una carga entera porque a un producto le falta el genero es peor
que publicarlo con la talla de origen, que es lo que pasaba antes solo que sin
que se enterara nadie.

**El genero importa y no se leia.** Un mismo numero US son dos tallas distintas:
US 8 de hombre es PE 40.5 y de mujer es PE 38.5. Sin genero se aplicaba la
columna de hombre en silencio, y por eso `5, 6, 7` salian `36.5, 38, 39` cuando
lo correcto era `35, 36, 37`. `custom.genero` se agrego a
`shopify_api.CAMPOS_PRODUCTO` -junto con `custom.color`, `custom.nombre_corto` y
`custom.descripcion_corta`, que tampoco se leian- y se propaga en
`shopify_products_to_matrixify_df`, donde esas columnas salian **siempre
vacias**.

**Solo hay guia de Vans**, que es la unica confirmada y coincide fila a fila con
el Excel oficial. Columbia solo necesita ORDEN, no conversion. Faltan las de
Hush Puppies, Keds, Sorel y Rockford: mientras no esten, su calzado en US se
publica como viene y sale avisado.

### Tres fallos dejaban el Mantenedor de Tallas sin efecto

Ninguna de sus 34 pruebas los atrapo: todas prueban el **motor**, y los tres
estaban en el **pegamento** con la pantalla.

1. `app_matrixify` llamaba a `orden_tallas._indice_de_opcion`, que **no existe**
   (es `indice_de_opcion`). `AttributeError` sin capturar: "Aplicar" moria en el
   primer producto que hubiera que reordenar y se llevaba la pantalla por
   delante.
2. `plan_de_producto` no devolvia `Type` ni `Genero`, asi que al **replanificar
   antes de escribir** el conversor salia `None` y el cambio de escala **no se
   aplicaba nunca**: la pantalla contestaba "Ya estaba bien al releerlo".
3. `values_in_order` en `_reorder_product_sizes` era codigo muerto.

---

## 5 septdecies. Carga Supermall (septiembre 2026)

`engines/carga_supermall.py` (sin Streamlit ni pandas) + `render_carga_supermall()`.
Pantalla propia **en el menu principal**, al lado de Status de carga.

### El agujero que cierra

La app resolvia los dos extremos y nada del medio. El espejo decia QUE FALTA y
entregaba un Excel de codigos que mandaba a "Carga parcial -> Carga Sial". Esa
pantalla **solo produce la hoja SIAL** -no el Matrixify, que es lo que crea el
producto- y **lee el catalogo de UN solo sitio: el activo**. Estando en
Supermall ese es el DESTINO, donde esos productos por definicion no estan, asi
que `product_lookup` salia vacio y el producto se armaba casi entero en blanco.

La informacion existia -en Vans.pe, Rockford.pe, Columbia.pe- pero el camino que
la app ofrecia no la miraba. **Lo que faltaba no era una pantalla: era el paso
de CONSOLIDACION.**

### Como consolida

**Campo a campo, no por sitio entero.** Tomar "el sitio ganador" desperdicia el
campo que solo tiene el otro.

**Ningun sitio manda sobre otro.** Supermall no tiene marca propia: las lleva
todas, asi que no hay un "sitio dueno" del producto. A igualdad de dato manda la
web donde el producto esta **prendido y visible**, que es la que alguien reviso
de verdad. El desempate final es el orden de `SITE_CONFIGS` y **no el de
llegada**: una consolidacion que cambia de resultado en cada ejecucion no se
puede comparar con la anterior.

Cada ficha lleva **de que web salio cada campo**. Cuando un producto salga raro
la pregunta va a ser "de donde saco esa descripcion", y tiene que poder
responderse sin abrir seis pestanas.

**No vuelve a escribir como se lee un producto de Shopify**: la identidad, la
marca y el estado web salen de `engines/load_status`, igual que el espejo.

### Bloquear y avisar no es lo mismo

Sin codigo Modelo-Color, sin nombre o sin tipo: **bloquea**, queda fuera del
archivo. Sin genero o sin fotos: **avisa y se carga igual**. Un aviso que
bloquea detiene una carga de miles por un dato que no lo merece.

### Las reglas de Supermall, confirmadas

- Entra **Activo y publicado**. Un producto que llega en borrador a un
  marketplace no lo ve nadie, y esperar a que alguien lo publique a mano es el
  mismo problema que el espejo existe para evitar.
- **Sin precio**: lo sincroniza el ERP. Mandar un precio aqui competiria con esa
  sincronizacion y ganaria el ultimo que escribiera (`precio_desde_erp`).
- **Con siblings**, siempre.
- **Bodega SIAL `13`**, confirmada.
- El calzado de las marcas **con guia registrada**, en tallas PE.

### Reutiliza el tramo comun, no lo copia

`matrixify_desde_codigos_modelo_color` recibe un catalogo de **ORIGEN** opcional
y uno de **DESTINO**. Sin ellos se comporta exactamente como antes.

**Separar origen de destino no es cosmetico:** el `ID` de Vans.pe no existe en
Supermall.pe, y usarlo haria un MERGE contra otro producto. Cuando origen y
destino son la misma tienda -Centry, Carga Sial- `fila_destino` es la misma fila
que `product_row`. Hay una prueba que exige que
`build_centry_matrixify_from_master` se siga llamando desde **un solo lugar**.

Se procesa **por bloques de 200 codigos**, con la misma `png_bloques` de fotos,
videos y tallas: con miles de codigos, una pasada unica que se cae a la mitad no
deja constancia de nada.

### Los siblings ahora los escribe tambien la carga por codigos

Hasta ahora **solo** los escribia la carga completa, asi que Centry, Carga Sial
y Supermall dejaban la ficha sin los otros colores del modelo. Es la **MISMA**
regla, extraida a `unir_siblings`: lo ya publicado no se pisa, y un modelo con
tres colores en la tienda que hoy recibe uno nuevo acaba con **cuatro**
hermanos, no con uno.

### Lo que sigue sin resolverse

- **`theme.siblings` y `custom.guia_de_tallas` del ORIGEN no son trasladables**:
  son referencias a productos y paginas de la tienda de origen. Los siblings se
  reconstruyen contra el catalogo de Supermall; la guia de tallas queda
  pendiente.
- `sial_tail_row` sigue poniendo "Crear"/"Actualizar" en TODAS las columnas
  `Nuevo o Actualizar (...)` con el `existing_id` del sitio que se carga. Es
  **preexistente** y afecta la hoja de los cinco sitios.

`scripts/test_carga_supermall.py` (30 pruebas) y `scripts/test_guias_tallas.py`
(21) fijan todo esto.

---

## 5 octodecies. La hoja Carga Sial: categoria, topes y que tallas salen (septiembre 2026)

`engines/sial_campos.py` (sin Streamlit ni pandas) + `talla_sirve_para_sial`.

Cuatro cosas que reporto el usuario, las cuatro reproducidas contra una carga
real antes de tocar nada:

```
Categoria           VACIA en toda la carga completa
Tipo de Material     65 caracteres  (tope 30)
Tecnologias          71 caracteres  (tope 50)
Caracteristicas     144 caracteres  (tope 130)
```

### La Categoria es la CLASE, y salia vacia

`product_category` miraba `custom.categoria`, `Categoria `, `Categoria` y
`Category`. El input comercial llama a esa columna **`Clase`** -es una de sus
columnas obligatorias- y no se miraba, asi que **la columna salia vacia en toda
la carga completa**. El respaldo es el diccionario de tipos
(`engines/garment_types`), de donde ya la deriva la hoja por codigos: un
ALPARGATA es Calzado se escriba o no. Asi las dos hojas dicen lo mismo del
mismo producto.

`Color web/filtro` tampoco estaba en `COLOR_WEB_COLUMNS`. Se agrego **al
final**: puesto ahi solo rellena lo que hoy sale en blanco, y donde ya habia
valor no cambia nada.

### Los topes: cada columna tiene su POLITICA

La hoja se emite desde DOS sitios -la carga completa y la carga por codigos, que
sirve a Centry, a la Carga Sial parcial y a Supermall-, asi que la regla vive en
`engines/sial_campos` y las dos la llaman. Escrita dos veces, el arreglo
siguiente entra en una hoja y se olvida en la otra.

**No se recorta por la mitad de una palabra.** Un "100% Algodon organi" no es un
material: es basura que alguien va a corregir a mano. Las tres politicas son
distintas porque los datos son distintos:

| Columna | Tope | Politica |
|---|---:|---|
| `Color Web` | 30 | antes de la coma |
| `Tipo de Material` | 30 | antes de la coma |
| `Tecnologias ` | 50 | primer valor, o **vacio** |
| `Caracteristicas` | 130 | recortar en palabra |

`Color Web` y `Tipo de Material` son listas donde el primer elemento es el valor
principal: "AZUL MARINO, BLANCO, ROJO" es fundamentalmente azul marino. Cortar
la lista conserva el dato; recortar la cadena lo destruye. En `Tecnologias ` una
tecnologia a medias es peor que ninguna -"Omni-Heat Reflec" no existe-, asi que
si ni el primer valor entra, se deja vacia. `Caracteristicas` es prosa
descriptiva: 130 caracteres siguen sirviendo.

**Todo ajuste se REPORTA** en la hoja de Revision. Un recorte silencioso es como
se pierde un dato sin que nadie se entere.

### Que tallas salen, y las fechas que dejo Excel

`talla_sirve_para_sial` deja fuera lo que no es una talla: las **internas K**
(`K1201`, `K601` — 162 formas en el maestro) y lo que el **diccionario no
reconoce** (`R`, `RH`, `LLH`, `REGRH` — medido, ~200 filas). Antes
`filter_centry_size_rows` solo miraba las K, asi que los codigos internos
llegaban a la hoja del almacen.

**Las fechas de Excel NO se borran: se decodifican.** `04-Jun` no es basura, es
la talla `4-6` que Excel convirtio al exportar el maestro; `08-Oct` es `8-10` y
`Dic-18` es `12-18`. Medido, son **~7.800 filas** del maestro real. Borrarlas
dejaria al almacen sin una talla real, asi que `normalize_size` las devuelve
decodificadas -- y va **en el normalizador compartido** para que la hoja y la
ficha de Shopify no puedan discrepar: si el Sial dijera `4-6` y la tienda
`04-Jun`, seria el mismo dato con dos nombres.

`6/6X` se agrego al diccionario: es una talla de nino real y caia en el cajon de
las desconocidas, asi que el filtro la habria dejado fuera.

La columna `Talla` sigue siendo el codigo del **MAESTRO**, no la talla que ve el
comprador -eso es `Talla Web`-: `400` se manda `400`. Lo unico que se corrige es
lo que viene roto, y por un solo embudo (`sial_size_value`).

### 16 cabeceras salian con el nombre equivocado

`repair_mojibake_dataframe` pasaba los NOMBRES de columna por
`repair_mojibake_text`, que empieza con `clean_value` y recorta espacios. Eso le
quitaba el espacio final a 16 cabeceras de la plantilla -`Categoria `,
`Talla Web `, `Tecnologias `, `Product Name `, `Adicional 2 `...- que SIAL
espera **con** el espacio, porque asi se llaman en su plantilla. La hoja de la
carga completa no pasa por ahi, asi que las dos hojas salian con cabeceras
distintas para la misma columna.

Un nombre de columna es una LLAVE: si se le quita un espacio, deja de coincidir
con la plantilla que lo espera. Ahora solo se reescribe cuando hay mojibake que
arreglar de verdad, que es la misma guarda que ya tenian los valores.

`scripts/test_carga_sial_campos.py` (27 pruebas) fija todo esto.

---

## 5 novodecies. La curva decide la talla, y la carga remota sin solicitud (septiembre 2026)

### Un valor suelto no se puede interpretar; la curva si

El maestro escribe el calzado multiplicado por diez (`85` es 8.5) y a veces con
relleno de ceros (`085`, `040`) o por cien (`850`). **Un valor suelto es
ambiguo**: `040` puede ser el PE 40 o el US 4, y son dos tallas y media.

Lo que SI se puede decidir es la **curva entera**, porque un producto de
calzado tiene sus tallas en UNA escala. `interpretar_curva` prueba las tres
lecturas -directa, entre diez, entre cien- y se queda con la que deja TODAS las
tallas dentro de un rango que existe (US 1-16.5, PE 26-50):

```
040, 050, 060, 070  ->  directa daria PE 40 a 70, que no existe  ->  US 4 a 7
070, 085            ->  US 7 y 8.5
800, 850            ->  entre cien: US 8 y 8.5
390, 400, 410       ->  entre diez: PE 39, 40, 41   (el maestro de hoy)
```

**La regla de mujer, que la dio el usuario:** "ninguna talla de mujer empieza de
la 40". Asi que una curva de calzado de MUJER cuyo minimo leido en PE sea 40 o
mas **no esta en PE** (`MINIMO_PE_MUJER`). Eso resuelve el unico caso realmente
ambiguo, `040` sola: en mujer es el US 4, en hombre sigue siendo el PE 40. Y es
el MINIMO de la curva, no el valor: una curva de mujer que llega a la 40 pero
empieza en la 36 sigue siendo PE.

**Se interpreta el valor CRUDO, no el normalizado.** `normalize_size` tiene su
propia regla por valor: divide `050` entre diez pero deja `040` tal cual. Con la
curva apoyada en el normalizado, la misma curva llegaba medio dividida y el
divisor se aplicaba dos veces a unas tallas y a otras no -- `400, 410` salia
`4, 4.1` y las filas se caian del filtro. Por eso `display_size_for_site` recibe
`curva` (los crudos) y `valor_crudo`, y cuando la curva decide una escala, ELLA
manda para el calzado. **Sin `curva` se comporta exactamente como antes.**

Toda lectura que no sea la directa se **reporta** en la hoja de Revision.

### Rockford: una sola talla es Talla Única, pero no en calzado

Un accesorio de Rockford con una sola talla sale como **"Talla Única"** aunque
esa talla venga con numero. Antes solo se miraba el VALOR (`O/S` o `0`).

**No se aplica a calzado ni a vestuario**, y no es un detalle: ahi "Talla Única"
esta bloqueada a proposito y `final_variant_filter` **BORRA** esas filas.
Renombrarla hacia **desaparecer el producto entero** -- medido: una zapatilla de
una sola talla salia del Matrixify con cero filas. La guarda
(`_talla_unica_bloqueada`) responde la misma pregunta que el filtro final, y
tiene que dar la misma respuesta.

### Las marcas sin guia se quedan como estan

Confirmado por el usuario: **Hush Puppies, Keds, Sorel y Columbia** no tienen
guia registrada, asi que su calzado se publica con la talla de origen y sale
avisado. **Supermall y Vans usan la misma guia** -- la de Vans -- y los dos
publican en PE.

### La carga remota ya no exige una solicitud

`start(ticket)` necesitaba una solicitud porque el job cuelga de ella: el
Matrixify es un adjunto del ticket y de ahi lo lee el runner. Eso dejaba fuera
el caso mas comun: **subir un Excel a mano y cargarlo**. En ese camino la carga
se hacia dentro de la sesion de Streamlit, asi que cerrar la pestana la
detenia -- justo lo que el runner existe para evitar.

`start_suelto` sube el Matrixify al repositorio de datos por su cuenta, al lado
del registro del job (`ruta_de_matrixify`), y **el resto del recorrido es EL
MISMO**: mismo registro, mismo workflow, mismo worker, mismo avance por bloques
y misma reanudacion. No hay un segundo motor de carga.

- **El archivo va PRIMERO.** Con el registro guardado y el archivo no, el runner
  arrancaria para morir leyendo una ruta que no existe.
- El codigo es sintetico y se ve como lo que es (`CARGA-VANS-20260908-...`):
  inventar un CAT-#### haria creer que existe una solicitud.
- `recordar_matrixify_de_carga` ya no corta cuando el codigo viene vacio. Era la
  puerta cerrada: sin solicitud no se apuntaba nada.
- El boton (`render_boton_carga_remota`) se dibuja **fuera** del
  `if complete_source == "Shopify API"` y fuera de la casilla de
  sincronizacion -- anidado ahi no aparecia con "Respaldo Excel", que es el
  mismo fallo que ya se corrigio con el cierre de la solicitud. Hay un test que
  compara la sangria.
- **No se dibuja cuando la carga SI sale de una solicitud**: ahi manda la barra
  de acciones, que ademas mueve su estado. Dos botones para lo mismo es peor
  que uno.
- Sin `[carga_remota]` en Secrets el boton dice **exactamente que falta** en vez
  de caer al camino local en silencio.

### El puente a la solicitud fallaba EN SILENCIO

Reportado con una captura: la solicitud decia *"La carga no llegó a iniciarse en
GitHub Actions. La solicitud no tiene un Matrixify adjunto. Genéralo en Carga
completa (Analizar input)"* justo despues de haberlo generado. El mensaje culpa
a la solicitud y manda a hacer algo que ya se hizo, asi que no hay salida.

`_adjuntar_matrixify_antes_de_cargar` tenia dos `return ""` -o sea "todo bien"-
**sin haber adjuntado nada**: cuando no habia Matrixify apuntado en la sesion y
cuando el codigo apuntado no era el de esa solicitud. En los dos casos la carga
seguia adelante para morir en el adaptador.

Y el segundo se hizo **mas probable** al permitir la carga remota sin solicitud:
desde entonces el codigo apuntado puede venir vacio a proposito.

Dos cambios:

- **El codigo apuntado ya no tiene que coincidir.** En la sesion solo cabe el
  ultimo Matrixify analizado, asi que si se ejecuta la carga de una solicitud
  justo despues de analizar, ese ES el archivo. Lo que si tiene que coincidir es
  el **SITIO**: un Matrixify de Vans.pe en una solicitud de Rockford.pe cargaria
  el catalogo equivocado, y eso se comprueba y se corta con el motivo.
- **Ninguna salida es silenciosa.** Cada caso dice exactamente que pasa: no hay
  nada analizado, es de otro sitio, o el Excel ya no esta en disco. La unica
  salida sin aviso que no adjunta es cuando la solicitud **ya tiene** un
  Matrixify de un intento anterior -- ahi cortar convertiria un reintento
  legitimo en un callejon sin salida.

Tras adjuntar, el Matrixify queda apuntado a esa solicitud, para que un segundo
clic no vuelva a subir el mismo archivo.

**Pero solo se bloquea si la carga remota esta ACTIVA.** Sin `[carga_remota]` la
carga se hace dentro de la sesion, por bloques, y no hay ningun runner que vaya
a buscar el archivo al repositorio: ahi no hay nada que adjuntar y cortar
romperia un camino valido. Eso es lo que la salida silenciosa protegia de
verdad; lo que estaba mal era hacerlo **tambien** cuando el runner si iba a
buscar el archivo. Lo destapo una prueba de la bandeja que se puso roja.

Y la funcion atrapa **cualquier** fallo al leer la solicitud, no solo
`TicketError`: su contrato es que nunca levanta, porque una excepcion aqui
impediria ejecutar la carga a mano.

`scripts/test_curva_y_carga_suelta.py` (42 pruebas) fija todo esto.

---

## 5 vicies. El panel del hueco por marca, y la vista previa de la carga (septiembre 2026)

`carga_supermall.hueco_por_marca` + `render_hueco_por_marca` +
`resumen_matrixify_por_marca`, dentro de **Carga Supermall**.

### Antes de cargar, que falta y comparado con quien

La pregunta es "que le falta a Supermall **comparado con las otras marcas**", y
esa se responde por marca. Sale de las fichas YA consolidadas, asi que **no
cuesta ninguna lectura extra**: los seis catalogos ya estan en la mano.

Cuatro estados, de mejor a peor: `Ya visible`, `Cargado sin publicar`,
`Falta cargar` y `No se puede cargar`. El ultimo va **aparte** de "falta" a
proposito: son los que no tienen codigo, nombre o tipo en ninguna web, y
mezclarlos haria creer que con pulsar el boton se resuelven.

Los totales del titular se suman sobre las FILAS por marca, no sobre las fichas
otra vez: dos calculos separados podrian dar numeros distintos, y un panel que
se contradice consigo mismo no se puede usar para decidir. Hay un test que lo
comprueba.

### Barra apilada horizontal, y cada una al 100 % de SU marca

La forma sale del trabajo del dato: es un **part-to-whole por marca** y las
marcas tienen nombre largo, asi que la barra va en horizontal -- con una
columna por marca los nombres se cortan o se giran.

**La primera version usaba una escala compartida y enganaba.** Medido con el
reparto real: Sorel salia con una barra del **2,6 %** del ancho, que se lee como
"esta bien", cuando en realidad le falta el **71 %** de su catalogo. La pregunta
es la comparacion ENTRE marcas, asi que lo que hay que poder comparar es la
PROPORCION; la magnitud absoluta va al lado, en la etiqueta, que es donde se lee
un numero. Hay un test que exige que cada barra sume 100 %.

Lo demas que no es negociable, y por que:

- **Los colores son de ESTADO, no de identidad.** Son cuatro situaciones de
  mejor a peor, asi que usan los tokens de estado de la app (`--c-ok`,
  `--c-warn`, `--c-bad`) y no una paleta categorica. Usar tokens de estado para
  identidad -o al reves- es un error con nombre propio.
- Los tres colores se **validaron** contra el fondo blanco: pasan banda de
  luminosidad, piso de croma, separacion para daltonismo (peor par 8,9 en
  protanopia) y piso de vision normal (19,8). El aviso de contraste por debajo
  de 3:1 se cubre con las **etiquetas visibles y la tabla**, que llevan todos
  los numeros -- ese aviso no se puede ignorar, se compensa.
- **La identidad nunca es solo color:** leyenda con las cuatro etiquetas y su
  numero, una etiqueta directa por fila y la tabla con todas las marcas.
- **Un numero por fila, no por segmento.** Un valor pegado a cada segmento es
  ruido y no se lee: se etiqueta lo que se va a usar para decidir -- lo que
  falta -- y el resto lo llevan la leyenda y el `title` de cada segmento.
- La separacion entre segmentos es un **hueco de 2px del color de la
  superficie**, no un borde: el borde ensucia el color y engorda la marca.
- **Ordenado por lo que falta**, no alfabetico: la primera fila es donde hay mas
  trabajo, que es la razon de mirar el panel.

Se dibujan las 12 marcas con mas pendiente y la tabla lleva el resto.

**Verificado en Chromium**, no solo en pruebas: 1440px y 390px, sin desborde
horizontal, sin textos recortados y las ocho filas de la misma altura. En movil
la cifra se queda con el ancho de un numero de cuatro digitos con separador de
miles; con menos, la etiqueta parte en dos lineas y las filas quedan desiguales.

### La vista previa de la carga

`resumen_matrixify_por_marca` dice **que hay dentro del archivo que se va a
subir**, marca por marca: productos y filas de talla. Sale del propio Matrixify
para que no pueda discrepar de el -- si se calculara aparte, el resumen y el
archivo podrian decir cosas distintas y entonces no sirve para revisar.

El Excel lleva cinco hojas: **Products** (el Matrixify), **Carga Sial**,
**Resumen por marca**, **Consolidacion** (de que web salio cada dato) y
**Revision**. La pantalla dice explicitamente que **todavia no se ha escrito
nada en Shopify**: es una vista previa, y hay un test que exige que ni el panel
ni el resumen puedan tocar la tienda.

`scripts/test_hueco_por_marca.py` (28 pruebas) fija todo esto.

---

## 5 unvicies. Un solo diccionario de tipos, y el de colecciones por marca (septiembre 2026)

`engines/colecciones.py` (sin Streamlit ni pandas) + `render_diccionario_colecciones()`,
pantalla propia **Diccionarios** en el menu principal, al lado de Carga Supermall.
`scripts/generar_diccionario_colecciones.py` + `data/colecciones_por_marca.json`.

### El tipo de prenda se decidia en DOS tablas que se contradecian

Habia dos diccionarios de tipos escritos a mano: `engines/garment_types` (el
Excel que confirmo el usuario, con los nombres por sitio) y
`catalog_rules.PRODUCT_TYPE_RULES` (con la clase, el grupo de guia de tallas y
la talla unica). Medido: **186 nombres** que solo conocia una de las dos, y
**diez prendas donde daban respuestas distintas**.

| Nombre | garment_types | catalog_rules |
|---|---|---|
| buzo | Polerones | **Pantalon** |
| falda | Faldas | **Short** |
| beanie | Chullos | **Gorro** |
| leggings | Leggings | **Pantalon** |
| cartera | Carteras | **Bolso** |
| jockey | Gorros | **Sombrero** |
| bandana | Pañuelos | **Cuellera** |
| overol | Overol | **Enterizo** |
| chompa | Chompas | **Sweater** |
| boot | Botines | **Bota** |

La validacion del input comercial usaba una tabla y la columna `Type` que se
escribe en Shopify usa la otra (`resolve_product_type` llama a
`tipo_para_sitio`), asi que **el mismo producto se clasificaba distinto segun
por donde pasara**. Es exactamente la trampa de las dos `normalize_size`.

**Ahora `PRODUCT_TYPE_RULES` se DERIVA del maestro** y `normalize_product_type`
le pregunta a el. La forma del diccionario no cambia: sus consumidores
(`commercial_product_type_rules_for_brand`, `catalog_rule_type_names`,
`resolve_size_guide`) siguen leyendo las mismas claves. Donde las dos se
contradecian manda el maestro, que es el dato confirmado.

Lo que gano el maestro:

- **460+ sinonimos** (523 nombres indexados, antes 345). Entran los 31 que solo
  conocia `catalog_rules` -- jogger, parka, morral, navaja, balaclava, bootie,
  guillermina, miton, micropolar, sweatshirt, portalata, portafolio, banano,
  gorro andino, gafa, trekking poles -- y ~150 formas nuevas medidas contra el
  catalogo real.
- **`Hoody` no estaba**, y son **91 productos vivos** en Columbia.pe.
- **`grupo_talla` y `talla_unica`**, que solo vivian en `catalog_rules`. Con
  eso se cierra el hueco de agosto: Chompas, Jeans, Enterizos, Blusas y
  Chalecos Polares se quedaban **sin grupo**, y sin grupo las guias de TOPS y
  BOTTOMS **empatan en prioridad 95** -- la elegida dependia del orden de la
  lista, no del producto.
- **`conflictos()`**. El indice es "gana el primero", asi que un nombre en dos
  tipos no reventaba: mandaba uno de los dos en silencio. Destapo **dos errores
  del propio maestro**: `Cremas Renovadoras` apuntaba a *Accesorios De
  Limpieza* existiendo el tipo *Crema renovadora*, y `Overoles` a *Enterizos*
  existiendo *Overol*.

**Lo que NO se mapea, a proposito:** `calzado` y `footwear` ya no resuelven a
Zapatilla. Son la **CLASE**, no el tipo, y con ese alias una sandalia declarada
como "calzado" se publicaba como zapatilla. Sin mapeo, la validacion lo avisa.

Medido: los **55 tipos del catalogo real** de Columbia.pe (2.401 productos) y
los 55 de `data/tipos_shopify.xlsx` quedan reconocidos, y las dos capas
coinciden en los 523 nombres.

Tres esperados de `test_tipos_de_prenda` cambiaron, y son la consecuencia
buscada: `"Ropa de Bano"` -> `"Ropa De Baño"`, `"Correa"` -> `"Cinturon"`, y
`bucket hat` ahora es Gorro y no Sombrero.

### El diccionario de colecciones

En Shopify una coleccion automatica **no se llena a mano**: se llena sola a
partir de una regla, y casi siempre la regla es un **TAG**. O sea que el tag
que escribe la carga decide en que colecciones aparece el producto -- y eso no
estaba escrito en ninguna parte. Nadie podia responder *"que le pongo a este
producto para que salga en Hiking"* sin abrir Shopify tienda por tienda.

**Va por MARCA y no por sitio** porque una marca vive en varias tiendas:
Columbia se carga en Columbia.pe, Rockford.pe y Supermall.pe, y cada tienda
tiene sus propias colecciones. "Las colecciones de Columbia" sin decir la
tienda no tiene una sola respuesta.

**El diccionario NO se escribe a mano: se LEE de Shopify.** Una lista inventada
se leeria como cierta, que es peor que no tenerla.

```
python scripts/generar_diccionario_colecciones.py
python scripts/generar_diccionario_colecciones.py --sitios columbia,vans
```

Lo que hay que saber para no romperlo:

- **Se lee `ruleSet`, no solo el nombre.** `shopify_api.fetch_collections` pide
  `appliedDisjunctively` y las reglas (`column`/`relation`/`condition`). Sin
  eso el diccionario seria una lista de nombres. Hay un test que lo fija.
- **Las colecciones se piden APARTE de los productos.** Metidas en la consulta
  de productos el costo se paga por producto, y ahi ya se rozan los 1.000
  puntos del maximo (seccion 5 decies). Son unas decenas por tienda: dos o tres
  viajes.
- **"No se puede evaluar" NO es "no".** Una regla por precio, peso o inventario
  no se responde con los tags, y una coleccion manual tampoco. Devolver `False`
  dejaria al producto fuera sin que nadie se entere. El motor devuelve
  **`None`** y la pantalla lo dice, en vez de dar un numero falso.
- **Lo declarado por la tienda manda sobre lo inferido.** Medido:
  `Impermeable` esta en 149 productos de Columbia como **atributo** (la prenda
  es impermeable), pero el diccionario maestro lo reconoce como el **tipo**
  "Impermeables". El vocabulario curado gana; la inferencia es el respaldo.
- **El generador no pisa el trabajo a mano.** Que "Hiking" sea una actividad y
  "Omni-Tech(tm)" una tecnologia no lo sabe Shopify: es un dato curado. Se
  conserva tal cual y los tags nuevos entran como `sin_clasificar`. Tampoco
  borra los tags que ya no estan en la tienda ni los sitios que no se leyeron
  esta vez -- se fusiona por sitio, no por archivo.
- **Un sitio caido no se reporta como tienda sin colecciones.** Eso se leeria
  como "no han creado ninguna". Su fallo viaja aparte y la pantalla avisa.
- **Un producto que no cae en NINGUNA coleccion automatica** esta cargado y no
  lo encuentra nadie navegando. Es la misma resta que el espejo de Supermall, y
  se reporta.

### Lo que se midio del catalogo real (Columbia.pe, 2.401 productos)

| | |
|---|---:|
| tags distintos | 1.175 |
| ...que son el codigo Modelo-Color del propio producto | **1.069** |
| vocabulario real | **104** |

**El codigo Modelo-Color se reconoce por IDENTIDAD, no por su forma.** La forma
(mayusculas, digitos y guiones) se pierde `AM8004-yFO`, que esta en el catalogo
con una minuscula. Con la lista de codigos del catalogo no hay que adivinar.
Ese tag ademas **no es el codigo de ningun producto**: es basura, y por eso
queda en `sin_clasificar` en vez de taparse.

Otros dos hallazgos que la pantalla muestra:

- **`Vtex` esta en 1.331 productos**, mas que ningun otro tag. Es de la epoca
  de VTEX, que se retiro en septiembre de 2026 (seccion 5 sexies bis).
- **`Mochila`/`mochila` y `Utensilios`/`utensilios`**. Shopify los trata como
  tags **distintos**, asi que una coleccion por uno se deja fuera los del otro.

### El estado del archivo hoy

`data/colecciones_por_marca.json` trae el **vocabulario de Columbia.pe**,
medido contra `data/matrixify_modelo.xlsx` y clasificado a mano (8 actividades,
30 tecnologias, 11 lineas, 9 atributos, 2 comerciales). Las **colecciones
siguen vacias**: hay que correr el generador con Secrets, que es lo unico que
no se puede hacer sin acceso a las tiendas.

`scripts/test_colecciones.py` (54 pruebas) fija todo esto, con un Shopify
falso: no sale a la red.

---

## 5 novemvicies. Carga Supermall: la marca, la duplicidad y el panel que no decía nada (septiembre 2026)

Reportado con dos capturas: el panel decía **8.815 consolidados · 8.815 se
pueden cargar · 8.815 se crean · 0 se actualizan · 0 bloqueados**, y la tabla
por marca tenía **2.872 "Sin marca"**, más un "Hush Puppies" con 2.399 al lado
de un "Hush puppies" con 2. Eran cinco fallos distintos.

### 1. El panel no podía decir otra cosa

La pantalla filtraba los códigos **antes** de consolidar, con la lista del
espejo (`codigos_a_cargar`, que solo devuelve los que FALTAN). O sea que de las
cuatro situaciones que el panel sabe repartir —`Ya visible`, `Cargado sin
publicar`, `Falta cargar`, `No se puede cargar`— **solo podía salir la
tercera**: los tres primeros números eran el mismo dato tres veces, "se
actualizan" estaba clavado en 0 y la cobertura en 0,0 % pasara lo que pasara.

Ahora se consolida el catálogo entero de las demás webs y **la situación es un
resultado, no un filtro previo**. Las cinco tarjetas reparten el total y suman
el total; hay un test que lo comprueba.

**Lo que se GENERA sigue siendo solo lo que falta.** Los cargados sin publicar
se publican, no se recargan —recargarlos les reescribiría la ficha sin que
nadie lo pida—, que es la misma regla que ya seguía el espejo.
`codigos_cargables` y `productos_para_matrixify` reciben ahora las situaciones
que entran.

### 2. `marca_de_producto` devolvía un CENTINELA, no vacío

Cuando no sabe la marca devuelve la cadena `"Sin marca"`, que es **verdadera**.
La consolidación tomaba "el primer valor no vacío" del grupo, así que ese
centinela **ganaba**: un producto sin metacampo en la primera web salía "Sin
marca" aunque la segunda lo tuviera perfectamente etiquetado.

### 3. La marca se leía sin saber de qué web salía

Se resolvía después, sobre el producto suelto, y para entonces ya no se sabía
en qué tienda estaba. Ahora se resuelve **con el sitio en la mano** y hay dos
respaldos nuevos, en este orden:

| # | De dónde | Cuándo |
|---|---|---|
| 1 | `custom.marca` | siempre que esté |
| 2 | un tag de marca conocida | productos que creó esta app |
| 3 | **el `Vendor`, si no es el de una tienda** | productos cargados por fuera |
| 4 | **la única marca del sitio** | Columbia.pe, Vans.pe, Patagonia.pe |

El **paso 3 es el que pidió el usuario**: "del proveedor que también dice la
marca". En los productos que crea esta app el vendor es el de la TIENDA
(`rockfordpe`), el mismo para todas sus marcas —por eso CLAUDE.md dice desde
siempre que no sirve—, pero en los cargados por fuera trae la marca de verdad:
de ahí salen los "Massimo Cerutti" del catálogo. **Sin la lista de vendors de
las tiendas ese paso no se hace**: sin poder distinguirlos, `rockfordpe` pasaría
por marca y el catálogo entero de Rockford saldría bajo una marca inventada, que
es peor que "Sin marca". Y un vendor que **ES** una marca conocida vale siempre,
aunque coincida con el vendor de una tienda: `Vans` es las dos cosas a la vez.

El **paso 4** no adivina: solo responde donde hay UNA respuesta. Rockford.pe
vende cuatro marcas y HushPuppies.pe cinco; ahí se queda en "Sin marca".

Los tres respaldos van también a `engines/load_status.inventario` y a
`engines/espejo_supermall`, así que el Status de carga y el espejo cuentan igual.
**Dos lectores del mismo producto se separan sin que nadie lo note.**

### 4. La misma marca partida en dos por una mayúscula

"Hush Puppies" (2.399) y "Hush puppies" (2) eran dos filas de la tabla. Ahora
`marca_de_producto` devuelve siempre el nombre **canónico** de
`marcas_conocidas` cuando el texto coincide sin distinguir mayúsculas, gane el
paso que gane. Hay un test que exige una sola fila en el hueco por marca.

### 5. Columbia está en Columbia.pe **y** en Rockford.pe

El mismo producto está en las dos webs. Por identidad (`clave_de_producto`) ya
salía UNA ficha —no había duplicado en el archivo—, pero la ficha se armaba con
la web que cayera primero en el orden de `SITE_CONFIGS`, que no es una razón.

Ahora manda **la tienda propia de la marca** (`sitio_propio_de_cada_marca`, que
sale de `SITE_CONFIGS` y no de una lista escrita a mano): la de Columbia.pe es
la que su equipo mantiene. Los tres criterios, en orden: sitio propio de la
marca → prendido y visible → orden declarado. Cada ficha dice ahora en
`Web principal` de cuál salió y en `En cuantas webs` en cuántas está.

Los sitios ESPEJO quedan fuera: Supermall.pe no es la tienda de nadie.

### El destino sin leer ya no pasa por destino vacío

En la captura, **Supermall.pe devolvía Error** —un HTTP 401 por token vencido,
que solo se veía yendo a su Dashboard— y la pantalla siguió adelante. Con el
catálogo del destino sin leer, TODO sale como "falta cargar" y **generar esa
carga crearía por duplicado miles de productos que ya existen**. El motor ya lo
distinguía (`resumen["destino_leido"]`, la misma regla del espejo); la pantalla
no lo miraba. Ahora corta, y **enseña el motivo**: la tabla de estado de los
seis sitios con su columna `Detalle` va en la propia pantalla. Un error sin su
motivo no se puede arreglar.

### Lo que se hacía en cada rerun

Con el catálogo completo, `filas_para_tabla` más su DataFrame costaba **0,24 s
medidos por clic** —y la pantalla tiene cuatro controles—. La tabla, el hueco,
los totales y la lista de códigos se calculan **una vez, al analizar**, igual
que `resumen_centry_para_pantalla`. Medido: 35.000 fichas → tabla de 10 MB.

Lo mismo en Status de carga, que ejecuta el cuerpo de las **seis** pestañas en
cada rerun: el detalle del espejo y los no visibles se arman ya como DataFrame
al actualizar el status, y `_tabla_status` deja pasar tal cual lo que ya es uno.

Consolidar el catálogo entero cuesta **3,0 s y 39 MB** medidos con 48.000
productos en cinco sitios, y se paga una vez por análisis.

`scripts/test_carga_supermall.py` pasó de 31 a **57 pruebas**.

---

## 5 tricies. Limpieza: 700 líneas sin llamador y los archivos corrompidos (septiembre 2026)

Pendientes 5 y 6 de la sección 8, y la regla 6 ("nunca dejes una función sin
llamador"), que llevaba **16 funciones** incumplida.

**Borradas por AST, no a ojo.** Se recorren todos los `.py` del repositorio
contando referencias por `Name` y por `Attribute`, y se comprueba además que el
nombre no aparezca en ningún texto (los tests de este repo leen el código con
`inspect`, así que una referencia solo en una cadena también cuenta). Solo se
borra lo que aparece **una vez**: su propia definición. Y se repite hasta que la
cuenta da cero, porque borrar una arrastra a las que solo ella usaba —así
cayeron `_commercial_values_rows`, `_url_is_reachable_image`,
`BRAND_STATE_LABELS` y las cinco `*_for_column` de `catalog_rules`.

| Dónde | Qué se fue |
|---|---:|
| `app_matrixify.py` | 16 funciones · **482 líneas** |
| `generate_columbia_matrixify.py` | 3 funciones |
| `catalog_rules.py` | 6 funciones |
| `ticket_system.py` | `brand_state` + su tabla de etiquetas |
| `engines/enrich.py` | `pares_de_texto` |

Entre ellas **`render_header`, `render_active_site_card` y
`render_input_upload_card`**: tres paneles definidos y nunca invocados, que es
exactamente el fallo que la regla 6 existe para impedir.

**`engines/normalize.py` (525 líneas) y `engines/excel_io.py`** se fueron con sus
dos archivos de pruebas. Quedaron de la Fase 0 descartada y **no los importaba
nadie más que sus propios tests**. Con ellos se va una de las dos
`normalize_size` de la sección 9: la que queda es la de
`generate_columbia_matrixify`, que es la que usa la app.

**Los archivos corrompidos de la raíz** (sección 10, verificados otra vez por
firma binaria antes de borrarlos): `config.toml` (que era JavaScript),
`download` y `download (1)` (copias del `.gitignore`),
`dimensiones_productos.xlsx` y `matrixify_modelo.xlsx` (imágenes WEBP),
`formato_input_catalog_control_center.xlsx` (texto plano) y los **nueve
`assets/logo_*` de la raíz**. Los dos `.xlsx` de verdad siguen en `data/`, que
es de donde los lee la app, y los nueve logos buenos siguen en `assets/brands/`.
Se confirmó por hash que los de la raíz están corridos una posición:
`assets/logo_sorel.webp` era, byte a byte, `assets/brands/logo_rockford.webp`.

**Una prueba que se apoyaba en un archivo roto se fabrica ahora el suyo.**
`test_un_archivo_corrupto_no_revienta` abría `assets/logo_columbia.png` (2 bytes)
y hacía `skipTest` si no estaba: borrar el archivo la habría dejado **verde sin
comprobar nada**, que es peor que roja. Ahora escribe sus dos bytes en un
temporal.

**Tres archivos de la raíz que se llamaban `test_*` y no eran pruebas.**
`test_catalog_rules.py`, `test_partial_maintenance_validations.py` y
`test_brand_commercial_input.py` eran generadores de Excel de un solo uso: los
dos primeros leen un archivo de una ruta de OneDrive de Windows escrita a mano
(`C:\Users\hcamara\...`), así que en Linux fallan siempre, y los tres escriben
en `parents[1]` — como si vivieran en `scripts/` — o sea **fuera del
repositorio**: correr la suite dejaba un `.xlsx` en `/home/user/outputs/`.
Además se llaman **igual** que las pruebas de verdad de `scripts/`, así que
cualquier runner recoge la equivocada. Las de `scripts/` se quedan; estas se
fueron.

**Y el BOM de `app_matrixify.py` desapareció.** El archivo empezaba con
`U+FEFF`, y eso hace que `ast.parse` del contenido crudo falle con
`SyntaxError: invalid non-printable character`. Python lo tolera al importar,
pero cualquier herramienta que lea el archivo como texto se tropieza. Ya no está.

---

## 5 duovicies. El catálogo se leía INCOMPLETO y no lo decía nadie (septiembre 2026)

Dos fallos de la lectura de Shopify detrás de los dos síntomas reportados:
`Patagonia.pe (Error), Supermall.pe (Error)` con los otros cuatro sitios bien,
y totales que no cuadran con la tienda.

### El tope de 5.000 productos, en silencio

`fetch_products` tenía `max_products=5000` por defecto y `_bulk_reensamblar`
hacía `break` **sin decir nada** al alcanzarlo. **Rockford.pe pasa de 9.000
modelo-color.** Y ese catálogo es el dato con el que se decide si un producto se
**crea** o se **actualiza**: lo que se quedaba fuera del tope se volvía a crear
y quedaba **duplicado en la tienda**.

`PRODUCTOS_MAXIMOS` son 50.000, ajustable con `max_products` en Secrets, y las
tres lecturas comparten el tope (`_limite_de_productos`) — si una leyera hasta
5.000 y otra hasta 50.000, el catálogo cambiaría según por dónde se leyó, que es
lo que ya se paga con las dos `normalize_size`. Un tope alto no cuesta memoria
por sí mismo: es un techo, no una reserva.

Alcanzar el tope **se avisa**, por el mismo `progreso` que ya reporta el avance,
y en las dos lecturas: masiva y paginada.

### El respaldo de la lectura masiva atrapaba solo `ShopifyApiError`

Un corte de red bajando el JSONL, un gzip a medias o un timeout se propagaban y
el **sitio entero quedaba sin leer** — que es exactamente cómo se ven dos sitios
en "(Error)" mientras los otros cuatro entran. La lectura paginada existe
precisamente como respaldo, así que ahora se cae a ella ante **cualquier** fallo
y lo dice.

### Y el parte de la lectura se tiraba

El aviso del motor es lo único que dice que se alcanzó el tope o que se cayó a
la paginada. `cargar_catalogos_de_todos_los_sitios` lo **recoge** por sitio —
dentro del hilo solo se acumula texto, porque `st.session_state` no se puede
tocar desde un hilo — y lo deja en `Detalle`.

- **El estado se queda en `"Leido"`.** Las pantallas comparan contra ese valor
  exacto para saber qué sitios faltaron, así que un estado nuevo tipo "Leido con
  avisos" contaría un sitio bueno como caído. Hay un test que recorre los
  estados que la función escribe y falla si aparece uno más.
- El error de un sitio lleva ahora el **tipo** de la excepción: un `URLError` a
  secas dice "urlopen error" y no distingue la red del token.
- **Las dos pantallas que leen los seis catálogos avisan igual** (Status de
  carga y Carga Supermall). Si una avisara y la otra no, el mismo total se
  leería bien en una pantalla y mal en la otra. El aviso mira solo los sitios
  LEÍDOS: uno caído ya tiene el suyo.

`scripts/test_lectura_completa_del_catalogo.py` (17 pruebas) fija todo esto; 15
fallan con el código anterior.

---

## 5 tervicies. La exportacion a Excel era lo que tumbaba el contenedor (septiembre 2026)

Auditoria completa de rendimiento y estabilidad. Todo medido, nada supuesto.

### El crash: `dataframe_to_excel_bytes` armaba el libro con openpyxl

`requirements.txt` lo dice desde hace meses -"openpyxl arma el libro entero en
memoria y es lo que tumbaba el proceso con el catalogo completo"-, pero solo se
habia cambiado `columbia_to_excel_bytes`. **La funcion que usan los 17 botones
de descarga se habia quedado atras.**

Medido con un Matrixify de 40.000 filas x 107 columnas:

| | tiempo | RSS |
|---|---:|---:|
| openpyxl (lo que habia) | **70,8 s** | **+1,79 GB** |
| xlsxwriter | 42,5 s | +0,49 GB |
| xlsxwriter + memo, en el rerun | **0,41 s** | +3 MB |

El contenedor da **1 GB POR APP**. La version vieja se lo comia entero ella
sola, con una sola persona pulsando una sola pantalla.

Y no hacia falta pulsar nada: **`st.download_button` exige los bytes POR
ADELANTADO**, no acepta un callable, asi que 17 botones rearmaban su Excel en
CADA rerun aunque nadie los tocara. Es el mismo problema que ya tenian los
adjuntos de las solicitudes, solo que aqui no se paga red sino CPU y RAM.

**El memo va por CONTENIDO, no por identidad.** Una huella de las hojas cuesta
0,38 s contra los 70 s de armar el libro. Con `id(df)` un frame modificado en el
sitio devolveria el Excel viejo; con el contenido, no puede.

**`constant_memory` de xlsxwriter NO se usa.** Baja el pico a cero, pero
comprobado: **se pierden datos** -- solo sobrevive la primera columna. Un
exportador que pierde columnas en silencio es peor que uno lento.

### xlsxwriter INTERPRETA lo que escribe, y eso corrompe el dato

Dos cosas que hay que apagar (`OPCIONES_XLSXWRITER`), y que `columbia_to_excel_bytes`
llevaba mal desde que se cambio de motor:

- **Un texto que empieza por `=` sale como FORMULA.** Medido: `"=1+1"` se lee de
  vuelta como `0`, no como el texto que puso la marca.
- **Un texto que parece URL sale como HIPERVINCULO.** Excel admite **65.530
  hipervinculos por hoja** y el Matrixify lleva columnas enteras de URLs de
  imagen: pasado ese numero xlsxwriter avisa y **descarta el resto**.

Comprobado que lo demas no cambia: ceros iniciales (`0012`, `000`, `007`),
tallas (`04-Jun`, `400`, `8.5`, `O/S`), acentos, y las 16 cabeceras que SIAL
espera **con** el espacio final.

### `repair_mojibake_dataframe` recorria TODAS las columnas, celda a celda

Tambien las numericas, donde un marcador de mojibake no puede existir. En cada
exportacion, de cada hoja. Medido: **2,33 s y +141 MB por hoja** en el
Matrixify grande; ahora **0,28 s y +10 MB**.

El descarte es vectorizado y el resultado es identico: una columna sin marcador
dejaba cada valor tal cual de todos modos. Y ahora se recorre **por POSICION**:
con dos columnas que se llaman igual, `repaired[nombre]` devolvia un DataFrame.

### `apply(..., axis=1)` armaba un Series por fila para leer dos columnas

| Donde | antes | ahora |
|---|---:|---:|
| clave Centry sobre el catalogo (30.000 x 104) | 11,84 s | **0,02 s** |
| clave de stock sobre el maestro ARTI (200.000) | 1,37 s | 0,28 s |
| buscadores de los paneles de pendientes | 0,15 s | 0,05 s |

Las tres llaman a **la misma funcion sobre los mismos valores**: lo unico que se
quita es el Series de pandas que se construia y se tiraba por cada fila.

**Con columnas repetidas se cae a `apply` a proposito**: ahi `row.get(nombre)`
devuelve un Series y no un valor. Y el buscador solo toma el atajo si TODAS las
columnas son `object`: si el frame mezcla tipos, el Series de la fila promueve
(un entero al lado de un decimal sale decimal) y el texto sobre el que se busca
cambiaria. Hay pruebas de los dos casos.

### El snapshot del job se recorria una vez POR PRODUCTO

`_sync_job_subset_df` recalculaba la serie de claves sobre el frame **entero**
para sacar las pocas filas de un producto. Con 1.000 productos eran mil pasadas
completas. Ahora el bloque la calcula **una vez** y la pasa.

Y `_create_sync_job` hacia `pickle.dump(source_df.copy())`: una copia del
Matrixify entero -cientos de MB- solo para serializarlo. Pickle no la necesita.

### Las caches de disco no se borraban NUNCA

El disco del contenedor es una **cuota fija**: cuando se acaba, la escritura
falla y la app cae con *"Error running app"* sin decir de que.

- Un catalogo `.pkl` caducado o de otra tienda se **ignoraba** pero se quedaba
  ocupando. Ahora se borra, y tambien el pickle ilegible -- una escritura
  cortada tampoco va a servir nunca.
- Cada proceso de sincronizacion dejaba su registro **y un pickle con el
  Matrixify entero**, para siempre. Se conservan los 10 mas recientes y se tiran
  los de mas de 7 dias, con su pickle. Se mira la fecha del ARCHIVO, no la del
  registro: uno ilegible tambien ocupa.

### `pd.ExcelFile` quedaba abierto, y el libro se parseaba una vez por hoja

Tres sitios abrian el libro sin cerrarlo. Dos ademas hacian
`pd.ExcelFile(path)` solo para leer `sheet_names` y despues
`pd.read_excel(path, sheet_name=...)` **por cada hoja**: el archivo se parseaba
N+1 veces. Ahora se reusa el libro abierto, dentro de un `with`.

### Varios archivos seguidos dejaban uno residente POR SITIO

El prefijo de `read_uploaded_excel_cached` lleva el sitio
(`complete_input_vans`, `complete_input_rockford`...), asi que pasar por tres
sitios con un input grande cargado dejaba tres DataFrames vivos, y ninguno se
soltaba. Ahora se conservan **3** y el cuarto suelta el primero; si esa pantalla
lo vuelve a pedir, el archivo sigue en el `file_uploader` y se relee. Cuesta una
lectura, no la memoria del contenedor.

Ademas el anterior se suelta **antes** de leer el nuevo: guardandolo despues,
los dos convivian mientras se parseaba el segundo.

**El registro va en `session_state`, no en un global.** Streamlit Cloud corre UN
proceso para todas las personas conectadas: en un global, el archivo que abre
una haria soltar el de otra.

### Y una hoja rara ya no tumba la descarga

Una hoja que llega como `None`, un nombre vacio, o dos nombres largos que chocan
al cortarse en los 31 caracteres de Excel (`Duplicate worksheet name`): los tres
tiraban la pantalla entera. Ahora se escriben vacia, como `Hoja`, y desempatados
con un numero.

### Lo medido de punta a punta

Carga real de 1.200 modelos (6.000 filas x 91 columnas, mas la hoja Sial):

| | antes | ahora |
|---|---:|---:|
| exportar el Excel | 13,08 s | **6,56 s** |
| exportarlo otra vez (rerun) | 12,17 s | **0,13 s** |
| RSS pico | 516 MB | **330 MB** |

Cinco archivos seguidos, sin recargar: **13,8 s -> 11,0 s** por archivo y
**+133 MB -> +87 MB** residentes, planos en los cinco.

**Y la salida es IDENTICA.** Comparadas las 6 hojas antes y despues, en los
DataFrames y releyendo el Excel: **cero celdas distintas** de 546.000. La unica
diferencia en todo el trabajo es que un `"=1+1"` que openpyxl **perdia** (volvia
como NaN) ahora se conserva.

### Lo que NO se toco, y por que

- **`inject_custom_css`**: rearmar su f-string cuesta 0,12 ms. Ya estaba medido.
- **`complete_sial_df` en la sesion** (191 MB): bajarlo a disco costaba 9 s de
  I/O por analisis y ya se probo. Es el Pendiente 10, no una regresion.
- **El `main()` del generador** (`generate_columbia_matrixify.py`) sigue con
  openpyxl: aplica `cell.style = "Headline 4"`, que xlsxwriter no hace igual, y
  corre fuera del contenedor. Queda anotado.

`scripts/test_optimizacion_memoria_excel.py` (38 pruebas) fija todo esto; **31
fallan con el codigo anterior**. Las 7 que pasan en las dos versiones son las
que exigen que **nada cambie**: ceros iniciales, tallas, cabeceras con espacio y
el resultado del reparador de mojibake.

---

## 5 quatervicies. "Lo de Supermall no carga" (septiembre 2026)

Reportado asi, literal. No estaba roto: **tardaba 20 minutos**, que desde la
pantalla se ve exactamente igual que colgado.

### Todo el trabajo pesado se rehacia una vez POR BLOQUE

La carga de Supermall va en bloques de 200 codigos
(`SUPERMALL_CODIGOS_POR_BLOQUE`) y llama a
`build_centry_matrixify_from_master` una vez por bloque. Con 11.000 codigos son
**55 llamadas**, y en CADA una se volvia a:

- copiar y normalizar el catalogo de **origen** entero y el de **destino**
  entero, recorrerlos con `forward_fill_product_block` y calcular sus claves;
- construir los dos `lookup` producto a producto;
- y **copiar y normalizar el maestro ARTI COMPLETO** -- 653.000 filas en
  produccion -- para quedarse despues con las 200 filas del bloque.

Nada de eso depende de los codigos del bloque. `supermall_generar` ya sacaba
del bucle `shopify_products_to_matrixify_df` y el maestro -- su comentario lo
dice-- pero **la preparacion cara vivia dentro de la funcion llamada**, asi que
seguia pagandose 55 veces.

Ahora `preparar_contexto_de_codigos` lo calcula **una vez** y el contexto se
pasa a cada bloque. Lo que SI depende de los codigos -- el acotado del maestro,
los siblings de la carga, las filas -- se queda en cada bloque, donde estaba.

**Los frames del contexto no se mutan**: el maestro se acota con `.copy()`
antes de tocarlo. Hay una prueba que lo comprueba, porque si un bloque tocara
el maestro compartido el siguiente veria otra cosa.

### Y dos cosas mas del perfil

- **`groupby` + `.iloc[0]` para armar los `lookup`**: 30 de los 58 segundos de
  una sola llamada. Trocear 11.000 grupos sobre 102 columnas rebana cada bloque
  interno una vez por grupo. `_lookup_por_clave` usa `drop_duplicates`, que
  conserva la primera fila de cada clave y respeta el orden -- **el mismo
  criterio**, sin trocear.
- **`.astype(object)` antes del bucle de filas**, y no es cosmetico: el
  catalogo mezcla columnas de texto de pyarrow con columnas `object`, asi que
  cada `iloc[posicion]` buscaba el tipo comun de las 102 columnas. Solo
  `find_common_type` eran **9,1 de 23 segundos**. El tipo comun que pandas
  calculaba ERA `object`, asi que los valores no cambian.
- **`centry_resolutor(arti)` estaba DENTRO del bucle por producto** y solo
  depende de las COLUMNAS del maestro: se rearmaba una vez por modelo-color.

### Lo medido

Con 11.000 codigos, catalogo de origen de 55.000 filas y destino de 15.000:

| | antes | ahora |
|---|---:|---:|
| preparacion | (no existia) | **2,2 s**, una vez |
| un bloque de 200 codigos | 22,4 s | **2,0 s** |
| **los 55 bloques** | **25,4 min** | **1,9 min** |

Una llamada **suelta** -- que es como la usan Centry y la Carga Sial parcial --
baja de 27,7 s a **4,4 s**, asi que esas dos pantallas tambien van mas rapido
sin haberlas tocado.

**La salida es IDENTICA.** Comparadas las tres hojas (Matrixify, Revision y
Carga Sial) antes y despues, con casos borde a proposito -- productos sin
nombre, sin tipo, sin genero, sin marca, filas descartadas por marca y sin
EAN --: **cero celdas distintas**.

`scripts/test_carga_supermall_rendimiento.py` (13 pruebas) lo fija; **las 13
fallan con el codigo anterior**. Una parte los mismos codigos en bloques y
exige que el resultado sea el mismo que de una sola vez.

---

## 5 quinvicies. El pico de memoria de Carga Supermall, medido con el maestro REAL (septiembre 2026)

Reportado como *"carga todo y cuando lee todo ya no bota nada"*. Esa es
exactamente la forma que tiene un **OOM en Streamlit Cloud**: el contenedor
mata el proceso, no hay traza ni `st.error` -- `run_app()` no llega a
atrapar nada porque el proceso muere entero -- y la pantalla vuelve vacia.

### Lo medido, a la escala del usuario

9.644 fichas consolidadas, 6 catalogos, y el **maestro ARTI de verdad**
(`data/arti.zip`, 653.431 filas). Es la regla de la seccion 5 nonies: un lector
nuevo se prueba con un archivo del TAMANO REAL, nunca con una muestra.

| Paso | antes | ahora |
|---|---:|---:|
| arranque | 137 MB | 137 MB |
| maestro ARTI real | 255 MB | 255 MB |
| 6 catalogos | 434 MB | 434 MB |
| origen_df + destino_df | 617 MB | 617 MB |
| contexto preparado | 829 MB | 829 MB |
| **durante los bloques** | **836 MB** | **639 MB** |
| **PICO FINAL** | **950 MB** | **756 MB** |

**El contenedor da 1.024 MB PARA TODA LA APP.** Con 950 MB basta con que entre
una segunda persona para que el proceso muera, y al morir se cierran TODAS las
sesiones.

### De donde salian los 200 MB

`preparar_contexto_de_codigos` devolvia `shopify_df` y `destino_df` -- una copia
entera del catalogo de origen y otra del de destino -- y los retenia durante
toda la generacion. Comprobado con AST: dentro de
`build_centry_matrixify_from_master` esos dos nombres **se asignaban y no se
leian ni una vez mas**. Lo que el bucle consume son los `lookup`, los siblings y
el maestro acotado.

Ahora el contexto lleva solo eso, y `supermall_generar` **suelta** los dos
Matrixify convertidos y la lista de productos de origen en cuanto lo tiene.
Para poder soltarlos, `matrixify_desde_codigos_modelo_color` ya no reconstruye
el catalogo cuando le pasan un contexto: lo que armaba se descartaba sin usarse.

`destino_es_el_origen` conserva el unico dato que si hacia falta de esos frames:
cuando no se pasa destino, el destino ES el origen (Centry, Carga Sial).

### Y la hoja de Revision cambiaba entre ejecuciones

Destapado al comparar dos versiones: **la misma carga, ejecutada dos veces,
escribia seis avisos distintos**. `avisos_de_talla_a_issues` hacia
`sorted(tallas_vistas, key=size_sort_key)` sobre un **`set`**, asi que cuando
dos tallas empatan en la clave -- `6` y `60`, `SM` y `S/M` -- el orden lo
decidia la iteracion del conjunto, que depende del hash de las cadenas y cambia
**en cada proceso**.

El desempate es ahora la talla en texto. Un informe que cambia entre ejecuciones
no se puede comparar con el anterior -- es la misma regla que ya seguia la
consolidacion de Supermall. Es un fallo **preexistente**, no una regresion:
comprobado ejecutando dos veces el codigo anterior.

### La salida es IDENTICA

Comparadas las tres hojas con **datos del maestro real** (1.500 codigos de
Columbia, 7.031 filas de Matrixify y 7.003 de Carga Sial): **cero celdas
distintas** en Matrixify y en Carga Sial. Y ahora dos ejecuciones seguidas dan
**cero diferencias** tambien en Revision, que antes no pasaba.

### Lo que sigue sin resolverse

756 MB de 1.024 **sigue siendo mucho para una sola sesion**. Lo que queda vivo
es lo que de verdad se usa: el maestro ARTI dos veces (el crudo en sesion y el
normalizado en el contexto), los 6 catalogos en `session_state`, los `lookup` y
el Matrixify resultante. Bajar de ahi es el Pendiente 7 -- mover el trabajo
pesado al worker --, no un ajuste mas.

`scripts/test_carga_supermall_rendimiento.py` pasa de 13 a **16 pruebas**.

---

## 5 sexvicies. El Handle salia a medias, y el tipo no se traducia (septiembre 2026)

Reportado como *"el Handle y otros campos salen incompletos/incorrectos"*. Eran
**cuatro** fallos distintos, todos en la carga POR CODIGOS -- la que sirve a
Centry, a la Carga Sial parcial y a **Carga Supermall** --, y todos reproducidos
contra el maestro real antes de tocar nada.

### 1. El Handle era el codigo pelado

Un producto que no esta en la tienda destino recibia `key.lower()`:
`10001330-n11`. La carga completa del MISMO producto arma
`cooler-pfg-welded-harbody-10001330-n11-negro` con `build_product_handle`.

Medido sobre una carga real: **2.448 de 2.448 filas** salian asi. Y el handle
**es la URL del producto** en la tienda.

Ahora las dos rutas llaman a `build_product_handle`. El que YA existe en el
destino conserva el suyo: cambiarselo romperia su URL y Shopify lo trataria
como un producto nuevo.

### 2. El handle estaba escrito en DOS sitios

Lo destapo una prueba nueva despues de arreglar el primero: los **siblings** se
armaban en un bloque aparte, ANTES del bucle, con la regla vieja. O sea que el
producto se listaba a si mismo como hermano con un handle **que no existe**.

Ahora el handle se calcula UNA vez, en el bucle, y los siblings se rellenan al
terminar, cuando ya se conocen los handles de todos los colores del modelo. Un
codigo que no dejo ninguna fila se sigue contando como hermano, igual que antes:
lo que cambia es CON QUE handle se le nombra, no QUIENES son hermanos.

### 3. El Type se copiaba del ORIGEN sin traducir

La carga por codigos nunca llamaba a `resolve_product_type`. Copiaba el `Type`
del catalogo de origen tal cual, asi que una carga de Supermall se llevaba los
nombres de Columbia.pe y **Rockford -- que es multimarca -- heredaba la
clasificacion de la marca de la que viniera el producto** en vez de la suya.

La regla vive ahora en `tipo_de_prenda_para_sitio`, que usan las DOS rutas.
Escrita dos veces, el mismo producto se clasificaria distinto segun por donde
pasara: es la trampa de las dos `normalize_size`.

**Traducir no puede vaciar el dato.** La cascada es: nombre del sitio ->
canonico -> el valor tal cual. El ultimo escalon importa porque
`tipo_para_sitio` devuelve `""` cuando el sitio no vende esa prenda, y
**Rockford no vende ocho de los sesenta tipos**. Medido: `Chaquetas` -> `Casacas`,
`Poleras` -> `Polos`, y un tipo que el diccionario no conoce sale igual que entro.

### 4. `custom.color` se leia de la tienda y se TIRABA

`shopify_api.fetch_products` lo lee, esta en la plantilla de escritura, y
`CENTRY_COLUMNAS_COLOR` lo busca como fuente del color. Pero
`shopify_products_to_matrixify_df` construye el frame con
`columns=default_columns` y esa columna **no estaba en la lista**: el valor que
el `row.update` le asignaba se descartaba en silencio.

Consecuencia: el color no llegaba ni a `Option2 Value` ni al handle. Con la
columna en su sitio, `AZUL MARINO` llega hasta
`casaca-hombre-bm1-a-azul-marino`.

Se recorrieron con AST todas las claves que ese `row.update` asigna contra las
columnas que el frame conserva: **era la unica** que se perdia.

### Y Modelo+Color no se puede duplicar

Dentro de una llamada el `groupby` colapsa un codigo repetido, pero la carga va
**por bloques de 200**: el mismo codigo en dos bloques distintos deja el
producto DOS VECES en el Matrixify concatenado. Se deduplica en los dos sitios
-- al entrar en `build_centry_matrixify_from_master` y, sobre todo, **antes** de
partir en bloques en `supermall_generar` --, conservando el orden de la primera
aparicion.

Verificado sobre 1.200 codigos del maestro real (5.529 filas): **0 pares
(Mod-Col, SKU) repetidos, 0 Mod-Col con mas de un handle, 0 handles compartidos
por dos Mod-Col**.

### Una prueba que se quedo obsoleta a proposito

`test_shopify_tiene_prioridad` distinguia las dos fuentes por sus valores:
Shopify `"Chaquetas"` y BigQuery `"Casacas"`. Desde que el tipo se traduce, los
dos salen `"Casacas"` y **la prueba ya no distinguia nada**. Se reescribio con
dos tipos que no son sinonimos, para que siga comprobando lo suyo, y se le
agregaron dos casos: que el sinonimo se normaliza y que un tipo desconocido no
se vacia.

`scripts/test_handle_tipo_y_duplicados.py` (18 pruebas) fija todo esto; **10
fallan con el codigo anterior**. Las 8 que pasan en las dos versiones son las
que exigen que **nada cambie**: SKU y tallas intactos, sin duplicados, y el
handle de un producto que ya existe.

---

## 5 septvicies. `use_container_width` estaba caducado, y las pantallas no se probaban (septiembre 2026)

### La bomba de relojeria: 105 llamadas a un parametro retirado

Streamlit avisaba en cada arranque: *"`use_container_width` will be removed
after 2025-12-31"*. Esa fecha **paso hace nueve meses**. La app lo usaba **105
veces** (76 `dataframe`, 25 `button`, 4 `download_button`): el dia que Streamlit
lo quite de verdad, cada una de esas llamadas levanta `TypeError` y **no queda
ni una pantalla en pie**.

Cambiado a `width="stretch"` / `width="content"`. Antes de tocarlo se
comprobo lo unico que importaba: que **streamlit 1.50** -- el minimo que declara
`requirements.txt` -- ya acepta `width` en los tres elementos. Se instalo esa
version en un entorno aparte para verlo, no se supuso.

### Y lo que faltaba de verdad: entrar a la app

Las ~1.800 pruebas del repo cubren los MOTORES. Los fallos que llegan a
produccion viven en el **pegamento** con la pantalla, y este repo ya se llevo
dos:

- `render_status_de_carga` pedia `kpis["Marcas con catálogo"]` con tilde: un
  `KeyError` que tumbaba la pantalla entera (seccion 5 quater).
- Tres fallos dejaron el Mantenedor de Tallas sin efecto y **ninguna de sus 34
  pruebas los vio**, porque todas prueban el motor (seccion 5 sexdecies).

`scripts/test_pantallas_reales.py` entra a la app -- `authenticated` en
`session_state`, sin credenciales -- y **recorre cada pantalla del menu, cada
opcion de Carga parcial, cada sitio de `SITE_CONFIGS` y pulsa todos los botones
de accion**, mirando `at.error` ademas de `at.exception` (regla 4).

Sin Secrets cada pantalla toma su camino de "no configurado", que es tambien un
camino que hay que probar. Esos avisos se distinguen de un fallo por texto
(`AVISOS_DE_CONFIGURACION`): son el comportamiento correcto, no un error.

**Resultado: las 8 pantallas se dibujan, los 6 sitios se dibujan, todas las
opciones de Carga parcial se dibujan y ningun boton levanta una excepcion.**

### "Analizar Input no ejecuta"

No estaba roto: **sin input el boton no se dibuja**, que es correcto. Lo que
estaba mal era el aviso. `can_process_complete` pide dos cosas -- el input
comercial y, con origen "Respaldo Excel", el respaldo del sitio -- y el `else`
decia siempre lo mismo: *"Carga el input comercial para comenzar"*. Quien ya lo
habia cargado y solo le faltaba el respaldo leia que le faltaba **lo que si
tenia**, y del boton no habia ni rastro.

Ahora se nombra exactamente lo que falta. Es la misma regla que ya seguia
`render_boton_carga_remota`: **un boton que no se dibuja y no explica por que se
lee como "no funciona"**.

### Lo que NO se pudo medir

Los reruns por pantalla salen todos en ~1,2 s, y **eso no es tiempo de la app**:
el perfil lo desmiente -- son 117 `time.sleep` del poller de `AppTest`, que
espera al hilo del script. `AppTest` no sirve para medir rendimiento; sirve para
comprobar que la pantalla se dibuja. Las mediciones de rendimiento buenas siguen
siendo las de las secciones 5 tervicies, quatervicies y quinvicies, hechas con
cProfile sobre las funciones pesadas.

`scripts/test_pantallas_reales.py` (10 pruebas).

---

## 5 octovicies. BigQuery bajaba TODO por REST (septiembre 2026)

El log de Streamlit Cloud repetia el mismo aviso una vez por consulta:

```
UserWarning: BigQuery Storage module not found, fetch data with the REST
endpoint instead.
```

No es un error -- la app arranca bien, `Uvicorn server started` esta ahi
mismo --, pero dice que **cada** resultado baja por el endpoint REST.
`google-cloud-bigquery-storage` no estaba en `requirements.txt`, aunque
`pyarrow` y `db-dtypes` si. Con el maestro ARTI, que son 653.000 filas, eso no
es cosmetico: la Storage API entrega el mismo resultado en Arrow y en
streaming.

**Pero instalarlo a secas podia ROMPER lo que hoy funciona.** La Storage API
pide un permiso IAM que el REST no pide (`bigquery.readsessions.create`). La
libreria cae sola a REST cuando el paquete NO esta -- eso es justamente lo que
avisaba --, pero cuando esta y a la cuenta de servicio le falta el permiso,
`to_dataframe()` **levanta** y la pantalla se queda sin KPIs.

Por eso las tres lecturas pasan ahora por `bigquery_a_dataframe`, que reintenta
con `create_bqstorage_client=False` -- que es exactamente lo que la app hacia
antes -- ante cualquier fallo. En el peor caso se paga una consulta de mas la
primera vez; a cambio, **tener el paquete nunca puede dejar la app peor que sin
el**. Un fallo que tampoco pasa por REST (credenciales, red) sigue subiendo:
taparlo dejaria la pantalla vacia sin decir por que.

Hay un test AST que recorre cada `.to_dataframe(...)` de los dos archivos y
falla si alguno se queda fuera del respaldo. Sin eso, una lectura nueva
escrita a mano se saltaria el reintento y volveria el fallo de permisos.

Comprobado antes de declararlo: el paquete es wheel puro (`py3-none-any`) y su
`grpcio` tiene wheel `manylinux` x86_64 para **cp314**, que es el Python de
Streamlit Cloud. No hay que compilar nada en el arranque.

`scripts/test_bigquery_storage.py` (10 pruebas); 9 fallan con el codigo
anterior.

---

## 5 novovicies. "Generar la carga de Supermall" se quedaba sin memoria (septiembre 2026)

Reportado literal: *"le di click a generar excel y cargo todo, termino y se
quedo asi; ya paso 20 min y no sale nada"*.

**No estaba colgado y no habia excepcion.** Es la forma exacta que tiene un
OOM en Streamlit Cloud: el contenedor mata el proceso, no hay traza ni
`st.error` -- `run_app()` no llega a atrapar nada porque muere el proceso
entero -- y la pantalla se queda como estaba.

### Lo medido, a la escala del usuario

8.928 codigos, 38.423 filas de Matrixify y el **maestro ARTI de verdad**
(653.431 filas). Con catalogos de PRUEBA, o sea **sin** los seis catalogos
reales que en produccion viven en `session_state` (+179 MB medidos en su dia):

| | antes | ahora |
|---|---:|---:|
| `supermall_generar` | 183,6 s | 183 s |
| ...de los cuales, los 45 bloques | 107,2 s | 110 s |
| ...la hoja Carga Sial | 69,7 s | 68 s |
| armar el Excel | 36,1 s | 36 s |
| **PICO** | **1.007 MB** | **710 MB** |
| residente al terminar | 932 MB | 663 MB |

**El contenedor da 1.024 MB PARA TODA LA APP.** Con 1.007 MB y los seis
catalogos de verdad encima, no cabe.

**Los bloques NO eran el problema y no son superlineales**: 2,2 s cada uno,
medido del primero al ultimo. Lo que mataba el proceso era lo que se quedaba
vivo mientras tanto.

### Que se estaba llevando la memoria

Medido con `memory_usage(deep=True)` sobre los objetos vivos al terminar:

| | |
|---|---:|
| **maestro ARTI** | **336,9 MB** |
| Matrixify | 70,5 MB |
| Carga Sial | 34,3 MB |
| Revision · tabla · Excel | 12,7 MB |

O sea: **el maestro pesa cinco veces mas que el resultado**. Cinco cosas, de
mayor a menor:

1. **El maestro ARTI entero se quedaba en `session_state` durante toda la
   generacion y todo el Excel.** En cuanto el contexto esta preparado, lo que
   el bucle lee es la copia ACOTADA -- unas 40.000 filas de las 653.431 --, no
   el maestro. `olvidar_arti_de_la_sesion` lo suelta ahi mismo, y tambien la
   referencia local (si no, borrarlo de la sesion no libera nada). Se paga que
   la proxima pantalla que lo necesite lo relea: **el trato es ese o que el
   proceso muera a mitad de la carga**.
2. **El contexto llevaba el maestro normalizado ENTERO.** Ahora se acota a los
   codigos de toda la carga (`preparar_contexto_de_codigos(codigos=...)`). Es
   exactamente la UNION de los filtros que cada bloque aplica despues, asi que
   cada bloque encuentra las mismas filas. Va **despues** de los diagnosticos:
   esos son sobre el estado del maestro, no sobre esta carga, y acotar antes
   cambiaria la hoja de Revision. Los dos llamadores le pasan los codigos, asi
   que Centry y la Carga Sial parcial ahorran lo mismo.
3. **El contexto seguia vivo durante la hoja Sial y el Excel**, que es donde
   mas memoria se pide. Se suelta en cuanto termina el ultimo bloque, junto con
   las listas de partes ya concatenadas.
4. **Copias que no hacian falta.** La lista de 38.000 diccionarios de la hoja
   Sial se suelta antes del `fillna`, que copia; `filter_centry_size_rows`
   recibe `copiar=False` de las dos hojas Sial -- que acaban de construir su
   frame y lo reemplazan con el resultado --; y la exportacion pregunta
   (`hoja_necesita_reparacion`) antes de llamar a `repair_mojibake_dataframe`,
   que copiaba la hoja entera aunque no hubiera ni un marcador que arreglar.
5. **`dataframe_to_excel_bytes` copiaba el archivo entero con `getvalue()`**
   aunque no fuera a memoizarlo. El tamano se mide ahora con
   `getbuffer().nbytes`, que no copia.

Y en la pantalla: los conteos se sacan **antes** del Excel y los tres frames
grandes se sueltan **en cuanto el Excel esta armado**, en vez de quedarse vivos
durante todo el resto del dibujado.

### La salida es IDENTICA

Comparadas con datos del maestro real, antes y despues: **cero celdas
distintas** en el Matrixify, en las dos hojas Carga Sial (la del sitio y la de
Centry), en la hoja de Revision y en las cuatro hojas del Excel releido --
incluida una hoja con mojibake a proposito, que se sigue reparando. El
Matrixify de entrada queda intacto (es lo que protege el `copiar=True` por
defecto).

### Lo que sigue sin resolverse

710 MB de 1.024 **sigue siendo la pantalla mas pesada de la app**, y con los
seis catalogos reales en sesion quedan unos 890 MB. Cabe, pero con dos
personas cargando a la vez sigue sin caber. Bajar de ahi es el **Pendiente 7**
-- mover el trabajo pesado al worker que ya esta desplegado en Render --, no un
ajuste mas.

`scripts/test_supermall_pico_de_memoria.py` (27 pruebas) fija todo esto; 17
fallan con el codigo anterior.

---

## 5 trigies. El calzado no salia en tallas PE (septiembre 2026)

Reportado con una captura de la hoja Carga Sial: *"las tallas no se estan
generando por las guias de tallas que te pase de Vans"*. Reproducido contra el
maestro real con la bota `1424692-2KQ` de Columbia antes de tocar nada. Eran
**cuatro** fallos distintos y ninguno era el que parecia.

### 1. La curva la votaban el `0` y las internas `K`

El maestro trae, junto a las tallas de verdad, un `0` de cabecera y codigos
internos tipo `K901`. Los dos se borran mas adelante -- `final_variant_filter`
los quita y `talla_sirve_para_sial` los deja fuera de la hoja --, pero se
colaban en la CURVA, que es lo que decide en que escala esta el calzado:

```
0, 50, 55, ..., 100, K901  ->  "no cabe en ninguna escala conocida"
50, 55, ..., 100           ->  entre diez: la curva esta en US
```

Con la curva sin interpretar, **el producto entero se quedaba sin convertir**.
Un valor que no es una talla no puede votar sobre la escala de las que si lo
son: `curva_de_tallas_reales` lo quita antes de leerla.

### 2. El conversor se quedaba sin genero

Un US 8 de hombre es PE 40.5 y uno de mujer 38.5, asi que **sin genero no se
convierte**. La hoja Sial ya resolvia el genero con una cascada -- primero el
dato (`custom.genero`, `Genero` del maestro) y, si falta, el texto de la ficha
-- y el conversor solo miraba el dato: una **"Bota Para Mujer Waterproof"** sin
el metacampo puesto se publicaba en US y la hoja de Revision decia "no se sabe
el genero del producto", con la palabra "Mujer" en el titulo de la fila de al
lado. Ahora los dos preguntan por `centry_gender`. **El dato sigue mandando
sobre el texto**: un `custom.genero` que diga Masculino no lo pisa un titulo.

### 3. Sin guia propia no se convertia -- y ahora la de Vans es la POR DEFECTO

**Decision del usuario, septiembre de 2026**, que revierte la de la seccion 5
novodecies: la guia de Vans -- la unica confirmada -- pasa a ser la guia por
defecto del calzado (`registrar_guia_por_defecto`).

Lo que se gana: el catalogo sale entero en una sola escala. En Supermall.pe,
que publica en PE, tener Columbia en US y Hush Puppies en PE en la misma tienda
es justo lo que el filtro de talla no puede resolver.

**Lo que se arriesga, y hay que saberlo:** la equivalencia de Vans puede no ser
la de la otra marca. Por eso **cada conversion hecha con la guia por defecto se
REPORTA** en la hoja de Revision, marca por marca; si alguna no cuadra, se ve y
se le registra la suya con `registrar_tabla`, que es una hoja de Excel y no un
`if`. Y la puerta se puede cerrar: quitar el registro por defecto devuelve el
comportamiento anterior, y hay una prueba que lo comprueba.

`hay_conversion(marca)` responde la misma pregunta para la CARGA y para el
Mantenedor de Tallas. Si el mantenedor mirara solo la guia propia, la carga
convertiria el calzado de Columbia y el mantenedor lo dejaria como esta: el
mismo producto saldria distinto segun por donde pasara.

### 4. `Talla Web ` salia del codigo del maestro, no de la talla publicada

`Talla Web ` es **la talla que ve el comprador**, y esa es la que se escribe en
la ficha (`Option1 Value` del Matrixify). Se recalculaba desde `Talla` -- el
codigo del maestro --, asi que con el calzado convertido la hoja del almacen
decia `5` y la tienda `34.5` **para el mismo SKU**. Ahora sale de la talla
publicada, y solo se rehace desde `Talla` donde el filtro la convirtio en
unica. **La columna `Talla` no se toca**: sigue siendo el codigo del maestro,
que es lo que el almacen espera.

### Y los avisos decian lo contrario de lo que pasaba

- La nota de la curva ("numeros leidos entre 10: la curva esta en US") dice
  COMO se leyo, no que la talla se haya quedado sin convertir, y salia como
  "se publican SIN convertir a PE porque...". Un aviso que manda a buscar un
  problema que no existe es peor que no avisar.
- El `0` y las internas `K` pasaban por el conversor y llenaban la Revision de
  avisos sobre filas que nadie va a ver.

### Que se ve ahora, con la bota real

| | antes | ahora |
|---|---|---|
| Matrixify `Option1 Value` | 5, 5.5, 6, ... 10 (US) | **34.5, 35, 36, ... 41 (PE)** |
| Carga Sial `Talla Web ` | 5, 5.5, 6, ... 10 | **34.5, 35, 36, ... 41** |
| Carga Sial `Talla` | 50, 55, 60, ... 100 | 50, 55, 60, ... 100 (sin cambio) |

`scripts/test_tallas_de_calzado_en_supermall.py` (17 pruebas) fija todo esto;
11 fallan con el codigo anterior. Cuatro pruebas de tres archivos cambiaron de
esperado y es la consecuencia buscada: eran las que fijaban "sin guia no se
convierte".

---

## 5 untrigies. La hoja `Products` no era Matrixify (septiembre 2026)

Reportado con una captura del Excel: la hoja `Products` -- la que se sube a
Shopify -- llevaba `Temporada`, `Coleccion`, `Ocasion`, `Deporte`, `Categoria`
y `SubCategoria`, y `Categoria` con valores del maestro como **`CORE`,
`TRAIL`, `VN_AC_C MENS`, `COLUMBIA`, `MALETINES`**, que ni son columnas de
Matrixify ni son una categoria.

El propio codigo ya lo decia desde que se escribieron -- *"No son columnas
Matrixify: viajan solo entre esta funcion y el constructor de Centry"* -- pero
**nadie las quitaba al escribir la hoja**.

### La regla, en un solo sitio

`es_columna_matrixify` decide, y `solo_columnas_matrixify` aplica. Se ejecuta
al **ESCRIBIR**, nunca antes: las hojas Carga Sial y Centry se arman del mismo
frame y necesitan esas columnas, y la sincronizacion con Shopify tambien.

Va dentro de `dataframe_to_excel_bytes`, asi que **una hoja que se llama
`Products` sale limpia la escriba quien la escriba** -- Carga Supermall, la
carga completa o la parcial --, sin que una pantalla nueva tenga que acordarse.

**Se quita por lista, no por adivinanza.** Las columnas de acarreo estan
enumeradas (`COLUMNAS_INTERNAS_DEL_MATRIXIFY`) y todo lo que empieza por `__`
se va; lo demas se conserva si esta en la lista estandar o empieza por un
prefijo que Matrixify acepta (`Metafield: `, `Inventory Available: `...).
Quitar de mas seria PERDER un dato, que es peor que dejar una columna de mas:
por eso lo que no encaja en ninguna de las dos listas **se reporta** en la hoja
de Validacion en vez de desaparecer en silencio.

### `Categoria` solo puede ser tres cosas

Accesorios, Calzado o Vestuario. Manda el diccionario de tipos, que es el dato
confirmado -- un ALPARGATA es Calzado se escriba lo que se escriba en el
maestro --, despues lo declarado y solo al final el texto de la ficha.
`categoria_de_catalogo` es la unica puerta, asi que la hoja Carga Sial y el
metacampo no pueden discrepar.

**Y van como METACAMPO.** `custom.categoria` y `custom.sub_categoria` estan en
la plantilla oficial y son lo que lee la tienda. La carga completa ya los
escribia (via `engines/catalog_map`); **la carga por codigos no**, asi que un
producto cargado por Supermall llegaba a Shopify sin categoria. La
subcategoria es el TIPO de prenda, y los dos salen en Nombre Propio.

### `Body HTML` salia en texto plano

El `Body HTML` de Shopify es HTML. Lo que llega del maestro (`DescripcionWeb`)
y de algunas webs es texto plano, y se copiaba tal cual: la ficha salia en una
sola tira, sin parrafos, y un `&` suelto rompia el marcado.

`asegurar_body_html` **respeta entero lo que ya trae etiquetas** -- reformatear
una ficha que alguien dejo como queria seria cambiarla -- y convierte lo que
no: un `<p>` por parrafo, `<br>` por salto suelto y los especiales escapados.
Un producto sin descripcion en ninguna fuente sale avisado.

### El color solo salia de Shopify

`color` se leia UNICAMENTE del catalogo de origen. Un producto que no esta en
esa web -- o que la tiene sin el metacampo `custom.color` -- se quedaba **sin
color**, y con el se van el `Option2 Value`, el metacampo y el trozo de color
del handle. Todo lo demas (titulo, descripcion, tipo, genero) ya caia al
maestro; el color era el unico que no, con `ColorNombre` en la fila de al lado.

Y sin color se escribia `Option2 Name: Color` con el valor vacio: **una opcion
sin valor**, que Shopify rechaza. Ahora la opcion 2 solo existe si hay color, y
la falta se reporta.

### La validacion, ANTES de exportar

`validar_matrixify` es una FOTO del archivo que se va a subir -- solo lee lo
que el Matrixify ya trae, no es una segunda fuente de verdad -- y sale en su
propia hoja, **Validacion**, y en la pantalla.

La regla critica -- **Modelo + Color no se duplica** -- se comprueba por los
tres caminos por los que se puede romper:

| Sintoma | Que pasaria en Shopify |
|---|---|
| el mismo codigo con dos handles | serian dos productos separados |
| dos codigos con el mismo handle | Shopify los fundiria en uno |
| el mismo par codigo+SKU dos veces | variante duplicada |

Ademas: campos obligatorios vacios **por producto** (una fila de variante sin
`Title` es lo normal en Matrixify -- los campos de producto van solo en la
primera fila --, asi que se mira si NINGUNA fila del handle lo trae), opciones
sin valor, variantes sin talla, categorias fuera de las tres y productos que
mezclan tallas de letra y de numero.

**Las columnas de acarreo conocidas NO se reportan**: un aviso que salta
siempre enseña a ignorar el panel.

### La carga a Shopify desde el servidor

El runner de GitHub Actions ya existia (seccion 5 nonies) con todo lo que
hacia falta -- cola persistente, bloques de 20, reanudacion, reintento y
registro del avance en el repositorio de datos --, pero **solo se podia lanzar
desde Carga completa**. Quien carga Supermall tenia que bajar el Excel y
subirlo a mano, o pasar por otra pantalla: de ahi que la carga "no continuara"
al apagar la laptop.

- `lanzar_carga_remota_suelta` acepta ahora el archivo explicito. Carga
  Supermall pasa el suyo -- ahi el Excel se arma entero en la pantalla y no
  pasa por `recordar_matrixify_de_carga` --. **No se escribio un segundo
  lanzador**: dos motores de carga se separan sin que nadie lo note.
- **No se puede lanzar con bloqueos**: si la validacion encuentra duplicados o
  campos obligatorios vacios, el boton no ejecuta.
- `render_estado_carga_remota` dibuja **Pendiente → Procesando → Completado /
  Error** leyendo el registro REAL del job, el que el runner publica despues
  de cada bloque. No es una barra de la pantalla: se puede cerrar la pestaña y
  volver mañana. Lleva cargados, parciales, con error y pendientes, el enlace a
  la ejecucion y cuando se actualizo.

### La validacion final, releyendo el Excel

Con 400 codigos del maestro real, exportando y **releyendo el archivo**: la
hoja Products sale con 45 columnas y **todas son de Matrixify**; ninguna se
llama Centry; todos los productos traen Handle, Title, Type, SKU y talla;
ningun handle es el codigo pelado; las tallas salen ordenadas y sin mezclar
letras con numeros; la categoria es una de las tres y en Nombre Propio; ni un
producto se queda en texto plano; todos salen con color y ninguna opcion tiene
nombre sin valor; y **cero duplicados de Modelo+Color** por los tres caminos.

Con la bota real `1424692-2KQ`: `34.5, 35, 36, 36.5, 37, 38, 38.5, 39, 40, 41`
en orden, color `Negro`, categoria `Calzado`, subcategoria `Botas`, handle
`bota-para-mujer-waterproof-1424692-2kq-negro` y la hoja Sial diciendo lo mismo
que la tienda. Cero hallazgos en la validacion.

**Una clase inventada BORRA el producto.** `categoria_de_catalogo` devuelve
"" cuando nada la dice, y el Matrixify pasa `por_defecto=""`: poniendole
"Vestuario" a un producto sin tipo, `final_variant_filter` lo trata como
vestuario y le **borra la talla 0** -- que en un producto de una sola talla es
el producto entero. La hoja Carga Sial conserva su valor por defecto, que es
lo que hacia. Lo destapo una prueba de `test_genero_tipo_tallas` que se puso
roja.

**Y tres orfanas que la limpieza de septiembre no vio.** El detector por AST
encuentra `build_matrixify`, `_missing_variant_inputs` y `render_sidebar` sin un
solo llamador en todo el repositorio, y las tres vienen del primer commit: son
**preexistentes**, no de este trabajo. No se borraron aqui porque borrarlas es
una decision aparte y este cambio ya toca la exportacion entera.

`scripts/test_export_matrixify_y_validacion.py` (42 pruebas) fija todo esto;
39 de 40 fallaban con el codigo anterior. Y una prueba de
`test_enriquecimiento` cambio de esperado, que es la consecuencia buscada del
`Body HTML`: la descripcion del maestro sale ahora `<p>Alpargata de verano</p>`
y no en texto plano. Se le agrego el caso complementario -- un body que YA es
HTML no se vuelve a envolver.

---

## 5 duotrigies. Supermall es una WEB, no una marca (septiembre 2026)

Pedido literal: *"la guia de tallas de vans cambiala en todo supermall porque
supermall es una web no una marca entonces tiene que verse igual la talla de
todos los calzados"*.

La guia de Vans ya era la guia POR DEFECTO del calzado (seccion 5 trigies) y
Supermall.pe ya publica en PE (`escala_calzado`), asi que el calzado de
Columbia, Sorel o Keds ya salia convertido. **Quedaban cuatro huecos**, y todos
dejaban unas zapatillas en `8, 9, 10` justo al lado de otras en `40.5, 42, 43`
-- que es exactamente lo que el filtro de talla de la tienda no puede resolver.
Y ademas se busco la guia propia de Columbia, que era el siguiente pedido.

### 1. El calzado UNISEX no se convertia

`escala_de_genero("Unisex")` devuelve `""`, **igual que un producto sin
genero**, y el conversor trataba los dos casos como "no se sabe". Pero no son
lo mismo:

- **No saber el genero** obliga a no convertir: un US 8 de hombre es PE 40.5 y
  uno de mujer 38.5, y adivinar publica una talla inventada como si fuera
  cierta.
- **Unisex es un DATO**, y la guia ya tenia respuesta: publica el calzado
  unisex en la escala de `ESCALA_UNISEX` -- la de hombre --, que es como lo
  publica Vans. Eso ya estaba escrito en `engines/tallas_calzado`; lo que
  faltaba era preguntarlo.

`es_unisex` distingue las dos cosas y `talla_pe_unisex` resuelve la primera.
Medido en el catalogo real de Columbia.pe: **7 de 428 productos de calzado**
son unisex, y los 7 se publicaban en US.

**La misma regla entra tambien por `registrar_tabla`**, que es la puerta de las
guias que llegan por Excel. Escrita solo en la guia del codigo, una marca con
guia propia dejaria su calzado unisex en US y el mismo producto saldria
distinto segun de que marca fuera.

**Las dos salvedades se leen las dos.** Una marca sin guia propia Y un producto
unisex son dos cosas que hay que poder ver en la hoja de Revision, asi que
`convertir` las compone (`guia por defecto, escala unisex`) en vez de pisar una
con la otra. Antes cualquier nota mandaba sobre `POR_DEFECTO`; ahora solo mandan
los PROBLEMAS de verdad -- sin genero, talla desconocida --, que es lo que hay
que arreglar.

### 2. La carga completa preguntaba el genero de otra forma

`build_columbia_matrixify` usaba `product_gender`, que lee **solo el dato
declarado**; la carga por codigos usa `centry_gender`, que ademas lee el titulo
de la ficha. O sea que **la misma bota se convertia a PE por un camino y se
quedaba en US por el otro**: la trampa de las dos `normalize_size`.

La cascada vive ahora en `generate_columbia_matrixify.genero_de_producto` y
`centry_gender` **delega**. Comprobado sobre las **11.158 filas** del catalogo
real: **cero diferencias** con la implementacion anterior.

**`product_gender` NO se toco, a proposito.** De ahi salen la columna `Genero`
de la hoja Carga Sial y los bullets, donde el almacen espera el valor del
maestro tal cual (`MUJER`), no el normalizado (`Femenino`). Un titulo no puede
inventarle un genero a la hoja del almacen; para decidir una TALLA si, porque
ahi la alternativa es publicar en la escala equivocada.

### 3. `MARCAS_TALLA_PE` decia lo contrario y ya no la usaba nadie

Era una lista escrita a mano -- `("VANS",)` -- que declaraba que solo Vans
publica en PE. Desde que la guia de Vans es la por defecto eso es falso, y el
Mantenedor de Tallas ya pregunta por `hay_conversion`. Solo la referenciaba su
propia prueba: se fue, con `marca_publica_en_pe`. Una lista que contradice al
codigo que ya no la usa es una trampa para el siguiente que la lea.

### Lo que sigue sin convertirse, y por que

**Un producto de calzado sin genero en NINGUNA fuente** -- ni el metacampo, ni
`Genero`/`GENERO_MA` del maestro, ni el titulo -- se publica en la escala de
origen y sale avisado en la hoja de Revision. Medido en el catalogo real:
**0 de 428 productos de calzado** estan en ese caso.

Y no se convierte "lo que se pueda" de esa curva: solo 20 de los 34 numeros de
la guia son inequivocos sin genero (`4`, `12`...`16` y los infantiles con
sufijo), asi que convertir esos y dejar los demas partiria **un mismo producto
en dos escalas** -- peor que dejarlo entero en US.

### 4. Y el calzado de NINO no salia en PE en ninguna tienda

Destapado al validar contra el catalogo real: **todas** las botas y zapatillas
de nino de Columbia.pe traen la curva `10, 20, 30, 40, 45` -- o sea `1, 2, 3,
4, 4.5` -- y esos numeros **no estaban en ninguna columna de la guia**, asi que
el producto entero se quedaba sin convertir. En Supermall.pe eso deja las de
nino en `1, 2, 3, 4` justo al lado de las de adulto en `39, 40, 41`.

`1Y` y `1` son la MISMA talla: la guia trae la columna infantil con sufijo
hasta el `3Y` y sigue sin el (`3.5`, `4`, `4.5`), asi que el sufijo es
notacion, no una escala aparte -- y el maestro escribe la forma sin sufijo.
Con el alias, la curva sale `31.5, 32.5, 34, 35, 36`.

**Solo se alian las `Y`, nunca las `C`.** Las de bebe van de `10.5C` a `13.5C`
y esos numeros SI existen en la columna de adulto: un `10.5` de hombre es PE
44, no el PE 27 de un `10.5C`. Aliadas, un adulto sin genero pasaba a ser
ambiguo y podia salir en talla de bebe. Las `Y` van de `1Y` a `3Y` y no chocan
con nada, porque en adulto no hay 1, 2 ni 3.

### Y un aviso que decia lo contrario de lo que pasaba

La nota `ambigua` -- el numero no esta en la escala que le toca a ese genero
pero si en otra, asi que se resuelve con esa -- estaba en la tabla de los
PROBLEMAS, asi que la hoja de Revision decia *"se publican SIN convertir a PE"*
sobre tallas que **si** se convirtieron. Medido: 7 tallas de una carga real de
Columbia. Es el mismo fallo que ya se corrigio con la nota de lectura, y la
frase nueva ademas dice que suele ser un producto de nino con numeracion de
adulto, que es lo que hay que ir a revisar.

### 5. La guia de COLUMBIA, buscada en la web

Pedido del usuario a continuacion: *"sobre la guia de tallas de columbia
podrias buscar en la web sus equivalencias"*.

**`columbia.com` y `help.columbia.com` estan BLOQUEADOS** por la politica de
salida de este entorno, asi que la tabla sale de la copia de la guia oficial
que publica un distribuidor (Peter Glenn, en S3) y se cruzo con lo que publica
RunRepeat: los dos coinciden en el largo de pie por talla.

**Columbia publica US -> LARGO DE PIE en cm, no US -> EU**, y su traduccion a
EU tiene fama de poco fiable. Por eso el PE se deriva del **centimetro**, que
es el dato fisico, con la misma columna CM de la tabla que ya usa la tienda.
Asi el catalogo entero sigue en una sola escala en vez de tener dos PE segun la
marca. Hay una prueba que exige que cada fila de `TABLA_COLUMBIA` cuadre con
esa columna.

Lo que cambia respecto de usar la guia de Vans:

| | |
|---|---|
| HOMBRE | **identico** -- las dos marcas dan el mismo cm para el mismo US |
| NINO | **identico** |
| MUJER | **media talla**: la mujer de Columbia calza 0,5 cm mas en el mismo numero US. Su US 8 son 25 cm -> **PE 39**, y con la tabla de Vans salia **38.5** |

O sea que **el calzado de mujer de Columbia se publica media talla mas arriba
que antes**. Es un cambio visible en la tienda y sale de la guia de la propia
marca; si el equipo comercial lo quiere al reves, se quita el registro y
vuelve a mandar la de Vans.

**Una talla fuera de SU tabla cae a la guia por defecto** y se reporta
(`FUERA_DE_LA_GUIA`). Las guias publicadas empiezan donde empieza su catalogo
-- la de Columbia, en el US 7 de hombre -- y el maestro trae numeros por
debajo: sin respaldo se quedarian en US justo al lado de las que si se
convirtieron, que es lo que la guia por defecto existe para evitar.

### Las otras marcas: se buscaron y NO se registraron

El usuario pidio meter tambien las de las demas marcas. Se buscaron; no entran,
y el motivo es concreto en cada caso:

- **Hush Puppies, Keds**: sus sitios y los de los distribuidores que publican
  su tabla estan **bloqueados** por la politica de salida. Lo unico que llega
  son fragmentos de buscador, y un fragmento tiene erratas que no se ven --
  el que se obtuvo salta de `EUR 43` a `EUR 45` sin el 44.
- **Sorel**: la copia alcanzable (Peter Glenn) da US -> PULGADAS y su columna
  de hombre es **internamente inconsistente**: pone el 10 en 27,5 cm y el 11,5
  en 29, o sea corrida una fila respecto de todas las demas marcas. Muy
  probablemente le falta la fila del 9,5. Transcribirla asi publicaria media
  talla de error en todo el calzado de Sorel.
- **Rockford** no publica tabla: es marca de casa y entrega casi todo su
  calzado ya en PE (medido: 2.078 mod-col en PE contra 328 en US).

**No se inventa una tabla para rellenar el hueco.** Las cuatro siguen
convirtiendo con la guia por defecto y saliendo avisadas marca por marca, que
es exactamente para lo que existe esa salvedad.

### Y para que la proxima no haga falta un commit: `data/guias_tallas.xlsx`

El docstring de `registrar_tabla` prometia ese Excel desde que se escribio y
**no lo leia nadie**, asi que agregar una guia seguia siendo tocar codigo.
`cargar_guias_de_tallas` lo lee ahora:

- **Una hoja por marca**, y el nombre de la hoja ES la marca.
- Cinco columnas: `US Men`, `US Women`, `US Boy`, `PE`, `CM` -- la misma forma
  que `TABLA_VANS` y `TABLA_COLUMBIA`, o sea la de las guias oficiales.
- **Lo del Excel manda sobre lo del codigo**: la guia oficial de una marca que
  aqui este aproximada gana sin tener que borrar nada.
- **Perezoso y memoizado.** Leerlo en tiempo de import costaria en cada
  arranque de la app, se convierta una talla o no -- es la leccion de
  `CENTRY_COLUMNS` --, y leerlo por talla seria un viaje a disco por variante.
- **Nunca levanta.** Que el archivo no este es el caso normal; una hoja rota se
  reporta y deja las demas en pie, porque perder la conversion de todas las
  marcas por una columna mal escrita seria peor que el problema.

Ojo con lo que se gana de verdad: **Hush Puppies entrega 8.165 mod-col ya en
PE** y solo 2.752 en US, asi que la mayor parte de su calzado no se convierte
en ningun caso.

### 6. No existe una talla 2.1

Reportado por el usuario: *"vi que habian tallas que decian 2.1 eso no tiene
sentido"*. Tenia razon y no era un caso raro de laboratorio.

`interpretar_curva` elegia el divisor **solo por el RANGO numerico**: probaba
directa, entre diez y entre cien, y se quedaba con la primera que dejara todas
las tallas dentro de US (1-16.5) o PE (26-50). Una curva `42, 44, 46, 48, 50,
52` -- que no es de calzado, son tallas de vestuario en un producto tipificado
como calzado -- no cabe directa (el 52 se pasa del PE), pero **entre diez cabe
de sobra en el rango del US**, asi que se publicaba `4.2, 4.4, 4.6, 4.8, 5,
5.2`.

**Las escalas de calzado van de media en media.** Un `2.1` no es una talla: es
la prueba de que ese divisor no era el bueno. `_es_media_talla` lo comprueba, y
una division que deja cualquier otro decimal se descarta.

**Solo se comprueba al DIVIDIR.** La lectura directa no transforma nada -- lo
que trae el maestro sale tal cual --, asi que ahi no hay nada que verificar;
dividir SI inventa un numero, y si el numero inventado no es una talla, el
divisor estaba mal.

Medido sobre el maestro real (653.431 filas): **18 modelo-color** lo hacian, 16
de Rockford y 2 de Columbia:

```
RK111021393-176   42, 44, 46, 48, 50, 52  ->  4.2, 4.4, 4.6, 4.8, 5, 5.2
TL8258-EN5        12, 36, 38, 40, 42      ->  1.2, 3.6, 3.8, 4, 4.2
```

Ahora los dos se publican con la talla del maestro y la Revision dice *"la
curva no cabe en ninguna escala de calzado conocida"*, que es la verdad: eso no
es una curva de calzado, y lo que hay que revisar es el tipo del producto.

Comprobado que **la guarda no cuesta ninguna lectura buena**: las siete formas
que el maestro trae hoy -- `50,55,60`, `390,400,410`, `800,850`, `085`,
`040,050`, `10,20,30,40,45` y `70,75,80` -- se leen exactamente igual.

### 7. `'str' object has no attribute 'strftime'`: el boton moria en el clic

Reportado con una captura de **Carga Supermall**: el panel decia *"Se envia a
un runner de GitHub Actions: 8.113 productos"*, y al pulsar **Cargar a Shopify
en el servidor** la pantalla entera se caia con

```
AttributeError: 'str' object has no attribute 'strftime'
```

`start_suelto` armaba el codigo de la carga asi:

```python
codigo = f"{CODIGO_CARGA_SUELTA}-{site_key.upper()}-{ahora_utc().strftime('%Y%m%d-%H%M%S')}"
```

y **`ahora_utc()` devuelve TEXTO** -- el ISO, que es lo que se guarda en el
registro del job --, no un `datetime`. O sea que `start_suelto` **nunca pudo
ejecutarse**: estaba roto desde que se escribio.

Ahora hay `sello_de_tiempo(formato)`, que es la que da la hora formateada, y la
usan las dos: `nuevo_id_job` y `start_suelto`. Con las dos funciones separadas
y con nombre, la pregunta "¿esto es un `datetime` o ya es texto?" tiene una
respuesta a la vista.

**Por que no lo vio ninguna de las 42 pruebas de `test_curva_y_carga_suelta`:**
las ocho que cubren `start_suelto` leen su **codigo fuente** con
`inspect.getsource` -- que suba el archivo antes que el registro, que use
`nuevo_registro_job`, que llame a `self._disparar` -- y **ninguna la llamaba**.

> **Leer el codigo no es ejecutarlo.** Una prueba que solo mira el texto de una
> funcion no puede ver un `AttributeError`.

Hay tres pruebas nuevas: una que **ejecuta** `start_suelto` con un almacen y un
disparador falsos, otra que ejecuta el **pegamento con la pantalla**
(`lanzar_carga_remota_suelta`, que es lo que pulsa el boton) y una que falla si
`ahora_utc().strftime` vuelve a aparecer en el modulo. Las tres fallan con el
codigo anterior, y la primera con el mismo `AttributeError` que veia el
usuario.

Comprobado ademas con AST que **es el unico** `.strftime` del repositorio sobre
algo que pueda no ser un `datetime`: los demas reciben un `datetime.now(...)` o
estan detras de un `isinstance`.

### Lo que la validacion con el catalogo REAL dejo a la vista

200 codigos de calzado del catalogo de Columbia.pe cruzados con el maestro real
(1.974 filas de Matrixify), cargados a Supermall.pe:

| | antes | ahora |
|---|---:|---:|
| filas publicadas FUERA de la escala PE | 59 | **2** |

Las 2 que quedan son un producto **mal tipificado en Shopify**: `2138331-XP9`
son unos *"Guantes Arctic Crest"* con `Type = Zapatillas`, y sus tallas son `S`
y `M`. La app hace lo correcto -- no hay talla PE para una S -- y lo reporta;
lo que hay que arreglar es el tipo del producto en la tienda.

`scripts/test_tallas_de_calzado_en_supermall.py` pasa de 17 a **39 pruebas** y
`test_guias_tallas.py` de 25 a **42**. Seis pruebas de tres archivos cambiaron
de esperado y son la consecuencia buscada: las que usaban a Columbia como
ejemplo de marca SIN guia propia (ahora ese papel lo hace Sorel) y las que
fijaban su talla de mujer.

---

## 5 tertrigies. "Se queda pegada la imagen anterior": no es cache (septiembre 2026)

Reportado con una captura entrando a **KPIs de catalogo** desde Carga
Supermall: arriba el titulo nuevo y el spinner *"Cargando dashboard
actualizado..."*, y **debajo, en gris, la pantalla anterior entera**. La
lectura del usuario fue *"hay mucho cache por eso se pone lenta"*.

### Lo gris de abajo es de Streamlit, y no se puede quitar

Mientras el script corre, Streamlit **deja a la vista los elementos de la
ejecucion anterior**, atenuados, y solo los poda cuando la ejecucion termina.
Los indices que la pantalla nueva YA escribio se reemplazan (por eso el titulo
viejo desaparece y el nuevo ocupa su sitio); los que todavia no ha escrito
siguen mostrando lo de antes.

Medido con Chromium sobre un repro de 30 lineas -- dos pantallas y un trabajo
lento de 5 s --, contando lo que se VE (no lo que esta en el DOM):

| | titulo viejo visible | lineas viejas visibles |
|---|---:|---:|
| como esta hoy | 0 | **6** |
| cuerpo en un `st.empty()` que se vacia al entrar | 0 | **6** |
| cuerpo en un `st.container(key=...)` por pantalla | 0 | **6** |
| pintar la pantalla y `st.rerun()` antes del trabajo | 0 | **6** |

**Los cuatro dan lo mismo.** No hay forma de blanquear la pantalla desde el
script: lo unico que quita el gris es que la ejecucion TERMINE. Asi que la
respuesta no es tocar el arbol de elementos -- es no hacer esperar.

> Y ojo con la conclusion contraria: la duplicacion de la seccion 5 terdecies
> **si** era nuestra y **si** se arreglo. Aquella cambiaba la FORMA del arbol
> (un `st.empty()` creado dentro de una rama) y dejaba el bloque nuevo DEBAJO
> del viejo. Esto otro es el gris de siempre, que aparece en cualquier app de
> Streamlit que tarde.

### Lo que si era nuestro: el Dashboard se saltaba la cache

`load_catalog_kpi_result` llamaba a **`fetch_products` directo**, o sea que era
la unica pantalla que no pasaba por `leer_catalogo_del_sitio` y se saltaba la
cache de sesion **y la de disco (2 horas)** que usan todas las demas. Entrar a
KPIs justo despues de que Status de carga o Carga Supermall hubieran leido ese
mismo sitio volvia a leer la tienda entera. En Vans.pe son minutos -- con la
pantalla anterior en gris todo ese rato, que es exactamente como se ve un
"esta lentisima".

Ahora lee por la misma puerta que el resto, y **"Actualizar" pasa
`force_refresh=True`**: la cache no puede convertirse en una trampa, el boton
existe justo para pasar por encima de ella.

Hay una prueba AST que recorre TODO el archivo y **falla si alguien vuelve a
llamar a `fetch_products` fuera de los dos sitios que si pueden**:
`session_shopify_products`, que cachea, y el lector en paralelo, que consulta
la cache antes en el hilo de la pantalla porque `st.session_state` no se puede
tocar desde un hilo.

`scripts/test_lectura_completa_del_catalogo.py` pasa de 17 a **21 pruebas**;
las 4 nuevas fallan con el codigo anterior.

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
5. ~~Borrar los archivos corrompidos de la raíz del repo.~~ **Hecho** en
   septiembre de 2026 — ver la sección 5 tricies.
6. ~~Limpiar `engines/normalize.py` y `engines/excel_io.py`.~~ **Hecho** en
   septiembre de 2026 — ver la sección 5 tricies. El archivo suelto llamado
   `engines` ya no existía.
7. **Mover el trabajo pesado al worker.** Streamlit reejecuta el script en
   cada clic y guarda todo en `session_state`; un catálogo de 300.000 SKUs
   nunca va a estar cómodo ahí. `sync_worker.py` y `api_main.py` ya están
   desplegados en Render. Es la solución de fondo del problema de memoria de
   septiembre de 2026 (sección 5 nonies), y de paso arregla la inversión de
   `catalog_engine.py`.

8. **Pasar la marca a `display_size_for_site`.** Hoy la conversión de tallas
   de calzado a PE en la CARGA depende de la bandera de sitio
   `tallas_calzado_pe`, así que Vans cargado en Supermall.pe sale en US. El
   Mantenedor de Tallas lo arregla después, pero lo limpio es decidirlo por
   marca también al cargar. Toca a todos los llamadores de
   `display_size_for_site`.

9. **Dos formas de cargar conviven y confunden.** Con `[carga_remota]`
   configurado, "Ejecutar carga" desde una solicitud manda la carga a un runner
   de GitHub Actions; pero la pantalla sigue mostrando también el panel de
   sincronización local. Quien no lo sabe carga a mano lo que ya se está
   cargando solo. Habría que esconder el panel local cuando el job remoto está
   vivo.

10. **La memoria volvió a subir.** El catálogo del sitio y el maestro ARTI
   volvieron a `st.session_state` (sección 5 nonies) para ahorrar 9 s de disco
   por análisis. Medido entonces: ~500 MB residentes, más el Matrixify (224 MB)
   y los 180 del arranque. Eso es ~900 MB de los 1.024 que da el contenedor
   **para toda la app**: con dos personas cargando a la vez se muere, y al
   morir se cierran TODAS las sesiones. Ahora que el análisis es 2,4 veces más
   rápido el trato es otro y hay un camino intermedio: `complete_template_df`
   es el mismo catálogo que ya está en la caché de sesión, solo que como
   DataFrame — medido, 95 MB de más que cuesta 2,8 s reconstruir.

11. **Rotar las credenciales del código.** `get_auth_users()` tiene un
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

**Ya no conviven dos `normalize_size`.** Eran la de `engines/normalize.py`
(Fase 0, sin usar) y la de `generate_columbia_matrixify.py`, y diferían en 15 de
27 casos: la segunda convierte tallas de calzado (`85` → `8.5`, `400` → `40`),
que es lo que piden los datos reales de ARTI (`TALNUM_MA` viene en formato ×10).
En septiembre de 2026 se borró `engines/normalize.py` entero, que no lo
importaba nadie: queda **una sola**, la que usa la app.

---

## 10. Archivos corrompidos en el repositorio — BORRADOS (septiembre 2026)

Ya no están: se borraron en septiembre de 2026 (sección 5 tricies) después de
volver a verificar por firma binaria que eran lo que esta tabla decía. Se deja
la tabla porque explica por qué existían y por dónde buscarlos en el historial
de git si alguna vez hicieran falta. La app lee los originales de `data/` y los
logos de `assets/brands/`.

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

**Un sitio nuevo hay que darlo de alta en TRES sitios**: `SITE_CONFIGS`,
`[shopify_sites.<clave>]` de Streamlit y el bloque `env:` de
`.github/workflows/carga-shopify.yml`. Si falta el tercero, la carga remota
falla con "faltan credenciales" y nada más. Hay un test que recorre
`SITE_CONFIGS` y lo comprueba contra el workflow — antes la lista estaba
escrita a mano y por eso no atrapó a Supermall.

---

## 12. Cómo validar antes de entregar

```bash
python scripts/test_brand_commercial_input.py          # 6
python scripts/test_carga_desde_solicitud.py           # 31
python scripts/test_carga_remota.py                    # 40
python scripts/test_engines_audit.py                   # 45
python scripts/test_engines_metrics.py                 # 26
python scripts/test_engines_notify.py                  # 88
python scripts/test_engines_price_check.py             # 19
python scripts/test_engines_stock.py                   # 35
python scripts/test_engines_ticket_flow.py             # 55
python scripts/test_engines_load_status.py             # 37
python scripts/test_engines_video_media.py             # 106
python scripts/test_carga_sial_parcial.py               # 30
python scripts/test_lectura_catalogo.py                # 30
python scripts/test_espejo_supermall.py                # 35
python scripts/test_mantenedor_tallas.py               # 42
python scripts/test_orden_tallas_reales.py             # 17
python scripts/test_guias_tallas.py                    # 42
python scripts/test_carga_supermall.py                 # 57
python scripts/test_lectura_completa_del_catalogo.py    # 21
python scripts/test_colecciones.py                     # 54
python scripts/test_tipos_de_prenda.py                 # 13
python scripts/test_carga_sial_campos.py               # 27
python scripts/test_curva_y_carga_suelta.py            # 46
python scripts/test_hueco_por_marca.py                 # 28
python scripts/test_memoria.py                         # 15
python scripts/test_css_movil.py                       # 33
python scripts/test_rendimiento.py                     # 47
python scripts/test_sincronizacion_y_limpieza.py       # 19
python scripts/test_bandeja_solicitudes.py             # 57
python scripts/test_partial_maintenance_validations.py # 6
python scripts/test_siblings_carga_completa.py         # 24
python scripts/test_siblings_referencias.py            # 14
python scripts/test_siblings_tipos.py                  # 20
python scripts/test_ticket_system.py                   # 28
python scripts/test_tipos_vestido_y_bloqueos.py       # 24
python scripts/test_optimizacion_memoria_excel.py       # 38
python scripts/test_carga_supermall_rendimiento.py     # 16
python scripts/test_handle_tipo_y_duplicados.py         # 18
python scripts/test_pantallas_reales.py                 # 10
python scripts/test_bigquery_storage.py                 # 10
python scripts/test_supermall_pico_de_memoria.py        # 27
python scripts/test_tallas_de_calzado_en_supermall.py   # 39
python scripts/test_export_matrixify_y_validacion.py    # 42
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
repositorio, no fragmentos para copiar ni ZIP para subir a mano (ver regla 7).
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
