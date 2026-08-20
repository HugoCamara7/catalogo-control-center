"""Enriquecimiento de atributos del producto, en un solo sitio.

Sin dependencias de Streamlit ni de pandas.

Que resuelve
------------
Una sola cadena de prioridades para **Género, Tipo de prenda, Materiales,
Composición, Cuidados y Tecnología**, compartida por la Carga Completa, la
Carga Parcial y Centry. Antes cada camino tenía su propia lista de columnas y
por eso un mismo producto salía completo en una carga y vacío en otra.

Las reglas del negocio, escritas como tales
------------------------------------------
- **Género y Tipo de prenda:** manda Shopify; si viene vacío, SIAL/BigQuery.
  Ese orden está en `ATRIBUTOS[...]["columnas"]`, no repartido por el código.
- **Materiales, Composición y Cuidados:** metafields de Shopify → columnas del
  input comercial → columnas del maestro → etiquetas `Etiqueta: Valor` que
  viven en el Body HTML, los tags y los bullets.
- **No se inventa nada.** Si ninguna fuente trae el dato se devuelve `""` y
  quien llama deja la advertencia. Un valor vacío es una respuesta válida.
- **Mapeos por marca:** `ALIAS_POR_MARCA` deja que una marca use otro nombre de
  columna sin tocar el resto. El nombre del *tipo* por sitio NO se duplica
  aquí: eso ya vive en `engines/garment_types.tipo_para_sitio`.

Como se usa
-----------
    from engines import enrich

    material, origen = enrich.resolver("material", fuentes=[fila], textos=[body])
    todo = enrich.resolver_todos([fila_shopify, fila_maestro], textos=[body])

`fuentes` es cualquier cosa con `.get(clave)`: un dict, una fila de pandas, un
registro del maestro. Se recorren en el orden en que llegan, y dentro de cada
una se recorren los alias de la columna en el orden declarado.
"""

import re
import unicodedata
from functools import lru_cache

# --- normalizacion --------------------------------------------------------


def _texto(valor):
    if valor is None:
        return ""
    # Camino rapido: casi todo llega ya como texto.
    if type(valor) is str:
        return valor.strip()
    # NaN de pandas sin importar pandas.
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


@lru_cache(maxsize=8192)
def _normalizar_cacheado(texto):
    plano = unicodedata.normalize("NFKD", texto.casefold())
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", plano)).strip()


def normalizar(valor):
    """Minusculas, sin tildes y sin puntuacion: la clave de comparacion.

    Con cache: esta funcion se llama decenas de veces por fila y los valores se
    repiten muchisimo (todas las variantes de un producto traen el mismo
    material, el mismo tipo y los mismos nombres de columna).
    """
    return _normalizar_cacheado(_texto(valor))


# Valores que ocupan la celda pero no dicen nada. Se tratan como vacio para
# que la cadena siga buscando en la fuente siguiente en vez de quedarse con un
# "No Aplica" y dar el atributo por resuelto.
VACIOS = {
    "", "-", "--", "n a", "na", "no aplica", "noaplica", "sin dato", "sin datos",
    "sin informacion", "ninguno", "ninguna", "none", "null", "nan", "n d", "nd",
    "#n d", "#n a", "0", "no definido", "por definir", "pendiente",
}


def util(valor):
    """True si el valor dice algo. Un "No Aplica" no dice nada.

    El texto largo nunca es un "no aplica": se acepta sin normalizar, que es el
    caso mayoritario y el mas caro.
    """
    texto = _texto(valor)
    if not texto:
        return False
    if len(texto) > 24:
        return True
    if texto.lower() in VACIOS:
        return False
    return _normalizar_cacheado(texto) not in VACIOS


