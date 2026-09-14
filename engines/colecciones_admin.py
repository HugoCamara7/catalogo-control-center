"""Mantenedor de colecciones y Boost del orden del PLP.

Sin dependencias de Streamlit ni de pandas: aqui solo se decide QUE hay que
escribir en Shopify. Quien lo escribe es `shopify_api`; quien lo dibuja es la
pantalla. Asi esto se puede probar sin red y sin navegador.

Que problema resuelve
---------------------
`engines/colecciones` responde "en que colecciones cae este producto": LEE. Lo
que faltaba era lo contrario -- decidir que productos entran en una coleccion y
EN QUE ORDEN salen en la PLP -- y eso hoy se hace a mano en el admin de
Shopify, coleccion por coleccion y arrastrando tarjetas con el raton.

Tres trabajos, y son distintos:

    asignar    que productos entran (por Excel, o por una regla)
    ordenar    en que orden se ven (el Boost)
    aplicar    la lista minima de escrituras para llegar de A a B

Las tres reglas que no son negociables
--------------------------------------
1. **Nada se escribe sin vista previa.** Ninguna funcion de este modulo toca
   Shopify: todas devuelven un PLAN. Una coleccion mal ordenada no revienta --
   se ve normal y llega al comprador --, que es el peor error silencioso, el
   mismo criterio que el video en la posicion 2.

2. **El orden es DETERMINISTA.** Todo empate se rompe por la posicion de
   origen, nunca por la iteracion de un `set`. Un plan que cambia entre dos
   ejecuciones no se puede comparar con el anterior, y es el fallo que ya se
   pago en `avisos_de_talla_a_issues`.

3. **La identidad es `clave_de_producto`**, no el `Mod-Col` pelado. Los
   productos viejos no tienen el metacampo, asi que contando por `Mod-Col`
   todos comparten la cadena vacia y el conjunto los colapsa en uno solo.
"""

import re

from engines import colecciones as _dicc
from engines.load_status import clave_de_producto, modelo_color

# --- lo que Shopify acepta -------------------------------------------------
# Un solo `collectionReorderProducts` admite 250 movimientos y un solo
# `collectionAddProductsV2` 250 productos. No es una eleccion nuestra: es el
# tope de los input objects de la API.
MOVIMIENTOS_POR_LLAMADA = 250
PRODUCTOS_POR_LLAMADA = 250

# El orden de la coleccion solo se puede fijar producto a producto cuando la
# coleccion esta en MANUAL. Con cualquier otro `sortOrder` Shopify reordena por
# su cuenta y los movimientos que mandemos no se ven: el Boost seria un boton
# que no hace nada.
ORDEN_MANUAL = "MANUAL"

ORDENES_DE_SHOPIFY = (
    "MANUAL", "BEST_SELLING", "ALPHA_ASC", "ALPHA_DESC",
    "PRICE_ASC", "PRICE_DESC", "CREATED", "CREATED_DESC",
)


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def _codigo(valor):
    return _texto(valor).upper()


def _entero(valor):
    texto = _texto(valor)
    if not texto:
        return None
    try:
        return int(float(texto.replace(",", ".")))
    except (TypeError, ValueError):
        return None


# --- 1. el Excel -----------------------------------------------------------
COLUMNAS_CODIGO = (
    "codigomodelocolor", "codmodcol", "modcol", "codigomodelo", "codigo",
    "codigomodelocolour", "modelocolor", "sku",
)
COLUMNAS_ORDEN = ("orden", "order", "posicion", "position", "boost", "prioridad", "rank")


def _cabecera(nombre):
    return re.sub(r"[^a-z0-9]+", "", _texto(nombre).lower().replace("ó", "o").replace("í", "i"))


def _columna(filas, candidatas):
    """El nombre real de la primera columna que coincide, sin distinguir
    tildes ni mayusculas. `Código Modelo Color` y `CODIGO_MODELO_COLOR` son la
    misma columna y el usuario escribe las dos."""
    for fila in filas or []:
        for nombre in fila:
            if _cabecera(nombre) in candidatas:
                return nombre
        break
    return None


