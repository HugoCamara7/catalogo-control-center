# Despliegue Streamlit + GitHub

## Flujo recomendado

La app vive en un repositorio privado de GitHub y se despliega en Streamlit Community Cloud.

El usuario final solo carga el input de Comercial. El ARTI se lee desde BigQuery y las otras bases quedan fijas dentro del repositorio:

```text
data/matrixify_modelo.xlsx
data/tipos_shopify.xlsx
```

`data/arti.zip` puede quedar como respaldo local, pero ya no es obligatorio si BigQuery esta configurado.

## Archivos que deben subirse al repositorio

```text
app_matrixify.py
generate_columbia_matrixify.py
requirements.txt
README.md
DEPLOY_STREAMLIT.md
.gitignore
.streamlit/config.toml
.streamlit/secrets.example.toml
data/matrixify_modelo.xlsx
data/tipos_shopify.xlsx
```

No subir:

```text
outputs/
data/arti.xlsx
data/arti.csv
__pycache__/
```

No subir nunca:

```text
.streamlit/secrets.toml
```

## Desplegar en Streamlit Community Cloud

1. Entrar a:

```text
https://share.streamlit.io
```

2. Iniciar sesion con GitHub.

3. Elegir **Create app**.

4. Seleccionar:

```text
Repository: app-matrixify-columbia
Branch: main
Main file path: app_matrixify.py
```

5. Presionar **Deploy**.

6. Antes de compartir, abrir **App settings -> Secrets** y pegar las credenciales:

```toml
[bigquery]
enabled = true
project_id = "forus-analitica-prod-datalake"
# Si la service account no puede crear jobs en el datalake,
# poner aqui un proyecto donde si tenga BigQuery Job User.
# job_project_id = "tu-proyecto-de-jobs"
table = "forus-analitica-prod-datalake.bronze.stg_pe_central_arti"
# location = "US"

[gcp_service_account]
type = "service_account"
project_id = "TU_PROJECT_ID"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "tu-service-account@tu-project.iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

Para la carga parcial **Activar inventario en sucursales**, el token de Shopify debe poder leer `locations` y escribir inventario. Si el token no tiene permiso para leer `locations`, agrega las sucursales manualmente en cada sitio:

```toml
[shopify_sites.columbia]
inventory_location_ids = "gid://shopify/Location/123456789,gid://shopify/Location/987654321"
```

Tambien acepta IDs numericos separados por coma:

```toml
inventory_location_ids = "123456789,987654321"
```

Si al ejecutar aparece un mensaje de permiso de escritura de inventario, el token debe recrearse o actualizarse con scope de inventario, por ejemplo `write_inventory` / Inventory management.

7. Compartir el link generado con el equipo.

## Actualizar bases

Cuando cambie el ARTI:

1. Actualizar la tabla en BigQuery.
2. Reiniciar la app desde Streamlit si quieres forzar lectura inmediata.

La app debe mostrar `OK BigQuery` en **Estado de bases** y `Arti usado: BigQuery: forus-analitica-prod-datalake.bronze.stg_pe_central_arti` al procesar.

Como el ARTI de BigQuery no trae precio, el archivo final queda asi:

```text
Status = Active
Published = FALSE
Variant Price = vacio
```

Esto es esperado.

La app tambien omite variantes con talla `0` y agrega una hoja `Carga Sial` al Excel descargado.

Cuando cambie la descarga Matrixify base:

1. Reemplazar:

```text
data/matrixify_modelo.xlsx
```

2. Hacer commit y push a GitHub.

Streamlit redeploya automaticamente despues del push.

## Como actualizar el repositorio en GitHub

Si editas desde la web de GitHub:

1. Entra al repositorio `app-matrixify-columbia`.
2. Presiona **Add file -> Upload files**.
3. Arrastra y reemplaza estos archivos actualizados:

```text
app_matrixify.py
generate_columbia_matrixify.py
requirements.txt
README.md
DEPLOY_STREAMLIT.md
.streamlit/secrets.example.toml
```

4. Escribe un mensaje como:

```text
Conecta ARTI BigQuery
```

5. Presiona **Commit changes**.

No subas ni edites en GitHub:

```text
.streamlit/secrets.toml
```

Los Secrets reales se mantienen solo en Streamlit Cloud.

## Permisos BigQuery necesarios

La service account debe tener:

```text
BigQuery Job User
```

en el proyecto donde se ejecutan los jobs, normalmente el valor de `project_id` o `job_project_id`.

Tambien debe tener permiso de lectura sobre la tabla:

```text
BigQuery Data Viewer
```

en el dataset o tabla `forus-analitica-prod-datalake.bronze.stg_pe_central_arti`.

Si aparece este error:

```text
User does not have bigquery.jobs.create permission
```

no es un error de codigo. Falta otorgar `BigQuery Job User` a la service account, o cambiar `job_project_id` a un proyecto donde esa cuenta si pueda crear jobs.
