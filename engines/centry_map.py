"""Motor de generacion Centry a partir de la plantilla oficial.

Sin dependencias de Streamlit.

Que hace
--------
1. Lee `data/plantilla_centry_productos.xlsx` como UNICA fuente de verdad de
   columnas y valores permitidos. Si Centry cambia la plantilla, se reemplaza el
   Excel y no hay que tocar Python.
2. Decide la familia del producto (superior, inferior, calzado, accesorios) a
   partir del tipo de prenda y la clase que ya trae el catalogo.
3. Arma las columnas del producto: las de la hoja SIEMPRE mas las de su familia.
4. Resuelve la categoria Centry con la tabla Marca|Tipo|Genero|Categoria,
   dando prioridad a la marca concreta sobre "Todos".
5. Valida los valores contra el diccionario de cada columna.

Que NO hace
-----------
No inventa valores. Cuando una equivalencia es dudosa devuelve un pendiente con
el motivo, para que la carga avise en vez de publicar algo inventado.
"""

import re
import unicodedata
from pathlib import Path

RUTA_PLANTILLA = Path(__file__).resolve().parents[1] / "data" / "plantilla_centry_productos.xlsx"

HOJA_SIEMPRE = "SIEMPRE"
HOJA_CATEGORIAS = "Categorias"

SUPERIOR = "superior"
INFERIOR = "inferior"
CALZADO = "calzado"
ACCESORIOS = "accesorios"

HOJA_POR_FAMILIA = {
    SUPERIOR: "Vestuario parte superior",
    INFERIOR: "Vestuario parte inferior",
    CALZADO: "Calzado",
    ACCESORIOS: "Accesorios",
}

ETIQUETA_FAMILIA = {
    SUPERIOR: "Vestuario parte superior",
    INFERIOR: "Vestuario parte inferior",
    CALZADO: "Calzado",
    ACCESORIOS: "Accesorios",
}


def _texto(valor):
    return "" if valor is None else str(valor).strip()


def normalizar(valor):
    """Minusculas, sin tildes, sin puntuacion y sin espacios repetidos.

    Es la clave con la que se comparan tipos, generos y valores de diccionario.
    "MOCASÍN", "Mocasin" y "mocasines" tienen que caer en la misma entrada.
    """
    texto = _texto(valor).casefold()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^\w\s/-]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def _singular(valor):
    """Quita el plural mas comun para emparejar 'Camisas' con 'Camisa'."""
    texto = normalizar(valor)
    if len(texto) > 3 and texto.endswith("es"):
        return texto[:-2]
    if len(texto) > 3 and texto.endswith("s"):
        return texto[:-1]
    return texto


# --- familia del producto ------------------------------------------------
# Se busca por palabra dentro del tipo de prenda. El orden importa: gana la
# primera familia cuyo termino aparezca, y calzado se evalua antes que vestuario
# porque "zapatilla de running" tambien contiene "running".
TERMINOS_FAMILIA = [
    (CALZADO, (
        "zapatilla", "zapato", "bota", "botin", "bototo", "sandalia", "mocasin",
        "alpargata", "ballerina", "pantufla", "chala", "hojota", "ojota",
        "calzado", "sueco", "zueco", "slipper", "nautico", "tacon", "taco",
    )),
    (ACCESORIOS, (
        "mochila", "bolso", "cartera", "billetera", "morral", "maleta", "canguro",
        "gorro", "gorra", "sombrero", "jockey", "bufanda", "panuelo", "guante",
        "cinturon", "correa", "media", "calcetin", "calcetine", "llavero",
        "collera", "anteojo", "lente", "botella", "termo", "bastone", "baston",
        "accesorio", "riñonera", "rinonera", "banano", "neceser", "estuche",
        "paraguas", "toalla", "manta", "saco de dormir", "carpa", "casco",
        # Tipos del diccionario de la app que no estaban cubiertos.
        "chullo", "pasamontana", "cuellera", "cooler", "funda para lata",
        "cuchilla", "maletin", "cantimplora", "silbato", "brujula", "linterna",
    )),
    (INFERIOR, (
        "pantalon", "short", "bermuda", "jogger", "falda", "legging", "calza",
        "buzo inferior", "pantaloneta", "capri", "jean", "cargo",
    )),
    (SUPERIOR, (
        "polo", "polera", "camisa", "camiseta", "casaca", "chaqueta", "chaleco",
        "abrigo", "sweater", "chompa", "poleron", "hoodie", "canguro superior",
        "cortavientos", "parka", "blusa", "top", "bividi", "musculosa", "vestido",
        "enterizo", "buzo", "primera capa", "polar", "hoody", "hoodie",
    )),
]

