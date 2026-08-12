# Motor de notificaciones y cierre de carga por etapas

Agosto 2026.

---

## 1. Mailchimp o casilla corporativa

**Recomendación: casilla corporativa. Mailchimp es la herramienta equivocada
para esto**, aunque ya esté contratada.

### Por qué no Mailchimp

Mailchimp es una plataforma de *marketing*, no de correo transaccional. Su
producto transaccional es **Mandrill**, que es un complemento de pago aparte:
exige un plan Standard o superior y comprar bloques de envío. O sea, aunque
Mailchimp esté contratado, el correo transaccional **no** viene incluido.

Si en cambio se usara la API de marketing de Mailchimp para estos avisos:

| Problema | Consecuencia concreta |
|---|---|
| Todo envío es una campaña a una audiencia | Habría que crear una campaña por cada cambio de estado |
| Los destinatarios son contactos de una audiencia | Clara, Hugo y el Área de Producto entran al CRM de marketing |
| Cada correo lleva enlace de baja obligatorio | Si alguien se da de baja, **deja de recibir avisos de sus solicitudes** y nadie se entera |
| Está pensado para envíos programados en lote | La latencia y el modelo no encajan con "avisar al cambiar de estado" |
| Los avisos internos entran en métricas de marketing | Aperturas y clics de operación ensucian los informes comerciales |

El punto que decide es el cuarto. Una baja de marketing no debería poder
apagar un aviso operativo, y con Mailchimp sí puede.

### Por qué la casilla corporativa

El caso real es pequeño y cerrado: unos 15 destinatarios, todos `@forus.pe`,
unos pocos correos por solicitud. Eso es correo interno, no difusión.

- **Sin coste ni proveedor nuevo.** Ya está pagado.
- **Entregabilidad resuelta.** Emisor y receptor están en el mismo tenant; no
  hay que configurar SPF, DKIM ni DMARC para un tercero.
- **Sin superficie de datos nueva.** Ningún correo de un empleado sale hacia
  una plataforma externa.
- **Sin dependencias.** El motor usa solo biblioteca estándar (`smtplib`,
  `email`, `urllib`). `requirements.txt` no cambia.

### El riesgo real, y cómo queda cubierto

Microsoft 365 **desactiva por defecto la autenticación básica de SMTP AUTH**
desde 2023. Si el correo de Forus está en M365 y sistemas no la habilita para
la casilla de envío, el SMTP simplemente no autentica.

Por eso el motor trae **dos transportes**, y se elige por configuración sin
tocar código:

| Transporte | Cuándo |
|---|---|
| `smtp` | Google Workspace, o M365 con SMTP AUTH habilitado en la casilla |
| `graph` | Microsoft 365 sin SMTP AUTH. Es el camino recomendado por Microsoft |
| `consola` | Desarrollo y pruebas. No sale a la red |

`graph` usa credenciales de aplicación (Entra ID, permiso de aplicación
`Mail.Send`). Conviene acotarlo con una política de acceso a aplicaciones para
que solo pueda enviar desde la casilla de catálogo.

**Qué pedirle a sistemas**, en este orden:

1. Una casilla de servicio, por ejemplo `catalogo@forus.pe`.
2. O bien SMTP AUTH habilitado en esa casilla (opción A), o bien un registro
   de aplicación en Entra ID con `Mail.Send` de aplicación (opción B).

Si no llega ninguna de las dos, la app sigue funcionando: el transporte cae a
`consola`, no se envía nada, y cada intento queda anotado en Auditoría con el
motivo.

> Si más adelante hubiera que mandar correo a clientes finales fuera del
> dominio, ahí sí conviene un servicio transaccional de verdad (Amazon SES,
> Postmark, SendGrid). Ese cambio son ~40 líneas: una clase de transporte
> nueva en `engines/notify.py`. Nada más se toca.

---

## 2. Arquitectura