# --- que se busca y donde -------------------------------------------------
# El orden de "columnas" ES la regla de prioridad. Shopify primero (sus
# metafields y sus campos nativos), despues el input comercial, y al final el
# maestro SIAL/BigQuery.
ATRIBUTOS = {
    "genero": {
        "columnas": (
            "Metafield: custom.genero [single_line_text_field]",
            "Género", "Genero", "GENERO", "Gender",
            "GENERO_MA", "genero_ma",
        ),
        "etiquetas": ("Género", "Genero", "Gender"),
    },
    "tipo": {
        "columnas": (
            "Type",
            "Metafield: custom.tipo [single_line_text_field]",
            "Tipo de Prenda", "Tipo De Prenda", "Tipo de Producto",
            "Tipo De Producto", "TipoProducto", "Tipo", "TIPO_MA",
            "SubCategoria", "Sub Categoria",
        ),
        "etiquetas": ("Tipo De Producto", "Tipo de Producto", "Tipo de Prenda"),
    },
    "material": {
        "columnas": (
            "Metafield: custom.materialidad [single_line_text_field]",
            "Materiales", "Material", "Materialidad", "MATERIAL",
            "Tipo de Material", "Tipo De Material", "Material principal",
        ),
        # "Capellada" es el material principal de un calzado: no es un invento,
        # es como lo rotula la ficha.
        "etiquetas": ("Material principal", "Materialidad", "Material", "Capellada"),
    },
    "composicion": {
        "columnas": (
            "Composición", "Composicion", "COMPOSICION", "Composition",
            "Materiales",
            "Metafield: custom.materialidad [single_line_text_field]",
        ),
        "etiquetas": ("Composición", "Composicion", "Composition", "Capellada"),
    },
    "cuidados": {
        "columnas": (
            "Cuidados", "Cuidado", "CUIDADOS", "CUIDADO", "Care",
            "Care Instructions", "Instrucciones de cuidado", "Lavado", "Washing",
        ),
        "etiquetas": ("Cuidados", "Cuidado", "Care", "Lavado",
                      "Instrucciones De Cuidado"),
    },
    "tecnologia": {
        "columnas": (
            "Metafield: custom.tecnologia [list.single_line_text_field]",
            "Tecnologias", "Tecnologías", "Tecnologia", "Tecnología",
            "Technology", "Technologies",
        ),
        "etiquetas": ("Tecnología", "Tecnologia", "Technology"),
    },
}

# Columnas propias de una marca, cuando difiere del resto. Se anteponen a las
# de `ATRIBUTOS`. Vacio a proposito: se llena cuando una marca lo necesite, sin
# tocar la cadena general.
#
#     ALIAS_POR_MARCA = {"hush puppies": {"material": ("Upper Material",)}}
ALIAS_POR_MARCA = {}


@lru_cache(maxsize=256)
def alias_de(atributo, marca=""):
    """Los nombres de columna a probar, en orden, para ese atributo y marca.

    Con cache: es una lista fija por (atributo, marca) y se pedia en cada fila.
    Si se toca `ALIAS_POR_MARCA` en caliente hay que llamar a
    `alias_de.cache_clear()`.
    """
    regla = ATRIBUTOS.get(atributo)
    if not regla:
        return ()
    propias = ALIAS_POR_MARCA.get(normalizar(marca), {}).get(atributo, ())
    return tuple(propias) + tuple(regla["columnas"])


# --- lectura de fuentes ---------------------------------------------------


def _leer(fuente, clave):
    """Lee una clave de un dict, una fila de pandas o cualquier mapeo."""
    if fuente is None:
        return ""
    try:
        valor = fuente.get(clave)
    except (AttributeError, TypeError):
        return ""
    except KeyError:
        return ""
    return _texto(valor)


def desde_columnas(fuentes, claves):
    """(valor, origen) de la primera columna con algo util.

    Recorre fuente por fuente y, dentro de cada una, alias por alias. El origen
    dice de que columna salio, para poder escribirlo en la advertencia.
    """
    for indice, fuente in enumerate(fuentes or ()):
        for clave in claves:
            valor = _leer(fuente, clave)
            if util(valor):
                return valor, f"columna {clave} (fuente {indice + 1})"
    return "", ""


@lru_cache(maxsize=2048)
def _pares_cacheados(texto):
    pares = []
    for trozo in re.split(r"[|\n\r]+", texto):
        if ":" not in trozo:
            continue
        etiqueta, _, valor = trozo.partition(":")
        etiqueta, valor = etiqueta.strip(), valor.strip(" ,;.")
        if etiqueta and valor:
            pares.append((etiqueta, valor))
    return tuple(pares)