# La clase que ya trae el catalogo (Calzado / Vestuario / Accesorios) sirve de
# respaldo cuando el tipo de prenda no coincide con ningun termino.
FAMILIA_POR_CLASE = {
    "calzado": CALZADO,
    "accesorio": ACCESORIOS,
    "accesorios": ACCESORIOS,
}


def resolver_tipo(tipo_prenda):
    """El tipo pasa PRIMERO por el diccionario de la app.

    Devuelve (tipo_canonico, clase, aviso). Si el diccionario no lo conoce se
    acepta el tipo tal cual y se devuelve un aviso: no se descarta el producto
    ni se inventa un tipo. Asi la carga sale y la advertencia queda escrita.
    """
    texto = _texto(tipo_prenda)
    if not texto:
        return "", "", "el producto no trae tipo de prenda"
    try:
        from engines import garment_types
    except ImportError:
        return texto, "", ""
    canonico = garment_types.tipo_canonico(texto)
    if canonico:
        return canonico, garment_types.clase_de(texto), ""
    return texto, "", f'"{texto}" no está en el diccionario de tipos de prenda'


def detectar_familia(tipo_prenda="", clase="", categoria=""):
    """Devuelve (familia, motivo). familia vacia = no se pudo decidir.

    No adivina entre superior e inferior: si la clase dice "Vestuario" pero el
    tipo no coincide con ningun termino conocido, se devuelve vacio para que la
    carga lo marque como pendiente de revision.
    """
    for texto in (tipo_prenda, categoria):
        clave = normalizar(texto)
        if not clave:
            continue
        for familia, terminos in TERMINOS_FAMILIA:
            for termino in terminos:
                if re.search(rf"\b{re.escape(termino)}", clave):
                    return familia, f'"{_texto(texto)}" contiene "{termino}"'
    clave_clase = normalizar(clase)
    for nombre, familia in FAMILIA_POR_CLASE.items():
        if nombre in clave_clase:
            return familia, f'clase "{_texto(clase)}"'
    return "", (
        f'no se pudo deducir la familia de "{_texto(tipo_prenda) or _texto(clase)}"'
    )


# --- lectura de la plantilla ---------------------------------------------
_PLANTILLA = {}


def _leer_hoja(libro, nombre):
    """(columnas, {columna: [valores permitidos]}) de una hoja de la plantilla.

    Una columna repetida se queda con la aparicion que SI trae diccionario:
    en Calzado, "Forma de la punta" sale dos veces y la primera esta vacia.
    """
    hoja = libro[nombre]
    filas = list(hoja.iter_rows(values_only=True))
    if not filas:
        return [], {}
    cabeceras = [_texto(valor) for valor in filas[0]]
    columnas = []
    diccionarios = {}
    for indice, columna in enumerate(cabeceras):
        if not columna:
            continue
        valores = []
        for fila in filas[1:]:
            if indice >= len(fila):
                continue
            valor = _texto(fila[indice])
            if valor and valor not in valores:
                valores.append(valor)
        if columna in diccionarios:
            if valores and not diccionarios[columna]:
                diccionarios[columna] = valores
            continue
        columnas.append(columna)
        diccionarios[columna] = valores
    return columnas, diccionarios


