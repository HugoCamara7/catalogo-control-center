# Catalogo Control Center - paquete go live

Este paquete contiene la aplicacion Streamlit para generar Matrixify, Centry, Carga Sial y sincronizar variantes con Shopify API.

## Inicio rapido

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app_matrixify.py
```

Luego abrir:

```text
http://localhost:8501
```

## Configuracion

Usar:

```text
.streamlit/secrets.example.toml
```

como base para crear:

```text
.streamlit/secrets.toml
```

No subir `secrets.toml` a ningun repositorio.

## Documentos

Leer en este orden:

1. `docs/00_INVENTARIO_ENTREGA.md`
2. `docs/01_INSTALACION_LOCAL.md`
3. `docs/03_SECRETS_CONFIGURACION.md`
4. `docs/02_DESPLIEGUE_STREAMLIT.md`
5. `docs/04_CHECKLIST_GO_LIVE.md`
6. `docs/05_FUNCIONALIDAD_VALIDADA.md`

## Archivos clave

- `app_matrixify.py`
- `generate_columbia_matrixify.py`
- `shopify_api.py`
- `centry_static_masters.py`
- `data/`
- `assets/`

## Importante

El paquete no incluye secretos reales. Completar credenciales BigQuery y Shopify antes de operar en produccion.
