"""El diccionario de tallas: como se escribe una talla y en que orden va.

Por que existe
--------------
El orden de las tallas lo decidian TRES criterios distintos en el repositorio
-uno en `generate_columbia_matrixify`, otro en `app_matrixify` y una copia
muerta en `engines/normalize`- y ninguno de los tres entendia mas que tres
formas: letra de una tabla de doce, numero puro y `numero/numero`.

Todo lo demas caia en un cajon que se ordenaba **alfabeticamente**. Medido
sobre el maestro real (`data/arti.zip`, 653.431 filas), eso deja **361 de los
15.690 modelo-color de Columbia** con la curva desordenada, y de la forma mas
visible posible:

    L/R, M/R, S/R, XL/R, XS/R        <- lo que se publica hoy
    XS/R, S/R, M/R, L/R, XL/R        <- lo que tiene que salir

    10/R, 12/R, 2/R, 4/R, 6/R, 8/R   <- hoy
    2/R, 4/R, 6/R, 8/R, 10/R, 12/R   <- correcto

Este modulo es el UNICO criterio de orden. `size_sort_key` de las dos capas
delega aqui, y `engines/orden_tallas` lo recibe inyectado como ya hacia. Dos
criterios se separan sin que nadie lo note, que es lo que este repositorio ya
paga con las dos `normalize_size`.

Sin Streamlit y sin pandas, como el resto de `engines/`.

La regla que hace que esto se pueda tocar sin miedo
---------------------------------------------------
Las familias 0, 1 y 2 son **exactamente** las tres que el criterio viejo
reconocia, con los mismos indices. Las formas nuevas van en familias 3 a 8, o
sea SIEMPRE despues. Consecuencia: en cualquier producto cuyas tallas el
criterio viejo ya reconocia todas, el orden nuevo es **identico**. Eso es lo
que garantiza que Rockford, Hush Puppies, Patagonia y el 97,7 % de Columbia no
se muevan un milimetro, y lo comprueba `scripts/test_orden_tallas_reales.py`
recorriendo los ~70.000 modelo-color del maestro de verdad.

Si agregas una familia nueva, va con numero >= 3 y con su caso en esa prueba.
"""

import re

# --- Familias -------------------------------------------------------------
# El numero ES la prioridad. No se renumeran: 0, 1 y 2 replican el criterio
# viejo y moverlas reordenaria catalogos que hoy salen bien.
LETRA = 0            # XS, S, M, L, XL ... y O/S al final de la escala
NUMERO = 1           # 5, 8.5, 38.5, 40
PAR_NUMERICO = 2     # 32/10, 14/16, 18/24, 35-38, 39-42
LETRA_LARGO = 3      # S/R, M/T, MS, MT, LT, XXL/R
LETRA_NUMERO = 4     # S/6, M/8, XL/6
NUMERO_LARGO = 5     # 2/R, 10/R
INFANTIL = 6         # 2T, 12M, 3-6M, 10.5C, 1Y
UNICA = 8            # ONE, OSFA, ONESIZE
DESCONOCIDA = 9      # lo que no se reconoce: por texto, y avisado

