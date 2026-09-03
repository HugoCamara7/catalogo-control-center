"""Motor del Status de carga de catalogos.

Sin dependencias de Streamlit ni de pandas.

Por que existe
--------------
El seguimiento de cuanto han inyectado las marcas y cuanto se cargo de verdad
se llevaba a mano en un Excel (`Status_Carga_Catalogo`), con las casillas de
marca por sitio y los SKUs por clase escritos uno a uno. Ese archivo envejece
en cuanto alguien carga algo y nadie lo actualiza, y no puede responder la
pregunta que de verdad importa: **de lo que entro, que quedo prendido y
visible en la web y que no**.

Aqui se arma lo mismo pero con los datos vivos, y con esa columna de mas:

- Lo que INYECTAN las marcas sale de las solicitudes (`ticket_system`).
- Lo que esta CARGADO sale del catalogo real de cada sitio (Shopify).
- Lo que FALTA es la resta: solicitudes que todavia no terminaron, y productos
  que estan creados pero apagados o sin publicar.

La unidad es el **Codigo Modelo-Color**, igual que en `engines/stock.py`: es lo
que se prende o se apaga en la web. Una variante no es un producto.

Que devuelve
------------
Tablas como DATOS (listas de diccionarios). Quien dibuja es la pantalla; este
modulo no sabe que existe Streamlit.
"""

CLASES = ("Accesorios", "Vestuario", "Calzado")
SIN_CLASE = "Sin clase"
SIN_MARCA = "Sin marca"

# Estado de un producto en la web. Solo el primero cuenta como "prendido":
# ACTIVE por si solo no basta, porque un producto activo que no esta publicado
# en el canal Online Store no lo ve nadie. Esa diferencia era justo la que no
# se podia mirar en el Excel a mano.
PRENDIDO = "Prendido y visible"
ACTIVO_SIN_PUBLICAR = "Activo sin publicar"
BORRADOR = "Borrador"
ARCHIVADO = "Archivado"
ESTADOS_WEB = (PRENDIDO, ACTIVO_SIN_PUBLICAR, BORRADOR, ARCHIVADO)

MARCADO = "☑"      # casilla marcada
SIN_MARCAR = "☐"   # casilla vacia

# El tipo de carga de la solicitud, con el nombre que usa el Excel de status.
TIPOS_DE_CARGA = {"complete": "Carga nueva", "partial": "Actualizacion"}


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def _clave(valor):
    return _texto(valor).casefold()


def _identidad(fila):
    """La llave con la que se cuenta una fila del inventario.

    `Clave` la pone `inventario()`. El respaldo es para filas armadas a mano
    (pruebas viejas, llamadas externas) que traen solo `Mod-Col`.
    """
    fila = fila or {}
    clave = _texto(fila.get("Clave"))
    if clave:
        return clave
    codigo = _texto(fila.get("Mod-Col")).upper()
    if codigo:
        return codigo
    handle = _clave(fila.get("Handle"))
    return "handle:%s" % handle if handle else ""


def _entero(valor):
    try:
        return int(float(_texto(valor) or 0))
    except (TypeError, ValueError):
        return 0


# --- lectura de un producto de Shopify -----------------------------------
def modelo_color(producto):
    """El Codigo Modelo-Color, en mayuscula. Es la llave de todo el modulo."""
    return _texto((producto or {}).get("Mod-Col")).upper()


def marca_de_producto(producto, marcas_conocidas=()):
    """La marca comercial del producto.

    `Vendor` NO sirve: en Shopify es el vendor del SITIO (`rockfordpe`), el
    mismo para todas las marcas de esa tienda. Contando por vendor, Rockford.pe
    saldria con una sola marca y Columbia, Patagonia y Sorel desaparecerian.

    Manda el metacampo `custom.marca`, que la app escribe en cada producto. Si
    falta (productos viejos), se busca alguna marca conocida entre los tags,
    que es donde tambien la deja el generador.
    """
    producto = producto or {}
    marca = _texto(producto.get("Marca"))
    if marca:
        return marca
    conocidas = {_clave(m): _texto(m) for m in marcas_conocidas if _texto(m)}
    if conocidas:
        for tag in _texto(producto.get("Tags")).split(","):
            encontrada = conocidas.get(_clave(tag))
            if encontrada:
                return encontrada
    return SIN_MARCA