def filas_de_asignacion(filas):
    """`(items, descartes)` a partir de las filas del Excel.

    `filas` es una lista de diccionarios -- una por fila, con la cabecera como
    clave --, no un DataFrame: este motor no importa pandas.

    Cada item es `{"fila", "codigo", "orden"}`. **Cada descarte se explica.**
    Pedir 200 y procesar 160 se lee igual de bien que procesar 200 si nadie
    dice que paso con los otros 40 -- es la misma regla que
    `png_codigos_desde_excel` y que `sial_codigos_sin_filas`.

    La columna de orden es OPCIONAL: sin ella el orden es el del archivo, que
    es lo que la gente espera de un Excel. Con ella manda el numero, y un
    numero repetido se avisa en vez de dejar que el desempate lo decida el
    azar.
    """
    filas = list(filas or [])
    if not filas:
        return [], [{"Fila": "", "Código Modelo Color": "",
                     "Motivo": "El Excel no tiene filas."}]

    columna_codigo = _columna(filas, COLUMNAS_CODIGO)
    if columna_codigo is None:
        return [], [{"Fila": "", "Código Modelo Color": "",
                     "Motivo": "El Excel no tiene una columna 'Código Modelo Color'."}]
    columna_orden = _columna(filas, COLUMNAS_ORDEN)

    items, descartes, vistos = [], [], {}
    ordenes_usados = {}
    for posicion, fila in enumerate(filas, start=2):
        codigo = _codigo(fila.get(columna_codigo))
        if not codigo:
            continue
        if codigo in vistos:
            descartes.append({"Fila": posicion, "Código Modelo Color": codigo,
                              "Motivo": "Duplicado en el Excel (manda la fila %s)" % vistos[codigo]})
            continue
        orden = None
        if columna_orden is not None:
            crudo = _texto(fila.get(columna_orden))
            if crudo:
                orden = _entero(crudo)
                if orden is None:
                    descartes.append({"Fila": posicion, "Código Modelo Color": codigo,
                                      "Motivo": "La columna de orden no es un número: %r" % crudo})
                    continue
                if orden in ordenes_usados:
                    descartes.append({"Fila": posicion, "Código Modelo Color": codigo,
                                      "Motivo": "El orden %s ya lo pidió la fila %s"
                                                % (orden, ordenes_usados[orden])})
                    continue
                ordenes_usados[orden] = posicion
        vistos[codigo] = posicion
        items.append({"fila": posicion, "codigo": codigo, "orden": orden})

    if not items and not descartes:
        descartes.append({"Fila": "", "Código Modelo Color": "",
                          "Motivo": "Ninguna fila traía un código."})
    return items, descartes


# --- 2. el catalogo --------------------------------------------------------
def indice_de_catalogo(productos):
    """`{codigo: [productos]}` para poder validar un Excel contra la tienda.

    Es una LISTA y no un producto suelto a proposito: dos productos con el
    mismo Modelo-Color son un error del catalogo, y hay que poder decirlo en
    vez de quedarse callado con el primero que caiga.

    Se indexa por el Modelo-Color **y** por el handle, porque un Excel puede
    traer cualquiera de los dos y rechazar el handle obligaria a traducirlo a
    mano.
    """
    indice = {}
    for producto in productos or []:
        for llave in {_codigo(modelo_color(producto)), _codigo(producto.get("Handle"))}:
            if llave:
                indice.setdefault(llave, []).append(producto)
    return indice


def validar_asignacion(items, indice, ya_en_coleccion=()):
    """Que se puede cargar y que no, ANTES de tocar Shopify.

    Devuelve un informe con cinco listas separadas. No se mezclan: "no existe"
    y "ya estaba dentro" son dos situaciones distintas y juntarlas haria creer
    que hay que arreglar algo que ya esta bien.

    `ya_en_coleccion` son las claves que la coleccion ya tiene. Un producto que
    ya esta dentro **no se vuelve a agregar**: la llamada seria un viaje de
    balde, y en una lista de 5.000 eso son 20 viajes que no escriben nada.
    """
    dentro = {_codigo(c) for c in ya_en_coleccion or () if _texto(c)}
    listos, no_encontrados, ambiguos, repetidos, ya_estaban = [], [], [], [], []
    claves_vistas = {}

    for item in items or []:
        codigo = item["codigo"]
        candidatos = indice.get(codigo) or []
        if not candidatos:
            no_encontrados.append({**item, "motivo": "No está en el catálogo de esta tienda"})
            continue
        if len(candidatos) > 1:
            ambiguos.append({**item, "motivo": "El código está en %d productos de la tienda"
                                               % len(candidatos),
                             "handles": [_texto(p.get("Handle")) for p in candidatos]})
            continue
        producto = candidatos[0]
        clave = clave_de_producto(producto)
        if clave in claves_vistas:
            # Dos codigos distintos del Excel que caen en el MISMO producto:
            # el segundo no agrega nada y su "orden" contradice al primero.
            repetidos.append({**item, "motivo": "Es el mismo producto que la fila %s"
                                                % claves_vistas[clave]})
            continue
        claves_vistas[clave] = item["fila"]
        destino = ya_estaban if _codigo(clave) in dentro or clave in dentro else listos
        destino.append({**item, "clave": clave, "producto": producto,
                        "handle": _texto(producto.get("Handle")),
                        "titulo": _texto(producto.get("Title"))})

    return {
        "listos": listos,
        "ya_estaban": ya_estaban,
        "no_encontrados": no_encontrados,
        "ambiguos": ambiguos,
        "repetidos": repetidos,
        "bloqueado": bool(no_encontrados or ambiguos),
    }


