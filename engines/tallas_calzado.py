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

# La conversion SI se hizo, con la escala unisex de la guia. No es un fallo:
# es una salvedad que tiene que quedar por escrito.
UNISEX = "unisex"

# El numero NO esta en la columna que le toca a ese genero. No se busca en las
# otras: son escalas distintas, no sinonimos. Se devuelve la talla de origen.
FUERA_DE_ESCALA = "fuera de la escala del genero"


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


def _alias_infantiles_sin_sufijo():
    """`1Y` y `1` son la MISMA talla; el maestro escribe la segunda.

    La guia trae la columna infantil con sufijo hasta el `3Y` y sigue sin el
    (`3.5`, `4`, `4.5`), asi que el sufijo es notacion, no una escala aparte.
    El maestro escribe el calzado de nino sin sufijo y multiplicado por diez
    -- `10, 20, 30, 40, 45` es `1, 2, 3, 4, 4.5` --, asi que sin este alias
    `1`, `2` y `3` no estaban en ninguna columna y el producto entero se
    quedaba sin convertir. Medido en el catalogo real de Columbia.pe: **todas**
    las botas y zapatillas de nino salian en `1, 2, 3, 4` al lado de las de
    adulto en `39, 40, 41`.

    **Solo las `Y`, nunca las `C`.** Las de bebe van de `10.5C` a `13.5C`, y
    esos numeros SI existen en la columna de adulto: un `10.5` de hombre es PE
    44, no el PE 27 de un `10.5C`. Aliadas, un adulto sin genero pasaba a ser
    ambiguo y podia salir en talla de bebe. Las `Y` van de `1Y` a `3Y` y no
    chocan con nada: en adulto no hay 1, 2 ni 3.

    Va con `setdefault`: un numero que la columna infantil ya tenga por su
    cuenta manda sobre el alias.
    """
    for clave in sorted(INFANTILES):
        if not clave.endswith("Y"):
            continue
        sin_sufijo = clave[:-1]
        if sin_sufijo:
            POR_ESCALA[NINO].setdefault(sin_sufijo, POR_ESCALA[NINO][clave])


_alias_infantiles_sin_sufijo()


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


# Palabras con las que una ficha DICE que el producto es unisex. No es lo
# mismo que no saber el genero: "no lo se" obliga a no convertir, y "unisex"
# es un dato que la guia si sabe responder.
_PALABRAS_UNISEX = ("unisex", "unisexo", "uni")


def es_unisex(genero):
    """True si el genero DICE unisex.

    `escala_de_genero` devuelve "" tanto para un unisex declarado como para un
    producto sin genero, y las dos cosas no se tratan igual: la primera tiene
    respuesta en la guia (Vans publica el calzado unisex en tallas de hombre) y
    la segunda no se puede adivinar.
    """
    texto = _texto(genero).lower()
    palabras = set(re.findall(r"[a-z]+", texto))
    return bool(palabras & set(_PALABRAS_UNISEX))


def ya_es_pe(valor):
    """True si la talla ya esta en la escala peruana."""
    return normalizar_talla(valor) in TALLAS_PE


def talla_pe_unisex(valor):
    """La talla PE de un calzado declarado UNISEX. `(talla, nota)`.

    **No es una adivinanza.** La guia publica el calzado unisex en la escala de
    `ESCALA_UNISEX` -- hoy la de hombre --, asi que la respuesta sale de la
    tabla igual que las demas. Lo que si hay que dejar por escrito es que se
    resolvio asi, y para eso esta la nota `UNISEX`.

    Sin esto un producto unisex se quedaba en US: `escala_de_genero("Unisex")`
    devuelve "" y el conversor lo trataba como "no se sabe el genero". En una
    tienda que publica en PE eso deja unas zapatillas en `8, 9, 10` justo al
    lado de otras en `40.5, 42, 43`.
    """
    convertida, nota = talla_pe(valor, "", permitir_unisex=True)
    return convertida, UNISEX if nota == "ambigua" else nota


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
        # **NO se cruza de escala.** Antes, si el numero no estaba en la
        # columna que le toca a ese genero, se buscaba en las otras y se
        # publicaba esa respuesta con la nota "ambigua". Eso no es una
        # ambiguedad: son ESCALAS DISTINTAS, y el mismo numero significa cosas
        # distintas en cada una.
        #
        # Medido en el catalogo real de Columbia.pe: las "Sandalias Nino
        # Techsun" (`1594632-3ZK`) traen la curva `80, 90, 100, 110, 120, 130`
        # -- US 8 a 13 de NINO -- y se publicaban **40.5, 42, 43, 44.5, 46,
        # 47**, o sea tallas de hombre en una sandalia de nino. Nueve productos
        # de ese catalogo estaban asi, y los nueve son de nino.
        #
        # Un numero fuera de su escala se devuelve TAL CUAL y se reporta. Una
        # talla en US se ve mal y alguien la corrige; una talla de hombre en un
        # zapato de nino se ve bien y llega al comprador.
        #
        # Se distinguen dos cosas, porque no se arreglan igual: si el numero
        # existe en OTRA columna, el producto trae la escala de otro genero --
        # casi siempre calzado infantil -- y lo que hace falta es su guia. Si
        # no esta en ninguna, no es una talla que la guia conozca.
        en_otra = any(clave in POR_ESCALA[otra] for otra in (HOMBRE, MUJER, NINO))
        return clave, (FUERA_DE_ESCALA if en_otra else "desconocida")

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


