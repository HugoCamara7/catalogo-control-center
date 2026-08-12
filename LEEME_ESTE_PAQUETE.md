# Paquete completo — solicitudes, correos y motor de catálogo

Agosto 2026. Construido sobre el commit `6da7f0d72` de `main`.

Este paquete **reemplaza a todos los ZIP anteriores de esta tanda**. Trae los
20 archivos que cambiaron, con la estructura exacta del repositorio.

---

## 1. Qué subir (20 archivos)

Sube todo respetando las carpetas. Los que están en `engines/` van dentro de
`engines/`, no en la raíz.

### Modificados (9)

```
app_matrixify.py
ticket_system.py
generate_columbia_matrixify.py
engines/audit.py
engines/ticket_flow.py
scripts/test_engines_ticket_flow.py
assets/app.css
.streamlit/secrets.example.toml
CLAUDE.md
```

### Nuevos (11)

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
remitente        = "catalogo@forus.pe"
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
usuario = "catalogo@forus.pe"
clave   = "AQUI_LA_CLAVE_DE_APLICACION"
```

Cambia `url_app`, `remitente`/`usuario` y `clave`. Guarda: la app se reinicia
sola.

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
usuario_envio = "catalogo@forus.pe"
```

Sistemas necesita crear un registro de aplicación en Entra ID con el permiso
**de aplicación** `Mail.Send`.

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
python scripts/test_engines_catalog_map.py   # 48
python scripts/test_engines_notify.py        # 88
python scripts/test_engines_ticket_flow.py   # 40
python scripts/test_engines_stock.py         # 35
python scripts/test_engines_metrics.py       # 26
python scripts/test_engines_price_check.py   # 19
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

**Motor de catálogo.** Tres fugas de datos corregidas:

- `[id]` mandaba un tipo que Shopify rechaza siempre → el Código Modelo-Color
  no llegaba por integración directa.
- Los "Tags adicionales" **reemplazaban** a los genéricos en vez de sumarse, y
  el motor no generaba ningún tag genérico.
- Había dos constructores de handle y uno descartaba el nombre del producto.

**Stock.** Se consolida por Modelo-Color, deduplicando talla a talla. Un caso
medido pasaba de 20 unidades a las 10 reales.

**KPI nuevo.** "Productos sin ninguna foto", contando productos (no imágenes ni
variantes), con ratio `12 / 185 productos`.

---

## 6. Pendiente

No lo hice para no tocar a ciegas lo que hoy funciona:

- **Tipo de prenda por sitio** — Patagonia en Rockford sigue saliendo Outdoor.
- **Body HTML** de Rockford.
- **Siblings** — necesito que me confirmes el tipo declarado en tu Shopify para
  `custom.siblings` y `custom.siblings_color`. Adivinarlo es exactamente lo que
  causó el problema del `[id]`.
- **Correo de anthony.fernandez** — no lo inventé. Cuando lo tengas, agrégalo a
  `area_producto` en Secrets.
