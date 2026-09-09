"""Registro de guias de tallas, por MARCA y CLASE de producto.

Por que existe
--------------
La conversion de escala dependia de `tallas_calzado_pe`, un booleano del SITIO.
Eso alcanzaba mientras Vans vivia solo en Vans.pe. Con **Supermall.pe** -- que
lleva Vans, Columbia, Hush Puppies, Rockford, Keds y Sorel en la misma tienda
-- un booleano de sitio solo permite dos respuestas: convertir TODO el calzado
del sitio, o nada. Y las dos son falsas: hay que convertir el calzado de las
marcas que entregan en US y dejar quieto el de las que ya entregan en PE.

Medido sobre el maestro real, por eso importa:

    marca            mod-col en US   mod-col en PE   con las DOS
    Hush Puppies         2.752           8.165            36
    Columbia             2.794               0             0
    Rockford               328           2.078             8
    Vans                   151             790             8

Asi que el dato se parte en dos, que es lo que estaba confundido:

- **La escala de publicacion es del SITIO** (`escala_calzado`): que ve el
  comprador. Supermall.pe y Vans.pe publican en PE; los demas, en origen.
- **La tabla de conversion es de la MARCA + CLASE**: como se traduce esa talla.
  Vive en este registro.

Separadas, un sitio nuevo es una linea de configuracion y una guia nueva es una
hoja de Excel.

La regla que no se negocia
--------------------------
**Sin guia no se convierte, y se reporta.** Nunca se inventa una equivalencia.
Una talla adivinada es peor que dejarla en US, porque en US al menos se ve que
esta en US; adivinada se publica como si fuera cierta y nadie se entera hasta
que llega un cambio.

Sin Streamlit y sin pandas, como el resto de `engines/`. El Excel de guias lo
lee la capa de aplicacion, que si tiene pandas, y lo registra con
`registrar_guia`.
"""

from engines import tallas_calzado

CALZADO = "CALZADO"
VESTUARIO = "VESTUARIO"

# Lo que devuelve una conversion que no se pudo hacer, para poder REPORTARLA.
SIN_GUIA = "sin guia"
SIN_GENERO = "sin genero"
# La talla no esta en la tabla. No es lo mismo que no tener guia: aqui la guia
# contesto, y contesto que ese numero no existe en ella.
DESCONOCIDA = "desconocida"
# El numero no esta en la columna que le toca a ese genero. NO se busca en las
# otras columnas: son escalas distintas, no sinonimos.
FUERA_DE_ESCALA = tallas_calzado.FUERA_DE_ESCALA
# La conversion SI se hizo, pero con la guia por defecto porque la marca no
# tiene la suya. No es un fallo: es una salvedad que hay que dejar por escrito.
POR_DEFECTO = "guia por defecto"
# La conversion se resolvio con la escala UNISEX de la guia. Tampoco es un
# fallo -- la guia publica el calzado unisex en tallas de hombre --, pero se
# reporta igual que la anterior.
UNISEX = tallas_calzado.UNISEX
POR_DEFECTO_UNISEX = "guia por defecto, escala unisex"

# La marca SI tiene guia, pero esa talla no esta en su tabla: se resolvio con
# la guia por defecto para no dejarla en la escala de origen.
FUERA_DE_LA_GUIA = "fuera de la guia de la marca"

# Notas que NO son un problema: la talla salio convertida y lo que llevan es
# una salvedad. Un problema de verdad (sin genero, talla desconocida) manda
# sobre ellas, porque lo que hay que arreglar es eso.
SALVEDADES = (POR_DEFECTO, UNISEX, POR_DEFECTO_UNISEX, FUERA_DE_LA_GUIA)


def _clave(marca, clase):
    return (
        ("" if marca is None else str(marca).strip().upper()),
        ("" if clase is None else str(clase).strip().upper()),
    )


class Guia:
    """Una tabla de conversion concreta.

    `convertir(talla, genero)` devuelve `(talla, nota)`. La nota va vacia
    cuando la conversion fue limpia y explica el problema cuando no.
    """

    def __init__(self, nombre, marca, clase, convertidor, ya_en_destino=None,
                 necesita_genero=True):
        self.nombre = nombre
        self.marca = marca
        self.clase = clase
        self._convertidor = convertidor
        self._ya_en_destino = ya_en_destino or (lambda talla: False)
        self.necesita_genero = necesita_genero

    def ya_en_destino(self, talla):
        return bool(self._ya_en_destino(talla))

    def convertir(self, talla, genero=""):
        return self._convertidor(talla, genero)


