"""Que hay que arreglarle a las tallas de un producto ya cargado.

Por que existe
--------------
Dos cosas que se ven en la ficha y que hoy solo se arreglan al CREAR el
producto, o sea nunca para lo que ya esta cargado:

1. **El orden.** Las variantes salen en el orden en que se crearon. Una curva
   ampliada despues deja la 44 entre la 38 y la 39, y en la web el selector de
   tallas queda desordenado. La Carga completa ya ordena al crear
   (`_reorder_product_sizes`), pero nadie vuelve a mirarlo.

2. **La escala.** Vans entrega el calzado en tallas **US** y la tienda las
   publica en **PE/EU** (41, 42...). Lo cargado antes de esa regla sigue
   diciendo "8" donde deberia decir "40.5".

Este motor solo DECIDE: recibe el producto tal y como lo devuelve
`shopify_api.fetch_products` y dice que habria que cambiarle. No toca Shopify
-- eso es de la pantalla -- y no trae su propia tabla de tallas ni su propio
criterio de orden: los dos se le **inyectan**, para que sean exactamente los
mismos que usa la Carga completa. Un segundo criterio de orden se separa del
primero sin que nadie lo note, que es lo que ya se paga en este repositorio
con las dos `normalize_size`.

Sin Streamlit y sin pandas, como el resto de `engines/`.
"""

# Como se llama la opcion de talla en Shopify. Un producto puede tener la
# opcion escrita de varias formas; el orden no importa, se compara normalizado.
NOMBRES_DE_TALLA = ("talla", "tallas", "size", "sizes", "talle")

# Situaciones en las que puede quedar un producto.
ORDENADO = "Ordenado"
DESORDENADO = "Fuera de orden"
ESCALA = "Escala equivocada"
ESCALA_Y_ORDEN = "Escala y orden"
SIN_TALLAS = "Sin opcion de talla"
NO_SE_TOCA = "No se toca"


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def _clave(valor):
    return _texto(valor).casefold()


def nombre_de_opcion_de_talla(variantes):
    """Como se llama la opcion de talla en este producto, o "" si no hay.

    Se mira `Option1 Name` y `Option2 Name` de las variantes tal y como los
    deja `fetch_products`.
    """
    for indice in ("1", "2", "3"):
        for variante in variantes or []:
            nombre = _texto(variante.get(f"Option{indice} Name"))
            if _clave(nombre) in NOMBRES_DE_TALLA:
                return nombre
    return ""


def indice_de_opcion(variantes, nombre):
    for indice in ("1", "2", "3"):
        for variante in variantes or []:
            if _clave(variante.get(f"Option{indice} Name")) == _clave(nombre):
                return indice
    return ""


def opciones_usadas(variantes):
    """Cuantas opciones distintas usa el producto (Talla, Color...)."""
    nombres = []
    for variante in variantes or []:
        for indice in ("1", "2", "3"):
            nombre = _texto(variante.get(f"Option{indice} Name"))
            if nombre and nombre not in nombres:
                nombres.append(nombre)
    return nombres


def tallas_en_orden_actual(variantes, nombre_opcion):
    """Los valores de talla en el orden en que Shopify devuelve las variantes.

    Se dedupica conservando la primera aparicion: el orden de la ficha es el de
    las variantes, y un valor repetido no cambia donde aparece por primera vez.
    """
    indice = indice_de_opcion(variantes, nombre_opcion)
    if not indice:
        return []
    valores = []
    for variante in variantes or []:
        valor = _texto(variante.get(f"Option{indice} Value"))
        if valor and valor not in valores:
            valores.append(valor)
    return valores


# ---------------------------------------------------------------------------
# Tallas pedidas a mano: "este SKU tiene que decir esta talla"
# ---------------------------------------------------------------------------
# El mantenedor automatico decide la talla por REGLA -- la guia de la marca, el
# genero, la escala del sitio -- y eso resuelve el catalogo entero de una vez.
# Lo que no resuelve es el caso suelto: una curva que la guia no cubre, un
# producto mal tipificado, una talla que el maestro trajo rota. Ahi la persona
# ya sabe que tiene que decir cada variante y no hay forma de decirselo a la
# app.
#
# La identidad es el SKU y no la talla actual, a proposito. Es el unico dato de
# la variante que no cambia: anclado en la talla actual, un plan armado hace
# cinco minutos se aplicaria sobre una etiqueta que ya no existe.
#
# Lo que se escribe sigue siendo el VALOR de la opcion, igual que en el
# automatico: Shopify renombra el valor y con el todas las variantes que lo
# usan. Por eso dos SKU que HOY comparten talla no pueden pedir tallas
# distintas -- eso no es un renombre, es partir una variante en dos -- y se
# reporta en vez de escribir a medias.

CAMPO_SKU = "Variant SKU"


def sku_de_variante(variante):
    return _texto((variante or {}).get(CAMPO_SKU)).upper()


def tallas_por_sku(variantes, nombre_opcion):
    """{SKU: talla que tiene hoy} para las variantes de este producto."""
    indice = indice_de_opcion(variantes, nombre_opcion)
    if not indice:
        return {}
    por_sku = {}
    for variante in variantes or []:
        sku = sku_de_variante(variante)
        if sku:
            por_sku[sku] = _texto(variante.get(f"Option{indice} Value"))
    return por_sku