def hay_que_revisar(informe):
    """True si el informe tiene algo que una persona deberia mirar.

    No es lo mismo que `bloqueado`: un duplicado dentro del Excel no impide
    cargar, pero callarlo haria que 200 codigos entraran como 160 sin que nadie
    lo notara.
    """
    informe = informe or {}
    return bool(informe.get("no_encontrados") or informe.get("ambiguos")
                or informe.get("repetidos"))


# --- 3. colecciones inteligentes ------------------------------------------
# Los conceptos del negocio, traducidos a los campos que Shopify entiende.
#
# La marca, el genero y el color NO son campos de Shopify: viven en metacampos
# `custom.*` que escribe esta app. Shopify sabe filtrar por ellos
# (`PRODUCT_METAFIELD_DEFINITION`), pero **solo si la definicion del metacampo
# tiene activada la condicion de coleccion** en el admin. Sin eso la regla se
# acepta y la coleccion sale VACIA -- un fallo silencioso -- asi que aqui se
# comprueba antes y se dice cual falta.
#
# `PRODUCT_TAXONOMY_NODE_ID` esta DEPRECADO en favor de `PRODUCT_CATEGORY_ID`:
# se usa el nuevo.
CONCEPTOS = {
    "marca":      {"etiqueta": "Marca",            "campo": "PRODUCT_METAFIELD_DEFINITION",
                   "metacampo": ("custom", "marca")},
    "genero":     {"etiqueta": "Género",           "campo": "PRODUCT_METAFIELD_DEFINITION",
                   "metacampo": ("custom", "genero")},
    "color":      {"etiqueta": "Color",            "campo": "PRODUCT_METAFIELD_DEFINITION",
                   "metacampo": ("custom", "color")},
    "modelo":     {"etiqueta": "Código Modelo-Color", "campo": "PRODUCT_METAFIELD_DEFINITION",
                   "metacampo": ("custom", "codigo_modelo_color")},
    "tipo":       {"etiqueta": "Tipo de prenda",   "campo": "TYPE",   "metacampo": None},
    "tag":        {"etiqueta": "Tag",              "campo": "TAG",    "metacampo": None},
    "titulo":     {"etiqueta": "Título",           "campo": "TITLE",  "metacampo": None},
    "proveedor":  {"etiqueta": "Proveedor (vendor)", "campo": "VENDOR", "metacampo": None},
    "categoria":  {"etiqueta": "Categoría de Shopify", "campo": "PRODUCT_CATEGORY_ID",
                   "metacampo": None},
    "precio":     {"etiqueta": "Precio",           "campo": "VARIANT_PRICE", "metacampo": None},
    "stock":      {"etiqueta": "Stock",            "campo": "VARIANT_INVENTORY", "metacampo": None},
}

RELACIONES = {
    "EQUALS": "es igual a",
    "NOT_EQUALS": "no es igual a",
    "CONTAINS": "contiene",
    "NOT_CONTAINS": "no contiene",
    "STARTS_WITH": "empieza por",
    "ENDS_WITH": "termina en",
    "GREATER_THAN": "es mayor que",
    "LESS_THAN": "es menor que",
}