# --- La escala de letras --------------------------------------------------
# Es la del maestro (`generate_columbia_matrixify.size_sort_key`) con los
# alias que le faltaban: 2XL/3XL/4XL los traen Caterpillar y Under Armour y
# caian en el cajon de las desconocidas.
#
# O/S se queda en 99 DENTRO de esta escala, donde estaba. Moverlo a una
# familia propia cambiaria el orden de los productos que mezclan O/S con
# numeros -- PARFOIS tiene varios -- y ahi hoy O/S va primero.
ESCALA_LETRAS = {
    "XXXS": 1, "3XS": 1,
    "XXS": 2, "2XS": 2,
    "XS": 3,
    "XS/S": 3.5,
    "S": 4,
    "S/M": 5,
    "M": 6,
    "M/L": 7,
    "L": 8,
    "L/XL": 9,
    "XL": 10,
    "XL/XXL": 10.5,
    "XXL": 11, "2XL": 11,
    "XXXL": 12, "3XL": 12,
    "XXXXL": 13, "4XL": 13,
    "XXXXXL": 14, "5XL": 14,
    # La escala escrita con dos letras, que usan Mountain Hardwear y Under
    # Armour. Van al MISMO indice que su equivalente: no se renombra la
    # etiqueta, solo se le da su sitio en el orden. Sin esto, `MD` y `LG`
    # caian en el cajon de las desconocidas -- 553 filas del maestro.
    #
    # `SM` no llega nunca porque `normalize_size` ya lo convierte en `S/M`;
    # esta aqui para que el parser pueda leer `SMT` como SM + Tall.
    "SM": 4, "MD": 6, "LG": 8, "XLG": 10,
    "O/S": 99,
}

# La escala JUVENIL, que se escribe con Y delante. Es una escala propia: una
# YLG no es una L de adulto. Se agrupan aparte para que no se intercalen.
ESCALA_JUVENIL = {
    "YXS": 3, "YS": 4, "YSM": 4, "YM": 6, "YMD": 6,
    "YL": 8, "YLG": 8, "YXL": 10, "YXXL": 11,
}

# Las que son "talla unica" pero no se escriben O/S. Van al final y por eso
# tienen familia propia: en el criterio viejo eran desconocidas, o sea que ya
# salian ultimas. Con familia 8 siguen saliendo ultimas, asi que ningun
# catalogo se mueve por esto.
TALLA_UNICA = {"ONE", "ONESIZE", "ONE SIZE", "OSFA", "OSFM", "1SZ",
               "UNITALLA", "TU"}

# El largo de la prenda, que va DESPUES de la talla: Short, Regular, Tall,
# Petite. Ascendente por largo real, que es como lo lista la guia: una M corta
# antes que una M regular y esa antes que una M larga.
ESCALA_LARGOS = {"P": 1, "S": 2, "R": 3, "T": 4}

# Los meses tal y como los escribe Excel en es-PE al convertir "3-6" en fecha.
# Ver `decodificar_fecha_de_excel`.
MESES = {
    "ENE": 1, "JAN": 1,
    "FEB": 2,
    "MAR": 3,
    "ABR": 4, "APR": 4,
    "MAY": 5,
    "JUN": 6,
    "JUL": 7,
    "AGO": 8, "AUG": 8,
    "SET": 9, "SEP": 9,
    "OCT": 10,
    "NOV": 11,
    "DIC": 12, "DEC": 12,
}

_LETRAS_POR_LARGO = sorted(
    (clave for clave in ESCALA_LETRAS if clave not in ("O/S",)),
    key=len,
    reverse=True,
)

_NUM = r"\d+(?:\.\d+)?"
_SEP = r"\s*[/\-]\s*"

_RE_NUMERO = re.compile(rf"^{_NUM}$")
_RE_PAR = re.compile(rf"^({_NUM}){_SEP}({_NUM})$")
_RE_INFANTIL_SUFIJO = re.compile(rf"^({_NUM})\s*(T|M|C|Y)$")
_RE_INFANTIL_RANGO = re.compile(rf"^({_NUM}){_SEP}({_NUM})\s*(M)$")
_RE_FECHA_MES = re.compile(r"^([A-Z]{3,4})$")


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def decodificar_fecha_de_excel(talla):
    """`03-JUN` -> `3-6`. Devuelve "" si no era una fecha de Excel.

    El maestro trae tallas como `3-6`, `6-12`, `12-18`, `28-8` o `4-5`, y al
    exportarlo Excel las interpreta como fechas y las escribe con el nombre del
    mes. Se decodifica sustituyendo el mes por su numero **en el sitio donde
    esta**: asi `03-JUN` da `3-6` y `DIC-18` da `12-18`, cada uno en el orden
    que tenia el original. No hay que adivinar cual de los dos numeros era el
    mes, porque el texto conserva la posicion.

    Solo se usa para ORDENAR. La etiqueta que se publica no se cambia aqui: eso
    es una correccion del dato y se reporta en la hoja de revision, no se hace
    a espaldas de nadie.
    """
    texto = _texto(talla).upper().replace(" ", "")
    if "-" not in texto:
        return ""
    partes = texto.split("-")
    if len(partes) != 2:
        return ""
    convertidas = []
    hubo_mes = False
    for parte in partes:
        mes = _RE_FECHA_MES.match(parte)
        if mes and mes.group(1) in MESES:
            convertidas.append(str(MESES[mes.group(1)]))
            hubo_mes = True
        elif re.fullmatch(r"\d+", parte):
            convertidas.append(str(int(parte)))
        else:
            return ""
    return "-".join(convertidas) if hubo_mes else ""


