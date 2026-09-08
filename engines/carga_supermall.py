"""La carga de Supermall, armada con lo que ya esta cargado en las otras webs.

Por que existe
--------------
Supermall.pe es el sitio ESPEJO: lleva el catalogo de TODOS los demas. Hasta
ahora la app resolvia los dos extremos del problema y nada de lo del medio:

- **La pestana "Espejo de Supermall"** dice QUE FALTA: la resta entre lo que
  hay en los demas sitios y lo que hay en Supermall, y entrega la lista de
  codigos Modelo-Color.
- **El boton "Preparar esta carga para Supermall.pe"** hace la segunda pasada
  de una carga que se acaba de hacer, reusando el input comercial del dia.

Entre los dos no habia nada. El espejo entregaba un Excel con miles de codigos
y mandaba a "Carga parcial -> Carga Sial", pero esa pantalla:

1. Solo produce la hoja Carga Sial. **No produce el Matrixify**, que es lo que
   crea el producto en Shopify. Sin Matrixify no hay carga.
2. Lee el catalogo de **UN solo sitio: el activo**. Y si el sitio activo es
   Supermall, ahi esos productos por definicion NO estan. De `product_lookup`
   salen el titulo, la descripcion, el tipo, los tags, el color y los
   metacampos: el producto habria salido casi vacio.

O sea que la informacion existe -- esta en Vans.pe, Rockford.pe, Columbia.pe --
pero el camino que la app ofrecia no la miraba. Y el otro camino, el de la
segunda pasada, solo sirve para lo que se acaba de cargar: para los miles de
productos historicos no hay input comercial que reusar.

**Lo que faltaba no era una pantalla: era el paso de CONSOLIDACION.** Eso es
este modulo.

Que hace y que no
-----------------
Recibe los catalogos de todos los sitios tal y como los deja
`cargar_catalogos_de_todos_los_sitios` y devuelve, por codigo Modelo-Color, la
mejor ficha disponible mas el parte de de donde salio cada campo. No habla con
Shopify, no lee BigQuery y no arma el Matrixify: eso es de la capa que lo usa,
que ya tiene `build_centry_matrixify_from_master` con sus pruebas.

**No vuelve a escribir como se lee un producto de Shopify**: la identidad, la
marca y el estado web salen de `engines/load_status`, igual que en
`engines/espejo_supermall`. Dos lectores del mismo producto se separan sin que
nadie lo note, que es lo que este repositorio ya paga con las dos
`normalize_size`.

Sin Streamlit y sin pandas, como el resto de `engines/`.
"""

from engines.espejo_supermall import DESTINO
from engines.load_status import (
    PRENDIDO,
    SIN_MARCA,
    clave_de_producto,
    estado_web,
    marca_de_producto,
    modelo_color,
)

# Los campos que se consolidan, en el orden en el que se miran. Cada uno se
# resuelve por SEPARADO: tomar "el sitio ganador" entero desperdicia el campo
# que solo tiene el otro.
CAMPOS = (
    "Title",
    "Body HTML",
    "Type",
    "Tags",
    "Image Src",
    "Metafield: custom.genero [single_line_text_field]",
    "Metafield: custom.color [single_line_text_field]",
    "Metafield: custom.materialidad [single_line_text_field]",
    "Metafield: custom.tecnologia [list.single_line_text_field]",
    "Metafield: custom.logo [list.metaobject_reference]",
    "Metafield: custom.nombre_corto [single_line_text_field]",
    "Metafield: custom.descripcion_corta [single_line_text_field]",
)

# Motivos por los que un codigo no se puede cargar. Bloquean.
SIN_CODIGO = "Sin codigo Modelo-Color"
SIN_TITULO = "Sin nombre de producto en ninguna web"
SIN_TIPO = "Sin tipo de prenda en ninguna web"
# Motivos que solo avisan: la carga sigue.
SIN_GENERO = "Sin genero en ninguna web"
SIN_FOTOS = "Sin fotos en ninguna web"
SIN_MARCA_CONOCIDA = "Marca sin identificar"


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def _primero_no_vacio(candidatos):
    """El primer valor con contenido, y de que sitio salio."""
    for sitio, valor in candidatos:
        if _texto(valor):
            return _texto(valor), sitio
    return "", ""


