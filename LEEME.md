# Subir estos 7 archivos

El ZIP ya viene con la estructura de carpetas correcta. Cada archivo va en la
misma ruta que tiene aquí dentro.

## Reemplazar (1)

| Archivo del ZIP | Ruta en GitHub |
|---|---|
| `app_matrixify.py` | raíz del repositorio |

## Agregar (6)

| Archivo del ZIP | Ruta en GitHub |
|---|---|
| `assets/app.css` | `assets/app.css` |
| `engines/__init__.py` | `engines/__init__.py` |
| `engines/normalize.py` | `engines/normalize.py` |
| `engines/excel_io.py` | `engines/excel_io.py` |
| `scripts/test_engines_normalize.py` | `scripts/test_engines_normalize.py` |
| `INVENTARIO_ARCHIVOS.md` | raíz del repositorio |

`engines/` es una carpeta **nueva**. Las demás ya existen.

---

## Importante

> **Sube los 7 en un solo commit.**
> Si subes `app_matrixify.py` sin la carpeta `engines/`, la app no arranca
> (`ModuleNotFoundError: engines`).

**Tus secretos no se tocan.** Este paquete no contiene ningún `secrets.toml`.
Tus credenciales reales están en Streamlit Cloud → Manage app → Settings → Secrets,
que no se ve afectado por subir archivos a GitHub.

---

## Paso a paso (web de GitHub)

1. **Add file → Create new file**. En el nombre escribe `engines/__init__.py`
   (al poner la barra `/` se crea la carpeta). Pega el contenido del archivo
   del ZIP y confirma.
2. Entra a la carpeta `engines/` → **Add file → Upload files** → arrastra
   `normalize.py` y `excel_io.py`.
3. Entra a `assets/` → **Upload files** → arrastra `app.css`.
4. Entra a `scripts/` → **Upload files** → arrastra `test_engines_normalize.py`.
5. Vuelve a la **raíz** → **Upload files** → arrastra `app_matrixify.py` e
   `INVENTARIO_ARCHIVOS.md`.
6. Mensaje de commit sugerido:
   `Fase 0 + Fase 1: CSS a assets, limpieza de codigo sin uso y motores normalize/excel_io`

## Paso a paso (Git)

```bash
git checkout -b fase1-motores
# copiar los archivos del ZIP respetando las rutas
git add app_matrixify.py assets/app.css engines/ scripts/test_engines_normalize.py INVENTARIO_ARCHIVOS.md
git commit -m "Fase 0 + Fase 1: CSS a assets, limpieza y motores normalize/excel_io"
git push origin fase1-motores
```

---

## Después del despliegue

Streamlit Cloud redespliega solo en 1–3 minutos.

- [ ] La pantalla de login se ve igual.
- [ ] La barra lateral conserva color, ancho y logos.
- [ ] Al cambiar de sitio (Columbia → Rockford → Hush Puppies → Vans) los
      colores cambian con cada marca.
- [ ] KPIs de catálogo cargan.
- [ ] Solicitudes abre la bandeja y el detalle.
- [ ] Carga completa genera el Matrixify.
- [ ] Carga parcial muestra el preview.

**Si algo falla:** GitHub → Commits → abre el commit → botón **Revert**.
O sube el `app_matrixify.py` de `Catalog_Control_Center_RESPALDO_COMPLETO.zip`
(sha256 `bfc74eb924350fcd6c2f07bbc401b28c9ffe2f6fb3a1239bbc78efd6731bf78e`).

| Síntoma | Solución |
|---|---|
| `ModuleNotFoundError: engines` | Falta la carpeta `engines/`; sube sus 3 archivos |
| App sin estilos + mensaje rojo con una ruta | Falta `assets/app.css`; súbelo |
