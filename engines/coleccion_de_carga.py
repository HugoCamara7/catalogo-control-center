"""La coleccion de revision que deja cada carga completa.

Por que existe
--------------
Al terminar una carga completa no habia forma de VER lo que se acababa de
cargar. El catalogo de la tienda tiene miles de productos y los de hoy quedan
mezclados con los de siempre: para revisarlos habia que buscarlos uno a uno por
codigo, o filtrar por fecha en el admin -- que no distingue una carga de otra
cuando se cargan dos el mismo dia.

Ahora cada carga completa deja una coleccion con EXACTAMENTE sus productos, y
el nombre dice de que carga es:

    Carga 2026-09-15 · Vans · CAT-0042

Tres datos, y cada uno responde una pregunta: **cuando** se cargo, **que marca**
y **que solicitud**.

Lo que hay que saber para no romperlo
------------------------------------
- **La fecha va en formato ISO** (`2026-09-15`), no `15-09-2026`. El admin de
  Shopify lista las colecciones por orden alfabetico: en ISO eso es orden
  cronologico, y en el otro formato las de un mismo dia de mes quedan juntas
  aunque sean de anos distintos.
- **La coleccion nace MANUAL**, no automatica. Una automatica se llena sola con
  una regla, y aqui no hay regla que valga: lo que entra es la lista exacta de
  esta carga. Ademas `collectionAddProductsV2` agrega al FINAL, asi que en
  MANUAL el orden de la coleccion ES el orden de la carga -- y no hace falta ni
  un movimiento de reordenamiento.
- **Y nace PUBLICADA.** Una coleccion creada por API queda sin publicar:
  existe, se llena y **no la ve nadie**. Es el mismo "cargado no es lo mismo que
  visible" del Status de carga. Publicarla hace que su URL
  (`/collections/<handle>`) funcione; no la mete en el menu de la tienda, que
  eso lo decide una persona.
- **Solo entran los productos que de verdad quedaron en la tienda.** Un
  producto con resultado ERROR no esta cargado: meterlo en la coleccion de
  revision seria decir que si. Los PARCIAL si entran -- estan en la tienda, con
  avisos --, que es justo lo que hay que ir a mirar.
- **Un producto sin id de Shopify no se puede agregar** y se cuenta aparte. La
  API pide el gid; callarlo dejaria la coleccion incompleta sin que nadie
  supiera cuales faltaron.

Sin Streamlit y sin pandas, como el resto de `engines/`: esto lo usan la
pantalla Y el runner de GitHub Actions, que no tiene Streamlit.
"""

import re
import unicodedata

# El prefijo y el separador van aqui y no pegados en el f-string: son lo que
# hace que dos tandas de la MISMA carga -- el runner se queda sin tiempo y
# encadena otra -- den el mismo nombre, y por tanto el mismo handle, y por
# tanto la misma coleccion en vez de dos.
PREFIJO = "Carga"
SEPARADOR = " · "

# Los resultados que significan "esta en la tienda". ERROR no esta.
RESULTADOS_CARGADOS = ("OK", "PARCIAL", "ACTUALIZADO", "CREADO")

# Tope de Shopify para el titulo de una coleccion.
MAXIMO_TITULO = 255


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:  # NaN
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def _sin_acentos(valor):
    return "".join(
        c for c in unicodedata.normalize("NFKD", _texto(valor))
        if not unicodedata.combining(c)
    )


def nombre_de_coleccion(fecha, marca="", ticket=""):
    """`Carga 2026-09-15 · Vans · CAT-0042`.

    Las partes que faltan simplemente no salen: un nombre con un hueco
    (`Carga 2026-09-15 ·  · CAT-0042`) se lee como un error de la app.
    """
    partes = [f"{PREFIJO} {_texto(fecha)}".strip()]
    for parte in (marca, ticket):
        if _texto(parte):
            partes.append(_texto(parte))
    return SEPARADOR.join(partes)[:MAXIMO_TITULO]


def handle_de_coleccion(titulo):
    """El handle con el que se busca y se crea.

    Es lo que hace que la coleccion se pueda REUSAR: dos tandas de la misma
    carga -- el runner se queda sin tiempo y encadena otra -- tienen que acabar
    en la misma coleccion, no en dos.
    """
    texto = _sin_acentos(titulo).lower()
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    return re.sub(r"-+", "-", texto).strip("-")[:255]


def marca_de_la_carga(marcas, etiqueta_del_sitio=""):
    """La marca que va en el nombre.

    Una carga de Vans.pe es de una marca y el nombre lo dice. Una de
    Rockford.pe o Supermall.pe puede traer cuatro o diez: ahi no hay UNA marca,
    y poner la primera seria mentir. Se pone la etiqueta del SITIO, que es
    cierta. Es el mismo criterio que `marca_para_siblings`: donde no hay una
    respuesta, no se adivina.
    """
    unicas = list(dict.fromkeys(_texto(m) for m in (marcas or []) if _texto(m)))
    if len(unicas) == 1:
        return unicas[0]
    return _texto(etiqueta_del_sitio)


def _gid(valor):
    texto = _texto(valor)
    if not texto:
        return ""
    if texto.startswith("gid://"):
        return texto
    return f"gid://shopify/Product/{texto}"


def productos_de_la_carga(filas):
    """`(gids, resumen)` de lo que de verdad quedo en la tienda.

    `filas` son los `result_rows` del job: una por producto (a veces varias),
    con `Handle`, `ID` y `Resultado`. El gid sale del `ID` que devolvio la
    propia carga, asi que **no cuesta ni una lectura mas a Shopify**.

    Un producto con varias filas entra si ALGUNA dice que se cargo: el mismo
    producto puede tener una fila OK del producto y otra de una foto que fallo,
    y dejarlo fuera de la revision por eso seria justo al reves de lo que hace
    falta.
    """
    estado = {}
    identificador = {}
    orden = []
    for fila in filas or []:
        handle = _texto((fila or {}).get("Handle"))
        if not handle:
            continue
        if handle not in estado:
            orden.append(handle)
            estado[handle] = False
        resultado = _texto((fila or {}).get("Resultado")).upper()
        if resultado in RESULTADOS_CARGADOS:
            estado[handle] = True
        gid = _gid((fila or {}).get("ID"))
        if gid and not identificador.get(handle):
            identificador[handle] = gid

    gids, sin_id, con_error = [], [], []
    for handle in orden:
        if not estado[handle]:
            con_error.append(handle)
            continue
        gid = identificador.get(handle, "")
        if gid:
            gids.append(gid)
        else:
            sin_id.append(handle)
    return list(dict.fromkeys(gids)), {
        "cargados": len(gids),
        "sin_id": sin_id,
        "con_error": con_error,
    }
