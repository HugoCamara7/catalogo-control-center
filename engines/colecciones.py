"""Diccionario de colecciones por marca, y que tags alimentan a cada una.

Sin dependencias de Streamlit ni de pandas.

Que problema resuelve
---------------------
En Shopify una coleccion automatica no se llena a mano: se llena SOLA a partir
de una regla, y casi siempre la regla es un TAG. O sea que el tag que se
escribe en la carga decide en que colecciones aparece el producto -- y eso hoy
no estaba escrito en ninguna parte. Nadie podia responder "que tengo que
etiquetar para que este producto salga en Hiking" sin abrir Shopify sitio por
sitio.

Este motor guarda esa relacion como DATO y responde tres preguntas:

    que colecciones tiene cada marca en cada sitio
    que tags alimentan cada coleccion
    en que colecciones cae un producto con estos tags -- y en cuales no cae
    ninguna

Es por MARCA y no por sitio porque una marca vive en varias tiendas:
Columbia se carga en Columbia.pe, en Rockford.pe y en Supermall.pe, y cada
tienda tiene sus propias colecciones. Preguntar "las colecciones de Columbia"
sin decir la tienda no tiene una sola respuesta.

De donde salen los datos
------------------------
El diccionario NO se escribe a mano: se LEE de Shopify con
`scripts/generar_diccionario_colecciones.py` y se guarda en
`data/colecciones_por_marca.json`. Inventar las colecciones de una tienda seria
peor que no tenerlas, porque se leerian como ciertas.

Lo unico que este modulo sabe por si mismo son las familias ESTRUCTURALES del
vocabulario -- genero, clase y tipo de prenda --, que son las mismas en las seis
tiendas y salen del diccionario maestro de tipos. El vocabulario propio de cada
tienda (actividades, tecnologias, lineas) viaja en el archivo.
"""

import json
import re

from engines.garment_types import clase_de as _clase_de_tipo
from engines.garment_types import clave, resolver as _resolver_tipo

# --- familias del vocabulario ---------------------------------------------
# El orden es el de resolucion: la primera familia que reclama el tag se lo
# queda. Las estructurales van primero porque son las unicas que no dependen de
# lo que cada tienda haya decidido llamar.
FAMILIAS = (
    "codigo",
    "genero",
    "clase",
    "tipo",
    "actividad",
    "tecnologia",
    "linea",
    "atributo",
    "comercial",
    "sin_clasificar",
)

FAMILIAS_ESTRUCTURALES = ("codigo", "genero", "clase", "tipo")

# "Niños" y "Niño" conviven en el catalogo real y son el mismo genero. No se
# unifican aqui: eso es una decision de la tienda. Solo se reconocen los dos.
GENEROS = (
    "Hombre", "Mujer", "Unisex", "Niño", "Niña", "Niños", "Niñas",
    "Bebe", "Bebé", "Junior", "Kids", "Adulto",
)

CLASES = ("Vestuario", "Calzado", "Accesorios")

_GENEROS = {clave(x) for x in GENEROS}
_CLASES = {clave(x) for x in CLASES}


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def es_codigo_modelo_color(tag, codigos_conocidos=()):
    """El codigo Modelo-Color del propio producto, usado como tag.

    En Columbia.pe son 1.043 de los 1.175 tags distintos: uno por producto, que
    no agrupa nada y que ninguna coleccion puede usar. No es un error -- sirve
    para buscar --, pero contarlo como vocabulario haria creer que la tienda
    tiene mil criterios de clasificacion.

    Cuando se conocen los codigos del catalogo, la respuesta es por
    IDENTIDAD: el tag es el Modelo-Color de algun producto o no lo es. Esa es
    la unica respuesta que no se puede equivocar, y es la que usa
    `vocabulario_de_catalogo`.

    Sin esa lista queda la forma: solo mayusculas, digitos y guiones, con al
    menos un digito y al menos un guion. Asi entran `2086961-TYA`,
    `1-16504-00-7-GIE`, `CSC-029-7XK` y `PFG-047-356-8KX`, y NO entra
    `Omni-Shield™` (minusculas), `NEW ARRIVALS` (espacio) ni `PFG` (sin
    guion). La forma sola no alcanza: en el catalogo real hay `AM8004-yFO`,
    con una minuscula, que la regla por forma se pierde.
    """
    texto = _texto(tag)
    if not texto:
        return False
    if clave(texto) in {clave(c) for c in codigos_conocidos if _texto(c)}:
        return True
    if "-" not in texto:
        return False
    if not re.fullmatch(r"[A-Z0-9-]+", texto):
        return False
    return any(c.isdigit() for c in texto)