# --- Interpretacion de la CURVA, no del valor suelto ----------------------
#
# El maestro escribe el calzado multiplicado por diez (`85` es 8.5) y a veces
# con relleno de ceros (`085`, `040`) o multiplicado por cien (`850`). Un valor
# suelto NO se puede interpretar: `040` puede ser el PE 40 o el US 4, y son dos
# tallas y media de diferencia.
#
# Lo que SI se puede decidir es la curva entera. Un producto de calzado tiene
# sus tallas en UNA escala, asi que se prueban las tres lecturas -tal cual,
# entre diez y entre cien- y se elige la unica que deja TODAS las tallas dentro
# de un rango que existe. Con `040, 050, 060, 070` la lectura directa daria PE
# 40 a 70, que no existe; entre diez da US 4 a 7, que si.

RANGO_US = (1.0, 16.5)
RANGO_PE = (26.0, 50.0)
DIVISORES = (1, 10, 100)


def _valor(talla):
    try:
        return float(normalizar_talla(talla))
    except (TypeError, ValueError):
        return None


def _cabe(valor, rango):
    return rango[0] <= valor <= rango[1]


def _es_media_talla(valor):
    """True si el numero cae en un escalon de talla real: entero o `.5`.

    **No existe una talla 2.1.** Las escalas de calzado van de media en media,
    asi que una division que deja `2.1, 2.2, 2.3` no es una lectura de la
    curva: es la prueba de que ese divisor no era el bueno. Sin esta guarda,
    una curva `21, 22, 23` -- que en el maestro son tallas PE de nino, o
    centimetros -- entraba en el rango numerico del US y se publicaba dividida
    entre diez.

    Se comprueba sobre el doble para no comparar decimales: `2.5 * 2` es 5, y
    `2.1 * 2` es 4.2.
    """
    doble = valor * 2
    return abs(doble - round(doble)) < 1e-9


# Una curva de calzado de MUJER no empieza en la 40. Las tallas PE de mujer van
# de la 34.5 a la 43, asi que una curva de mujer cuyo minimo leido como PE sea
# 40 o mas no esta en PE: es US mal escrito. Es la regla que dio el usuario --
# "ninguna talla de mujer empieza de la 40" -- y es lo que resuelve el caso
# ambiguo de verdad: `040` sola, que puede ser PE 40 o US 4.
MINIMO_PE_MUJER = 40.0


def interpretar_curva(valores, genero=""):
    """Como hay que leer los numeros de esta curva de calzado.

    Devuelve `(divisor, escala, nota)`:

    - `divisor` es por cuanto hay que dividir cada numero (1, 10 o 100).
    - `escala` es `"US"`, `"PE"` o `""` si no se pudo decidir.
    - `nota` explica la lectura cuando no fue la directa; vacia cuando si.

    Con `divisor` 1 y escala `""` no se toca nada: es lo que devuelve cuando la
    curva no es de calzado reconocible, y ahi manda el comportamiento de
    siempre.

    Se prueba la lectura DIRECTA primero, que es la que no supone nada, y entre
    dos directas manda PE, porque es lo que el maestro trae para la mayoria de
    las marcas. La excepcion es el calzado de mujer que leido en PE empezaria en
    la 40 o mas: eso no existe, asi que se lee como US.
    """
    numeros = [n for n in (_valor(v) for v in valores or []) if n is not None]
    if not numeros:
        return 1, "", ""

    es_mujer = escala_de_genero(genero) == MUJER
    lecturas = []
    descartadas_por_mujer = []
    for divisor in DIVISORES:
        convertidos = [n / divisor for n in numeros]
        # Una DIVISION tiene que dejar tallas reales. La lectura directa no
        # transforma nada -- lo que trae el maestro sale tal cual --, asi que
        # ahi no hay nada que comprobar; dividir SI inventa un numero, y si el
        # numero inventado no es una talla, el divisor estaba mal.
        if divisor != 1 and not all(_es_media_talla(n) for n in convertidos):
            continue
        if all(_cabe(n, RANGO_PE) for n in convertidos):
            # La regla de mujer DESCARTA la lectura PE, no elige otra: si la
            # curva de mujer empezara en la 40 leida en PE, no es PE.
            if es_mujer and min(convertidos) >= MINIMO_PE_MUJER:
                descartadas_por_mujer.append(min(convertidos))
            else:
                lecturas.append((divisor, "PE"))
        if all(_cabe(n, RANGO_US) for n in convertidos):
            lecturas.append((divisor, "US"))
    if not lecturas:
        return 1, "", "la curva no cabe en ninguna escala de calzado conocida"

    # Directa antes que dividida, y PE antes que US a igualdad de divisor.
    lecturas.sort(key=lambda par: (DIVISORES.index(par[0]), 0 if par[1] == "PE" else 1))
    divisor, escala = lecturas[0]

    nota = ""
    if divisor != 1:
        nota = f"numeros leidos entre {divisor}: la curva esta en {escala}"
    if descartadas_por_mujer:
        nota = (
            f"calzado de mujer: se descarto la lectura PE porque la curva "
            f"empezaria en la {min(descartadas_por_mujer):g}, y una curva de mujer "
            f"no empieza en la {MINIMO_PE_MUJER:g}; se leyo como {escala}"
        )
    elif len(lecturas) > 1 and not nota:
        otras = ", ".join(f"/{d} {e}" for d, e in lecturas[1:3])
        nota = f"la curva tambien cabria como {otras}; se leyo directa en {escala}"
    return divisor, escala, nota
