# Inventario de entrega - Catalogo Control Center

Fecha de entrega: 2026-06-15

## Archivos principales

- `app_matrixify.py`: aplicacion Streamlit principal.
- `generate_columbia_matrixify.py`: generador Matrixify/Sial por sitio.
- `shopify_api.py`: cliente Shopify Admin API.
- `centry_static_masters.py`: maestros estaticos para Centry.
- `requirements.txt`: dependencias Python.

## Configuracion

- `.streamlit/config.toml`: configuracion Streamlit.
- `.streamlit/secrets.example.toml`: plantilla de credenciales. No contiene secretos reales.

## Datos maestros incluidos

- `data/matrixify_modelo.xlsx`
- `data/tipos_shopify.xlsx`
- `data/arti.zip`
- `data/base_categorias_centry.xlsx`
- `data/centry_codex_categorias.xlsx`
- `data/dimensiones_productos.xlsx`
- `data/bodegas_ecomm.xlsx`

## Assets y scripts

- `assets/brands/*`: logos por marca.
- `scripts/*.py`: utilitarios de conversion de inputs.

## Documentacion

- `docs/01_INSTALACION_LOCAL.md`
- `docs/02_DESPLIEGUE_STREAMLIT.md`
- `docs/03_SECRETS_CONFIGURACION.md`
- `docs/04_CHECKLIST_GO_LIVE.md`
- `docs/05_FUNCIONALIDAD_VALIDADA.md`

## No incluido

- `.streamlit/secrets.toml`
- `outputs/`
- `__pycache__/`
- archivos temporales locales