# Un concepto numerico no se puede comparar con "contiene".
RELACIONES_POR_CAMPO = {
    "VARIANT_PRICE": ("EQUALS", "NOT_EQUALS", "GREATER_THAN", "LESS_THAN"),
    "VARIANT_INVENTORY": ("EQUALS", "NOT_EQUALS", "GREATER_THAN", "LESS_THAN"),
    "PRODUCT_CATEGORY_ID": ("EQUALS", "NOT_EQUALS"),
}
RELACIONES_DE_TEXTO = ("EQUALS", "NOT_EQUALS", "CONTAINS", "NOT_CONTAINS",
                       "STARTS_WITH", "ENDS_WITH")


def relaciones_de(concepto):
    campo = (CONCEPTOS.get(concepto) or {}).get("campo", "")
    return RELACIONES_POR_CAMPO.get(campo, RELACIONES_DE_TEXTO)


def regla_de_concepto(concepto, relacion, valor, definiciones=None):
    """Una regla de coleccion automatica a partir de un concepto del negocio.

    Devuelve `(regla, error)`. **El error no se levanta**: una regla que no se
    puede construir tiene que poder dibujarse en rojo al lado de las que si,
    no tumbar la pantalla entera.

    `definiciones` es `{(namespace, key): gid}` con las definiciones de
    metacampo que la tienda tiene habilitadas para condiciones de coleccion.
    """
    datos = CONCEPTOS.get(_texto(concepto))
    if not datos:
        return None, "Concepto desconocido: %r" % concepto
    relacion = _texto(relacion).upper()
    if relacion not in relaciones_de(concepto):
        return None, "La relación %s no vale para %s" % (relacion or "(vacía)", datos["etiqueta"])
    valor = _texto(valor)
    if not valor:
        return None, "Falta el valor de la regla de %s" % datos["etiqueta"]

    regla = {"campo": datos["campo"], "relacion": relacion, "valor": valor,
             "concepto": _texto(concepto)}
    if datos["metacampo"]:
        gid = (definiciones or {}).get(datos["metacampo"])
        if not gid:
            namespace, key = datos["metacampo"]
            return None, (
                "La tienda no tiene el metacampo %s.%s habilitado como condición de colección. "
                "Se activa en Configuración → Datos personalizados → esa definición → "
                "«Usar como condición de colección». Sin eso Shopify acepta la regla y la "
                "colección sale VACÍA." % (namespace, key)
            )
        regla["definicion_id"] = gid
    return regla, ""


def describir_regla(regla):
    regla = regla or {}
    concepto = _texto(regla.get("concepto"))
    etiqueta = (CONCEPTOS.get(concepto) or {}).get("etiqueta") or _texto(regla.get("campo"))
    relacion = RELACIONES.get(_texto(regla.get("relacion")).upper(), _texto(regla.get("relacion")))
    return "%s %s «%s»" % (etiqueta, relacion, _texto(regla.get("valor")))


def _producto_para_motor(producto):
    """La forma que entiende `engines/colecciones`, con los metacampos.

    La traduccion vive aqui y no en el motor de lectura: ese no tiene que saber
    como se llaman las columnas del catalogo.
    """
    producto = producto or {}
    return {
        "clave": clave_de_producto(producto),
        "tags": [t.strip() for t in _texto(producto.get("Tags")).split(",") if t.strip()],
        "tipo": _texto(producto.get("Type")),
        "vendor": _texto(producto.get("Vendor")),
        "titulo": _texto(producto.get("Title")),
    }


def _valor_de_metacampo(producto, metacampo):
    namespace, key = metacampo
    if (namespace, key) == ("custom", "codigo_modelo_color"):
        return _texto(modelo_color(producto))
    if (namespace, key) == ("custom", "marca"):
        return _texto(producto.get("Marca"))
    return _texto(producto.get("Metafield: %s.%s [single_line_text_field]" % (namespace, key)))


