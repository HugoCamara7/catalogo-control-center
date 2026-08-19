# Reassign Control Center

Aplicacion Streamlit para automatizar la **reasignacion de pedidos que no pudieron
despacharse** (`SIN_STOCK` / `SIN_DESPACHO`) hacia la tienda de mayor prioridad que
tenga stock disponible.

Parte de la familia de herramientas internas de Forus Peru, con el mismo lenguaje
visual que Catalogo Control Center y Revenue Control Center.

```
Subir archivo -> Validar -> Consultar BigQuery -> Reasignar -> Revisar -> Descargar
```

> **BigQuery es solo lectura.** La app consulta stock; nunca lo modifica. El
> descuento de unidades ocurre en memoria durante la corrida.

---

## Que hace

1. Lee el Excel de pedidos (`.xls` o `.xlsx`) conservando **todas** sus columnas.
2. Identifica los pedidos a reasignar. **Los estados se eligen en la propia
   interfaz**, con los que trae el archivo: por defecto `SIN_STOCK` y
   `SIN_DESPACHO`, pero sirve cualquiera (`PENDIENTE_ASIGNACION`, etc.).
   Tolera `sin stock`, `Sin-Stock`, `SIN_STOCK` como el mismo estado.
3. Toma el SKU de cada pedido y consulta el stock por tienda en BigQuery.
4. Reasigna segun una **lista de prioridad configurable en Excel**, nunca en codigo.
5. Descuenta el stock utilizado durante la misma corrida, para no comprometer dos
   veces el mismo par (SKU, tienda).
6. Nunca reasigna a la tienda de origen del propio pedido.
7. Marca `SIN OPCION DE REASIGNACION` cuando ninguna tienda alcanza.
8. Genera el Excel final con las columnas originales intactas y la tienda escrita
   en `Nom Tda Reasignada` (la crea si el archivo no la trae).

Antes de programar nada se analizo un archivo real de 402 pedidos y 58 columnas:
ver **[docs/ANALISIS_EXCEL.md](docs/ANALISIS_EXCEL.md)** para columnas, estados,
riesgos detectados y el diseno de la tabla de prioridades.

---

## Instalacion

```bash
git clone <url-del-repositorio>
cd reassign-control-center
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
```

Configura los secretos:

```bash
copy .streamlit\secrets.example.toml .streamlit\secrets.toml
```

### Compatible con los secrets de Catalogo Control Center

Puedes pegar tal cual los bloques `[bigquery]`, `[gcp_service_account]` y
`[app_auth]` de esa aplicacion: las claves que esta app no usa se ignoran, y el
login acepta el mismo formato (`username`/`password` o `[app_auth.users]`).

Una advertencia que importa: **en Catalogo Control Center la clave `table`
apunta a la tabla ARTI** (maestro de productos), no al stock. Esta app la
**ignora a proposito** y resuelve el stock asi:

| Clave | Uso |
|-------|-----|
| `stock_table` | tabla de stock, si quieres fijar otra |
| *(ausente)* | `forus-analitica-prod-datalake.bronze.stg_pe_central_stock_bi` |
| `table` | **ignorada** (es la tabla ARTI) |

Tambien acepta un `stock_query` propio. Si trae el parametro `@skus` se consulta
por lotes; si no, se ejecuta completa una vez y se filtra en memoria. Las columnas
pueden venir como `sku`/`id_producto` y `cod_tienda`/`codigo_tienda`.

La seccion `[app_auth]` es **opcional**: si no existe, la app queda sin login.

Genera la configuracion de prioridad y arranca:

```bash
python -m scripts.build_priority_template
python -m streamlit run app.py
```

El repositorio incluye `config/prioridad_tiendas.ejemplo.xlsx` como referencia.
El archivo real (`config/prioridad_tiendas.xlsx`) esta en `.gitignore`: es
operativo, cambia seguido y no tiene por que viajar en el repo.

---

## Configuracion de prioridad (no se toca codigo)

Todo el criterio de negocio vive en `config/prioridad_tiendas.xlsx`, editable desde
Excel por el equipo comercial. Se puede tambien subir desde la barra lateral sin
tocar el servidor.

