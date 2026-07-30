# Inventario de archivos

Repositorio `HugoCamara7/catalogo-control-center`. 102 archivos, 14.2 MB.

Generado analizando imports, rutas literales y rutas construidas en tiempo de ejecucion, y verificando la **firma binaria** de cada archivo contra su extension.


## Archivos corrompidos: eliminar del repositorio

El nombre no corresponde al contenido. Ninguno se usa; la app lee los originales de `data/`.

| Ruta | Contenido real | Accion |
|---|---|---|
| `config.toml` | JavaScript de generate_catalog_input_template.mjs | **ELIMINAR** |
| `dimensiones_productos.xlsx` | imagen WEBP, no un Excel. El real esta en data/ | **ELIMINAR** |
| `download` | copia del .gitignore | **ELIMINAR** |
| `formato_input_catalog_control_center.xlsx` | texto plano, no es un Excel valido | **ELIMINAR** |
| `matrixify_modelo.xlsx` | imagen WEBP, no un Excel. El real esta en data/ | **ELIMINAR** |

## Datos maestros (obligatorios en produccion)

| Ruta | Tipo | Tamano | Quien lo usa | Nota |
|---|---|---:|---|---|
| `data/arti.zip` | ZIP/XLSX | 5.7 MB | `app_matrixify.py`, `generate_columbia_matrixify.py` | Respaldo del maestro ARTI. La app lee BigQuery primero. |
| `data/base_categorias_centry.xlsx` | ZIP/XLSX | 44.8 KB | `app_matrixify.py` | Categorias Centry. |
| `data/bodegas_ecomm.xlsx` | ZIP/XLSX | 10.2 KB | `app_matrixify.py` | Reglas de bodegas eCommerce. |
| `data/centry_codex_categorias.xlsx` | ZIP/XLSX | 7.8 KB | `app_matrixify.py` | Codex de categorias. |
| `data/dimensiones_productos.xlsx` | ZIP/XLSX | 158.9 KB | `app_matrixify.py` | Dimensiones para Centry. |
| `data/matrixify_modelo.xlsx` | ZIP/XLSX | 3.3 MB | `app_matrixify.py` | Catalogo Matrixify de referencia. |
| `data/tipos_shopify.xlsx` | ZIP/XLSX | 5.3 KB | `app_matrixify.py`, `generate_columbia_matrixify.py` | Tipos/familias vigentes en Shopify. |

## Codigo

| Ruta | Lineas | Tamano | SHA-256 |
|---|---:|---:|---|
| `app_matrixify.py` | 17,063 | 771.2 KB | `378e6f0892992e01` |
| `centry_static_masters.py` | 5,874 | 144.0 KB | `da93677657723e0f` |
| `generate_columbia_matrixify.py` | 3,319 | 122.5 KB | `617e8c435a1a4fb2` |
| `ticket_system.py` | 1,093 | 49.0 KB | `b1f91c89e7ccd377` |
| `shopify_api.py` | 1,421 | 43.7 KB | `2e432abdeb14e265` |
| `catalog_rules.py` | 632 | 24.7 KB | `6379faaff094244a` |
| `engines/audit.py` | 437 | 15.6 KB | `f47ee0112ae47e33` |
| `scripts/test_ticket_system.py` | 314 | 13.4 KB | `108383200f4d9520` |
| `scripts/test_engines_audit.py` | 288 | 11.9 KB | `389d01c5eb65aa94` |
| `scripts/convert_rockford_create_inputs.py` | 321 | 11.4 KB | `1d0594e36e5b1b30` |
| `test_partial_maintenance_validations.py` | 321 | 11.4 KB | `1d0594e36e5b1b30` |
| `scripts/convert_rockford_accessories_input.py` | 246 | 9.4 KB | `291ca96b884b3a8c` |
| `test_catalog_rules.py` | 246 | 9.4 KB | `291ca96b884b3a8c` |
| `engines/storage_check.py` | 176 | 7.8 KB | `02c9ac3d649b7700` |
| `scripts/build_hush_input_template.py` | 177 | 7.5 KB | `a20e7247b6fdeda2` |
| `test_brand_commercial_input.py` | 177 | 7.5 KB | `a20e7247b6fdeda2` |
| `scripts/run_matrixify_from_input.py` | 205 | 7.1 KB | `74f0da496a7185fb` |
| `scripts/test_brand_commercial_input.py` | 177 | 6.7 KB | `5e0dc05a99e1c333` |
| `scripts/test_partial_maintenance_validations.py` | 146 | 4.9 KB | `0ee4bea4736204e2` |
| `job_store.py` | 145 | 4.3 KB | `4a14162123c06efb` |

## Configuracion y despliegue

| Ruta | Para que sirve | Contiene secretos |
|---|---|---|
| `.streamlit/config.toml` | Configuracion de Streamlit (tamano de subida, tema, watcher) | NO |
| `.streamlit/secrets.example.toml` | Plantilla de secretos, sin valores reales | NO |
| `requirements.txt` | Dependencias de la app Streamlit | NO |
| `requirements-api.txt` | Dependencias del worker FastAPI (no se usa en Streamlit Cloud) | NO |
| `.github/workflows/catalog-control-center.yml` | GitHub Actions: genera Matrixify por sitio | NO, usa GitHub Secrets |
| `render.yaml` | Despliegue del worker en Render | NO |
| `Dockerfile.api` | Imagen del worker FastAPI | NO |
| `.gitignore` | Excluye outputs/, secrets.toml y bases pesadas | NO |

## Nunca deben subirse

| Ruta | Motivo |
|---|---|
| `.streamlit/secrets.toml` | Credenciales reales. Va en Streamlit Cloud > Settings > Secrets. |
| `outputs/` | Todo lo que genera la app. Se regenera solo. |
| `data/jobs.sqlite*` | Base local de trabajos. |