def _orden_de_sitios(catalogos_por_sitio, orden_declarado=()):
    """El orden en el que se miran los sitios. Estable entre ejecuciones.

    **Ningun sitio manda sobre otro.** Supermall no tiene marca propia: lleva
    todas, asi que no hay un "sitio dueno" del producto al que darle
    preferencia. Lo que decide, campo a campo, es quien tiene el dato -- y a
    igualdad, el sitio donde el producto esta PRENDIDO Y VISIBLE, porque ese es
    el que alguien reviso de verdad.

    El desempate final es el orden declarado (el de `SITE_CONFIGS`) y no el de
    llegada: una consolidacion que cambia de resultado en cada ejecucion no se
    puede comparar con la anterior, que es la misma regla que la tabla de
    sitios del Status de carga.
    """
    declarado = [s for s in orden_declarado if s in catalogos_por_sitio]
    resto = sorted(s for s in catalogos_por_sitio if s not in declarado)
    return [s for s in declarado + resto if s != DESTINO]


def consolidar(catalogos_por_sitio, codigos=(), destino=DESTINO,
               etiquetas_de_sitio=None, marcas_conocidas=(), orden_de_sitios=()):
    """La mejor ficha de cada codigo, con el parte de de donde salio cada campo.

    `codigos` acota a una lista (la que entrega el espejo). Vacia = todos los
    que existan en algun sitio distinto del destino.

    Devuelve `{"fichas": [...], "resumen": {...}}`. Cada ficha lleva:

    - los campos consolidados,
    - `Origen por campo`: que sitio aporto cada uno,
    - `Sitios de origen` y `Estado en Supermall`,
    - `Bloqueos` y `Avisos`, que es lo que la pantalla tiene que ensenar antes
      de dejar generar nada.
    """
    catalogos_por_sitio = catalogos_por_sitio or {}
    etiquetas_de_sitio = etiquetas_de_sitio or {}
    pedidos = {_texto(c).upper() for c in codigos or [] if _texto(c)}
    sitios = _orden_de_sitios(catalogos_por_sitio, orden_de_sitios)

    en_destino = {}
    for producto in catalogos_por_sitio.get(destino) or []:
        clave = clave_de_producto(producto)
        if clave:
            en_destino[clave] = producto

    # Se agrupa por identidad. Dentro de cada grupo, los productos van en el
    # orden de `sitios`, y los PRENDIDOS primero: a igualdad de dato manda el
    # sitio donde el producto esta visible de verdad.
    grupos = {}
    for site_key in sitios:
        etiqueta = _texto(etiquetas_de_sitio.get(site_key)) or site_key
        for producto in catalogos_por_sitio.get(site_key) or []:
            clave = clave_de_producto(producto)
            if not clave:
                continue
            codigo = modelo_color(producto)
            if pedidos and codigo.upper() not in pedidos and clave.upper() not in pedidos:
                continue
            grupos.setdefault(clave, []).append((etiqueta, producto))

    fichas = []
    for clave, candidatos in grupos.items():
        candidatos.sort(key=lambda par: 0 if estado_web(par[1]) == PRENDIDO else 1)
        fichas.append(_ficha(clave, candidatos, en_destino, marcas_conocidas))

    fichas.sort(key=lambda f: (f["Mod-Col"] or f["Clave"]))
    return {"fichas": fichas, "resumen": resumen(fichas)}


def _ficha(clave, candidatos, en_destino, marcas_conocidas):
    principal = candidatos[0][1]
    codigo = ""
    for _etiqueta, producto in candidatos:
        codigo = modelo_color(producto)
        if codigo:
            break

    ficha = {
        "Clave": clave,
        "Mod-Col": codigo,
        "Sitios de origen": ", ".join(dict.fromkeys(e for e, _ in candidatos)),
    }
    origen_por_campo = {}
    for campo in CAMPOS:
        valor, sitio = _primero_no_vacio(
            (etiqueta, producto.get(campo)) for etiqueta, producto in candidatos
        )
        ficha[campo] = valor
        if valor:
            origen_por_campo[campo] = sitio
    # `Genero` viaja tambien con su nombre corto: es lo que lee el conversor de
    # tallas, y sin el una zapatilla de Vans no se puede pasar a PE.
    ficha["Genero"] = ficha.get("Metafield: custom.genero [single_line_text_field]", "")

    marca, _sitio_marca = _primero_no_vacio(
        (etiqueta, marca_de_producto(producto, marcas_conocidas))
        for etiqueta, producto in candidatos
    )
    ficha["Marca"] = marca or SIN_MARCA
    ficha["Origen por campo"] = ", ".join(
        f"{campo.split('.')[-1].split(' ')[0] or campo}={sitio}"
        for campo, sitio in origen_por_campo.items()
    )

    producto_destino = en_destino.get(clave)
    ficha["Estado en Supermall"] = estado_web(producto_destino) if producto_destino else ""
    ficha["Ya esta en Supermall"] = producto_destino is not None
    ficha["Accion"] = "Actualizar" if producto_destino is not None else "Crear"

    bloqueos, avisos = _revisar(ficha)
    ficha["Bloqueos"] = "; ".join(bloqueos)
    ficha["Avisos"] = "; ".join(avisos)
    ficha["Se puede cargar"] = not bloqueos
    ficha["_principal"] = principal
    return ficha


