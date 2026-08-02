# Que subir a GitHub

Espejo completo de `HugoCamara7/catalogo-control-center` rama `main`, descargado
el 2026-08-02 despues de tus commits de las 09:29 UTC, con lo que falta aplicado
encima.

## Lo que paso (importante)

Hoy subiste dos paquetes seguidos:

| Commit | Hora UTC | Contenido |
|---|---|---|
| `118ae43c0` | 09:25 | mi entrega de nombres/handle/bullets (app `+16/-7`, generate `+221/-24`) |
| `88276e508` | 09:29 | tipos de prenda (app `+7/-16`, catalog_rules `+791/-632`) |
| `b1cb8d31d` | 09:29 | `scripts/test_tipos_de_prenda.py` |

El paquete de tipos de prenda venia armado sobre un `app_matrixify.py` anterior,
asi que su `+7/-16` **deshizo exactamente** el `+16/-7` del paquete previo. Por
eso los nombres dejaron de funcionar: `generate_columbia_matrixify.py` si quedo
con los cambios, pero `app_matrixify.py` volvio a la version sin ellos.

Nada de tipos de prenda se perdio: ese paquete solo cambiaba `catalog_rules.py`
y los tests. Su `app_matrixify.py` era identico al base.

## Solo hay que subir 1 archivo

```
app_matrixify.py          (23 lineas cambiadas respecto de main)
```

Lo demas ya esta correcto en `main` y en esta carpeta queda igual:

| Archivo | Estado en main |
|---|---|
| `generate_columbia_matrixify.py` | ya tiene mis cambios, no tocar |
| `catalog_rules.py` | ya tiene tipos de prenda, no tocar |
| `scripts/test_tipos_de_prenda.py` | ya esta, no tocar |
| `scripts/test_separadores_lista.py` | ya esta, no tocar |
| `CAMBIOS_NOMBRE_HANDLE_BULLETS.md` | ya esta, identico |

## Que hace el cambio de app_matrixify.py

1. Importa `MissingInputColumnError` y `split_pipe_items` del generador.
2. `_split_tags` delega en `split_pipe_items` en vez de tener su propia regla.
3. Al crear un producto en Shopify ya no cae a `title=... or handle`: si el
   Title viene vacio, ese producto falla con mensaje claro en vez de crearse con
   el codigo modelo-color como nombre.
4. Captura `MissingInputColumnError` antes del `except Exception` generico, para
   mostrar un error limpio cuando el input no trae la columna del nombre.

Sin este archivo, el generador arma bien el Title y el Handle en el Excel, pero
la sincronizacion directa a Shopify vuelve a poner el codigo como nombre.

## Validacion ejecutada sobre esta carpeta

| Test | Resultado |
|---|---|
| test_engines_audit.py | 45 OK |
| test_separadores_lista.py | 42 OK |
| test_engines_normalize.py | 38 OK |
| test_engines_ticket_flow.py | 29 OK |
| test_ticket_system.py | 28 OK |
| test_carga_desde_solicitud.py | 20 OK |
| test_engines_excel_io.py | 18 OK |
| **test_tipos_de_prenda.py** | **13 OK** |
| test_catalog_rules.py | OK |
| test_partial_maintenance_validations.py | OK |
| test_auth_accesos.py | falla, **igual en main limpio de hoy** |
| test_brand_commercial_input.py | falla, **igual en main limpio de hoy** |

Los 13 tests de tipos de prenda pasan con mis cambios aplicados: las dos cosas
conviven sin chocar. Las dos que fallan se comprobaron contra una copia limpia
del main de hoy y fallan exactamente igual, asi que son anteriores.

## Antes de correr la carga completa

Cambian **1.956 URLs de producto** entre las cuatro marcas. Los productos no se
duplican (el emparejamiento va por el metafield `codigo_modelo_color` y se
conserva el `ID`, asi que Matrixify renombra), pero la URL publica si cambia.

**Confirma que Shopify tenga activada la creacion automatica de redirecciones**
antes de correr. Conviene empezar por Vans, que son 30 productos.

## Para la proxima

Si vas a subir dos paquetes seguidos, avisame antes de armar el segundo: lo
construyo sobre el resultado del primero y no se pisan.
