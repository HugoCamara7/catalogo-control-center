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


def _clave_texto(valor):
    return _texto(valor).casefold()


class _Candidato:
    """Un producto en un sitio concreto, con su marca ya resuelta.

    Antes esto era una tupla `(etiqueta, producto)` y la marca se resolvia
    despues, sobre el producto suelto. Eso perdia el sitio, que es justo el
    ultimo respaldo para leerla: un producto de Columbia.pe sin metacampo y sin
    tag solo se puede saber que es Columbia porque esta en Columbia.pe.
    """

    __slots__ = ("site_key", "etiqueta", "producto", "marca")

    def __init__(self, site_key, etiqueta, producto, marca):
        self.site_key = site_key
        self.etiqueta = etiqueta
        self.producto = producto
        self.marca = marca


def _primero_no_vacio(candidatos):
    """El primer valor con contenido, y de que sitio salio."""
    for sitio, valor in candidatos:
        if _texto(valor):
            return _texto(valor), sitio
    return "", ""


def _marca_del_grupo(candidatos):
    """La marca del producto, mirando TODAS las webs donde esta.

    `marca_de_producto` nunca devuelve vacio: cuando no la sabe devuelve la
    cadena "Sin marca". Tomando "el primer valor no vacio" del grupo, ese
    centinela GANABA -- un producto sin metacampo en la primera web salia "Sin
    marca" aunque la segunda lo tuviera perfectamente etiquetado. Aqui se
    salta el centinela y solo se cae en el cuando ninguna web sabe la marca.
    """
    for candidato in candidatos:
        if candidato.marca and candidato.marca != SIN_MARCA:
            return candidato.marca
    return SIN_MARCA