def _convertir_con_vans(talla, genero=""):
    """La guia oficial de Vans, transcrita en `engines/tallas_calzado`.

    Sin genero NO se convierte. Un mismo numero US son dos tallas distintas
    -- un 8 de hombre es PE 40.5 y uno de mujer es PE 38.5, dos tallas y media
    de diferencia -- y antes se aplicaba la columna de hombre en silencio. Es
    exactamente el fallo que reporto el usuario: pedia `5, 6, 7 -> 35, 36, 37`
    (columna de mujer) y la app devolvia `36.5, 38, 39` (columna de hombre).
    """
    if tallas_calzado.ya_es_pe(talla):
        return tallas_calzado.normalizar_talla(talla), ""
    # Las infantiles llevan sufijo (`10.5C`, `1Y`) y no son ambiguas: esas si
    # se pueden convertir sin genero.
    clave = tallas_calzado.normalizar_talla(talla)
    if clave in tallas_calzado.INFANTILES:
        return tallas_calzado.POR_ESCALA[tallas_calzado.NINO][clave], ""
    # Un unisex DECLARADO no es un producto sin genero. `escala_de_genero`
    # devuelve "" para los dos, y por eso un producto unisex se quedaba en US
    # al lado del resto del calzado ya convertido a PE -- en una tienda como
    # Supermall.pe, que publica todo en PE, eso es justo lo que el comprador no
    # puede resolver. La guia si tiene respuesta: publica el unisex en la
    # escala de `ESCALA_UNISEX`, y la conversion se reporta.
    if tallas_calzado.es_unisex(genero):
        return tallas_calzado.talla_pe_unisex(talla)
    if not tallas_calzado.escala_de_genero(genero):
        return tallas_calzado.normalizar_talla(talla), SIN_GENERO
    convertida, nota = tallas_calzado.talla_pe(talla, genero, permitir_unisex=False)
    return convertida, nota


_GUIAS = {}
_POR_DEFECTO = {}


def registrar_guia(marca, clase, guia):
    _GUIAS[_clave(marca, clase)] = guia
    return guia


def registrar_guia_por_defecto(clase, guia):
    """La guia que se usa cuando la marca no tiene la suya.

    Se agrego en septiembre de 2026 a peticion del usuario: *"las tallas no se
    estan generando por las guias de tallas que te pase de Vans"*. Hasta
    entonces, sin guia propia el calzado se publicaba con la talla de origen, y
    en Supermall.pe -- que publica en PE -- eso deja US y PE mezclados en la
    misma tienda, que es justo lo que el filtro de talla no puede resolver.

    **Lo que se gana y lo que se arriesga.** Se gana que el catalogo salga
    entero en una sola escala. Se arriesga que la equivalencia de Vans no sea
    la de la otra marca: un US 8 de Vans es PE 40.5, y otra marca puede calzar
    distinto. Por eso toda conversion hecha con esta guia se REPORTA en la hoja
    de Revision, marca por marca -- si alguna no cuadra, se ve y se le registra
    la suya con `registrar_tabla`, que es una hoja de Excel, no un `if`.
    """
    _POR_DEFECTO[_clave("", clase)[1]] = guia
    return guia


def guia_por_defecto(clase=CALZADO):
    return _POR_DEFECTO.get(_clave("", clase)[1])


def hay_conversion(marca, clase=CALZADO):
    """Si esa marca se puede convertir, con su guia o con la por defecto.

    La usan la CARGA y el Mantenedor de Tallas. Escrita dos veces, una
    convertiria y la otra no, y el mismo producto saldria distinto segun por
    donde pasara: es la trampa de las dos `normalize_size`.
    """
    return guia_para(marca, clase) is not None or guia_por_defecto(clase) is not None


