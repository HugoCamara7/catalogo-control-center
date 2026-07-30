# Migrar el proyecto a otro repositorio

Guía para levantar el Catalog Control Center desde cero en un repositorio nuevo,
conservando Streamlit, GitHub Actions, Shopify y BigQuery.

---

## 1. Qué copiar

**Código** (raíz)

```
app_matrixify.py              catalog_engine.py       job_store.py
generate_columbia_matrixify.py  catalog_rules.py      sync_worker.py
ticket_system.py              centry_static_masters.py  api_main.py
shopify_api.py
```

**Carpetas**

```
engines/          motores sin Streamlit (normalize, excel_io, audit, storage_check)
scripts/          utilidades y pruebas
assets/brands/    logos de marca
data/             datos maestros
docs/             documentación
.streamlit/       config.toml y secrets.example.toml
.github/workflows/ catalog-control-center.yml
```

**Configuración**

```
requirements.txt  requirements-api.txt  .gitignore
render.yaml       Dockerfile.api
```

**No copies:** `outputs/`, `job_inputs/`, `__pycache__/`, `.streamlit/secrets.toml`,
ni los 5 archivos corrompidos listados en `INVENTARIO_ARCHIVOS.md`.

---

## 2. Archivos grandes

`data/arti.zip` pesa 5.7 MB. Entra en GitHub sin problema (avisa a los 50 MB,
bloquea a los 100 MB), pero **es solo un respaldo**: la app lee ARTI desde
BigQuery y solo cae a este archivo si BigQuery no responde.

Si prefieres no subirlo, la app arranca igual — solo pierdes ese respaldo.

---

## 3. Secretos

Ninguno va al repositorio. Se configuran en **Streamlit Cloud → Manage app →
Settings → Secrets**. La plantilla exacta está en `.streamlit/secrets.example.toml`.

Secciones necesarias:

| Sección | Para qué |
|---|---|
| `[bigquery]` | Lectura del maestro ARTI y del stock |
| `[gcp_service_account]` | Credenciales de servicio de Google |
| `[app_auth]` y `[app_auth.users]` | Usuarios y contraseñas |
| `[app_auth.roles]` | Rol por usuario |
| `[shopify_sites.*]` | Un bloque por sitio: columbia, rockford, hush_puppies, vans |
| `[ticketing]` | Persistencia de solicitudes y auditoría |

> **Atención:** `auth_access_scope()` devuelve **administrador** por defecto para
> cualquier usuario que no esté en ninguna lista. Asigna siempre un rol explícito
> en `[app_auth.roles]` al agregar usuarios.

> **Nunca** pegues estos valores en `.streamlit/config.toml`. Streamlit los
> interpretará como configuración, los rechazará uno por uno en los logs y
> `st.secrets` quedará vacío. Eso ya pasó en este proyecto (commit `542c3757`).

### GitHub Actions

El workflow usa **GitHub Secrets** (Settings → Secrets and variables → Actions),
que son distintos de los de Streamlit:

```
COLUMBIA_SHOP_DOMAIN            COLUMBIA_ADMIN_API_ACCESS_TOKEN
ROCKFORD_SHOP_DOMAIN            ROCKFORD_ADMIN_API_ACCESS_TOKEN
HUSHPUPPIES_SHOP_DOMAIN         HUSHPUPPIES_ADMIN_API_ACCESS_TOKEN
VANS_SHOP_DOMAIN                VANS_ADMIN_API_ACCESS_TOKEN
BIGQUERY_PROJECT_ID             BIGQUERY_TABLE
BIGQUERY_SERVICE_ACCOUNT_JSON
```

---

## 4. Persistencia de solicitudes y auditoría

Sin la sección `[ticketing]`, el backend es `local` y escribe en
`outputs/catalog_tickets`, que **Streamlit Cloud borra en cada redespliegue**.
Se pierden las solicitudes, sus archivos adjuntos y la auditoría.

```toml
[ticketing]
backend = "github"
repository = "ORGANIZACION/REPOSITORIO"
token = "TOKEN_CON_PERMISO_CONTENTS_READ_WRITE"
branch = "catalog-tickets"
prefix = "catalog_tickets"
```

Pasos:

1. Crea la rama `catalog-tickets` en el repositorio nuevo (puede estar vacía).
2. Genera un *fine-grained personal access token* con permiso
   **Contents: Read and write** sobre ese repositorio.
3. Pega el bloque en Secrets.
4. Entra a la app como operador y abre el panel **Almacenamiento** en la barra
   lateral. Debe salir todo en verde.

El panel comprueba de verdad: token válido, repositorio accesible, permiso de
escritura, existencia de la rama y solicitudes ya guardadas. Si algo falla,
indica exactamente qué corregir.

---

## 5. Instalación local

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Crea `.streamlit/secrets.toml` copiando `secrets.example.toml` y completando los
valores. Ese archivo está en `.gitignore`.

```bash
streamlit run app_matrixify.py
```

---

## 6. Pruebas

```bash
python scripts/test_engines_audit.py
python scripts/test_ticket_system.py
python scripts/test_catalog_rules.py
python scripts/test_partial_maintenance_validations.py
python scripts/test_brand_commercial_input.py
```

> `test_brand_commercial_input.py` falla desde antes de esta fase: espera hojas
> `INPUT_COMERCIAL / GUIA / DICCIONARIO` y el código genera
> `PARA_COMPLETAR / EJEMPLO / COMO_LLENAR`. Es el test el que está desactualizado.

---

## 7. Checklist de migración

- [ ] Repositorio nuevo creado, rama `main`
- [ ] Código y carpetas copiados (sin `outputs/` ni archivos corrompidos)
- [ ] `.gitignore` en su sitio
- [ ] Rama `catalog-tickets` creada
- [ ] Secrets de Streamlit Cloud completos, incluido `[ticketing]`
- [ ] GitHub Secrets para Actions
- [ ] App desplegada y arrancando sin errores en los logs
- [ ] Panel de Almacenamiento en verde
- [ ] Los cuatro sitios cargan (Columbia, Rockford, Hush Puppies, Vans)
- [ ] Una solicitud de prueba aparece en `catalog_tickets/tickets/` de la rama
- [ ] La auditoría registra el inicio de sesión en `catalog_tickets/audit/`
