# Despliegue en Streamlit

## Archivos que deben subirse

Subir todo el contenido del paquete `release_matrixify_go_live`, excepto secretos reales.

No subir:

- `.streamlit/secrets.toml`
- `outputs/`
- `__pycache__/`

## Configuracion en Streamlit Cloud

Main file:

```text
app_matrixify.py
```

Dependencias:

```text
requirements.txt
```

Secrets:

Pegar el contenido final en **App settings -> Secrets** usando como base:

```text
.streamlit/secrets.example.toml
```

## Despues de desplegar

1. Entrar a la app.
2. Confirmar que BigQuery aparezca activo si corresponde.
3. Probar un input pequeno por sitio.
4. Descargar Matrixify, Centry y Carga Sial.
5. Confirmar que no haya tildes danadas ni colores codigo en Centry.
