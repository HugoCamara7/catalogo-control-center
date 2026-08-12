# Paquete completo — solicitudes, correos y motor de catálogo

Agosto 2026. Construido sobre el commit `6da7f0d72` de `main`.

Este paquete **reemplaza a todos los ZIP anteriores de esta tanda**. Trae los
23 archivos que cambiaron, con la estructura exacta del repositorio.

---

## 1. Qué subir (23 archivos)

Sube todo respetando las carpetas. Los que están en `engines/` van dentro de
`engines/`, no en la raíz.

### Modificados (10)

```
app_matrixify.py
ticket_system.py
generate_columbia_matrixify.py
catalog_rules.py
engines/audit.py
engines/ticket_flow.py
scripts/test_engines_ticket_flow.py
assets/app.css
.streamlit/secrets.example.toml
CLAUDE.md
```

### Nuevos (13)

```
engines/catalog_map.py
engines/notify.py
engines/stock.py
engines/metrics.py
engines/price_check.py
scripts/test_engines_catalog_map.py
scripts/test_engines_notify.py
scripts/test_engines_stock.py
scripts/test_engines_metrics.py
scripts/test_engines_price_check.py
scripts/test_body_html.py
scripts/test_tipo_de_prenda_por_sitio.py
docs/MOTOR_NOTIFICACIONES.md
```

> `assets/app.css` lleva el estilo del seguimiento visual del ticket. Sin él la
> app funciona, pero las 6 etapas se ven sin formato.

---

## 2. Activar los correos

Streamlit Cloud → tu app → ⋮ **Settings** → pestaña **Secrets**.

**No borres lo que ya está.** Baja al final del todo y pega esto:

```toml
[notificaciones]
activo           = true
transporte       = "smtp"
remitente        = "bi@forus.pe"
remitente_nombre = "Catalog Control Center"
url_app          = "https://TU-APP.streamlit.app"
area_producto    = [
  "rosa.terrones@forus.pe",
  "melisa.senador@forus.pe",
  "candy.rios@forus.pe",
  "andrea.ventocilla@forus.pe",
]

[notificaciones.smtp]
host    = "smtp.office365.com"
puerto  = 587
usuario = "bi@forus.pe"
clave   = "AQUI_LA_CLAVE_DE_APLICACION"
```

Cambia `url_app` y `clave`. Guarda: la app se reinicia sola.

`remitente` y `usuario` tienen que ser **la misma casilla**: Microsoft 365
rechaza el envío si intentas mandar «desde» un buzón distinto del que inició
sesión.

**Tres errores típicos:**

1. `activo = true` va en minúscula y **sin comillas**.
2. La línea `area_producto = [...]` tiene que ir **antes** de
   `[notificaciones.smtp]`. Si la pones después queda dentro de smtp y no se lee.
3. Nunca pegues secretos en `.streamlit/config.toml`. Solo en Secrets.

### Si Microsoft 365 bloquea SMTP

Si al probar sale `SmtpClientAuthentication is disabled`, cambia a Graph. No se
toca código:

```toml
[notificaciones]
transporte = "graph"

[notificaciones.graph]
tenant_id     = "..."
client_id     = "..."
client_secret = "..."
usuario_envio = "bi@forus.pe"
```

Sistemas necesita crear un registro de aplicación en Entra ID con el permiso
**de aplicación** `Mail.Send`.

Para SMTP hacen falta **dos** cosas y solo una la puedes hacer tú:

| Requisito | Quién |
|---|---|
| Contraseña de aplicación de `bi@forus.pe` | Tú, en mysignins.microsoft.com/security-info → Agregar método → Contraseña de aplicación (si no aparece, está bloqueada por el administrador) |
| **SMTP AUTH habilitado en el buzón** | Solo el administrador |

### Sin configurar nada

La app arranca igual y **no envía ningún correo**: el transporte cae a
`consola` y cada intento queda anotado en Auditoría con el motivo.

---

## 3. Borrar del repositorio

Verificado por firma binaria: **no son lo que dicen ser** y no los usa nadie.
La app lee los originales de `data/`.

| Archivo | Contenido real |
|---|---|
| `config.toml` (raíz) | código fuente, no TOML |
| `dimensiones_productos.xlsx` (raíz) | imagen WEBP |
| `matrixify_modelo.xlsx` (raíz) | imagen WEBP |
| `formato_input_catalog_control_center.xlsx` | texto plano |
| `download` · `download (1)` | basura |
| `engines/engines` · `docs/s` · `scripts/d` | archivos de 2 bytes |
| `test_brand_commercial_input.py` (raíz) | duplicado de `scripts/` |
| `test_catalog_rules.py` (raíz) | duplicado de `scripts/` |
| `test_partial_maintenance_validations.py` (raíz) | duplicado de `scripts/` |

**No borres `engines/normalize.py`**: sí tiene un importador.

---

## 4. Probar que quedó bien

```bash
python scripts/test_engines_catalog_map.py   # 54
python scripts/test_engines_notify.py        # 88
python scripts/test_engines_ticket_flow.py   # 40
python scripts/test_engines_stock.py         # 35
python scripts/test_engines_metrics.py       # 26
python scripts/test_engines_price_check.py   # 19
python scripts/test_body_html.py             # 14
python scripts/test_tipo_de_prenda_por_sitio.py  # 14
```