def previsualizar_reglas(productos, reglas, disyuntiva=False):
    """Que productos caerian en la coleccion, SIN crearla.

    Devuelve `(dentro, no_evaluables)`. Son dos listas y no una: una regla por
    precio o por inventario no se puede responder con el catalogo que tenemos
    leido, y devolver "no entra" dejaria al producto fuera sin que nadie se
    entere. Es la misma regla de `None` que ya sigue `engines/colecciones`.

    Ojo con lo que esto es: una APROXIMACION de lo que hara Shopify con los
    datos que la app tiene en la mano. La coleccion automatica la resuelve
    Shopify, no nosotros. Sirve para revisar antes de crear -- que es justo lo
    que nadie puede hacer hoy en el admin --, no para reemplazar el conteo real.
    """
    reglas = list(reglas or [])
    dentro, dudosos = [], []
    for producto in productos or []:
        adaptado = _producto_para_motor(producto)
        resultados = []
        for regla in reglas:
            campo = _texto(regla.get("campo")).upper()
            if campo == "PRODUCT_METAFIELD_DEFINITION":
                concepto = _texto(regla.get("concepto"))
                metacampo = (CONCEPTOS.get(concepto) or {}).get("metacampo")
                if not metacampo:
                    resultados.append(None)
                    continue
                valor = _valor_de_metacampo(producto, metacampo)
                comparar = _dicc.RELACIONES_TEXTO.get(_texto(regla.get("relacion")).upper())
                resultados.append(
                    None if comparar is None else bool(comparar(valor, _texto(regla.get("valor"))))
                )
                continue
            resultados.append(_dicc.evaluar_regla(adaptado, regla))

        if not resultados:
            continue
        if disyuntiva:
            entra = True if any(r is True for r in resultados) else (
                None if any(r is None for r in resultados) else False)
        else:
            entra = False if any(r is False for r in resultados) else (
                None if any(r is None for r in resultados) else True)
        if entra is True:
            dentro.append(producto)
        elif entra is None:
            dudosos.append(producto)
    return dentro, dudosos


# --- 4. el Boost -----------------------------------------------------------
# Cada criterio devuelve `(falta, valor)`.
#
# `falta` es lo que hace que esto no mienta: un producto del que no sabemos las
# ventas NO puede colarse arriba solo porque su valor sea cero. Los que no
# tienen el dato van SIEMPRE al final del tramo, se ordene ascendente o
# descendente, y por eso el flag va aparte del valor y no dentro de el.
def _valor_excel(clave, contexto):
    orden = (contexto.get("orden") or {}).get(clave)
    return (0, orden) if orden is not None else (1, 0)


def _valor_rango(nombre):
    def leer(clave, contexto):
        rango = (contexto.get(nombre) or {}).get(clave)
        return (0, rango) if rango is not None else (1, 0)
    return leer


def _stock_de(producto):
    total = 0
    for variante in (producto or {}).get("Variants") or []:
        cantidad = _entero(variante.get("Variant Inventory Qty"))
        if cantidad and cantidad > 0:
            total += cantidad
    return total


def _valor_stock(clave, contexto):
    producto = (contexto.get("productos") or {}).get(clave)
    if producto is None:
        return (1, 0)
    return (0, _stock_de(producto))


def _valor_por_prioridad(campo, nombre_prioridad, leer=None):
    """Ordena por una lista de prioridad declarada (Mujer antes que Hombre...).

    Lo que no esta en la lista va al final y **en su orden de origen**, no
    alfabetico: alfabetico inventaria una jerarquia que nadie pidio.
    """
    def valor(clave, contexto):
        producto = (contexto.get("productos") or {}).get(clave)
        if producto is None:
            return (1, 0)
        texto = _texto(leer(producto) if leer else producto.get(campo))
        prioridad = [_texto(x).casefold() for x in (contexto.get(nombre_prioridad) or [])]
        if not texto:
            return (1, 0)
        try:
            return (0, prioridad.index(texto.casefold()))
        except ValueError:
            return (1, 0)
    return valor


def _valor_titulo(clave, contexto):
    producto = (contexto.get("productos") or {}).get(clave)
    titulo = _texto((producto or {}).get("Title")).casefold()
    return (0, titulo) if titulo else (1, "")


def _valor_manual(clave, contexto):
    orden = (contexto.get("orden_manual") or {}).get(clave)
    return (0, orden) if orden is not None else (1, 0)