def familia_de_tag(tag, vocabulario=None, codigos_conocidos=()):
    """La familia a la que pertenece el tag.

    `vocabulario` es el de la tienda: {familia: [tags]}. Lo que no reclama
    ninguna familia sale como "sin_clasificar", que es una respuesta util --
    significa que ese tag no esta en el diccionario y nadie sabe para que
    sirve.

    **Lo declarado por la tienda manda sobre lo estructural**, y no al reves.
    Medido en Columbia.pe: `Impermeable` esta en 149 productos como ATRIBUTO
    (la prenda es impermeable), pero el diccionario maestro lo reconoce como el
    TIPO de prenda "Impermeables". Con lo estructural mandando, ese tag se
    contaria como tipo en una tienda donde no lo es. El vocabulario declarado
    es un dato curado a mano; la inferencia es el respaldo para lo que nadie
    curo todavia.
    """
    texto = _texto(tag)
    if not texto:
        return ""
    k = clave(texto)
    for familia in FAMILIAS:
        for declarado in (vocabulario or {}).get(familia, []):
            if clave(declarado) == k:
                return familia
    if es_codigo_modelo_color(texto, codigos_conocidos):
        return "codigo"
    if k in _GENEROS:
        return "genero"
    if k in _CLASES:
        return "clase"
    if _resolver_tipo(texto):
        return "tipo"
    return "sin_clasificar"


def clasificar_tags(tags, vocabulario=None, codigos_conocidos=()):
    """{familia: [tags]} conservando el orden de aparicion y sin repetidos."""
    salida = {familia: [] for familia in FAMILIAS}
    vistos = set()
    for tag in tags or []:
        texto = _texto(tag)
        k = clave(texto)
        if not k or k in vistos:
            continue
        vistos.add(k)
        salida[familia_de_tag(texto, vocabulario, codigos_conocidos)].append(texto)
    return salida


# --- reglas de coleccion ---------------------------------------------------
# Shopify llama a esto ruleSet: una lista de reglas y una bandera que dice si
# se cumplen TODAS (AND) o basta UNA (OR, `appliedDisjunctively`).
CAMPOS_EVALUABLES = {"TAG", "TYPE", "VENDOR", "TITLE", "PRODUCT_TAXONOMY_NODE_ID"}

RELACIONES_TEXTO = {
    "EQUALS": lambda valor, cond: clave(valor) == clave(cond),
    "NOT_EQUALS": lambda valor, cond: clave(valor) != clave(cond),
    "CONTAINS": lambda valor, cond: clave(cond) in clave(valor),
    "NOT_CONTAINS": lambda valor, cond: clave(cond) not in clave(valor),
    "STARTS_WITH": lambda valor, cond: clave(valor).startswith(clave(cond)),
    "ENDS_WITH": lambda valor, cond: clave(valor).endswith(clave(cond)),
}


def _valores_del_producto(producto, campo):
    campo = _texto(campo).upper()
    if campo == "TAG":
        return [_texto(t) for t in (producto.get("tags") or [])]
    if campo == "TYPE":
        return [_texto(producto.get("tipo"))]
    if campo == "VENDOR":
        return [_texto(producto.get("vendor"))]
    if campo == "TITLE":
        return [_texto(producto.get("titulo"))]
    return []


