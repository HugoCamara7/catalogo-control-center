# Instalacion local

## Requisitos

- Python 3.11 o superior.
- Acceso a internet para instalar dependencias.
- Credenciales Shopify y BigQuery si se usara la integracion completa.

## Pasos

1. Abrir PowerShell en la carpeta del paquete.

2. Crear ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. Instalar dependencias:

```powershell
pip install -r requirements.txt
```

4. Crear secrets locales:

```powershell
Copy-Item .streamlit\secrets.example.toml .streamlit\secrets.toml
```

5. Completar `.streamlit/secrets.toml` con BigQuery y Shopify.

6. Ejecutar:

```powershell
streamlit run app_matrixify.py
```

7. Abrir:

```text
http://localhost:8501
```

## Validacion rapida

- La app debe cargar sin error.
- En el sidebar debe permitir seleccionar sitio.
- Debe mostrar estado de BigQuery/Shopify segun la configuracion.
