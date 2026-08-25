"""Conversion de tallas de calzado a la escala peruana (PE).

Sin dependencias de Streamlit ni de pandas.

Por que existe
--------------
Vans entrega el calzado en tallas **US** y la tienda las publica en **PE**. La
tabla oficial que confirmo el usuario tiene cinco columnas -US Men, US Women,
US Boy, PE y CM- y la conversion NO es una formula: es una tabla, con saltos
propios (de US Men 12 se pasa a 13, y PE salta de 46 a 47).

La trampa: **un mismo numero US significa dos tallas distintas segun el
genero**. Un 8 de hombre es PE 40.5; un 8 de mujer es PE 38.5. Dos tallas y
media de diferencia. Por eso `talla_pe` pide el genero y, cuando no lo tiene,
lo dice en vez de elegir a ciegas.

Lo que SI se puede decidir solo: las escalas no se solapan. US va de 1 a 16 y
PE de 27 a 50, asi que un numero suelto nunca puede ser de las dos. Un valor
que ya esta en PE se devuelve tal cual, y por eso convertir dos veces es
inofensivo.

Las tallas infantiles vienen con sufijo (`10.5C`, `1Y`) y no son ambiguas.

Solo aplica a CALZADO. En vestuario una talla "12" es una talla de nino, no un
US 12, y convertirla seria destrozar el dato.
"""

import re

# (US Men, US Women, US Boy, PE, CM). "" = esa escala no cubre esa talla.
# Transcrita de la guia oficial de Vans.
TABLA_VANS = (
    ("", "", "10.5C", "27", "16.5"),
    ("", "", "11C", "27.5", "16.5"),
    ("", "", "11.5C", "28", "17"),
    ("", "", "12C", "29", "17.5"),
    ("", "", "12.5C", "30", "18"),
    ("", "", "13C", "30.5", "18.5"),
    ("", "", "13.5C", "31", "18.5"),
    ("", "", "1Y", "31.5", "19"),
    ("", "", "1.5Y", "32", "19.5"),
    ("", "", "2Y", "32.5", "20"),
    ("", "", "2.5Y", "33", "20.5"),
    ("", "", "3Y", "34", "21"),
    # US Men por debajo de 6.5 no venia en la guia, pero el catalogo si trae
    # esas tallas (una zapatilla de hombre 5 a 12). Se derivan del desfase de
    # la propia tabla: en las OCHO filas donde Men y Women coinciden, Men es
    # siempre Women menos 1.5. Man 5 = Women 6.5 = PE 36.5.
    #
    # Sin esto, un "5" de hombre caia en la columna de mujer y salia PE 34.5
    # en vez de 36.5: dos tallas de menos.
    ("3.5", "5", "3.5", "34.5", "21.5"),
    ("4", "5.5", "4", "35", "22"),
    ("4.5", "6", "4.5", "36", "22.5"),
    ("5", "6.5", "5", "36.5", "23"),
    ("5.5", "7", "5.5", "37", "23.5"),
    ("6", "7.5", "6", "38", "24"),
    ("6.5", "8", "", "38.5", "24.5"),
    ("7", "8.5", "", "39", "25"),
    ("7.5", "9", "", "40", "25.5"),
    ("8", "9.5", "", "40.5", "26"),
    ("8.5", "10", "", "41", "26.5"),
    ("9", "10.5", "", "42", "27"),
    ("9.5", "11", "", "42.5", "27.5"),
    ("10", "11.5", "", "43", "28"),
    ("10.5", "", "", "44", "28.5"),
    ("11", "", "", "44.5", "29"),
    ("11.5", "", "", "45", "29.5"),
    ("12", "", "", "46", "30"),
    ("13", "", "", "47", "31"),
    ("14", "", "", "48", "32"),
    ("15", "", "", "49", "33"),
    ("16", "", "", "50", "34"),
)

HOMBRE = "men"
MUJER = "women"
NINO = "boy"

# Cuando el producto es unisex y el numero existe en las dos escalas, hay que
# elegir. Vans publica el calzado unisex en tallas de hombre, asi que ese es el
# valor por defecto. Si alguna vez llega al reves, se cambia AQUI y con eso
# basta; la conversion avisa cuantas resolvio de esta forma.
ESCALA_UNISEX = HOMBRE


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def normalizar_talla(valor):
    """Deja la talla comparable: sin espacios, con punto y sin ceros de mas.

    "8,5" -> "8.5" | "8.0" -> "8" | " 10.5c " -> "10.5C" | "38.50" -> "38.5"
    """
    texto = _texto(valor).upper().replace(",", ".").replace(" ", "")
    if not texto:
        return ""
    sufijo = ""
    if texto.endswith(("C", "Y")):
        sufijo = texto[-1]
        texto = texto[:-1]
    if not re.fullmatch(r"\d+(\.\d+)?", texto):
        return _texto(valor).upper().replace(" ", "")
    # "040" y "045" son tallas PE escritas con relleno: asi las trae el
    # catalogo cargado. Sin quitar el cero no coinciden con nada y salian tal
    # cual. Se conserva al menos un digito para no convertir "0" en vacio.
    if texto.startswith("0") and not texto.startswith("0."):
        sin_ceros = texto.lstrip("0")
        texto = sin_ceros if sin_ceros and not sin_ceros.startswith(".") else texto.lstrip("0") or "0"
    if "." in texto:
        entero, _, decimales = texto.partition(".")
        decimales = decimales.rstrip("0")
        texto = f"{entero}.{decimales}" if decimales else entero
    return texto + sufijo