def clase_de_producto(producto, clase_de_tipo=None):
    """Accesorios / Vestuario / Calzado. Se DERIVA del tipo, no se pide.

    `clase_de_tipo` es `engines.garment_types.clase_de` inyectada, para no
    amarrar este motor a ese diccionario ni duplicarlo aqui.
    """
    producto = producto or {}
    tipo = _texto(producto.get("Type"))
    if clase_de_tipo and tipo:
        clase = _texto(clase_de_tipo(tipo))
        if clase:
            return clase
    # Respaldo: el tag de clase que el generador ya escribe en el producto.
    tags = {_clave(t) for t in _texto(producto.get("Tags")).split(",")}
    for clase in CLASES:
        if _clave(clase) in tags:
            return clase
    return SIN_CLASE


def estado_web(producto):
    """En que estado esta el producto para el comprador.

    Publicado se lee de `Published Online Store`, que la consulta trae del
    canal Online Store. Cuando la tienda no expone el canal ese campo llega
    vacio: en ese caso no se puede afirmar que este publicado, y un ACTIVE sin
    confirmacion se reporta como "Activo sin publicar" en vez de inventar un SI.
    """
    producto = producto or {}
    estado = _texto(producto.get("Status")).upper()
    publicado = _texto(producto.get("Published Online Store")).upper() == "SI"
    if estado == "ARCHIVED":
        return ARCHIVADO
    if estado == "DRAFT":
        return BORRADOR
    if estado == "ACTIVE" and publicado:
        return PRENDIDO
    return ACTIVO_SIN_PUBLICAR


def visible_en_la_web(producto):
    return estado_web(producto) == PRENDIDO


def clave_de_producto(producto):
    """Identidad estable de un producto, para poder contarlo.

    Es el Modelo-Color cuando lo hay. Cuando NO lo hay se usa el handle, con
    prefijo para que no pueda chocar con un codigo real.

    Por que no alcanza con el Modelo-Color: sale del metacampo
    `custom.codigo_modelo_color`, que los productos viejos no tienen. Contando
    directamente por ese campo, TODOS los productos sin metacampo comparten la
    misma llave (la cadena vacia) y el `set` los colapsa en uno solo. Medido:
    7 productos de los cuales 4 sin metacampo se reportaban como 4, mientras la
    tabla de visibilidad -- que cuenta filas -- decia 7. Dos numeros distintos
    para lo mismo en la misma pantalla.

    Peor todavia en la resta: con dos productos sin metacampo, uno visible y
    uno en borrador, la cadena vacia quedaba en el conjunto de cargados Y en el
    de visibles, asi que "No visibles" daba 0 con la mitad del catalogo apagado.
    """
    producto = producto or {}
    codigo = modelo_color(producto)
    if codigo:
        return codigo
    handle = _clave(producto.get("Handle"))
    return "handle:%s" % handle if handle else ""


# --- inventario aplanado --------------------------------------------------
def inventario(productos_por_sitio, clase_de_tipo=None, marcas_conocidas=(), etiquetas_de_sitio=None):
    """Una fila por (sitio, producto), ya con marca, clase y estado web.

    Es la base de todas las tablas de abajo: se recorre Shopify UNA vez.

    `productos_por_sitio` es {site_key: [producto, ...]}. Un sitio que no
    respondio se pasa como lista vacia y simplemente no aporta filas; no se
    inventan ceros que parecerian catalogo apagado.
    """
    etiquetas = dict(etiquetas_de_sitio or {})
    filas = []
    for site_key, productos in (productos_por_sitio or {}).items():
        etiqueta = _texto(etiquetas.get(site_key)) or _texto(site_key)
        vistos = set()
        for producto in productos or []:
            clave = clave_de_producto(producto)
            if not clave or clave in vistos:
                # Un Modelo-Color se cuenta UNA vez por sitio. Dos productos
                # con el mismo codigo son un duplicado del catalogo, no dos SKU.
                continue
            vistos.add(clave)
            estado = estado_web(producto)
            codigo = modelo_color(producto)
            filas.append({
                "Sitio": etiqueta,
                "Sitio key": _texto(site_key),
                "Marca": marca_de_producto(producto, marcas_conocidas),
                "Clase": clase_de_producto(producto, clase_de_tipo),
                # `Mod-Col` es para MOSTRAR: vacio si el producto no tiene el
                # metacampo, que es la verdad. `Clave` es para CONTAR.
                "Mod-Col": codigo,
                "Clave": clave,
                "Sin codigo": not codigo,
                "Handle": _texto(producto.get("Handle")),
                "Tipo": _texto(producto.get("Type")),
                "Estado web": estado,
                "Visible": estado == PRENDIDO,
                "Fotos": len([u for u in _texto(producto.get("Image Src")).split(";") if _texto(u)]),
            })
    return filas