def _revisar(ficha):
    """Que impide cargar este producto, y que solo hay que saber.

    La separacion importa: un producto sin nombre no se puede publicar, pero
    uno sin genero SI -- solo que su calzado se queda en la talla de origen. Un
    aviso que bloquea detiene una carga de miles por un dato que no lo merece.
    """
    bloqueos = []
    avisos = []
    if not ficha["Mod-Col"]:
        bloqueos.append(SIN_CODIGO)
    if not ficha.get("Title"):
        bloqueos.append(SIN_TITULO)
    if not ficha.get("Type"):
        bloqueos.append(SIN_TIPO)
    if not ficha.get("Genero"):
        avisos.append(SIN_GENERO)
    if not ficha.get("Image Src"):
        avisos.append(SIN_FOTOS)
    if ficha.get("Marca") == SIN_MARCA:
        avisos.append(SIN_MARCA_CONOCIDA)
    return bloqueos, avisos


def resumen(fichas):
    """Los numeros de arriba de la pantalla.

    Las CLAVES no llevan tilde, igual que en `engines/load_status`: una clave
    con tilde que la pantalla pide sin ella es un KeyError que tumba la
    pantalla, y con `.get()` es peor -- devuelve None y no aparece nunca.
    """
    fichas = fichas or []
    return {
        "Productos consolidados": len(fichas),
        "Se pueden cargar": sum(1 for f in fichas if f["Se puede cargar"]),
        "Bloqueados": sum(1 for f in fichas if not f["Se puede cargar"]),
        "Con aviso": sum(1 for f in fichas if f["Avisos"]),
        "Se crean": sum(1 for f in fichas if f["Accion"] == "Crear" and f["Se puede cargar"]),
        "Se actualizan": sum(1 for f in fichas if f["Accion"] == "Actualizar" and f["Se puede cargar"]),
    }


def codigos_cargables(fichas):
    """Los codigos que se pueden pedir, sin repetir y sin los bloqueados."""
    codigos = []
    for ficha in fichas or []:
        if not ficha.get("Se puede cargar"):
            continue
        codigo = _texto(ficha.get("Mod-Col")).upper()
        if codigo and codigo not in codigos:
            codigos.append(codigo)
    return codigos


def productos_para_matrixify(fichas):
    """Las fichas con la forma de un producto de `fetch_products`.

    Es lo que se le pasa a `build_centry_matrixify_from_master` como catalogo
    de ORIGEN, en vez del catalogo del sitio activo. Asi el titulo, la
    descripcion, el tipo, los tags y los metacampos salen de la web donde el
    producto SI esta, que es el agujero que este modulo cierra.
    """
    productos = []
    for ficha in fichas or []:
        if not ficha.get("Se puede cargar"):
            continue
        principal = ficha.get("_principal") or {}
        producto = dict(principal)
        producto.update({campo: ficha.get(campo, "") for campo in CAMPOS})
        producto["Mod-Col"] = ficha["Mod-Col"]
        producto["Marca"] = ficha["Marca"]
        producto["Genero"] = ficha.get("Genero", "")
        # El Handle y el ID son de la tienda de ORIGEN y no valen en el
        # destino: un producto que no esta en Supermall se CREA, y darle el
        # handle de Vans.pe lo enlazaria con una ficha que no existe. La capa
        # de aplicacion los resuelve contra el catalogo de Supermall.
        producto.pop("Handle", None)
        producto.pop("Product ID", None)
        producto.pop("Legacy ID", None)
        productos.append(producto)
    return productos


def filas_para_tabla(fichas):
    """La consolidacion como tabla legible, sin el producto crudo dentro."""
    return [
        {
            "Mod-Col": f["Mod-Col"],
            "Marca": f["Marca"],
            "Producto": f.get("Title", ""),
            "Tipo": f.get("Type", ""),
            "Genero": f.get("Genero", ""),
            "Accion": f["Accion"],
            "Estado en Supermall": f["Estado en Supermall"],
            "Sitios de origen": f["Sitios de origen"],
            "Bloqueos": f["Bloqueos"],
            "Avisos": f["Avisos"],
            "Origen por campo": f["Origen por campo"],
        }
        for f in fichas or []
    ]
