# FastAPI + Cloud Run para sincronizaciones largas

Este es el primer MVP para mover la sincronizacion pesada fuera de Streamlit.

## Objetivo

- Streamlit queda como interfaz operativa.
- FastAPI recibe un Excel Matrixify y crea un `job_id`.
- El worker procesa producto por producto usando la misma logica de `app_matrixify.py`.
- El avance queda guardado en SQLite y el resultado final queda en `outputs/jobs`.

## Archivos nuevos

- `api_main.py`: API HTTP para crear jobs, consultar estado y descargar resultado.
- `catalog_engine.py`: wrapper de sincronizacion que llama a `apply_full_product_updates`.
- `job_store.py`: persistencia SQLite para estado/eventos.
- `sync_worker.py`: CLI para ejecutar un job por fuera de la API.
- `requirements-api.txt`: dependencias del backend.
- `Dockerfile.api`: contenedor para Cloud Run.

## Ejecutar local

Instalar dependencias:

```powershell
pip install -r requirements-api.txt
```

Configurar credenciales en variables de entorno. Puedes usar variables genericas:

```powershell
$env:SHOPIFY_SHOP_DOMAIN="columbiape.myshopify.com"
$env:SHOPIFY_ADMIN_API_ACCESS_TOKEN="shpat_xxx"
$env:SHOPIFY_INVENTORY_LOCATION_IDS="gid://shopify/Location/123,gid://shopify/Location/456"
```

O por sitio:

```powershell
$env:COLUMBIA_SHOP_DOMAIN="columbiape.myshopify.com"
$env:COLUMBIA_ADMIN_API_ACCESS_TOKEN="shpat_xxx"
$env:COLUMBIA_INVENTORY_LOCATION_IDS="gid://shopify/Location/123,gid://shopify/Location/456"
```

Levantar API:

```powershell
uvicorn api_main:app --reload --port 8080
```

Crear job con un Excel Matrixify:

```powershell
curl -X POST "http://localhost:8080/jobs/sync-shopify" `
  -F "site_key=COLUMBIA" `
  -F "start_immediately=true" `
  -F "file=@outputs/matrixify_columbia_generado.xlsx"
```

Consultar avance:

```powershell
curl "http://localhost:8080/jobs/{job_id}"
```

Descargar resultado:

```powershell
curl -L "http://localhost:8080/jobs/{job_id}/result" -o resultado.xlsx
```

## Despliegue Cloud Run

Construir imagen:

```powershell
gcloud builds submit --tag gcr.io/PROJECT_ID/catalog-control-api -f Dockerfile.api
```

Desplegar API:

```powershell
gcloud run deploy catalog-control-api `
  --image gcr.io/PROJECT_ID/catalog-control-api `
  --region us-central1 `
  --allow-unauthenticated `
  --memory 1Gi `
  --cpu 1
```

Configurar secrets/variables de entorno en Cloud Run:

- `SHOPIFY_SHOP_DOMAIN`
- `SHOPIFY_ADMIN_API_ACCESS_TOKEN`
- `SHOPIFY_INVENTORY_LOCATION_IDS`
- `GOOGLE_APPLICATION_CREDENTIALS` si corresponde

## Nota importante para produccion

Este MVP usa SQLite dentro del contenedor para estado. Eso sirve para prueba local y primera validacion.

Para produccion real en Cloud Run, el siguiente paso debe ser mover persistencia a uno de estos:

- Firestore
- Cloud SQL PostgreSQL
- Cloud Storage para eventos/resultados

Asi el estado no se pierde si Cloud Run reinicia la instancia.

## Siguiente mejora recomendada

Agregar en Streamlit una pantalla "Sincronizacion avanzada" que:

1. Envie el Excel a `POST /jobs/sync-shopify`.
2. Guarde el `job_id`.
3. Consulte `GET /jobs/{job_id}` cada pocos segundos.
4. Muestre avance.
5. Permita descargar `GET /jobs/{job_id}/result`.