| Hoja | Contenido |
|------|-----------|
| `Prioridad` | `sitio`, `marca`, `cod_tienda`, `nom_tienda`, `prioridad`, `activo`, `stock_seguridad`, `max_unidades` |
| `Tiendas` | maestro de bodegas: codigo, nombre, activo, stock de seguridad |
| `Parametros` | reglas conmutables del motor (ver tabla abajo) |
| `Instrucciones` | ayuda para quien edita el archivo |

`sitio` y `marca` aceptan `*` como comodin. **Una fila con el sitio exacto siempre
desplaza a las filas comodin**, asi el resultado es predecible.

### Parametros

| Parametro | Default | Efecto |
|-----------|---------|--------|
| `estados_objetivo` | `SIN_STOCK,SIN_DESPACHO` | que estados se reasignan |
| `excluir_tienda_origen` | `SI` | no reasignar a la tienda que ya tenia el pedido |
| `permitir_reasignacion_parcial` | `NO` | cubrir solo parte de las unidades |
| `agrupar_por_shgroup` | `NO` | todas las lineas de un despacho a la misma tienda |
| `fallback_linea_si_grupo_falla` | `SI` | si nadie cubre el grupo, resolver linea por linea |
| `incluir_stock_bodega_central` | `SI` | en la bodega 320 suma `stock_bodega` |
| `stock_seguridad_global` | `0` | unidades intocables en todas las tiendas |
| `max_unidades_por_tienda` | `0` | tope por tienda y corrida (`0` = sin tope) |
| `columna_salida` | `Nom Tda Reasignada` | nombre exacto de la columna destino |

---

## Interfaz

Capturas de la aplicacion en ejecucion, en `capturas/`:

| Archivo | Pantalla |
|---------|----------|
| `capturas/1-acceso.png` | Acceso |
| `capturas/2-validacion.png` | Validacion del archivo (paso 2) |
| `capturas/3-resultado.png` | KPIs, vista previa y descargas (paso 5) |

Las mismas pantallas en HTML responsive: **[docs/preview.html](docs/preview.html)**.

**Pantalla de acceso**: se activa configurando `[app_auth]` en `secrets.toml`.
Sin esa seccion la app queda abierta, para que un despliegue nuevo no se bloquee
antes de estar configurado.

Barra lateral **permanente** (no colapsable) con marca, rail de pasos, configuracion
de prioridad y fuente de stock.

**Selector de estados**: en el paso 2 se marcan los estados a reasignar entre los
que realmente trae el archivo, sin editar ningun Excel. El resto de las filas se
conservan intactas en la salida.

**Nombres de columna tolerantes**: reconoce `Sitio_1` (sufijo que agrega Excel al
duplicar), `Método_de_Despacho` con tilde y `MÃ©todo_de_Despacho` con la
codificacion danada. El encabezado original se conserva byte a byte en la salida.

**KPIs**: pedidos recibidos, pedidos a reasignar, reasignados, sin stock disponible,
errores; mas unidades, tiendas usadas y tasa de exito.

**Vista previa**: `Pedido | SKU | Tienda origen | Unidades | Tienda reasignada |
Stock disponible | Resultado`, con buscador y pestanas por resultado, por tienda y
de validacion.

**Descargas**:

| Archivo | Para que |
|---------|----------|
| `reasignacion_<fecha>.xlsx` | el que se sube a la plataforma destino |
| `reporte_reasignacion_<fecha>.xlsx` | interno: KPIs, detalle, uso por tienda, validaciones, prioridad usada |

Las columnas de trazabilidad (`Reasig_*`) son **opcionales**: desactivadas, el Excel
de carga queda con exactamente las columnas originales mas la de reasignacion.

---

## Modo sin BigQuery

En la barra lateral se puede elegir **"Archivo de stock"** y subir un Excel/CSV con
al menos `sku`, `cod_tienda` y `stock`. Sirve para probar la app sin credenciales y
para simulaciones puntuales del equipo.

---

## Estructura

