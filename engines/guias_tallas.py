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
    if not tallas_calzado.escala_de_genero(genero):
        return tallas_calzado.normalizar_talla(talla), SIN_GENERO
    convertida, nota = tallas_calzado.talla_pe(talla, genero, permitir_unisex=False)
    return convertida, nota


_GUIAS = {}


def registrar_guia(marca, clase, guia):
    _GUIAS[_clave(marca, clase)] = guia
    return guia


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
        if not escala:
            return clave, SIN_GENERO
        destino = por_escala[escala].get(clave)
        if destino:
            return destino, ""
        return clave, "desconocida"

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
    guia = guia_para(marca, clase)
    if guia is None:
        return talla, SIN_GUIA
    return guia.convertir(talla, genero)


# --- Las guias que vienen en el codigo ------------------------------------
# Vans es la unica confirmada por el usuario: su tabla esta transcrita en
# `engines/tallas_calzado` y coincide fila a fila con el Excel oficial.
registrar_guia(
    "VANS", CALZADO,
    Guia(nombre="Guia de Tallas Vans 2026", marca="VANS", clase=CALZADO,
         convertidor=_convertir_con_vans,
         ya_en_destino=tallas_calzado.ya_es_pe),
)