CRITERIOS = {
    "excel": {
        "etiqueta": "Orden del Excel",
        "ayuda": "El orden de la columna «Orden», o el orden de las filas del archivo.",
        "necesita": "orden", "descendente": False, "valor": _valor_excel,
    },
    "ventas": {
        "etiqueta": "Más vendidos",
        "ayuda": "El ranking de ventas de la PROPIA colección, calculado por Shopify.",
        "necesita": "rango_ventas", "descendente": False, "valor": _valor_rango("rango_ventas"),
    },
    "nuevos": {
        "etiqueta": "Más nuevos",
        "ayuda": "Los creados más recientemente primero, según la fecha de Shopify.",
        "necesita": "rango_novedad", "descendente": False, "valor": _valor_rango("rango_novedad"),
    },
    "stock": {
        "etiqueta": "Stock / disponibilidad",
        "ayuda": "Más unidades disponibles primero. Los agotados caen al final.",
        "necesita": None, "descendente": True, "valor": _valor_stock,
    },
    "genero": {
        "etiqueta": "Género",
        "ayuda": "Según la prioridad de géneros que elijas abajo.",
        "necesita": None, "descendente": False,
        "valor": _valor_por_prioridad("Genero", "prioridad_genero"),
    },
    "tipo": {
        "etiqueta": "Tipo de prenda",
        "ayuda": "Según la prioridad de tipos que elijas abajo.",
        "necesita": None, "descendente": False,
        "valor": _valor_por_prioridad("Type", "prioridad_tipo"),
    },
    "titulo": {
        "etiqueta": "Título (A-Z)",
        "ayuda": "Alfabético por el nombre del producto.",
        "necesita": None, "descendente": False, "valor": _valor_titulo,
    },
    "manual": {
        "etiqueta": "Orden manual",
        "ayuda": "El orden que dejaste tú arrastrando o numerando en la pantalla.",
        "necesita": "orden_manual", "descendente": False, "valor": _valor_manual,
    },
}

ORDEN_DE_CRITERIOS = ("excel", "manual", "ventas", "nuevos", "stock", "genero", "tipo", "titulo")


def criterios_disponibles(contexto):
    """Que criterios se pueden usar con los datos que hay en la mano.

    Un criterio que se ofrece y no tiene su dato produce un orden que no cambia
    nada, y eso se lee como "el Boost no funciona". Mejor no ofrecerlo y decir
    por que.
    """
    salida = []
    for clave in ORDEN_DE_CRITERIOS:
        datos = CRITERIOS[clave]
        necesita = datos["necesita"]
        listo = not necesita or bool((contexto or {}).get(necesita))
        salida.append({"clave": clave, "etiqueta": datos["etiqueta"], "ayuda": datos["ayuda"],
                       "listo": listo,
                       "falta": "" if listo else "Todavía no se ha cargado ese dato."})
    return salida


def ordenar(claves, criterios, contexto):
    """El orden final de la coleccion. Devuelve una lista de claves.

    `criterios` es una lista en ORDEN DE PRIORIDAD:
    `[{"clave": "ventas", "descendente": True}, {"clave": "titulo"}]`
    -- primero manda ventas y solo desempata el titulo.

    Se aplica una ordenacion estable POR CRITERIO, del ultimo al primero. Es la
    forma clasica de componer varias claves y tiene una propiedad que aqui
    importa: cada criterio conserva el orden que dejo el anterior cuando
    empata, asi que el ultimo desempate siempre es la posicion de ORIGEN. Sin
    eso, dos productos que empatan en todo saldrian en un orden distinto en
    cada ejecucion y el plan no se podria comparar con el anterior.
    """
    orden = [c for c in (claves or []) if _texto(c)]
    contexto = contexto or {}
    for criterio in reversed(list(criterios or [])):
        datos = CRITERIOS.get(_texto(criterio.get("clave")))
        if not datos:
            continue
        descendente = bool(criterio.get("descendente", datos["descendente"]))
        leer = datos["valor"]
        presentes, ausentes = [], []
        for clave in orden:
            (ausentes if leer(clave, contexto)[0] else presentes).append(clave)
        presentes.sort(key=lambda clave: leer(clave, contexto)[1], reverse=descendente)
        orden = presentes + ausentes
    return orden