def registrar_tabla(nombre, marca, clase, filas):
    """Registra una guia desde una tabla `(US Men, US Women, US Boy, PE, CM)`.

    Es la puerta por la que entran las guias que vienen de
    `data/guias_tallas.xlsx`: la capa de aplicacion lee el Excel -- ella si
    tiene pandas -- y llama aqui con las filas. Asi una guia nueva es una hoja,
    no un `if`.
    """
    tabla = tuple(tuple(("" if c is None else str(c).strip()) for c in fila[:5]) for fila in filas)
    tabla = tuple(tuple("" if c == "-" else c for c in fila) for fila in tabla)
    por_escala = {tallas_calzado.HOMBRE: {}, tallas_calzado.MUJER: {}, tallas_calzado.NINO: {}}
    validos = set()
    for us_men, us_women, us_boy, pe, _cm in tabla:
        pe_norm = tallas_calzado.normalizar_talla(pe)
        if not pe_norm:
            continue
        validos.add(pe_norm)
        for escala, valor in ((tallas_calzado.HOMBRE, us_men),
                              (tallas_calzado.MUJER, us_women),
                              (tallas_calzado.NINO, us_boy)):
            entrada = tallas_calzado.normalizar_talla(valor)
            if entrada:
                por_escala[escala].setdefault(entrada, pe_norm)

    def convertir(talla, genero=""):
        clave = tallas_calzado.normalizar_talla(talla)
        if not clave:
            return "", ""
        if clave in validos:
            return clave, ""
        escala = tallas_calzado.escala_de_genero(genero)
        if not escala and tallas_calzado.es_unisex(genero):
            # La misma regla que la guia del codigo: el unisex se publica en la
            # escala de `ESCALA_UNISEX`. Escrita solo alli, una guia que entrara
            # por Excel dejaria su calzado unisex en US y el mismo producto
            # saldria distinto segun de que marca fuera.
            escala = tallas_calzado.ESCALA_UNISEX
            destino = por_escala[escala].get(clave)
            return (destino, UNISEX) if destino else (clave, DESCONOCIDA)
        if not escala:
            return clave, SIN_GENERO
        destino = por_escala[escala].get(clave)
        if destino:
            return destino, ""
        # La misma regla que la guia del codigo: no se cruza de escala. Un
        # numero que no esta en la columna de ese genero NO es la misma talla
        # en otra columna.
        return clave, FUERA_DE_ESCALA

    return registrar_guia(marca, clase, Guia(
        nombre=nombre, marca=marca, clase=clase, convertidor=convertir,
        ya_en_destino=lambda talla: tallas_calzado.normalizar_talla(talla) in validos,
    ))


def guia_para(marca, clase):
    """La guia de esa marca y clase, o None. **None significa no convertir.**"""
    return _GUIAS.get(_clave(marca, clase))


def marcas_con_guia(clase=CALZADO):
    return sorted(m for m, c in _GUIAS if c == _clave("", clase)[1])


def convertir(talla, marca, clase, genero=""):
    """`(talla, nota)`. Sin guia devuelve la talla tal cual y la nota SIN_GUIA.

    Nunca levanta y nunca inventa: es la unica puerta por la que la carga
    convierte una talla, y tiene que poder decir por que no lo hizo.
    """
    respaldo = guia_por_defecto(clase)
    guia = guia_para(marca, clase)
    if guia is not None:
        convertida, nota = guia.convertir(talla, genero)
        if nota not in (DESCONOCIDA, FUERA_DE_ESCALA) or respaldo is None:
            return convertida, nota
        # La marca tiene guia pero esa talla no esta en su tabla. Las guias
        # publicadas empiezan donde empieza su catalogo -- la de Columbia, en
        # el US 7 de hombre --, y el maestro trae numeros por debajo. Dejarla
        # sin convertir la publicaria en la escala de origen justo al lado de
        # las que si se convirtieron, que es lo que la guia por defecto existe
        # para evitar. Se convierte con ella y se dice.
        de_respaldo, nota_respaldo = respaldo.convertir(talla, genero)
        if nota_respaldo in (SIN_GENERO, SIN_GUIA, DESCONOCIDA, FUERA_DE_ESCALA):
            # El respaldo tampoco sabe: manda el "desconocida" de la marca.
            return convertida, nota
        # Una nota que NO es un fallo significa que SI se convirtio, con su
        # salvedad ("ambigua" es el caso de un producto de nino con numeracion
        # de adulto). Se propaga tal cual para que la hoja de Revision explique
        # que paso, en vez de decir que no se convirtio.
        return de_respaldo, nota_respaldo or FUERA_DE_LA_GUIA
    if respaldo is None:
        return talla, SIN_GUIA
    convertida, nota = respaldo.convertir(talla, genero)
    if nota and nota not in SALVEDADES:
        # Un problema de verdad -- sin genero, talla desconocida -- manda sobre
        # la salvedad: lo que hay que arreglar es eso, no de que guia salio.
        return convertida, nota
    if respaldo.ya_en_destino(talla):
        # La talla ya venia en la escala de destino: no se convirtio nada, asi
        # que no hay nada que advertir. Es el caso de Hush Puppies y Rockford,
        # que entregan la mayor parte de su calzado ya en PE.
        return convertida, ""
    # Las dos salvedades se pueden dar a la vez -- una marca sin guia propia y
    # un producto unisex -- y las dos hay que poder leerlas en la hoja de
    # Revision. Pisar una con la otra deja la mitad del informe sin escribir.
    if nota == UNISEX:
        return convertida, POR_DEFECTO_UNISEX
    return convertida, POR_DEFECTO