def evaluar_regla(producto, regla):
    """True / False / None. None es "no se puede evaluar", y NO es False.

    Una regla por precio, peso o inventario no se puede responder con los tags,
    y devolver False dejaria al producto fuera de la coleccion sin que nadie se
    entere -- justo el error silencioso que hay que evitar. La pantalla marca
    esas colecciones como no evaluables en vez de dar un numero falso.
    """
    campo = _texto(regla.get("campo")).upper()
    relacion = _texto(regla.get("relacion")).upper()
    condicion = _texto(regla.get("valor"))
    if campo not in CAMPOS_EVALUABLES or relacion not in RELACIONES_TEXTO:
        return None
    comparar = RELACIONES_TEXTO[relacion]
    valores = _valores_del_producto(producto, campo)
    if relacion.startswith("NOT_"):
        # Negativa: se cumple solo si NINGUN valor del producto la contradice.
        return all(comparar(valor, condicion) for valor in valores) if valores else True
    return any(comparar(valor, condicion) for valor in valores)


def producto_en_coleccion(producto, coleccion):
    """True / False / None, con la misma regla de None que `evaluar_regla`."""
    reglas = coleccion.get("reglas") or []
    if not reglas:
        # Sin reglas es una coleccion MANUAL: quien esta dentro lo decidio una
        # persona, y eso no se deduce de los tags.
        return None
    resultados = [evaluar_regla(producto, regla) for regla in reglas]
    if coleccion.get("disyuntiva"):
        if any(r is True for r in resultados):
            return True
        return None if any(r is None for r in resultados) else False
    if any(r is False for r in resultados):
        return False
    return None if any(r is None for r in resultados) else True


def coleccion_evaluable(coleccion):
    reglas = coleccion.get("reglas") or []
    return bool(reglas) and all(
        _texto(r.get("campo")).upper() in CAMPOS_EVALUABLES
        and _texto(r.get("relacion")).upper() in RELACIONES_TEXTO
        for r in reglas
    )


def tags_de_coleccion(coleccion):
    """Los tags que alimentan la coleccion, en el orden de sus reglas.

    Es la respuesta a "que le pongo al producto para que salga aqui". Solo las
    reglas POSITIVAS por tag: una regla NOT_EQUALS no dice que poner, dice que
    quitar, y mezclarlas daria una lista que hace lo contrario de lo que
    parece.
    """
    salida, vistos = [], set()
    for regla in coleccion.get("reglas") or []:
        if _texto(regla.get("campo")).upper() != "TAG":
            continue
        if _texto(regla.get("relacion")).upper() not in ("EQUALS", "CONTAINS", "STARTS_WITH", "ENDS_WITH"):
            continue
        valor = _texto(regla.get("valor"))
        k = clave(valor)
        if valor and k not in vistos:
            vistos.add(k)
            salida.append(valor)
    return salida


def colecciones_de_producto(producto, colecciones):
    """(dentro, no_evaluables). Dos listas de handles, nunca una sola: mezclar
    "esta dentro" con "no se sabe" es como se publica un numero falso."""
    dentro, dudosas = [], []
    for coleccion in colecciones or []:
        resultado = producto_en_coleccion(producto, coleccion)
        if resultado is True:
            dentro.append(coleccion.get("handle", ""))
        elif resultado is None:
            dudosas.append(coleccion.get("handle", ""))
    return dentro, dudosas


def evaluar_catalogo(productos, colecciones):
    """Cuantos productos cae en cada coleccion, cuales quedan fuera de todas y
    que colecciones no recibieron ninguno.

    Un producto que no cae en NINGUNA coleccion automatica esta cargado y no lo
    encuentra nadie navegando: es la resta que hace falta ver, igual que en el
    espejo de Supermall.
    """
    conteo = {c.get("handle", ""): 0 for c in colecciones or []}
    huerfanos, indeterminados = [], []
    for producto in productos or []:
        dentro, dudosas = colecciones_de_producto(producto, colecciones)
        for handle in dentro:
            conteo[handle] = conteo.get(handle, 0) + 1
        if dentro:
            continue
        (indeterminados if dudosas else huerfanos).append(producto)
    return {
        "por_coleccion": conteo,
        "huerfanos": huerfanos,
        "indeterminados": indeterminados,
        "vacias": sorted(h for h, n in conteo.items() if not n),
    }