def conversor_de_tallas_pedidas(variantes, nombre_opcion, pedidas):
    """(convertir, avisos, sin_encontrar) para las tallas que pidio la persona.

    `convertir` tiene la MISMA forma que el conversor de escala del automatico
    -- `callable(talla) -> (nueva, nota)` --, asi que entra por el mismo
    `plan_de_producto` y hereda entero lo que ya esta probado: el rechazo de
    tallas que quedarian repetidas, el reordenamiento sobre los valores
    finales y la guarda del producto con mas de una opcion.

    `sin_encontrar` son los SKU del Excel que este producto no tiene. No es un
    error de la app: casi siempre es un SKU de otro producto o mal escrito, y
    callarlo dejaria a la persona creyendo que se aplico.
    """
    pedidas = {_texto(k).upper(): _texto(v) for k, v in (pedidas or {}).items() if _texto(k)}
    por_sku = tallas_por_sku(variantes, nombre_opcion)
    avisos = []
    sin_encontrar = sorted(sku for sku in pedidas if sku not in por_sku)

    # Que pide cada valor ACTUAL de la opcion. Un valor con dos peticiones
    # distintas no se puede resolver renombrando.
    pedido_por_valor = {}
    for sku, nueva in pedidas.items():
        actual = por_sku.get(sku)
        if actual is None or not nueva or nueva == actual:
            continue
        pedido_por_valor.setdefault(actual, {}).setdefault(nueva, []).append(sku)

    resueltas = {}
    for actual, opciones in pedido_por_valor.items():
        if len(opciones) > 1:
            detalle = "; ".join(
                f"{nueva} ({', '.join(sorted(skus))})" for nueva, skus in sorted(opciones.items())
            )
            avisos.append(
                f"la talla '{actual}' recibe dos valores distintos y se renombra "
                f"para todas sus variantes a la vez: {detalle}"
            )
            continue
        resueltas[actual] = next(iter(opciones))

    def convertir(talla):
        nueva = resueltas.get(_texto(talla))
        return (nueva, "") if nueva else ("", "")

    return convertir, avisos, sin_encontrar


def tallas_pedidas_a_texto(pedidas):
    """{SKU: talla} -> "SKU=TALLA | SKU=TALLA".

    Hace falta porque el plan viaja al runner DENTRO de una hoja de Excel, y
    ahi una celda es texto. Es el mismo motivo por el que el sitio y el genero
    viajan como columnas y no como objetos.
    """
    return " | ".join(
        f"{_texto(sku).upper()}={_texto(talla)}"
        for sku, talla in (pedidas or {}).items()
        if _texto(sku) and _texto(talla)
    )


def tallas_pedidas_desde_texto(valor):
    """La vuelta de `tallas_pedidas_a_texto`. Lo que no tenga `=` se ignora."""
    pedidas = {}
    for trozo in _texto(valor).split("|"):
        sku, sep, talla = trozo.partition("=")
        if sep and _texto(sku) and _texto(talla):
            pedidas[_texto(sku).upper()] = _texto(talla)
    return pedidas