```
engines/notify.py     motor de correo (plantillas, dedupe, transportes)
engines/stock.py      consolidacion de stock por Codigo Modelo-Color
engines/ticket_flow.py  estados visibles y acciones por rol
engines/audit.py      auditoria
ticket_system.py      maquina de estados y persistencia
app_matrixify.py      solo cableado: ningun correo se arma en una pantalla
```

Ningún motor importa Streamlit. Hay una prueba que lo verifica.

### Por dónde sale el correo

`TicketService` ya recibía el notificador por inyección y ya llamaba a
`notifier.notify()` en cada transición. Ese era el punto correcto: enchufando
`AdaptadorCorreoTickets` ahí, **el correo sale desde las 18 pantallas sin
tocar ninguna**.

```
pantalla -> TicketService._transition -> _notify -> AdaptadorCorreoTickets
                                                        |
                                        MotorNotificaciones.enviar
                                          |                    |
                                    ¿cambió el estado?    Transporte
                                    ¿ya se envió?         (SMTP/Graph)
                                          |
                                   registro -> Auditoria + historial
```

### Qué garantiza el motor

| Requisito | Cómo |
|---|---|
| Un correo por cambio de estado | `_transition`, `set_status_manual` y `assign` avisan |
| Nunca duplicados si el estado no cambió | `hay_cambio_de_estado()` corta antes de armar el mensaje |
| Ni por doble clic o rerun | Clave de idempotencia + ventana de 5 minutos sobre el historial de la solicitud |
| El correo no puede tumbar la operación | `enviar()` nunca lanza; `_notify` atrapa todo |
| El correo no puede colgar la pantalla | El envío va en un hilo aparte, igual que la auditoría |
| Todo envío queda auditado | Registro con solicitud, marca, estado anterior/nuevo, responsable y resultado |

Un intento **fallido** no cuenta como enviado: se puede reintentar.

### Contenido del correo de cambio de estado

Solicitud · Marca · Sitios · Estado anterior → Estado nuevo · Responsable ·
Fecha y hora (Perú) · Observación (solo si existe).

Va en HTML y en texto plano. Todo lo que escribe el usuario se escapa: una
observación con `<script>` no se ejecuta en el cliente de correo.

---

## 3. Cierre de carga por etapas

Cadena objetivo:

```
Carga SIAL -> Carga de precios -> Validacion precio/stock -> Shopify -> Finalizada
```

Se agregaron **3 estados internos** a los 19 que ya existían. Los 19 anteriores
no se tocaron: las solicitudes históricas se leen sin migración.

| Estado interno | Etiqueta |
|---|---|
| `sial_loaded` | Carga SIAL finalizada |
| `price_load_requested` | Carga de precios solicitada |
| `price_stock_validation` | Validación de precio y stock |

Los tres se muestran como **"En ejecución"** con matiz entre paréntesis, así
que la vista de 5 estados no cambia para la marca.

### El recorrido

| Estado | Acción principal | Método |
|---|---|---|
| Cargando | Finalizar solicitud | `record_job_result` |
| Cargando | *(secundaria)* Carga SIAL terminada | `complete_sial_load` |
| Carga SIAL finalizada | **Solicitar carga de precios** | `request_price_load` |
| Carga de precios solicitada | Validar precio y stock | `start_price_validation` |
| Validación de precio y stock | Enviar a Shopify | `change_state` |

"Carga SIAL terminada" queda **secundaria** a propósito: quien no use la
cadena completa sigue cargando y finalizando como siempre.

### El archivo Carga SIAL va adjunto

Al pulsar **"Carga SIAL terminada"**, la app toma la hoja *Carga Sial* que
quedó en pantalla, la guarda como **adjunto de la solicitud**
(`put_artifact(..., kind="sial", ...)`) y anota su ruta en `ticket["sial"]`.