def _leer_categorias(libro):
    """Tabla Marca|Tipo|Genero -> [categorias].

    Se guardan TODAS las categorias de una clave: 28 claves traen mas de una y
    la plantilla no dice cual manda. La eleccion se hace en resolver_categoria.
    """
    filas = list(libro[HOJA_CATEGORIAS].iter_rows(values_only=True))
    tabla = {}
    for fila in filas[1:]:
        if not fila or not _texto(fila[0]):
            continue
        marca, tipo, genero, categoria = (_texto(fila[indice]) if indice < len(fila) else "" for indice in range(4))
        if not categoria:
            continue
        clave = (normalizar(marca), _singular(tipo), normalizar(genero))
        tabla.setdefault(clave, [])
        if categoria not in tabla[clave]:
            tabla[clave].append(categoria)
    return tabla


def cargar_plantilla(ruta=None, recargar=False):
    """Lee la plantilla una sola vez y la deja en memoria."""
    global _PLANTILLA
    ruta = Path(ruta or RUTA_PLANTILLA)
    clave = str(ruta)
    if not recargar and _PLANTILLA.get("__clave__") == clave:
        return _PLANTILLA
    import openpyxl

    libro = openpyxl.load_workbook(ruta, read_only=True, data_only=True)
    # OJO: las filas de SIEMPRE son dos productos de EJEMPLO, no un diccionario
    # de valores permitidos. Tomarlas como diccionario rechazaria todo producto
    # real ("Casaca Lino Hombre..." no estaria "entre los valores permitidos").
    # Solo las cuatro hojas de tipo traen listas cerradas.
    siempre, ejemplos = _leer_hoja(libro, HOJA_SIEMPRE)
    datos = {
        "__clave__": clave,
        "siempre": siempre,
        "ejemplos": ejemplos,
        "diccionarios": {},
        "familias": {},
        "categorias": _leer_categorias(libro),
    }
    for familia, hoja in HOJA_POR_FAMILIA.items():
        columnas, diccionarios = _leer_hoja(libro, hoja)
        datos["familias"][familia] = columnas
        datos["diccionarios"].update(diccionarios)
    libro.close()
    _PLANTILLA = datos
    return datos


# Claves operativas que NO vienen en la plantilla de Centry pero la carga
# necesita para cruzar contra el maestro. Van siempre al final, en este orden.
COLUMNAS_CLAVE = ("COD MOD", "COD COL", "TALLA")
COLUMNA_ADVERTENCIA = "Advertencias"


def columnas_de(familia, ruta=None):
    """SIEMPRE + las de la familia + las claves + la advertencia, en ese orden.

    Con la familia sin determinar se devuelven solo las de SIEMPRE mas la cola:
    el producto igual sale, y la advertencia dice que le faltan los atributos
    de marketplace.
    """
    plantilla = cargar_plantilla(ruta)
    propias = plantilla["familias"].get(familia, [])
    cola = list(COLUMNAS_CLAVE) + [COLUMNA_ADVERTENCIA]
    return list(dict.fromkeys(plantilla["siempre"] + propias + cola))


def valores_permitidos(columna, ruta=None):
    """Diccionario de la columna. Lista vacia = texto libre, no se valida."""
    return list(cargar_plantilla(ruta)["diccionarios"].get(_texto(columna), []))


def valor_valido(columna, valor, ruta=None):
    """(valor_normalizado, ok). Empareja sin tildes ni mayusculas.

    Devuelve el valor tal y como lo escribe la plantilla, para que el archivo
    salga con la ortografia que Centry espera.
    """
    texto = _texto(valor)
    permitidos = valores_permitidos(columna, ruta)
    if not texto:
        return "", True
    if not permitidos:
        return texto, True
    for permitido in permitidos:
        if normalizar(permitido) == normalizar(texto):
            return permitido, True
    return texto, False


# --- categoria ------------------------------------------------------------
# Equivalencias de genero entre el catalogo y la plantilla.
GENEROS = {
    "hombre": "Hombre", "masculino": "Hombre", "varon": "Hombre", "caballero": "Hombre",
    "mujer": "Mujer", "femenino": "Mujer", "dama": "Mujer",
    "unisex": "Unisex Adultos", "unisex adultos": "Unisex Adultos",
    "unisex adulto": "Unisex Adultos", "adulto": "Unisex Adultos",
    "unisex ninos": "Unisex Niños", "unisex nino": "Unisex Niños",
    "nino": "Niños", "ninos": "Niños", "junior": "Niños",
    "nina": "Niñas", "ninas": "Niñas",
    "bebe": "Unisex Niños", "infantil": "Unisex Niños", "kids": "Unisex Niños",
}