def limpiar_separadores(talla):
    """Quita los espacios alrededor de `/` y `-`.

    `S/ 8` y `S/8` son la misma talla, y el maestro las escribe de las dos
    formas DENTRO DEL MISMO producto (visto en `2078861-HHD`: `S/ 8` junto a
    `M/8`). Ninguna talla real lleva espacio pegado a la barra, asi que
    quitarlo no puede confundir dos tallas distintas.
    """
    texto = _texto(talla)
    return re.sub(r"\s*([/\-])\s*", r"\1", texto)


def descomponer(talla):
    """La talla, entendida: `(familia, componentes, canonica)`.

    `componentes` es la tupla por la que se ordena dentro de la familia y
    `canonica` la forma comparable. Nunca levanta: lo que no reconoce sale como
    `DESCONOCIDA`, que se ordena por texto y se puede reportar.
    """
    bruto = _texto(talla)
    if not bruto:
        return (DESCONOCIDA, (), "")
    texto = limpiar_separadores(bruto).upper().replace(",", ".")

    # 1. Escala de letras, tal cual (incluido O/S en 99).
    if texto in ESCALA_LETRAS:
        return (LETRA, (ESCALA_LETRAS[texto],), texto)
    if texto in TALLA_UNICA:
        return (UNICA, (0,), texto)
    if texto in ESCALA_JUVENIL:
        indice = ESCALA_JUVENIL[texto]
        return (INFANTIL, (5, indice, indice), texto)

    # 2. Numero puro.
    if _RE_NUMERO.match(texto):
        return (NUMERO, (float(texto),), texto)

    # 3. Infantil con sufijo: 2T, 12M, 10.5C, 1Y. Antes que el par numerico,
    #    porque `3-6M` tambien lleva guion.
    rango_meses = _RE_INFANTIL_RANGO.match(texto)
    if rango_meses:
        # `3-6M` y `12M` son la MISMA escala y se ordenan por el primer numero:
        # 3-6M, 6-9M, 9-12M, 12M, 18M, 24M. En dos subfamilias distintas
        # saldrian los rangos detras de los sueltos, que es al reves de como se
        # usa la curva de bebe.
        return (INFANTIL, (0, float(rango_meses.group(1)), float(rango_meses.group(2))),
                texto)
    sufijo = _RE_INFANTIL_SUFIJO.match(texto)
    if sufijo:
        # Cada sufijo es su propia escala y no se mezclan: los meses (M) van
        # antes que los anos de nino (T), y las de bebe (C/Y) son la escala de
        # calzado infantil de la guia de Vans.
        orden_sufijo = {"M": 0, "T": 2, "C": 3, "Y": 4}[sufijo.group(2)]
        numero = float(sufijo.group(1))
        return (INFANTIL, (orden_sufijo, numero, numero), texto)

    # 4. Par numerico: 32/10 (cintura/largo), 14/16 y 18/24 (rangos de nino),
    #    35-38 (rango de calzado) y las fechas de Excel ya decodificadas.
    #    `/` y `-` van en la MISMA familia a proposito: si no, un producto con
    #    `18/24` y `3-6` los pondria en dos bloques y el orden seguiria mal.
    par = _RE_PAR.match(texto)
    if par:
        return (PAR_NUMERICO, (float(par.group(1)), float(par.group(2))), texto)
    decodificada = decodificar_fecha_de_excel(texto)
    if decodificada:
        par = _RE_PAR.match(decodificada)
        if par:
            return (PAR_NUMERICO, (float(par.group(1)), float(par.group(2))), decodificada)

    # 4 bis. Rango de letras escrito con guion: `S-M`, `L-XL`, `M-L`. Es la
    #    misma talla combinada que `S/M`, escrita de otra forma, asi que va al
    #    punto medio de las dos y queda entre ellas.
    rango_letras = re.match(r"^([A-Z]{1,6})[/\-]([A-Z]{1,6})$", texto)
    if (rango_letras
            and rango_letras.group(1) in ESCALA_LETRAS
            and rango_letras.group(2) in ESCALA_LETRAS):
        indices = (ESCALA_LETRAS[rango_letras.group(1)], ESCALA_LETRAS[rango_letras.group(2)])
        return (LETRA, ((indices[0] + indices[1]) / 2.0,), texto)

    # 5. Letra + algo. Se prueba la letra mas larga primero para que XXL no se
    #    lea como XX + L.
    for letra in _LETRAS_POR_LARGO:
        if not texto.startswith(letra):
            continue
        resto = texto[len(letra):].lstrip("/-")
        if not resto:
            continue
        indice_letra = ESCALA_LETRAS[letra]
        if resto in ESCALA_LARGOS:
            return (LETRA_LARGO, (indice_letra, ESCALA_LARGOS[resto]), f"{letra}/{resto}")
        if _RE_NUMERO.match(resto):
            return (LETRA_NUMERO, (indice_letra, float(resto)), f"{letra}/{resto}")

    # 6. Numero + largo: 2/R, 10/R.
    numero_largo = re.match(rf"^({_NUM})/?([A-Z])$", texto)
    if numero_largo and numero_largo.group(2) in ESCALA_LARGOS:
        return (NUMERO_LARGO,
                (float(numero_largo.group(1)), ESCALA_LARGOS[numero_largo.group(2)]),
                f"{numero_largo.group(1)}/{numero_largo.group(2)}")

    return (DESCONOCIDA, (), texto)