def _indices():
    """Diccionarios de busqueda, construidos una sola vez."""
    por_escala = {HOMBRE: {}, MUJER: {}, NINO: {}}
    por_cm = {}
    validos_pe = set()
    for us_men, us_women, us_boy, pe, cm in TABLA_VANS:
        pe_norm = normalizar_talla(pe)
        validos_pe.add(pe_norm)
        for escala, valor in ((HOMBRE, us_men), (MUJER, us_women), (NINO, us_boy)):
            clave = normalizar_talla(valor)
            if clave and clave != "-":
                por_escala[escala].setdefault(clave, pe_norm)
        clave_cm = normalizar_talla(cm)
        if clave_cm:
            por_cm.setdefault(clave_cm, pe_norm)
    return por_escala, por_cm, validos_pe


POR_ESCALA, POR_CM, TALLAS_PE = _indices()

# Los sufijos infantiles no son ambiguos: van siempre a la columna US Boy.
INFANTILES = {clave for clave in POR_ESCALA[NINO] if clave.endswith(("C", "Y"))}


# Se compara por PALABRA COMPLETA, no por subcadena. "femenino" contiene "men"
# y con `in` caia en la escala de hombre: un 8 de mujer salia PE 40.5 en vez de
# 38.5, dos tallas y media de mas.
_PALABRAS_GENERO = (
    (MUJER, ("femenino", "femenina", "mujer", "mujeres", "women", "woman", "dama", "damas", "girl", "girls", "nina", "ninas")),
    (HOMBRE, ("masculino", "masculina", "hombre", "hombres", "men", "man", "varon", "varones")),
    (NINO, ("nino", "ninos", "kid", "kids", "junior", "infantil", "bebe", "bebes", "boy", "boys", "youth")),
)


def escala_de_genero(genero):
    """La columna de la tabla que le toca a ese genero, o "" si es unisex.

    El orden importa: primero mujer y nina, porque "femenino" contiene "men".
    Y luego nino, para que "nina" no acabe en la columna infantil cuando la
    talla venia en escala de mujer.
    """
    texto = _texto(genero).lower()
    texto = (texto.replace("á", "a").replace("é", "e").replace("í", "i")
                  .replace("ó", "o").replace("ú", "u").replace("ñ", "n"))
    palabras = set(re.findall(r"[a-z]+", texto))
    for escala, claves in _PALABRAS_GENERO:
        if palabras & set(claves):
            return escala
    return ""


def ya_es_pe(valor):
    """True si la talla ya esta en la escala peruana."""
    return normalizar_talla(valor) in TALLAS_PE


def talla_pe(valor, genero="", permitir_unisex=True):
    """Convierte una talla de calzado a PE. Devuelve (talla, nota).

    `nota` explica que paso, y va vacia cuando la conversion fue directa:

    - ``""``            convertida sin dudas, o ya venia en PE.
    - ``"ambigua"``     el numero existe en hombre y mujer y no habia genero;
                        se resolvio con la escala por defecto.
    - ``"desconocida"`` no esta en la tabla; se devuelve el valor original.

    Nunca inventa: si no encuentra la talla, devuelve lo que le dieron.
    """
    clave = normalizar_talla(valor)
    if not clave:
        return "", ""
    # Ya esta en PE: no se toca. Convertir dos veces es inofensivo.
    if clave in TALLAS_PE:
        return clave, ""
    # Infantil con sufijo: no hay ambigüedad posible.
    if clave in INFANTILES:
        return POR_ESCALA[NINO][clave], ""

    escala = escala_de_genero(genero)
    if escala:
        destino = POR_ESCALA[escala].get(clave)
        if destino:
            return destino, ""
        # El genero dice una escala pero la talla no esta en ella. Antes de
        # rendirse se miran las otras: un nino con talla de mujer pequena es
        # justo la zona donde las dos columnas se cruzan.
        for otra in (HOMBRE, MUJER, NINO):
            destino = POR_ESCALA[otra].get(clave)
            if destino:
                return destino, "ambigua"
        return clave, "desconocida"

    # Sin genero. Si el numero solo existe en una escala, no hay duda.
    encontrados = {
        nombre: POR_ESCALA[nombre][clave]
        for nombre in (HOMBRE, MUJER, NINO)
        if clave in POR_ESCALA[nombre]
    }
    if not encontrados:
        return clave, "desconocida"
    if len(set(encontrados.values())) == 1:
        return next(iter(encontrados.values())), ""
    if not permitir_unisex:
        return clave, "ambigua"
    preferida = encontrados.get(ESCALA_UNISEX)
    if preferida:
        return preferida, "ambigua"
    return next(iter(encontrados.values())), "ambigua"


def talla_pe_desde_cm(valor):
    """Conversion desde centimetros, que no es ambigua. "" si no esta."""
    return POR_CM.get(normalizar_talla(valor), "")