def _orden_de_candidatos(candidatos, marca, sitio_de_marca, posicion):
    """En que orden se miran las webs de un mismo producto.

    Tres criterios, en este orden:

    1. **El sitio PROPIO de la marca primero.** Columbia se vende en
       Columbia.pe y tambien en Rockford.pe; un producto de Columbia esta en
       las dos y hay que quedarse con UNA ficha. La que vale es la de
       Columbia.pe: es la tienda de la marca, la que su equipo mantiene, y la
       que lleva la ficha completa. Sin este criterio la ficha salia de la web
       que cayera primero en el orden de `SITE_CONFIGS`, o sea de Columbia.pe
       o de Rockford.pe segun el alfabeto, que no es una razon.
    2. **Prendido y visible antes que apagado**, porque ese es el que alguien
       reviso de verdad.
    3. **El orden declarado** (`SITE_CONFIGS`) como desempate final, nunca el
       de llegada: una consolidacion que cambia en cada ejecucion no se puede
       comparar con la anterior.
    """
    propio = sitio_de_marca.get(_clave_texto(marca), "")
    return sorted(
        candidatos,
        key=lambda c: (
            0 if propio and c.site_key == propio else 1,
            0 if estado_web(c.producto) == PRENDIDO else 1,
            posicion.get(c.site_key, len(posicion)),
        ),
    )


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
               etiquetas_de_sitio=None, marcas_conocidas=(), orden_de_sitios=(),
               marcas_por_sitio=None, sitio_de_marca=None, destino_leido=None,
               vendors_de_sitio=()):
    """La mejor ficha de cada codigo, con el parte de de donde salio cada campo.

    `codigos` acota a una lista (la que entrega el espejo). Vacia = todos los
    que existan en algun sitio distinto del destino.

    Devuelve `{"fichas": [...], "resumen": {...}}`. Cada ficha lleva:

    - los campos consolidados,
    - `Origen por campo`: que sitio aporto cada uno,
    - `Sitios de origen` y `Estado en Supermall`,
    - `Bloqueos` y `Avisos`, que es lo que la pantalla tiene que ensenar antes
      de dejar generar nada.

    `marcas_por_sitio` ({site_key: [marcas]}) es el ultimo respaldo para leer
    la marca: en un sitio de una sola marca, un producto sin metacampo y sin
    tag es de esa marca. `sitio_de_marca` ({marca: site_key}) dice cual es el
    sitio PROPIO de cada marca -- ver `_orden_de_candidatos`.

    `destino_leido` distingue el destino AUSENTE del destino VACIO. Si el
    catalogo de Supermall no se pudo leer, todo saldria como "Crear" y eso se
    leeria como "hay que cargar el catalogo entero"; peor todavia, generar esa
    carga crearia productos que ya existen. Viaja en `resumen["destino_leido"]`
    para que la pantalla corte.
    """
    catalogos_por_sitio = catalogos_por_sitio or {}
    etiquetas_de_sitio = etiquetas_de_sitio or {}
    marcas_por_sitio = dict(marcas_por_sitio or {})
    sitio_de_marca = {_clave_texto(m): s for m, s in (sitio_de_marca or {}).items()}
    if destino_leido is None:
        destino_leido = destino in catalogos_por_sitio
    pedidos = {_texto(c).upper() for c in codigos or [] if _texto(c)}
    sitios = _orden_de_sitios(catalogos_por_sitio, orden_de_sitios)
    posicion = {site_key: indice for indice, site_key in enumerate(sitios)}

    en_destino = {}
    for producto in catalogos_por_sitio.get(destino) or []:
        clave = clave_de_producto(producto)
        if clave:
            en_destino[clave] = producto

    # Se agrupa por identidad -- el mismo Modelo-Color en Columbia.pe y en
    # Rockford.pe es UN producto, no dos. El orden dentro del grupo lo decide
    # `_orden_de_candidatos`, ya con la marca resuelta.
    grupos = {}
    for site_key in sitios:
        etiqueta = _texto(etiquetas_de_sitio.get(site_key)) or site_key
        del_sitio = marcas_por_sitio.get(site_key) or ()
        for producto in catalogos_por_sitio.get(site_key) or []:
            clave = clave_de_producto(producto)
            if not clave:
                continue
            codigo = modelo_color(producto)
            if pedidos and codigo.upper() not in pedidos and clave.upper() not in pedidos:
                continue
            marca = marca_de_producto(
                producto, marcas_conocidas, del_sitio, vendors_de_sitio)
            grupos.setdefault(clave, []).append(
                _Candidato(site_key, etiqueta, producto, marca))

    fichas = []
    for clave, candidatos in grupos.items():
        marca = _marca_del_grupo(candidatos)
        candidatos = _orden_de_candidatos(candidatos, marca, sitio_de_marca, posicion)
        fichas.append(_ficha(clave, candidatos, en_destino, marca))

    fichas.sort(key=lambda f: (f["Mod-Col"] or f["Clave"]))
    return {"fichas": fichas, "resumen": resumen(fichas, destino_leido=destino_leido)}


def _ficha(clave, candidatos, en_destino, marca):
    principal = candidatos[0].producto
    codigo = ""
    for candidato in candidatos:
        codigo = modelo_color(candidato.producto)
        if codigo:
            break

    ficha = {
        "Clave": clave,
        "Mod-Col": codigo,
        "Marca": marca or SIN_MARCA,
        # El primero de la lista ya es el que manda: el sitio propio de la
        # marca. Se nombra aparte porque cuando un producto esta en tres webs
        # la pregunta siguiente siempre es de cual salio la ficha.
        "Web principal": candidatos[0].etiqueta,
        "Sitios de origen": ", ".join(dict.fromkeys(c.etiqueta for c in candidatos)),
        "En cuantas webs": len(dict.fromkeys(c.etiqueta for c in candidatos)),
    }
    origen_por_campo = {}
    for campo in CAMPOS:
        valor, sitio = _primero_no_vacio(
            (c.etiqueta, c.producto.get(campo)) for c in candidatos
        )
        ficha[campo] = valor
        if valor:
            origen_por_campo[campo] = sitio
    # `Genero` viaja tambien con su nombre corto: es lo que lee el conversor de
    # tallas, y sin el una zapatilla de Vans no se puede pasar a PE.
    ficha["Genero"] = ficha.get("Metafield: custom.genero [single_line_text_field]", "")

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
    ficha["Situacion"] = _situacion_de_ficha(ficha)
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