Eso importa: el archivo deja de vivir en la sesión de Streamlit. Se puede
volver a descargar meses después, y `request_price_load` lo recupera del
almacenamiento para adjuntarlo al correo.

| Situación | Qué pasa |
|---|---|
| Hay archivo y pesa menos del tope | Va adjunto al correo del Área de Producto |
| Pesa más del tope (8 MB SMTP, 3 MB Graph) | El correo **sale igual**, sin adjunto, diciendo que se descargue desde la app |
| No se generó la hoja Carga Sial | El correo sale sin adjunto y la pantalla avisa antes |

Un correo que rebota por tamaño es peor que uno sin adjunto: nadie se entera
de que rebotó.

**Del adjunto solo queda el nombre en el registro.** El registro se guarda
dentro de la solicitud, que es un JSON; meterle los bytes del Excel lo haría
imposible de serializar. Hay una prueba que hace `json.dumps(ticket)`.

### Qué pasa al pulsar "Solicitar carga de precios"

1. La solicitud pasa a **Carga de precios solicitada**.
2. Sale un correo al **Área de Producto** con el **archivo Carga SIAL
   adjunto**, más marca, solicitud, modelos-color y productos procesados,
   responsable y observación.
3. Sale el correo de cambio de estado a la **marca**.
4. Queda el evento en el historial de la solicitud y dos registros en
   Auditoría, con fecha, usuario y resultado del envío.

Los dos correos se anotan en **una sola escritura** de la solicitud. Con el
backend de GitHub, una escritura extra es un viaje HTTP más y una posibilidad
más de `TicketConflictError`.

Si no hay correos del Área de Producto configurados, el botón sale
desactivado con el aviso de qué falta en Secrets.

### Cuidado al tocar la cola

`MotorNotificaciones` tiene dos métodos, y la diferencia importa:

- **`preparar()`** decide si toca enviar y arma el mensaje. **No entrega.**
- **`enviar()`** es `preparar()` + entrega.

Con la cola hay que **decidir en el hilo de la pantalla y entregar en el de
correo**. Si se usa `enviar()` para decidir, el aviso sale **dos veces**: una
en línea y otra al desencolar. Pasó, y hay una prueba que lo fija
(`test_con_cola_no_envia_en_linea` comprueba que el transporte queda intacto).

---

## 4. Stock por Código Modelo-Color

El stock llega por variante: una fila por talla. El producto que se prende o
se apaga en la web es el Modelo-Color completo.

**El problema que había:** el total del modelo se calculaba sumando filas. Si
una talla venía en más de una fila (dos SKU del maestro que normalizan a la
misma talla, o filas repetidas), esa existencia se contaba dos veces.

`engines/stock.py` consolida **primero por talla y después por modelo**.

Medido con un caso de dos SKU sobre la talla 8 con 10 unidades:

| | Antes | Ahora |
|---|---:|---:|
| Unidades del modelo | 20 | **10** |
| Tallas con stock (de 2 tallas, una en cero) | 2 | **1** |

Por cada Modelo-Color el motor devuelve: unidades, tallas totales, tallas con
y sin stock, cobertura, y si debe estar visible. Tres políticas de
visibilidad: basta una talla (por defecto), todas las tallas, o un mínimo de N.

En la auditoría de KPIs se agregaron tres indicadores, entre ellos **"Filas de
talla repetidas"**: si sale alto, el maestro está duplicando variantes.

---

## 5. Pruebas

```bash
python scripts/test_engines_notify.py       # 80
python scripts/test_engines_stock.py        # 35
python scripts/test_engines_ticket_flow.py  # 33
python scripts/test_ticket_system.py        # 28
python scripts/test_engines_audit.py        # 45
python scripts/test_carga_desde_solicitud.py # 20
```

Ninguna prueba sale a la red: se usa el transporte de consola.

> `test_auth_accesos.py` y `test_brand_commercial_input.py` fallan desde antes
> de estos cambios (ver `CLAUDE.md` §9).