# --- Las guias que vienen en el codigo ------------------------------------
# Vans es la unica confirmada por el usuario: su tabla esta transcrita en
# `engines/tallas_calzado` y coincide fila a fila con el Excel oficial.
registrar_guia(
    "VANS", CALZADO,
    Guia(nombre="Guia de Tallas Vans 2026", marca="VANS", clase=CALZADO,
         convertidor=_convertir_con_vans,
         ya_en_destino=tallas_calzado.ya_es_pe),
)

# --- Columbia -------------------------------------------------------------
#
# Buscada en la web a peticion del usuario (septiembre 2026). `columbia.com` y
# `help.columbia.com` estan BLOQUEADOS por la politica de salida de este
# entorno, asi que la tabla sale de la copia de la guia oficial que publica un
# distribuidor (Peter Glenn) y se cruzo con lo que publica RunRepeat: los dos
# coinciden en el largo de pie por talla.
#
# **Columbia publica US -> LARGO DE PIE en cm, no US -> EU.** Y su traduccion a
# EU es conocida por poco fiable (lo dice hasta RunRepeat), asi que el PE se
# deriva del CENTIMETRO, que es el dato fisico, con la misma columna CM de la
# tabla que ya usa la tienda. Asi el catalogo entero sigue en una sola escala.
#
# Lo que cambia respecto de usar la guia de Vans, y por que hacia falta:
#
#   HOMBRE  identico  (Columbia y Vans dan el mismo cm para el mismo US)
#   NINO    identico
#   MUJER   MEDIA TALLA de diferencia: la mujer de Columbia calza 0,5 cm mas
#           que la de Vans en el mismo numero US. Un US 8 de mujer es 25 cm ->
#           PE 39 en Columbia, y PE 38.5 con la tabla de Vans.
#
# (US Men, US Women, US Boy, PE, CM)
TABLA_COLUMBIA = (
    ("", "", "1", "31.5", "19"),
    ("", "", "2", "32.5", "20"),
    ("", "", "3", "34", "21"),
    ("", "5", "4", "35", "22"),
    ("", "5.5", "", "36", "22.5"),
    ("", "6", "5", "36.5", "23"),
    ("", "6.5", "5.5", "37", "23.5"),
    ("", "7", "6", "38", "24"),
    ("", "7.5", "", "38.5", "24.5"),
    ("7", "8", "7", "39", "25"),
    ("7.5", "8.5", "", "40", "25.5"),
    ("8", "9", "", "40.5", "26"),
    ("8.5", "9.5", "", "41", "26.5"),
    ("9", "10", "", "42", "27"),
    ("9.5", "10.5", "", "42.5", "27.5"),
    ("10", "11", "", "43", "28"),
    ("10.5", "", "", "44", "28.5"),
    ("11", "12", "", "44.5", "29"),
    ("11.5", "", "", "45", "29.5"),
    ("12", "", "", "46", "30"),
    ("13", "", "", "47", "31"),
    ("14", "", "", "48", "32"),
    ("15", "", "", "49", "33"),
    ("16", "", "", "50", "34"),
)

registrar_tabla("Guia de Tallas Columbia (largo de pie)", "COLUMBIA", CALZADO,
                TABLA_COLUMBIA)

# Y es tambien la guia POR DEFECTO del calzado: es la unica confirmada, y sin
# ella el calzado de Columbia, Keds y Sorel -- que entregan todo en US -- se
# publicaba en US dentro de una tienda que publica en PE. Ver
# `registrar_guia_por_defecto` para lo que esto gana y lo que arriesga.
registrar_guia_por_defecto(CALZADO, guia_para("VANS", CALZADO))
