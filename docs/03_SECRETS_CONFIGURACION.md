# Configuracion de secrets

## BigQuery

La app puede leer ARTI y datos maestros desde BigQuery.

Ejemplo:

```toml
[bigquery]
enabled = true
project_id = "forus-analitica-prod-datalake"
table = "forus-analitica-prod-datalake.bronze.stg_pe_central_arti"
# job_project_id = "proyecto-para-jobs-si-aplica"
# location = "US"
```

Service account:

```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

## Shopify

Ejemplo por sitio:

```toml
[shopify_sites.rockford]
shop_domain = "rockfordpe.myshopify.com"
admin_access_token = "shpat_..."
api_version = "2026-04"
```

Sitios esperados:

- `columbia`
- `rockford`
- `hush_puppies`
- `vans`

## Seguridad

Nunca subir `.streamlit/secrets.toml` al repositorio.