def vocabulario_de_catalogo(productos, vocabulario=None):
    """El vocabulario REAL: cada tag del catalogo con su familia y cuantos
    productos lo llevan. Es lo que deja ver los tags que sobran."""
    conteo, muestra = {}, {}
    # El Modelo-Color de cada producto: asi un tag que ES el codigo del
    # producto se reconoce por identidad y no por su forma.
    codigos = {_texto(p.get("mod_col")) for p in productos or [] if _texto(p.get("mod_col"))}
    for producto in productos or []:
        for tag in producto.get("tags") or []:
            texto = _texto(tag)
            k = clave(texto)
            if not k:
                continue
            conteo[k] = conteo.get(k, 0) + 1
            muestra.setdefault(k, texto)
    filas = [
        {"tag": muestra[k], "familia": familia_de_tag(muestra[k], vocabulario, codigos), "productos": n}
        for k, n in conteo.items()
    ]
    filas.sort(key=lambda f: (-f["productos"], f["tag"].casefold()))
    return filas


def tags_en_dos_cajas(productos):
    """Tags que solo se diferencian en mayusculas o tildes.

    Medido en Columbia.pe: `Mochila`/`mochila` y `Utensilios`/`utensilios`.
    Shopify los trata como tags DISTINTOS, asi que una coleccion por
    `Utensilios` se deja fuera los que se cargaron en minuscula.
    """
    formas = {}
    for producto in productos or []:
        for tag in producto.get("tags") or []:
            texto = _texto(tag)
            k = clave(texto)
            if k:
                formas.setdefault(k, set()).add(texto)
    return sorted(
        (sorted(v) for v in formas.values() if len(v) > 1),
        key=lambda formas_: formas_[0].casefold(),
    )


# --- el archivo ------------------------------------------------------------
def diccionario_vacio():
    return {"version": 1, "generado": "", "marcas": {}}


def cargar_diccionario(ruta):
    """El diccionario del archivo, o uno vacio si no esta.

    Que falte NO es un error: mientras nadie corra el generador, la pantalla
    tiene que poder decir "esto todavia no se ha leido de Shopify" en vez de
    reventar.
    """
    try:
        with open(ruta, encoding="utf-8") as archivo:
            datos = json.load(archivo)
    except (OSError, ValueError):
        return diccionario_vacio()
    if not isinstance(datos, dict) or "marcas" not in datos:
        return diccionario_vacio()
    return datos


def guardar_diccionario(ruta, datos):
    with open(ruta, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, ensure_ascii=False, indent=1, sort_keys=True)
        archivo.write("\n")


def marcas_del_diccionario(datos):
    return sorted((datos or {}).get("marcas", {}))


def sitios_de_marca(datos, marca):
    entrada = ((datos or {}).get("marcas", {}) or {}).get(_texto(marca), {})
    return sorted((entrada.get("sitios") or {}))


def colecciones_de(datos, marca, sitio):
    entrada = ((datos or {}).get("marcas", {}) or {}).get(_texto(marca), {})
    sitio_datos = (entrada.get("sitios") or {}).get(_texto(sitio), {})
    return list(sitio_datos.get("colecciones") or [])


def vocabulario_de(datos, marca, sitio):
    entrada = ((datos or {}).get("marcas", {}) or {}).get(_texto(marca), {})
    sitio_datos = (entrada.get("sitios") or {}).get(_texto(sitio), {})
    return dict(sitio_datos.get("vocabulario") or {})


def clase_de_tipo(valor):
    """Reexportado a proposito: la clase se deriva del tipo en UN solo sitio."""
    return _clase_de_tipo(valor)
