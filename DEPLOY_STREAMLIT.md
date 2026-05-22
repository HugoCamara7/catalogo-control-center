# Despliegue Streamlit + GitHub

## Flujo recomendado

La app vive en un repositorio privado de GitHub y se despliega en Streamlit Community Cloud.

El usuario final solo carga el input de Comercial. Las bases quedan fijas dentro del repositorio:

```text
data/arti.zip
data/matrixify_modelo.xlsx
data/tipos_shopify.xlsx
```

## Archivos que deben subirse al repositorio

```text
app_matrixify.py
generate_columbia_matrixify.py
requirements.txt
README.md
DEPLOY_STREAMLIT.md
.gitignore
.streamlit/config.toml
data/arti.zip
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

6. Compartir el link generado con el equipo.

## Actualizar bases

Cuando cambie el ARTI:

1. Reemplazar:

```text
data/arti.zip
```

2. Hacer commit y push a GitHub.

Cuando cambie la descarga Matrixify base:

1. Reemplazar:

```text
data/matrixify_modelo.xlsx
```

2. Hacer commit y push a GitHub.

Streamlit redeploya automaticamente despues del push.