def plan_de_producto(producto, orden_clave, convertir=None):
    """Que habria que cambiarle a este producto. No toca Shopify.

    `orden_clave` es la MISMA funcion de orden que usa la Carga completa.
    `convertir` es `callable(talla) -> (nueva, nota)` cuando a este producto le
    toca cambiar de escala, y None cuando no. La pantalla es la que decide si
    toca, porque eso depende de la marca y de si es calzado, y ninguna de las
    dos cosas se lee igual en todos los sitios.

    Devuelve None cuando no hay nada que mirar (sin variantes).
    """
    producto = producto or {}
    variantes = producto.get("Variants") or []
    base = {
        "Mod-Col": _texto(producto.get("Mod-Col")),
        "Handle": _texto(producto.get("Handle")),
        "Title": _texto(producto.get("Title")),
        "Marca": _texto(producto.get("Marca")),
        # El TIPO y el GENERO viajan en el plan porque antes de escribir se
        # REPLANIFICA sobre el producto releido, y quien decide si hay que
        # convertir la escala necesita los dos. Sin ellos, `plan.get("Type")`
        # era "" en el segundo pase, el conversor salia None y el cambio de
        # escala se perdia en silencio: la pantalla decia "Ya estaba bien al
        # releerlo" y no convertia nada, nunca.
        "Type": _texto(producto.get("Type")),
        "Genero": _texto(producto.get("Genero")),
        "Product ID": _texto(producto.get("Product ID")),
        "Opcion": "",
        "Actual": [],
        "Renombrar": {},
        "Propuesto": [],
        "Cambia_escala": False,
        "Cambia_orden": False,
        "Situacion": SIN_TALLAS,
        "Nota": "",
    }
    if not variantes:
        base["Nota"] = "El producto no tiene variantes."
        return base

    nombre_opcion = nombre_de_opcion_de_talla(variantes)
    if not nombre_opcion:
        base["Nota"] = "Ninguna opcion se llama Talla."
        return base
    base["Opcion"] = nombre_opcion
    actuales = tallas_en_orden_actual(variantes, nombre_opcion)
    base["Actual"] = actuales
    if not actuales:
        base["Nota"] = "La opcion de talla no tiene valores."
        return base

    # Escala: se renombra el VALOR de la opcion, asi que un mismo valor no
    # puede terminar en dos nombres distintos.
    renombres = {}
    notas = []
    if convertir is not None:
        for talla in actuales:
            nueva, nota = convertir(talla)
            nueva = _texto(nueva)
            if nueva and nueva != talla:
                renombres[talla] = nueva
            if nota:
                notas.append(f"{talla}: {nota}")

    # Dos tallas distintas que caen en la misma PE serian dos valores iguales en
    # la misma opcion, y Shopify rechaza el duplicado. No se elige cual sobra:
    # se avisa y no se renombra ninguna de las dos.
    finales = [renombres.get(talla, talla) for talla in actuales]
    repetidas = {valor for valor in finales if finales.count(valor) > 1}
    if repetidas:
        for talla in list(renombres):
            if renombres[talla] in repetidas:
                renombres.pop(talla)
        notas.append(
            "no se cambia la escala porque quedarian tallas repetidas: "
            + ", ".join(sorted(repetidas))
        )
        finales = [renombres.get(talla, talla) for talla in actuales]

    base["Renombrar"] = renombres
    base["Cambia_escala"] = bool(renombres)

    # Orden: se calcula sobre los valores FINALES. Ordenar primero y renombrar
    # despues dejaria las etiquetas nuevas en las posiciones viejas.
    propuesto = sorted(finales, key=orden_clave)
    base["Propuesto"] = propuesto
    base["Cambia_orden"] = propuesto != finales

    # Un producto con mas de una opcion (Talla y Color) tiene las variantes en
    # matriz: reordenarlas solo por talla las mezclaria. La escala si se puede
    # cambiar, que es un renombre y no mueve nada de sitio.
    if base["Cambia_orden"] and len(opciones_usadas(variantes)) > 1:
        base["Cambia_orden"] = False
        notas.append(
            "no se reordena porque el producto tiene mas de una opcion y las "
            "variantes van en matriz"
        )

    if base["Cambia_escala"] and base["Cambia_orden"]:
        base["Situacion"] = ESCALA_Y_ORDEN
    elif base["Cambia_escala"]:
        base["Situacion"] = ESCALA
    elif base["Cambia_orden"]:
        base["Situacion"] = DESORDENADO
    else:
        base["Situacion"] = ORDENADO
    base["Nota"] = " | ".join(notas)
    return base


def planificar(productos, orden_clave, convertir_de=None):
    """El plan de todo un catalogo. `convertir_de(producto)` da el conversor."""
    planes = []
    for producto in productos or []:
        convertir = convertir_de(producto) if convertir_de else None
        plan = plan_de_producto(producto, orden_clave, convertir=convertir)
        if plan:
            planes.append(plan)
    return planes


def pendientes(planes):
    """Solo los que hay que tocar. Es lo que se ejecuta."""
    return [p for p in planes or [] if p.get("Cambia_escala") or p.get("Cambia_orden")]


def resumen(planes):
    """Los numeros de arriba de la pantalla.

    Las CLAVES no llevan tilde, igual que en `engines/load_status`: una clave
    con tilde que la pantalla pide sin ella es un KeyError que tumba la
    pantalla, y con `.get()` es peor -- devuelve None y no aparece nunca.
    """
    planes = planes or []
    cuenta = {}
    for plan in planes:
        cuenta[plan["Situacion"]] = cuenta.get(plan["Situacion"], 0) + 1
    revisados = len(planes)
    por_arreglar = len(pendientes(planes))
    return {
        "Productos revisados": revisados,
        "Ya estan bien": cuenta.get(ORDENADO, 0),
        "Fuera de orden": cuenta.get(DESORDENADO, 0) + cuenta.get(ESCALA_Y_ORDEN, 0),
        "Escala equivocada": cuenta.get(ESCALA, 0) + cuenta.get(ESCALA_Y_ORDEN, 0),
        "Sin opcion de talla": cuenta.get(SIN_TALLAS, 0),
        "Por arreglar": por_arreglar,
        "Con aviso": sum(1 for plan in planes if plan.get("Nota")),
    }


def filas_para_tabla(planes):
    """El plan como tabla legible. Las listas se aplanan a texto."""
    filas = []
    for plan in planes or []:
        filas.append({
            "Mod-Col": plan["Mod-Col"],
            "Marca": plan["Marca"],
            "Producto": plan["Title"],
            "Situacion": plan["Situacion"],
            "Tallas ahora": ", ".join(plan["Actual"]),
            "Tallas propuestas": ", ".join(plan["Propuesto"]),
            "Cambia escala": "SI" if plan["Cambia_escala"] else "",
            "Cambia orden": "SI" if plan["Cambia_orden"] else "",
            "Aviso": plan["Nota"],
        })
    return filas