def normalizar_genero(valor):
    """Devuelve el genero tal como lo escribe la plantilla, o "" si no se sabe."""
    clave = normalizar(valor)
    if not clave:
        return ""
    if clave in GENEROS:
        return GENEROS[clave]
    for nombre, salida in GENEROS.items():
        if re.search(rf"\b{re.escape(nombre)}\b", clave):
            return salida
    return ""


def _categoria_mas_general(opciones):
    """La de menos niveles. Entre "Botas" y "Botas / Botas de Invierno" gana la
    primera: es la que vale para cualquier producto de ese tipo."""
    return min(opciones, key=lambda texto: (texto.count("/"), len(texto)))


def resolver_categoria(marca="", tipo="", genero="", ruta=None):
    """(categoria, aviso). categoria vacia = no se encontro y queda pendiente.

    La marca concreta gana sobre "Todos". Si la clave trae varias categorias se
    elige la mas general y se avisa; si las opciones estan al mismo nivel (el
    caso de Guantes/Unisex Adultos, que duda entre Deporte Masculino y Femenino)
    no se elige ninguna: eso lo tiene que definir una persona.
    """
    plantilla = cargar_plantilla(ruta)
    tabla = plantilla["categorias"]
    genero_normalizado = normalizar_genero(genero)
    if not genero_normalizado:
        return "", f'genero "{_texto(genero)}" no reconocido'
    clave_tipo = _singular(tipo)
    if not clave_tipo:
        return "", "el producto no trae tipo de prenda"

    for marca_clave in (normalizar(marca), "todos"):
        if not marca_clave:
            continue
        opciones = tabla.get((marca_clave, clave_tipo, normalizar(genero_normalizado)))
        if not opciones:
            continue
        origen = "" if marca_clave != "todos" else " (regla Todos)"
        if len(opciones) == 1:
            return opciones[0], ""
        niveles = {texto.count("/") for texto in opciones}
        if len(niveles) == 1:
            # Mismo nivel: son alternativas de verdad, no general vs especifica.
            return "", (
                f'"{_texto(tipo)}" / {genero_normalizado} tiene {len(opciones)} categorias '
                f'igual de especificas en la plantilla: {" | ".join(opciones)}'
            )
        elegida = _categoria_mas_general(opciones)
        descartadas = [texto for texto in opciones if texto != elegida]
        return elegida, (
            f'se eligio la categoria general{origen}; revisar si corresponde '
            f'{" o ".join(descartadas)}'
        )
    return "", (
        f'no hay categoria para tipo "{_texto(tipo)}" y genero {genero_normalizado}'
    )


# --- construccion y validacion -------------------------------------------
# Campos de SIEMPRE sin los que Centry rechaza el producto.
OBLIGATORIAS = (
    "Nombre del Producto", "Marca", "Categoría", "SKU del producto",
    "SKU de la variante", "Color", "Talla", "URL imagen principal",
)

# Valores fijos que la plantilla trae con una sola opcion: no hay nada que
# elegir, se rellenan solos.
def _valores_fijos(familia, ruta=None):
    fijos = {}
    for columna in columnas_de(familia, ruta):
        permitidos = valores_permitidos(columna, ruta)
        if len(permitidos) == 1:
            fijos[columna] = permitidos[0]
    return fijos