# --- tablas ---------------------------------------------------------------
def matriz_marcas_por_sitio(filas, sitios=()):
    """Marca x sitio, con casilla marcada donde la marca ya tiene catalogo.

    Es la hoja "Marcas x Sitios" del Excel, pero la casilla ya no la pone
    nadie a mano: esta marcada si ese sitio tiene al menos un producto de esa
    marca. Los SKUs por clase cuentan el Modelo-Color una sola vez por marca,
    aunque este publicado en tres sitios (si no, Rockford sumaria 435 x 3).
    """
    columnas_sitio = [_texto(s) for s in sitios if _texto(s)]
    if not columnas_sitio:
        columnas_sitio = sorted({fila["Sitio"] for fila in filas})

    por_marca = {}
    for fila in filas:
        datos = por_marca.setdefault(fila["Marca"], {"sitios": set(), "por_clase": {}})
        datos["sitios"].add(fila["Sitio"])
        datos["por_clase"].setdefault(fila["Clase"], set()).add(_identidad(fila))

    tabla = []
    for marca in sorted(por_marca, key=_clave):
        datos = por_marca[marca]
        registro = {"Marca": marca}
        for sitio in columnas_sitio:
            registro[sitio] = MARCADO if sitio in datos["sitios"] else SIN_MARCAR
        registro["Sitios activos"] = len(datos["sitios"] & set(columnas_sitio))
        total = set()
        for clase in CLASES:
            modelos = datos["por_clase"].get(clase, set())
            registro[f"SKUs {clase}"] = len(modelos)
            total |= modelos
        sin_clase = datos["por_clase"].get(SIN_CLASE, set())
        registro[f"SKUs {SIN_CLASE}"] = len(sin_clase)
        registro["Total SKUs"] = len(total | sin_clase)
        tabla.append(registro)
    return tabla


def resumen_por_clase(filas):
    """SKUs por marca y clase. La hoja "Resumen por clase" del Excel."""
    por_marca = {}
    for fila in filas:
        por_marca.setdefault(fila["Marca"], {}).setdefault(fila["Clase"], set()).add(_identidad(fila))

    columnas = list(CLASES) + [SIN_CLASE]
    tabla = []
    acumulado = {clase: set() for clase in columnas}
    for marca in sorted(por_marca, key=_clave):
        registro = {"Marca": marca}
        total = set()
        for clase in columnas:
            modelos = por_marca[marca].get(clase, set())
            registro[clase] = len(modelos)
            total |= modelos
            acumulado[clase] |= modelos
        registro["Total"] = len(total)
        tabla.append(registro)
    if tabla:
        cierre = {"Marca": "Total"}
        todos = set()
        for clase in columnas:
            cierre[clase] = len(acumulado[clase])
            todos |= acumulado[clase]
        cierre["Total"] = len(todos)
        tabla.append(cierre)
    return tabla


def estado_de_visibilidad(filas):
    """Por sitio y marca: cuanto esta prendido y visible, y cuanto no.

    Esta es la tabla que el Excel a mano no tenia. "Cargado" no es lo mismo que
    "visible": un producto puede existir en Shopify, estar en borrador o activo
    sin publicar, y no lo ve ningun comprador. La columna "% visible" es la que
    dice si la carga quedo realmente operativa.
    """
    por_grupo = {}
    for fila in filas:
        clave = (fila["Sitio"], fila["Marca"])
        datos = por_grupo.setdefault(clave, {estado: 0 for estado in ESTADOS_WEB})
        datos[fila["Estado web"]] = datos.get(fila["Estado web"], 0) + 1

    tabla = []
    for (sitio, marca) in sorted(por_grupo, key=lambda c: (_clave(c[0]), _clave(c[1]))):
        datos = por_grupo[(sitio, marca)]
        cargados = sum(datos.values())
        visibles = datos.get(PRENDIDO, 0)
        tabla.append({
            "Sitio": sitio,
            "Marca": marca,
            "Cargados": cargados,
            PRENDIDO: visibles,
            ACTIVO_SIN_PUBLICAR: datos.get(ACTIVO_SIN_PUBLICAR, 0),
            BORRADOR: datos.get(BORRADOR, 0),
            ARCHIVADO: datos.get(ARCHIVADO, 0),
            "No visibles": cargados - visibles,
            "% visible": round(visibles * 100.0 / cargados, 1) if cargados else 0.0,
        })
    return tabla


