"""Los limites de las columnas de la hoja Carga Sial, y como se respetan.

Por que existe
--------------
SIAL rechaza -o trunca por su cuenta- los valores que se pasan de largo. Cuatro
columnas tienen tope confirmado por el usuario, y ninguna se estaba respetando.
Medido con una carga de Rockford de una sola fila:

    Tipo de Material    65 caracteres  (tope 30)
    Tecnologias         71 caracteres  (tope 50)
    Caracteristicas    144 caracteres  (tope 130)
    Color Web           -- sin recorte

La hoja se emite desde DOS sitios -la carga completa (`build_sial_row`) y la
carga por codigos Modelo-Color (`_filas_sial_desde_matrixify`, que sirve a
Centry, a la Carga Sial parcial y a Supermall)-. Con la regla escrita dos veces,
el arreglo siguiente entra en una hoja y se olvida en la otra: es exactamente lo
que este repositorio ya paga con las dos `normalize_size`. Por eso esta aqui, y
las dos la llaman.

No recorta por la mitad de una palabra
--------------------------------------
Un "100% Algodon organi" no es un material: es basura que alguien va a tener que
corregir a mano. Cada columna tiene su POLITICA, y las tres son distintas porque
los datos son distintos:

- **Antes de la coma** (`Color Web`, `Tipo de Material`). Son listas donde el
  primer elemento es el valor principal: "AZUL MARINO, BLANCO, ROJO" es
  fundamentalmente azul marino, y "100% Algodon, Forro Poliester" es algodon.
  Cortar la lista conserva el dato; recortar la cadena lo destruye.
- **O vacio** (`Tecnologias `). Una tecnologia a medias es peor que ninguna:
  "Omni-Heat Reflec" no existe. Se intenta con el primer elemento y, si tampoco
  entra, se deja vacio.
- **Recortar** (`Caracteristicas`). Es prosa descriptiva, no una clave: 130
  caracteres de caracteristicas siguen sirviendo. Se corta en el ultimo
  separador o espacio, nunca a mitad de palabra.

Todo ajuste se REPORTA. Un recorte silencioso es como se pierde un dato sin que
nadie se entere, y despues no hay forma de saber por que la ficha salio corta.

Sin Streamlit y sin pandas, como el resto de `engines/`.
"""

import re

# Los topes confirmados por el usuario, con el nombre EXACTO de la columna de la
# hoja (varias llevan un espacio al final: es el nombre real de la plantilla).
COLOR_WEB = "Color Web"
MATERIAL = "Tipo de Material"
TECNOLOGIAS = "Tecnologias "
CARACTERISTICAS = "Caracteristicas"

ANTES_DE_LA_COMA = "antes_de_la_coma"
O_VACIO = "o_vacio"
RECORTAR = "recortar"

LIMITES = {
    COLOR_WEB: (30, ANTES_DE_LA_COMA),
    MATERIAL: (30, ANTES_DE_LA_COMA),
    TECNOLOGIAS: (50, O_VACIO),
    CARACTERISTICAS: (130, RECORTAR),
}

# Los separadores de lista que usa el input comercial y el catalogo: la coma, el
# pipe (el separador declarado del input) y el punto y coma.
_SEPARADORES = re.compile(r"\s*[,|;]\s*")


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:  # NaN
        return ""
    return re.sub(r"\s+", " ", str(valor)).strip()


def primer_elemento(valor):
    """Lo que hay antes del primer separador de lista."""
    texto = _texto(valor)
    if not texto:
        return ""
    return _SEPARADORES.split(texto, maxsplit=1)[0].strip(" -:;,.|")


def recortar_en_palabra(valor, limite):
    """Recorta a `limite` caracteres sin partir una palabra.

    Se corta en el ultimo separador de lista que quepa y, si no hay ninguno, en
    el ultimo espacio. Solo si la primera palabra ya se pasa del limite se
    recorta en seco, porque ahi no hay alternativa.
    """
    texto = _texto(valor)
    if len(texto) <= limite:
        return texto
    trozo = texto[:limite]
    for corte in (max(trozo.rfind(sep) for sep in (",", "|", ";")), trozo.rfind(" ")):
        if corte > 0:
            return trozo[:corte].strip(" -:;,.|")
    return trozo.strip(" -:;,.|")


def acortar(valor, limite, politica=ANTES_DE_LA_COMA):
    """`(valor, motivo)` respetando el limite. `motivo` vacio = no se toco.

    Nunca devuelve algo mas largo que `limite`, sea cual sea la politica: es la
    unica garantia que la hoja necesita.
    """
    texto = _texto(valor)
    if not texto or len(texto) <= limite:
        return texto, ""

    if politica == RECORTAR:
        return recortar_en_palabra(texto, limite), f"recortado a {limite} caracteres"

    primero = primer_elemento(texto)
    if primero and len(primero) <= limite:
        return primero, f"se dejo solo el primer valor (el completo pasaba de {limite})"

    if politica == O_VACIO:
        return "", f"vaciado: ni el primer valor entra en {limite} caracteres"

    # Antes de la coma pero el primer elemento tambien se pasa: se recorta ese,
    # que es mejor que perder la columna entera.
    return recortar_en_palabra(primero or texto, limite), f"recortado a {limite} caracteres"


def ajustar_fila(fila, avisos=None, clave="", limites=None):
    """Ajusta EN SITIO las columnas con tope y devuelve la misma fila.

    `avisos` es una lista opcional donde se deja constancia de cada ajuste; la
    carga la vuelca en la hoja de Revision. Un recorte silencioso es como se
    pierde un dato sin que nadie se entere.
    """
    for columna, (limite, politica) in (limites or LIMITES).items():
        if columna not in fila:
            continue
        antes = _texto(fila.get(columna))
        despues, motivo = acortar(antes, limite, politica)
        fila[columna] = despues
        if motivo and avisos is not None:
            avisos.append({
                "Mod-Col": clave,
                "Columna": columna,
                "Motivo": motivo,
                "Antes": antes[:160],
                "Despues": despues,
            })
    return fila


def avisos_a_issues(avisos):
    """Los ajustes agrupados por columna y motivo, para la hoja de Revision."""
    if not avisos:
        return []
    agrupados = {}
    for aviso in avisos:
        clave = (aviso.get("Columna", ""), aviso.get("Motivo", ""))
        agrupados.setdefault(clave, []).append(aviso.get("Mod-Col", ""))
    filas = []
    for (columna, motivo), codigos in sorted(agrupados.items()):
        unicos = list(dict.fromkeys(c for c in codigos if c))
        filas.append({
            "Mod-Col": "Limites de la hoja Sial",
            "Problema": (
                f"{columna}: {len(codigos):,} valores ajustados ({motivo})."
                + (f" Ejemplos: {', '.join(unicos[:8])}" if unicos else "")
            ),
        })
    return filas