def resumen(fichas, destino_leido=True):
    """Los numeros de arriba de la pantalla.

    Las CLAVES no llevan tilde, igual que en `engines/load_status`: una clave
    con tilde que la pantalla pide sin ella es un KeyError que tumba la
    pantalla, y con `.get()` es peor -- devuelve None y no aparece nunca.

    Los cuatro numeros de SITUACION son los que hacen que la pantalla diga algo.
    Antes las tarjetas eran "consolidados / se pueden cargar / se crean", y con
    la lista ya filtrada a lo que falta los tres daban el MISMO numero: tres
    tarjetas para un solo dato. Estos cuatro reparten el total y suman el total.
    """
    fichas = fichas or []
    cuenta = {}
    for ficha in fichas:
        situacion = ficha.get("Situacion") or _situacion_de_ficha(ficha)
        cuenta[situacion] = cuenta.get(situacion, 0) + 1
    total = len(fichas)
    ya = cuenta.get(YA_VISIBLE, 0)
    return {
        "Productos consolidados": total,
        "Se pueden cargar": sum(1 for f in fichas if f["Se puede cargar"]),
        "Bloqueados": sum(1 for f in fichas if not f["Se puede cargar"]),
        "Con aviso": sum(1 for f in fichas if f["Avisos"]),
        "Se crean": sum(1 for f in fichas if f["Accion"] == "Crear" and f["Se puede cargar"]),
        "Se actualizan": sum(1 for f in fichas if f["Accion"] == "Actualizar" and f["Se puede cargar"]),
        YA_VISIBLE: ya,
        SIN_PUBLICAR: cuenta.get(SIN_PUBLICAR, 0),
        FALTA_CARGAR: cuenta.get(FALTA_CARGAR, 0),
        NO_CARGABLE: cuenta.get(NO_CARGABLE, 0),
        "Marcas": len({_texto(f.get("Marca")) or SIN_MARCA for f in fichas}),
        "Sin marca": sum(1 for f in fichas if (_texto(f.get("Marca")) or SIN_MARCA) == SIN_MARCA),
        "En mas de una web": sum(1 for f in fichas if (f.get("En cuantas webs") or 1) > 1),
        "Cobertura": round(100.0 * ya / total, 1) if total else 0.0,
        "destino_leido": bool(destino_leido),
    }


def codigos_cargables(fichas, situaciones=None):
    """Los codigos que se pueden pedir, sin repetir y sin los bloqueados.

    `situaciones` acota a un subconjunto de `SEGMENTOS`. La pantalla pasa
    `(FALTA_CARGAR,)`: lo que ya esta en Supermall no se vuelve a cargar --
    recargarlo le reescribiria la ficha sin que nadie lo haya pedido, que es la
    misma regla que ya sigue el espejo. Sin el parametro entran todos los
    cargables, que es lo que hace falta cuando se quiere REHACER la ficha.
    """
    permitidas = set(situaciones) if situaciones else None
    codigos = []
    vistos = set()
    for ficha in fichas or []:
        if not ficha.get("Se puede cargar"):
            continue
        if permitidas is not None and (ficha.get("Situacion") or _situacion_de_ficha(ficha)) not in permitidas:
            continue
        codigo = _texto(ficha.get("Mod-Col")).upper()
        if codigo and codigo not in vistos:
            vistos.add(codigo)
            codigos.append(codigo)
    return codigos