def pares_de_texto(texto):
    """Los pares "Etiqueta: Valor" de un listado separado por | o salto.

    Con cache: el mismo Body se consulta una vez por cada atributo y por cada
    variante del producto.
    """
    return list(_pares_cacheados(_texto(texto)))


def desde_etiquetas(textos, etiquetas):
    """(valor, origen) buscando "Etiqueta : Valor" dentro de textos libres."""
    buscadas = [normalizar(etiqueta) for etiqueta in etiquetas]
    for texto in textos or ():
        pares = _pares_cacheados(_texto(texto))
        if not pares:
            continue
        normalizados = [(normalizar(etiqueta), etiqueta, valor) for etiqueta, valor in pares]
        for buscada in buscadas:
            for clave, etiqueta, valor in normalizados:
                if clave == buscada and util(valor):
                    return valor, f"etiqueta {etiqueta}"
    return "", ""


def resolver(atributo, fuentes=(), textos=(), marca=""):
    """(valor, origen) del atributo. Vacio si ninguna fuente lo trae.

    Primero las columnas, en el orden declarado; despues las etiquetas dentro
    de los textos libres. Nunca al reves: una columna es un dato, una etiqueta
    es texto que hubo que interpretar.
    """
    if atributo not in ATRIBUTOS:
        return "", ""
    valor, origen = desde_columnas(fuentes, alias_de(atributo, marca))
    if valor:
        return valor, origen
    return desde_etiquetas(textos, ATRIBUTOS[atributo]["etiquetas"])


def alias_presentes(atributo, columnas, marca=""):
    """Los alias que EXISTEN en ese conjunto de columnas, en orden.

    Se calcula una vez por archivo, no por fila: las columnas son las mismas
    para todas. Sin esto se consultaban ~33 columnas inexistentes en cada fila,
    y en pandas cada consulta a una fila cuesta de verdad.
    """
    # OJO: `columnas or ()` no sirve aqui. Con un Index de pandas, ese `or`
    # lanza "truth value of an Index is ambiguous" y el resolutor se caia en
    # silencio, volviendo a la busqueda lenta sin que nada lo dijera.
    disponibles = set() if columnas is None else {str(columna) for columna in columnas}
    return tuple(clave for clave in alias_de(atributo, marca) if clave in disponibles)


class Resolutor:
    """Resuelve atributos para un archivo concreto, sin repetir el trabajo fijo.

    Se crea UNA vez por DataFrame y se reutiliza en cada fila:

        resolutor = enrich.Resolutor(df.columns)
        for fila in filas:
            material, _ = resolutor.resolver("material", [fila], textos, marca)

    Mismas reglas y mismo orden que `resolver`; lo unico que cambia es que las
    columnas que no existen no se vuelven a preguntar.
    """

    def __init__(self, columnas=()):
        self._columnas = () if columnas is None else tuple(str(columna) for columna in columnas)
        self._claves = {}

    def claves(self, atributo, marca=""):
        cache = self._claves.setdefault(normalizar(marca), {})
        if atributo not in cache:
            cache[atributo] = alias_presentes(atributo, self._columnas, marca)
        return cache[atributo]

    def resolver(self, atributo, fuentes=(), textos=(), marca=""):
        if atributo not in ATRIBUTOS:
            return "", ""
        valor, origen = desde_columnas(fuentes, self.claves(atributo, marca))
        if valor:
            return valor, origen
        return desde_etiquetas(textos, ATRIBUTOS[atributo]["etiquetas"])


def resolver_todos(fuentes=(), textos=(), marca="", atributos=None):
    """{atributo: {"valor", "origen"}} para varios atributos de una vez."""
    nombres = atributos or tuple(ATRIBUTOS)
    salida = {}
    for nombre in nombres:
        valor, origen = resolver(nombre, fuentes, textos, marca)
        salida[nombre] = {"valor": valor, "origen": origen}
    return salida


def faltantes(resueltos):
    """Los atributos que quedaron vacios. Para escribir la advertencia."""
    return sorted(
        nombre for nombre, dato in (resueltos or {}).items()
        if not _texto(dato.get("valor"))
    )