def productos_no_visibles(filas, limite=0):
    """El detalle de lo que esta cargado pero apagado. Es la lista de trabajo.

    Un porcentaje no se puede accionar; una lista de Modelo-Color si.
    """
    pendientes = [
        {
            "Sitio": fila["Sitio"],
            "Marca": fila["Marca"],
            "Clase": fila["Clase"],
            "Mod-Col": fila["Mod-Col"],
            "Handle": fila["Handle"],
            "Estado web": fila["Estado web"],
            "Fotos": fila["Fotos"],
        }
        for fila in filas
        if not fila["Visible"]
    ]
    pendientes.sort(key=lambda f: (_clave(f["Sitio"]), _clave(f["Marca"]), f["Mod-Col"]))
    return pendientes[:limite] if limite else pendientes


# --- lo que inyectan las marcas ------------------------------------------
def _skus_de_solicitud(solicitud):
    """Cuantos Modelo-Color trae la solicitud.

    `model_colors` es la lista real; `summary.products` es el respaldo para
    solicitudes viejas que se guardaron sin ella.
    """
    modelos = [m for m in (solicitud.get("model_colors") or []) if _texto(m)]
    if modelos:
        return len(modelos)
    return _entero((solicitud.get("summary") or {}).get("products"))


def registro_de_cargas(solicitudes, estado_visible=None, clase_de_solicitud=None):
    """Una fila por solicitud: lo que cada marca inyecto y en que quedo.

    Es la hoja "Registro de cargas" del Excel, que se llenaba a mano fila por
    fila. Aqui sale de las solicitudes, asi que no se puede olvidar ninguna.
    """
    tabla = []
    for solicitud in solicitudes or []:
        estado_interno = _texto(solicitud.get("status"))
        tabla.append({
            "Codigo": _texto(solicitud.get("code")),
            "Fecha": _texto(solicitud.get("created_at"))[:10],
            "Marca": _texto(solicitud.get("brand")) or SIN_MARCA,
            "Clase": _texto(clase_de_solicitud(solicitud)) if clase_de_solicitud else "",
            "Sitios": ", ".join(_texto(s) for s in (solicitud.get("sites") or []) if _texto(s)),
            "Tipo de carga": TIPOS_DE_CARGA.get(_clave(solicitud.get("load_type")), _texto(solicitud.get("load_type"))),
            "Cantidad de SKUs": _skus_de_solicitud(solicitud),
            "Estado": _texto(estado_visible(estado_interno)) if estado_visible else estado_interno,
            "Solicitante": _texto(solicitud.get("requester_name")) or _texto(solicitud.get("requester")),
            "Notas": _texto(solicitud.get("brand_comment")),
        })
    tabla.sort(key=lambda f: (f["Fecha"], f["Codigo"]), reverse=True)
    return tabla


def resumen_de_solicitudes(solicitudes, estado_visible=None, estados_finales=()):
    """Por marca: cuanto inyecto, cuanto ya termino y cuanto sigue en curso.

    "Cuanto falta" no es una opinion: es la suma de SKUs de las solicitudes que
    todavia no llegaron a un estado final.
    """
    finales = {_texto(e) for e in estados_finales if _texto(e)}
    por_marca = {}
    for solicitud in solicitudes or []:
        marca = _texto(solicitud.get("brand")) or SIN_MARCA
        datos = por_marca.setdefault(marca, {
            "Solicitudes": 0, "SKUs inyectados": 0,
            "Solicitudes terminadas": 0, "SKUs terminados": 0,
        })
        skus = _skus_de_solicitud(solicitud)
        datos["Solicitudes"] += 1
        datos["SKUs inyectados"] += skus
        visible = _texto(estado_visible(solicitud.get("status"))) if estado_visible else ""
        if visible in finales:
            datos["Solicitudes terminadas"] += 1
            datos["SKUs terminados"] += skus

    tabla = []
    for marca in sorted(por_marca, key=_clave):
        datos = por_marca[marca]
        pendientes = datos["SKUs inyectados"] - datos["SKUs terminados"]
        tabla.append({
            "Marca": marca,
            "Solicitudes": datos["Solicitudes"],
            "SKUs inyectados": datos["SKUs inyectados"],
            "Solicitudes terminadas": datos["Solicitudes terminadas"],
            "SKUs terminados": datos["SKUs terminados"],
            "SKUs en curso": pendientes,
            "% avance": round(datos["SKUs terminados"] * 100.0 / datos["SKUs inyectados"], 1)
            if datos["SKUs inyectados"] else 0.0,
        })
    return tabla