def productos_para_matrixify(fichas, situaciones=None):
    """Las fichas con la forma de un producto de `fetch_products`.

    Es lo que se le pasa a `build_centry_matrixify_from_master` como catalogo
    de ORIGEN, en vez del catalogo del sitio activo. Asi el titulo, la
    descripcion, el tipo, los tags y los metacampos salen de la web donde el
    producto SI esta, que es el agujero que este modulo cierra.
    """
    permitidas = set(situaciones) if situaciones else None
    productos = []
    for ficha in fichas or []:
        if not ficha.get("Se puede cargar"):
            continue
        if permitidas is not None and (ficha.get("Situacion") or _situacion_de_ficha(ficha)) not in permitidas:
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
            "Situacion": f.get("Situacion") or _situacion_de_ficha(f),
            "Producto": f.get("Title", ""),
            "Tipo": f.get("Type", ""),
            "Genero": f.get("Genero", ""),
            "Accion": f["Accion"],
            "Estado en Supermall": f["Estado en Supermall"],
            "Web principal": f.get("Web principal", ""),
            "Sitios de origen": f["Sitios de origen"],
            "En cuantas webs": f.get("En cuantas webs", 1),
            "Bloqueos": f["Bloqueos"],
            "Avisos": f["Avisos"],
            "Origen por campo": f["Origen por campo"],
        }
        for f in fichas or []
    ]


# --- El hueco por marca, para el panel de antes de cargar -----------------
#
# La pregunta es "que le falta a Supermall COMPARADO con las otras marcas", y
# esa se responde por marca: cuanto de lo que existe en las demas webs ya esta
# visible en Supermall y cuanto no. Sale de las fichas YA consolidadas, asi que
# no cuesta ninguna lectura extra.

YA_VISIBLE = "Ya visible"
SIN_PUBLICAR = "Cargado sin publicar"
FALTA_CARGAR = "Falta cargar"
NO_CARGABLE = "No se puede cargar"

# El orden es el de la barra, y es un orden de ESTADO -de mejor a peor-, no de
# identidad: por eso lleva los colores de estado de la app y no una paleta
# categorica. Cada segmento va con su etiqueta y su numero, nunca solo color.
SEGMENTOS = (YA_VISIBLE, SIN_PUBLICAR, FALTA_CARGAR, NO_CARGABLE)


def _situacion_de_ficha(ficha):
    """En que estado esta este producto respecto de Supermall.

    `No se puede cargar` va aparte de `Falta cargar` a proposito: son los que
    no tienen codigo, nombre o tipo en ninguna web. Mezclarlos haria creer que
    con pulsar el boton se resuelven, y no.
    """
    if not ficha.get("Se puede cargar"):
        return NO_CARGABLE
    if not ficha.get("Ya esta en Supermall"):
        return FALTA_CARGAR
    return YA_VISIBLE if ficha.get("Estado en Supermall") == PRENDIDO else SIN_PUBLICAR


def hueco_por_marca(fichas):
    """Una fila por marca con el reparto de sus productos entre los 4 estados.

    Ordenado por lo que FALTA, de mayor a menor: la primera fila es donde hay
    mas trabajo, que es la razon de mirar el panel. Un orden alfabetico
    obligaria a leer las 10 filas para encontrar eso.
    """
    marcas = {}
    for ficha in fichas or []:
        marca = _texto(ficha.get("Marca")) or SIN_MARCA
        fila = marcas.setdefault(marca, {
            "Marca": marca, "Total": 0,
            YA_VISIBLE: 0, SIN_PUBLICAR: 0, FALTA_CARGAR: 0, NO_CARGABLE: 0,
        })
        fila["Total"] += 1
        fila[_situacion_de_ficha(ficha)] += 1
    filas = []
    for fila in marcas.values():
        total = fila["Total"] or 1
        fila["Cobertura"] = round(100.0 * fila[YA_VISIBLE] / total, 1)
        filas.append(fila)
    return sorted(filas, key=lambda f: (-f[FALTA_CARGAR], -f["Total"], f["Marca"]))


def totales_del_hueco(filas):
    """La fila de totales, para el titular del panel.

    Se suma sobre las FILAS por marca y no sobre las fichas otra vez: si los
    dos numeros se calcularan por separado podrian discrepar, y un panel que se
    contradice consigo mismo no se puede usar para decidir.
    """
    filas = filas or []
    totales = {clave: sum(f.get(clave, 0) for f in filas) for clave in SEGMENTOS}
    totales["Total"] = sum(f.get("Total", 0) for f in filas)
    totales["Marcas"] = len(filas)
    base = totales["Total"] or 1
    totales["Cobertura"] = round(100.0 * totales[YA_VISIBLE] / base, 1)
    return totales