En la app:

1. Cambia el estado de una solicitud → le llega correo a quien la creó.
2. Entra a **Auditoría** → filas con acción *"Notificar por correo"*, con
   destinatarios y resultado.
3. Ejecuta una carga → **Carga SIAL terminada** → **Notificar a Producto**
   (va con el Excel adjunto) → **Precios cargados** → validar → **Finalizar**.

> `test_auth_accesos.py` y `test_brand_commercial_input.py` fallan **desde
> antes** de estos cambios. No los rompí yo; ver `CLAUDE.md` §9.

---

## 5. Qué cambió, en corto

**Solicitudes.** 4 estados nuevos. "Completada" ya **solo** se alcanza desde
"Lista para cierre": antes se podía cerrar apenas terminaba el SIAL, sin
precios cargados ni validados.

**Correos.** Motor único en `engines/notify.py`, enchufado donde
`TicketService` ya llamaba al notificador: sale desde las 18 pantallas sin
tocar ninguna. No duplica si el estado no cambió. Todo envío queda auditado.

**Motor de catálogo.** Seis fugas de datos corregidas:

- `[id]` mandaba un tipo que Shopify rechaza siempre → el Código Modelo-Color
  no llegaba por integración directa.
- Los "Tags adicionales" **reemplazaban** a los genéricos en vez de sumarse, y
  el motor no generaba ningún tag genérico.
- Había dos constructores de handle y uno descartaba el nombre del producto.
- **Body HTML nunca emitía la Descripción.** La leía, pero solo como sustituto
  de Características. Con las dos columnas llenas —el caso de Rockford, que
  llena las tres— la Descripción se perdía entera; con solo Descripción, salía
  publicada bajo el título "Características".
- **El tipo de prenda no leía el campo del brand.** El modelo es
  `Categoría = clase` y `Subcategoría = tipo de prenda`, igual en los cuatro
  sitios. Pero `"Type"`/`"Product Type"` iban antes que `"Tipo de prenda"`, y
  `"Categoria"` estaba en la MISMA lista de alias. Como se toma el primer alias
  no vacío, Patagonia en Rockford salía como **"Outdoor"** — su clase, que el
  diccionario de tipos ni reconoce como prenda. Ahora la clase se deriva del
  tipo (`Chalecos → Vestuario`), nunca al revés, y sin tipo se avisa en vez de
  inventarlo.
- **Siblings con tipos contradictorios.** `custom.siblings` estaba declarado
  como `list.product_reference` en el mantenedor y en la API, pero como
  `single_line_text_field` en otras cuatro rutas; `theme.siblings` igual. El
  que no coincidía lo rechazaba Shopify, y de ahí que unos siblings llegaran y
  otros no según por dónde pasara la carga. Los cuatro metafields
  (`custom.siblings`, `custom.siblings_color`, `theme.siblings`,
  `theme.siblings_color`) están ahora en el registro con un solo tipo cada uno,
  iguales en los cuatro sitios.

**Stock.** Se consolida por Modelo-Color, deduplicando talla a talla. Un caso
medido pasaba de 20 unidades a las 10 reales.

**KPI nuevo.** "Productos sin ninguna foto", contando productos (no imágenes ni
variantes), con ratio `12 / 185 productos`.

---

## 6. Pendiente

No lo hice para no tocar a ciegas lo que hoy funciona:

- **Tres decisiones de criterio del diccionario** (ver sección 7).
- **Correo de anthony.fernandez** — no lo inventé. Cuando lo tengas, agrégalo a
  `area_producto` en Secrets.


---

## 7. Diccionario de tipos: qué quedó y qué falta decidir

`PRODUCT_TYPE_RULES` pasó de **24 a 45 reglas**. Calzado, que tenía solo 2
tipos pese a ser marcas de calzado, ahora tiene 9. **Los 55 tipos de
`data/tipos_shopify.xlsx` quedan reconocidos: cero sin regla.**

Se agregaron, entre otros: Botas, Botines, Sandalias, Pantuflas, Zapatos,
Mocasines, Ballerinas, Sweaters (= Chompas), Blusas, Jeans, Enterizos, Medias
(= Calcetines), Pasamontañas, Lentes de Sol, Billeteras, Botellas, Coolers,
Bastones, Cuchillas y Fundas para Lata.

### Tres cosas que NO decidí yo

El diccionario ya tenía dueño para estos alias, y son criterio de negocio:

| Alias | Hoy apunta a | ¿Debería ser su propio tipo? |
|---|---|---|
| `chaqueta`, `jacket` | **Casacas** | ¿O separar Chaquetas? |
| `falda` | **Shorts** | Una falda no es un short |
| `cartera` | **Bolsos** | ¿O separar Carteras? |

Dime tu criterio en cada uno y los ajusto. Mientras tanto quedan como estaban,
que es lo que hoy funciona.

### `Calzado` usado como tipo

Vans usa **`Calzado`** —que es la clase— como tipo de prenda en ~309
productos, y hoy el diccionario lo resuelve como *Zapatillas*. Puede ser
correcto, pero también podrían ser botas o sandalias. Lo dejé como estaba para
no cambiar 309 productos sin tu visto bueno. Es el mismo caso que `Outdoor`,
que sí quedó sin regla para que se avise.
