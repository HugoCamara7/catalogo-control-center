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

6. **El usuario sube los archivos a mano.** No hay push automático. Entrega
   siempre en ZIP con la estructura exacta del repositorio.

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
│   ├── ticket_flow.py  390 lin · 23 estados -> 5 visibles (40 pruebas)
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
pending_assignment → Tomar solicitud
assigned           → Iniciar revisión
digital_review     → Aprobar para carga
load_approved      → Ejecutar carga
loading            → Finalizar solicitud
```

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

Verificado con capturas reales (Chromium 390px, 360px y 1440px): sin desborde
horizontal en ninguno, y escritorio intacto en 4 columnas.

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
python scripts/test_carga_desde_solicitud.py           # 20
python scripts/test_engines_audit.py                   # 45
python scripts/test_engines_metrics.py                 # 26
python scripts/test_engines_notify.py                  # 88
python scripts/test_engines_price_check.py             # 19
python scripts/test_engines_stock.py                   # 35
python scripts/test_engines_ticket_flow.py             # 40
python scripts/test_engines_load_status.py             # 28
python scripts/test_css_movil.py                       # 15
python scripts/test_partial_maintenance_validations.py # 6
python scripts/test_siblings_carga_completa.py         # 24
python scripts/test_siblings_referencias.py            # 14
python scripts/test_siblings_tipos.py                  # 20
python scripts/test_ticket_system.py                   # 28
```

> `test_brand_commercial_input.py` falla desde antes de estos cambios.

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

Trabaja en español. Prefiere entregas completas en ZIP, no fragmentos para
copiar. Valora que se le diga con claridad qué no se hizo y por qué, y que se
distinga un fallo propio de uno preexistente.

Cuando pida algo que parezca arriesgado, hay que decírselo — pero si lo
reafirma, se hace.