def construir_producto(datos, marca="", tipo="", genero="", clase="", mod_col="", talla="", ruta=None):
    """Arma la fila Centry de un producto.

    Devuelve {"familia", "columnas", "fila", "pendientes"}.

    El producto SIEMPRE sale, aunque no se reconozca el tipo de prenda: en ese
    caso lleva las columnas de SIEMPRE y las claves, sin los atributos de
    marketplace, y la columna Advertencias explica que falta. Antes se devolvia
    vacio y el producto desaparecia del archivo.
    """
    pendientes = []
    familia, motivo = detectar_familia(tipo, clase, (datos or {}).get("Categoría", ""))
    if not familia:
        pendientes.append({
            "campo": "Familia",
            "problema": f"{motivo}; sale sin los atributos de Falabella/MercadoLibre",
        })

    columnas = columnas_de(familia, ruta)
    fila = {columna: "" for columna in columnas}
    if familia:
        fila.update(_valores_fijos(familia, ruta))

    for columna, valor in (datos or {}).items():
        if columna not in fila:
            continue
        limpio, ok = valor_valido(columna, valor, ruta)
        fila[columna] = limpio
        if not ok:
            pendientes.append({
                "campo": columna,
                "problema": f'"{_texto(valor)}" no está entre los valores permitidos',
                "permitidos": ", ".join(valores_permitidos(columna, ruta)[:8]),
            })

    if not _texto(fila.get("Categoría")):
        categoria, aviso = resolver_categoria(marca, tipo, genero, ruta)
        fila["Categoría"] = categoria
        if aviso:
            pendientes.append({"campo": "Categoría", "problema": aviso})

    genero_plantilla = normalizar_genero(genero)
    if genero_plantilla and not _texto(fila.get("Género")):
        fila["Género"] = genero_plantilla

    # Claves operativas: el modelo y el color salen del Mod-Col.
    modelo, color = _partir_mod_col(mod_col)
    fila["COD MOD"] = modelo
    fila["COD COL"] = color
    fila["TALLA"] = _texto(talla) or _texto(fila.get("Talla"))
    for columna in COLUMNAS_CLAVE:
        if not _texto(fila.get(columna)):
            pendientes.append({"campo": columna, "problema": "clave vacía; revisar el Mod-Col"})

    for columna in OBLIGATORIAS:
        if columna in fila and not _texto(fila[columna]):
            pendientes.append({"campo": columna, "problema": "obligatorio y está vacío"})

    fila[COLUMNA_ADVERTENCIA] = " | ".join(
        f'{p["campo"]}: {p["problema"]}' for p in pendientes
    )
    return {"familia": familia, "columnas": columnas, "fila": fila, "pendientes": pendientes}


def _partir_mod_col(mod_col):
    """"RK202011432-645" -> ("RK202011432", "645"). Sin guion, todo es modelo."""
    texto = _texto(mod_col).upper()
    if "-" not in texto:
        return texto, ""
    modelo, color = texto.rsplit("-", 1)
    return modelo.strip(), color.strip()


def validar_productos(productos, ruta=None):
    """Recorre una lista de productos ya construidos y junta sus pendientes.

    Cada producto es {"sku": ..., "resultado": <lo que devuelve construir_producto>}.
    Devuelve filas listas para la hoja de revision.
    """
    avisos = []
    for producto in productos or []:
        sku = _texto(producto.get("sku"))
        resultado = producto.get("resultado") or {}
        for pendiente in resultado.get("pendientes", []):
            avisos.append({
                "SKU": sku,
                "Familia": ETIQUETA_FAMILIA.get(resultado.get("familia"), "Sin determinar"),
                "Campo": pendiente.get("campo", ""),
                "Problema": pendiente.get("problema", ""),
                "Valores permitidos": pendiente.get("permitidos", ""),
            })
    return avisos


def resumen_plantilla(ruta=None):
    """Para diagnostico: cuantas columnas y diccionarios trae cada familia."""
    plantilla = cargar_plantilla(ruta)
    filas = [{
        "Hoja": HOJA_SIEMPRE,
        "Columnas": len(plantilla["siempre"]),
        "Con diccionario": sum(1 for c in plantilla["siempre"] if plantilla["diccionarios"].get(c)),
    }]
    for familia, columnas in plantilla["familias"].items():
        filas.append({
            "Hoja": HOJA_POR_FAMILIA[familia],
            "Columnas": len(columnas) + len(plantilla["siempre"]),
            "Con diccionario": sum(1 for c in columnas if plantilla["diccionarios"].get(c)),
        })
    filas.append({"Hoja": HOJA_CATEGORIAS, "Columnas": len(plantilla["categorias"]), "Con diccionario": ""})
    return filas