def clave_de_orden(talla, normalizador=None):
    """La clave de orden de una talla. Es el UNICO criterio de la app.

    `normalizador` es opcional y existe porque las dos capas normalizan antes
    de comparar (`normalize_size`): se le pasa la de quien llama para no tener
    aqui una tercera. Sin ella se ordena el texto tal cual.
    """
    valor = normalizador(talla) if normalizador else talla
    familia, componentes, canonica = descomponer(valor)
    if familia == DESCONOCIDA:
        # Igual que antes: al final y por texto, para que el orden sea estable.
        return (DESCONOCIDA, (9999.0,), canonica)
    return (familia, tuple(float(c) for c in componentes), canonica)


def es_reconocida(talla):
    return descomponer(talla)[0] != DESCONOCIDA


def ordenar(tallas, normalizador=None):
    """Las tallas ordenadas. Atajo para las pruebas y las pantallas."""
    return sorted(tallas or [], key=lambda t: clave_de_orden(t, normalizador))


def no_reconocidas(tallas, normalizador=None):
    """Las que no se entienden, para poder REPORTARLAS en vez de esconderlas.

    Una talla que no se reconoce se ordena por texto, y eso es exactamente el
    fallo que este modulo arregla. Si aparece una forma nueva en el maestro, la
    hoja de revision la nombra en vez de dejar la curva desordenada en silencio.
    """
    sueltas = []
    for talla in tallas or []:
        valor = normalizador(talla) if normalizador else talla
        if _texto(valor) and not es_reconocida(valor) and valor not in sueltas:
            sueltas.append(valor)
    return sueltas