```
app.py                          entrypoint Streamlit (flujo de 6 pasos)
config/
  settings.py                   columnas, rutas, defaults (sin reglas de negocio)
  prioridad_tiendas.ejemplo.xlsx  configuracion de ejemplo (versionada)
  prioridad_tiendas.xlsx        configuracion real (no versionada)
core/
  excel_io.py                   lectura/escritura fiel de .xls y .xlsx
  validation.py                 validaciones y deteccion de riesgos
  priority.py                   carga y resolucion de la lista de prioridad
  stock_source.py               BigQuery (solo lectura) y archivo de stock
  engine.py                     motor de reasignacion y KPIs
ui/
  theme.py                      tema Forus + barra lateral permanente
  components.py                 hero, KPIs, notas, rail de pasos
scripts/
  build_priority_template.py    genera la plantilla de configuracion
  build_release_zip.py          empaqueta el proyecto para GitHub
  test_rules.py                 22 pruebas de reglas de negocio
  test_app_flow.py              9 pruebas de la app (acceso, flujo, sesion)
  test_secrets_compat.py        11 pruebas de compatibilidad de secrets
  smoke_test.py                 prueba end-to-end contra un Excel real
docs/
  ANALISIS_EXCEL.md             analisis del formato de entrada
  preview.html                  vista previa de las pantallas
capturas/                       PNG de la app en ejecucion
assets/forus.png                logotipo institucional
```

No usa FastAPI: es una aplicacion Streamlit autocontenida.

---

## Pruebas

```bash
python -m scripts.test_rules
```

22 casos sobre el motor. Cubre prioridad, descuento temporal de stock, no-sobreventa, exclusion de tienda
origen, `SIN OPCION DE REASIGNACION`, filtro de estados, stock de seguridad, topes
por tienda, reasignacion parcial, agrupacion por `ShGroup`, creacion de la columna
de salida, reconocimiento de columnas con tilde/mojibake/sufijo y manejo de
filas sin SKU.

```bash
python -m scripts.test_app_flow
```

9 casos sobre la aplicacion con `streamlit.testing.AppTest`: pantalla de acceso,
credenciales correctas e incorrectas, normalizacion del correo, cierre de sesion y
arranque del flujo con la sesion iniciada.

```bash
python -m scripts.test_secrets_compat
```

11 casos que fijan la compatibilidad con los secrets de Catalogo Control Center:
que `table` (tabla ARTI) nunca se use como tabla de stock, que la service account
se acepte como dict o como JSON en texto, y que una consulta con el esquema de
`stg_pe_central_stock_bi` se entienda igual que una propia.

```bash
python -m scripts.smoke_test "ruta\al\Formato de Carga Reasignacion.xls"
```

Corre el flujo completo con stock sintetico y verifica que no haya sobreasignacion,
que ninguna fila vuelva a su tienda origen y que el archivo escrito conserve las 58
columnas originales.

---

## Notas de operacion

* **`ShGroup` de mas de 15 digitos**: Excel los guarda como coma flotante y los
  ultimos digitos ya vienen alterados desde el origen. La app los escribe como texto
  para no empeorarlo, pero conviene pedirlos como texto al sistema que genera el
  archivo.
* **`Nom_Tienda_Asig` vacio**: en el archivo de muestra lo esta en el 94 % de las
  filas, asi que la regla de excluir la tienda origen aplica a muy pocos casos. La
  app lo reporta como alerta en el paso 2.
* **Encabezados con mojibake** (`Â¿Quien_Recibe?`): se conservan byte a byte porque
  la plataforma destino los espera asi.
* **`client.showSidebarNavigation = false`**: no activarlo. En Streamlit 1.60 esa
  opcion elimina la barra lateral completa en apps de una sola pagina.

---

## Empaquetar para GitHub

```bash
python -m scripts.build_release_zip
```

Genera `reassign-control-center.zip` dejando fuera `secrets.toml`, la configuracion
operativa de prioridad, `outputs/` y los caches. Aborta si detecta un secreto dentro
del paquete.

---

## Despliegue

**Streamlit Community Cloud**: apuntar a `app.py`, pegar el contenido de
`secrets.example.toml` en *Settings -> Secrets* con los valores reales, y subir
`config/prioridad_tiendas.xlsx` por la barra lateral (o versionarlo si no es
sensible).

`.streamlit/secrets.toml` y `config/prioridad_tiendas.xlsx` estan en `.gitignore`:
las credenciales y la configuracion operativa nunca van al repositorio.