def solicitudes_por_estado(solicitudes, estado_visible=None, orden=()):
    """Cuantas solicitudes y cuantos SKUs hay parados en cada estado visible."""
    por_estado = {}
    for solicitud in solicitudes or []:
        visible = _texto(estado_visible(solicitud.get("status"))) if estado_visible else _texto(solicitud.get("status"))
        datos = por_estado.setdefault(visible, {"Solicitudes": 0, "SKUs": 0})
        datos["Solicitudes"] += 1
        datos["SKUs"] += _skus_de_solicitud(solicitud)
    secuencia = [_texto(e) for e in orden if _texto(e) in por_estado]
    secuencia += sorted(e for e in por_estado if e not in secuencia)
    return [
        {"Estado": estado, "Solicitudes": por_estado[estado]["Solicitudes"], "SKUs": por_estado[estado]["SKUs"]}
        for estado in secuencia
    ]


# --- el titular -----------------------------------------------------------
def kpis(filas, solicitudes, estado_visible=None, estados_finales=()):
    """Los numeros de arriba del panel, en una sola pasada.

    `SKUs en curso` es lo que falta: inyectado menos terminado. `No visibles`
    es lo que ya se cargo pero no lo ve nadie todavia.
    """
    finales = {_texto(e) for e in estados_finales if _texto(e)}
    # Se cuenta por `_identidad`, no por `Mod-Col`: ver `clave_de_producto`.
    # Con `Mod-Col` a secas, cada producto sin metacampo colapsaba con todos
    # los demas sin metacampo y estos cuatro numeros dejaban de cuadrar entre
    # si y con la tabla de visibilidad.
    cargados = len({(fila["Sitio"], _identidad(fila)) for fila in filas})
    modelos = len({fila["Mod-Col"] for fila in filas if fila["Mod-Col"]})
    visibles = len({(fila["Sitio"], _identidad(fila)) for fila in filas if fila["Visible"]})
    sin_codigo = sum(1 for fila in filas if not _texto(fila.get("Mod-Col")))
    sin_marca = sum(1 for fila in filas if _texto(fila.get("Marca")) in ("", SIN_MARCA))

    inyectados = 0
    terminados = 0
    abiertas = 0
    for solicitud in solicitudes or []:
        skus = _skus_de_solicitud(solicitud)
        inyectados += skus
        visible = _texto(estado_visible(solicitud.get("status"))) if estado_visible else ""
        if visible in finales:
            terminados += skus
        else:
            abiertas += 1

    return {
        "Sitios con catalogo": len({fila["Sitio"] for fila in filas}),
        # "Sin marca" NO es una marca. Contandola, un sitio con productos sin
        # el metacampo `custom.marca` reportaba una marca de mas.
        "Marcas con catalogo": len({
            fila["Marca"] for fila in filas if _texto(fila["Marca"]) not in ("", SIN_MARCA)
        }),
        "Productos cargados": cargados,
        "Modelo-Color unicos": modelos,
        "Prendidos y visibles": visibles,
        "No visibles": cargados - visibles,
        "% visible": round(visibles * 100.0 / cargados, 1) if cargados else 0.0,
        "Solicitudes": len(solicitudes or []),
        "Solicitudes en curso": abiertas,
        "SKUs inyectados": inyectados,
        "SKUs terminados": terminados,
        "SKUs en curso": inyectados - terminados,
        # Los dos de abajo explican por que un total puede verse raro, en vez
        # de dejar que el usuario descubra el desfase por su cuenta.
        "Productos sin codigo Modelo-Color": sin_codigo,
        "Productos sin marca": sin_marca,
    }