def movimientos(orden_actual, orden_deseado):
    """La lista MINIMA de movimientos para llegar de un orden al otro.

    Shopify aplica los movimientos **uno detras de otro**, no a la vez: cada
    uno saca el producto de donde esta y lo mete en la posicion pedida,
    corriendo a todos los demas. Por eso no se puede calcular comparando las
    dos listas posicion a posicion -- eso daria posiciones que ya no son las
    que Shopify vera cuando le toque ese movimiento --, y hay que SIMULAR.

    El resultado es `[{"clave", "posicion"}]` con la posicion EMPEZANDO EN 0,
    que es lo que pide `MoveInput`. Confundir esa numeracion con la que ve una
    persona deja todo corrido un puesto, que es el mismo error que dejaba el
    video en la posicion 3.

    Lo que no esta en la coleccion no genera movimiento: eso es un alta, y va
    por `collectionAddProductsV2`.
    """
    actual = [c for c in (orden_actual or []) if _texto(c)]
    indice = {clave: posicion for posicion, clave in enumerate(actual)}
    # Lo que NO esta en la coleccion se quita del orden deseado ANTES de
    # numerar las posiciones, no dentro del bucle. Saltandolo alli, la posicion
    # seguia avanzando y el producto siguiente se pedia una casilla mas abajo
    # de la que le toca: pedir [NUEVO, A, B] sobre [A, B] emitia un movimiento
    # de A a la posicion 1 -- o sea desordenaba una coleccion que ya estaba
    # bien. Lo que falta es un ALTA y va por `collectionAddProductsV2`.
    deseado = [c for c in (orden_deseado or []) if _texto(c) and c in indice]
    salida = []
    for destino, clave in enumerate(deseado):
        if destino >= len(actual):
            break
        if actual[destino] == clave:
            continue
        origen = indice.get(clave)
        if origen is None:
            continue
        actual.pop(origen)
        actual.insert(destino, clave)
        for posicion in range(min(origen, destino), max(origen, destino) + 1):
            indice[actual[posicion]] = posicion
        salida.append({"clave": clave, "posicion": destino})
    return salida


def bloques(items, tamano):
    tamano = max(1, int(tamano or 1))
    items = list(items or [])
    return [items[inicio:inicio + tamano] for inicio in range(0, len(items), tamano)]


# --- 5. el plan ------------------------------------------------------------
def plan_de_asignacion(claves_actuales, claves_deseadas, quitar_sobrantes=False):
    """Que agregar y que quitar. Devuelve `(agregar, quitar)`.

    `quitar_sobrantes` es False por defecto **a proposito**: un Excel de 50
    codigos sobre una coleccion de 3.000 normalmente quiere AGREGAR 50, no
    borrar 2.950. Vaciar una coleccion por un archivo parcial no tiene vuelta
    atras desde la app, asi que se pide explicitamente.
    """
    actuales = [c for c in (claves_actuales or []) if _texto(c)]
    deseadas = [c for c in (claves_deseadas or []) if _texto(c)]
    en_coleccion = set(actuales)
    pedidas = set(deseadas)
    agregar = [c for c in deseadas if c not in en_coleccion]
    quitar = [c for c in actuales if c not in pedidas] if quitar_sobrantes else []
    return agregar, quitar


def plan_de_coleccion(coleccion, claves_actuales, claves_deseadas, criterios=None,
                      contexto=None, quitar_sobrantes=False, reordenar=True):
    """El plan COMPLETO de una coleccion: que se agrega, que se quita, como
    queda ordenada y cuantas llamadas cuesta.

    Nada de esto escribe. Es lo que se dibuja en la vista previa y lo que se
    confirma; la ejecucion es otra funcion y vive en la pantalla.
    """
    agregar, quitar = plan_de_asignacion(claves_actuales, claves_deseadas, quitar_sobrantes)
    # Tras agregar y quitar, la coleccion queda con esto -- y en ese orden --,
    # porque `collectionAddProductsV2` agrega al FINAL. Los movimientos se
    # calculan sobre ese estado y no sobre el de ahora, o quedarian corridos.
    quitadas = set(quitar)
    tras_escribir = [c for c in (claves_actuales or []) if c not in quitadas] + list(agregar)

    if criterios:
        deseado = ordenar(tras_escribir, criterios, contexto or {})
    elif claves_deseadas and reordenar:
        # Sin criterios manda el orden en que llegaron las claves pedidas, y
        # detras lo que ya estaba y el Excel no nombra.
        pedidas = [c for c in claves_deseadas if c in set(tras_escribir)]
        deseado = pedidas + [c for c in tras_escribir if c not in set(pedidas)]
    else:
        deseado = list(tras_escribir)

    moves = movimientos(tras_escribir, deseado) if reordenar else []
    llamadas = (len(bloques(agregar, PRODUCTOS_POR_LLAMADA))
                + len(bloques(quitar, PRODUCTOS_POR_LLAMADA))
                + len(bloques(moves, MOVIMIENTOS_POR_LLAMADA)))
    return {
        "coleccion": coleccion,
        "agregar": agregar,
        "quitar": quitar,
        "orden_final": deseado,
        "movimientos": moves,
        "llamadas": llamadas,
        "requiere_orden_manual": bool(moves),
        "sin_cambios": not agregar and not quitar and not moves,
    }
