"""Motor de la carga MANUAL a VTEX. Sin Streamlit y sin pandas.

Que resuelve
------------
La app trabaja con Shopify. VTEX no se toca por API: la carga se hace a mano,
subiendo cuatro planillas al admin. Este motor arma esas cuatro planillas a
partir de lo que la app ya sabe de cada Modelo-Color, y **sin inventar un solo
ID**.

El dato que hace todo esto posible es que la referencia de producto de VTEX ES
el Modelo-Color de la app:

    Mod-Col  HP102011307-251   ==   Product reference code  HP102011307-251

Por eso el cruce no necesita ninguna tabla de equivalencias: se busca el
Mod-Col tal cual en el catalogo maestro.

Por que el catalogo maestro es obligatorio
------------------------------------------
VTEX identifica por ID numerico, no por referencia. Un producto cargado con el
`Product ID` en blanco se CREA; uno con el ID puesto se ACTUALIZA. Si se
generan las planillas sin mirar el maestro, todo producto que ya existe se
vuelve a crear duplicado, con otra URL y otro ID, y el catalogo queda partido
en dos. El maestro es la unica fuente de verdad de los IDs que ya existen:

    referencia de producto -> Product ID
    referencia de SKU      -> SKU ID
    Product ID             -> sus SKUs (ID, referencia, nombre, talla)

Un ID que sale del maestro NUNCA se reemplaza. Lo que no esta en el maestro se
marca NUEVO y va con el ID en blanco, que es como VTEX pide una creacion.

Como se emparejan los SKUs
--------------------------
En esta tienda el `SKU reference code` es el propio `SKU ID` (verificado: en la
muestra coinciden en las 499 filas), asi que la referencia no sirve para
reconocer un SKU que todavia no se ha cargado. El emparejamiento real es por
**talla dentro del producto**: el maestro trae `SKU name` = "TALLA 39" y de ahi
sale la talla. Si el producto existe y ya tiene la talla, se reutiliza su SKU
ID; si no la tiene, es un SKU nuevo de un producto existente, que es el caso
mas comun al ampliar una curva.

Que NO hace este modulo
-----------------------
- No se conecta a VTEX. Ni para leer ni para escribir.
- No lee Excel: recibe FILAS ya leidas (listas de listas) y devuelve filas.
  Quien abre y guarda los archivos es la capa de pantalla, que es la que tiene
  pandas y openpyxl.
- No sabe de Shopify ni de BigQuery: recibe las entradas ya armadas.
"""

import re
import unicodedata

# --- Estructura EXACTA de las cuatro planillas ---------------------------
#
# Copiada de las exportaciones reales de supermallpe (septiembre 2026). El
# orden, los nombres y las tildes son los del archivo: VTEX empareja por
# cabecera, asi que cambiar una tilde rompe la carga entera. No se agregan
# columnas ni se quitan.
COLUMNAS_PRODUCTOS_Y_SKUS = (
    "Product ID",
    "Product Name",
    "Active product",
    "Description",
    "Additional description",
    "Brand ID",
    "Brand",
    "Department ID",
    "Department",
    "Category ID",
    "Category",
    "Sales channels",
    "Global category ID",
    "Global category",
    "Product URL",
    "Page Title",
    "Meta description",
    "Display on website",
    "Show when out of stock",
    "Release date",
    "Substitute words",
    "Product reference code",
    "Tax code",
    "SKU ID",
    "SKU name",
    "Activate SKU if possible",
    "Active SKU",
    "Bundle",
    "SKU reference code",
    "EAN/UPC",
    "Manufacturer code",
    "Package weight",
    "Package width",
    "Package height",
    "Package length",
    "Actual weight",
    "Actual width",
    "Actual height",
    "Actual length",
    "Cubic Weight",
    "Unit of measure",
    "Unit multiplier",
    "Commercial condition",
    "Loyalty amount",
    "Presale date",
    "Attachments",
    "Accessories",
    "Suggestions",
    "Similar products",
    "Show together",
)

# La planilla mezcla dos niveles en una sola fila: las primeras 23 columnas son
# del PRODUCTO y se repiten en cada uno de sus SKUs; el resto es del SKU. El
# corte esta en "SKU ID". Guardar el maestro partido en dos evita repetir 23
# textos largos (descripcion, meta description) por cada talla: un catalogo de
# 300.000 SKUs no cabe en memoria de otra forma.
CORTE_NIVEL_SKU = COLUMNAS_PRODUCTOS_Y_SKUS.index("SKU ID")
COLUMNAS_NIVEL_PRODUCTO = COLUMNAS_PRODUCTOS_Y_SKUS[:CORTE_NIVEL_SKU]
COLUMNAS_NIVEL_SKU = COLUMNAS_PRODUCTOS_Y_SKUS[CORTE_NIVEL_SKU:]

COLUMNAS_ESPECIFICACIONES_PRODUCTO = (
    "ID del producto",
    "Nombre del producto",
    "Código de referencia del producto",
    "ID de marca",
    "Marca",
    "ID del departamento",
    "Departamento",
    "ID de categoría",
    "Categoría",
    "ID de campo",
    "Nombre del campo",
    "Tipo de campo",
    "IDs de valores de campo",
    "Valores de campo",
    "IDs de especificación",
    "Valores de especificación",
)

COLUMNAS_ESPECIFICACIONES_SKU = (
    "ID de SKU",
    "Nombre de SKU",
    "Código de referencia de SKU",
    "ID de marca",
    "Marca",
    "ID del departamento",
    "Departamento",
    "ID de categoría",
    "Categoría",
    "ID de campo",
    "Nombre del campo",
    "Tipo de campo",
    "IDs de valores de campo",
    "Valores de campo",
    "IDs de especificación",
    "Valores de especificación",
)

COLUMNAS_IMAGENES = (
    "ID del producto",
    "Nombre del producto",
    "ID de SKU",
    "Nombre de SKU",
    "Código de referencia de SKU",
    "ID de la imagen",
    "Nombre de la imagen",
    "Posición de la imagen",
    "Label de la imagen",
    "Texto de la imagen",
    "Ruta de la imagen",
    "URL de importación de la imagen",
)

# Los cuatro archivos del ZIP, en el orden en que se cargan en VTEX: primero
# productos y SKUs (crea los IDs), despues lo que cuelga de ellos.
ARCHIVO_PRODUCTOS = "Products_and_SKUs"
ARCHIVO_ESPEC_PRODUCTO = "Product_Specifications"
ARCHIVO_ESPEC_SKU = "SKU_Specifications"
ARCHIVO_IMAGENES = "Images"

COLUMNAS_POR_ARCHIVO = {
    ARCHIVO_PRODUCTOS: COLUMNAS_PRODUCTOS_Y_SKUS,
    ARCHIVO_ESPEC_PRODUCTO: COLUMNAS_ESPECIFICACIONES_PRODUCTO,
    ARCHIVO_ESPEC_SKU: COLUMNAS_ESPECIFICACIONES_SKU,
    ARCHIVO_IMAGENES: COLUMNAS_IMAGENES,
}

ORDEN_ARCHIVOS = (
    ARCHIVO_PRODUCTOS,
    ARCHIVO_ESPEC_PRODUCTO,
    ARCHIVO_ESPEC_SKU,
    ARCHIVO_IMAGENES,
)

# En las exportaciones de VTEX la primera fila de la hoja va vacia y la
# cabecera esta en la SEGUNDA. Se conserva al escribir para que el archivo
# generado se vea igual que el que el usuario descarga del admin.
FILAS_VACIAS_ANTES_DE_CABECERA = 1

# Cuantas filas se miran buscando la cabecera al leer un archivo del usuario.
# No se asume la fila 2: si alguien guarda la hoja sin la fila en blanco, o le
# agrega un titulo, el archivo tiene que seguir leyendose.
MAXIMO_FILAS_PARA_CABECERA = 25

# Peso volumetrico = ancho * alto * largo / 4800. Verificado contra la
# exportacion real: coincide en 495 de las 495 filas con medidas.
DIVISOR_PESO_CUBICO = 4800


# --- Texto ---------------------------------------------------------------

def texto(valor):
    """Todo valor se trata como texto. Los IDs de VTEX son numeros que NO se
    pueden operar: 0310669 y 310669 son referencias distintas."""
    if valor is None:
        return ""
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, float):
        # Excel devuelve 310669.0 para una celda numerica. Ese ".0" convierte
        # una referencia valida en una que no empareja con nada.
        if valor == int(valor):
            return str(int(valor))
        return repr(valor).strip()
    return str(valor).strip()


def sin_tildes(valor):
    base = unicodedata.normalize("NFKD", texto(valor))
    return "".join(caracter for caracter in base if not unicodedata.combining(caracter))


def normalizar(valor):
    """Para comparar nombres de campo, categorias y marcas."""
    return re.sub(r"\s+", " ", sin_tildes(valor).lower()).strip()


def normalizar_encabezado(valor):
    return re.sub(r"[^a-z0-9]+", "", sin_tildes(valor).lower())


def slug(valor):
    base = sin_tildes(valor).lower()
    base = re.sub(r"[^a-z0-9]+", "-", base)
    return re.sub(r"-{2,}", "-", base).strip("-")


def normalizar_referencia(valor):
    """La llave de cruce. Mayusculas y sin espacios, nada mas.

    No se le quitan guiones ni ceros: `HP102011307-251` y `HP102011307251` son
    referencias distintas para VTEX y confundirlas apuntaria a otro producto.
    """
    return re.sub(r"\s+", "", texto(valor)).upper()


_PREFIJO_TALLA = re.compile(r"^(talla|size|t)\b[\s.:-]*", re.IGNORECASE)


def normalizar_talla(valor):
    """"TALLA 39" -> "39". "Talla ST" -> "ST". "10,5" -> "10.5".

    El maestro guarda la talla dentro del nombre del SKU, asi que sin esto no
    hay forma de saber si la talla que se quiere cargar ya existe.
    """
    base = texto(valor)
    if not base:
        return ""
    base = _PREFIJO_TALLA.sub("", base).strip()
    base = base.replace(",", ".")
    if re.fullmatch(r"\d+\.0+", base):
        base = base.split(".")[0]
    return base.upper()


def nombre_de_sku(talla):
    """El nombre con el que VTEX muestra la talla. La forma dominante en el
    maestro real es "TALLA 39" (437 de 496 filas)."""
    talla = normalizar_talla(talla)
    return f"TALLA {talla}".strip() if talla else ""


def peso_cubico(ancho, alto, largo):
    try:
        valor = float(texto(ancho) or 0) * float(texto(alto) or 0) * float(texto(largo) or 0)
    except ValueError:
        return ""
    if valor <= 0:
        return ""
    return f"{valor / DIVISOR_PESO_CUBICO:.4f}".rstrip("0").rstrip(".")


# --- Lectura de las planillas del usuario --------------------------------

def detectar_fila_encabezado(filas, columnas_esperadas):
    """Indice de la fila que trae la cabecera, o -1.

    Se busca en vez de asumirla: la exportacion deja la fila 1 vacia, pero un
    archivo reguardado a mano puede no tenerla y con un indice fijo se leeria
    la cabecera como si fuera un dato.
    """
    buscadas = {normalizar_encabezado(columna) for columna in columnas_esperadas}
    mejor_indice = -1
    mejor_puntaje = 0
    for indice, fila in enumerate(filas[:MAXIMO_FILAS_PARA_CABECERA]):
        presentes = {normalizar_encabezado(celda) for celda in fila if texto(celda)}
        puntaje = len(presentes & buscadas)
        if puntaje > mejor_puntaje:
            mejor_indice, mejor_puntaje = indice, puntaje
    # Con menos de tres columnas reconocidas no es la cabecera: es una fila de
    # datos que casualmente coincidio en algo.
    return mejor_indice if mejor_puntaje >= 3 else -1


def registros_en_streaming(filas, columnas_esperadas, reporte=None,
                           columnas_previas=(), decidir=None):
    """Genera los registros UNO A UNO, sin materializar el archivo.

    Por que existe
    --------------
    La primera version hacia `list(filas)` antes de indexar. Medido con 60.000
    filas -una quinta parte de un maestro real- esa lista sola son 242 MB, y el
    indice encima otros 222 MB. Extrapolado a 300.000 filas pasa de 2 GB, en un
    contenedor de 1 GB: la app se muere sin decir nada.

    Aqui no se guarda ninguna fila. `filas` puede ser un generador que lee del
    disco, y lo que sale es un dict por fila que el llamador usa y suelta.

    `reporte` es un dict opcional donde se dejan las columnas encontradas, las
    que faltan y cuantas filas se leyeron: un generador no puede devolver eso
    aparte, y sin ese dato no se puede avisar de un archivo con la cabecera mal.

    `decidir(previa)` es el segundo ahorro, y es el que manda en el tiempo.
    Recibe un dict con SOLO `columnas_previas` -tres o nueve celdas- y dice si
    hace falta armar el registro completo. De 300.000 filas interesan las 5.000
    del pedido: armar las otras 295.000 con sus 50 columnas eran 15 millones de
    conversiones de celda para tirarlas acto seguido. Medido: 73 s contra 4 s
    de recorrer el archivo.
    """
    reporte = reporte if reporte is not None else {}
    reporte.update({"columnas": [], "faltantes": list(columnas_esperadas), "leidos": 0})
    iterador = iter(filas or ())
    # Solo se retienen las primeras filas, las que puede ocupar la cabecera.
    cabeza = []
    for fila in iterador:
        cabeza.append(list(fila))
        if len(cabeza) >= MAXIMO_FILAS_PARA_CABECERA:
            break
    indice = detectar_fila_encabezado(cabeza, columnas_esperadas)
    if indice < 0:
        return
    cabecera = [texto(celda) for celda in cabeza[indice]]
    posicion = {}
    for columna in columnas_esperadas:
        clave = normalizar_encabezado(columna)
        for numero, celda in enumerate(cabecera):
            if normalizar_encabezado(celda) == clave:
                posicion[columna] = numero
                break
    reporte["columnas"] = [columna for columna in columnas_esperadas if columna in posicion]
    reporte["faltantes"] = [columna for columna in columnas_esperadas if columna not in posicion]
    firma_cabecera = {normalizar_encabezado(celda) for celda in cabecera if texto(celda)}
    # La primera columna reconocida basta para sospechar de una cabecera
    # repetida. Normalizar las 50 celdas de cada fila para compararla entera
    # costaba mas que todo lo demas junto.
    primera_columna = next(iter(posicion.values()), 0)
    marca_de_cabecera = normalizar_encabezado(cabecera[primera_columna]) if cabecera else ""
    previas = [(columna, posicion[columna]) for columna in columnas_previas if columna in posicion]
    pares = list(posicion.items())
    leidos = 0
    import itertools
    for fila in itertools.chain(cabeza[indice + 1:], iterador):
        if not any(fila):
            continue
        largo = len(fila)
        if marca_de_cabecera and primera_columna < largo and \
                normalizar_encabezado(fila[primera_columna]) == marca_de_cabecera and \
                {normalizar_encabezado(celda) for celda in fila if texto(celda)} == firma_cabecera:
            # VTEX parte los archivos grandes en varias hojas y REPITE la
            # cabecera en cada una. Pegadas una detras de otra, esa segunda
            # cabecera entraria como un producto llamado "Product ID".
            continue
        leidos += 1
        if decidir is not None:
            previa = {columna: (texto(fila[numero]) if numero < largo else "")
                      for columna, numero in previas}
            if not decidir(previa):
                continue
        registro = {}
        for columna, numero in pares:
            registro[columna] = texto(fila[numero]) if numero < largo else ""
        yield registro
    reporte["leidos"] = leidos


def registros_desde_filas(filas, columnas_esperadas):
    """(registros, columnas_encontradas, faltantes), todo en memoria.

    Es la version comoda, para archivos chicos y para las pruebas. Los maestros
    grandes NO pasan por aqui: usan `registros_en_streaming`.
    """
    reporte = {}
    registros = list(registros_en_streaming(filas, columnas_esperadas, reporte))
    return registros, reporte["columnas"], reporte["faltantes"]


def separar_lista(valor):
    """"625,626,627" -> ["625", "626", "627"].

    El maestro deja una coma final en varias filas ("...,654,"), asi que los
    vacios se descartan en vez de convertirse en un valor vacio del campo.
    """
    return [parte.strip() for parte in texto(valor).split(",") if parte.strip()]


# --- Catalogo maestro ----------------------------------------------------

def campo_desde_registro(registro):
    """Un campo de la tienda a partir de una fila de la exportacion.

    Cada fila REPITE la lista completa de valores admitidos del campo con sus
    IDs, no solo el valor que usa ese producto. Por eso con una fila cualquiera
    ya se tiene el campo entero, y por eso el diccionario se puede guardar.
    """
    campo = {
        "ID de campo": texto(registro.get("ID de campo")),
        "Nombre del campo": texto(registro.get("Nombre del campo")),
        "Tipo de campo": texto(registro.get("Tipo de campo")),
        "IDs de valores de campo": texto(registro.get("IDs de valores de campo")),
        "Valores de campo": texto(registro.get("Valores de campo")),
        "valores": {},
        "categorias": set(),
    }
    ids_valores = separar_lista(campo["IDs de valores de campo"])
    textos_valores = separar_lista(campo["Valores de campo"])
    for valor_id, valor_texto in zip(ids_valores, textos_valores):
        campo["valores"].setdefault(normalizar(valor_texto), (valor_id, valor_texto))
    for categoria in registro.get("categorias") or []:
        if isinstance(categoria, (list, tuple)) and len(categoria) == 2:
            campo["categorias"].add((normalizar(categoria[0]), normalizar(categoria[1])))
    if "Departamento" in registro or "Categoría" in registro:
        campo["categorias"].add((
            normalizar(registro.get("Departamento")),
            normalizar(registro.get("Categoría")),
        ))
    return campo


def _campo_a_registro(campo):
    return {
        "ID de campo": campo["ID de campo"],
        "Nombre del campo": campo["Nombre del campo"],
        "Tipo de campo": campo["Tipo de campo"],
        "IDs de valores de campo": campo["IDs de valores de campo"],
        "Valores de campo": campo["Valores de campo"],
        "categorias": sorted(campo["categorias"]),
    }


def diccionario_de(maestro):
    """El diccionario de la tienda, listo para guardar como JSON.

    Que campos tiene cada categoria y que valores admite cada Radio o CheckBox,
    con sus IDs. Se guarda aparte del catalogo porque son dos cosas que cambian
    a ritmos MUY distintos: el catalogo cambia con cada carga (IDs nuevos), y el
    diccionario solo cuando alguien crea un campo o un valor en el admin de
    VTEX. Obligar a subir las dos exportaciones de especificaciones cada vez es
    pedir 90 MB para leer algo que no se movio en meses.
    """
    return {
        "campos_producto": [_campo_a_registro(campo) for campo in maestro.campos_producto.values()],
        "campos_sku": [_campo_a_registro(campo) for campo in maestro.campos_sku.values()],
    }


def aplicar_diccionario(maestro, datos):
    """Carga un diccionario guardado sobre el maestro. Devuelve el maestro.

    Lo que venga del archivo de especificaciones subido en esta sesion MANDA:
    un campo ya cargado no se pisa. Si no, actualizar el diccionario desde la
    pantalla no serviria de nada, porque el guardado lo volveria a tapar.
    """
    for clave, campos in (("campos_producto", maestro.campos_producto),
                          ("campos_sku", maestro.campos_sku)):
        for registro in (datos or {}).get(clave) or []:
            campo_id = texto(registro.get("ID de campo"))
            if campo_id and campo_id not in campos:
                campos[campo_id] = campo_desde_registro(registro)
    return maestro


class CatalogoMaestroVTEX:
    """El ultimo catalogo de VTEX, leido y ordenado para consultarlo.

    Se arma con las filas de la exportacion "Products and SKUs" (obligatoria) y,
    opcionalmente, con las de especificaciones de producto, de SKU e imagenes.
    Las tres opcionales no aportan IDs de producto: aportan el DICCIONARIO de
    campos de la tienda (que campos tiene cada categoria, que valores admite un
    Radio y con que ID) y las imagenes ya cargadas.
    """

    def __init__(self):
        self.productos_por_referencia = {}
        self.productos_por_id = {}
        self.referencias_duplicadas = {}
        self.skus_por_referencia = {}
        self.skus_por_id = {}
        self.skus_por_producto = {}
        self.categorias = []
        self.marcas = {}
        self.campos_producto = {}
        self.campos_sku = {}
        self.especificaciones_producto = {}
        self.especificaciones_sku = {}
        self.imagenes_por_sku = {}
        self.faltantes = {}
        self.leidos = {}
        self.referencias_de_interes = None
        self.total_productos = 0
        self.total_skus = 0
        self._conteo_configuracion = {}
        self._medidas_por_categoria = {}
        self._medidas_de_la_tienda = {}

    # -- construccion ------------------------------------------------------
    @classmethod
    def desde_filas(cls, filas_productos, filas_especificaciones_producto=None,
                    filas_especificaciones_sku=None, filas_imagenes=None,
                    referencias=None):
        """Indexa el maestro. `referencias` acota lo que se GUARDA.

        Con `referencias` (los Mod-Col que se van a cargar) solo se conservan
        las filas de esos productos. Del resto se cuentan totales y se aprenden
        marcas, categorias y valores por defecto, que son diccionarios chicos.

        Sin `referencias` se guarda todo, que es lo que quieren las pruebas y
        los archivos chicos. En un maestro real eso son gigas: la pantalla
        SIEMPRE pasa las referencias.
        """
        maestro = cls()
        maestro.referencias_de_interes = (
            {normalizar_referencia(referencia) for referencia in referencias}
            if referencias is not None else None
        )
        maestro._cargar_productos(filas_productos)
        maestro._cargar_especificaciones(
            filas_especificaciones_producto,
            COLUMNAS_ESPECIFICACIONES_PRODUCTO,
            "ID del producto",
            maestro.campos_producto,
            maestro.especificaciones_producto,
            "especificaciones_producto",
        )
        maestro._cargar_especificaciones(
            filas_especificaciones_sku,
            COLUMNAS_ESPECIFICACIONES_SKU,
            "ID de SKU",
            maestro.campos_sku,
            maestro.especificaciones_sku,
            "especificaciones_sku",
        )
        maestro._cargar_imagenes(filas_imagenes)
        return maestro

    # Columnas cuyo valor por defecto se aprende de la tienda en vez de
    # escribirlo en el codigo ("Padrão" es de esta cuenta, no una constante).
    # Se cuentan al vuelo: derivarlas despues de los productos guardados
    # obligaria a guardarlos todos.
    COLUMNAS_DE_CONFIGURACION = (
        "Sales channels", "Unit of measure", "Unit multiplier", "Commercial condition",
        "Loyalty amount", "Show when out of stock", "Display on website", "Active product",
        "Bundle", "Activate SKU if possible", "Active SKU", "Global category ID",
        "Global category",
    )
    # Tope de valores distintos por columna de configuracion. Una columna que
    # resulte no ser de configuracion (un ID, una fecha) tendria un valor
    # distinto por fila y el contador creceria como el catalogo.
    MAXIMO_VALORES_DE_CONFIGURACION = 50

    def _interesa(self, referencia):
        if self.referencias_de_interes is None:
            return True
        return referencia in self.referencias_de_interes

    def _contar_configuracion(self, registro):
        for columna in self.COLUMNAS_DE_CONFIGURACION:
            valor = texto(registro.get(columna))
            if not valor:
                continue
            conteo = self._conteo_configuracion.setdefault(columna, {})
            if valor in conteo:
                conteo[valor] += 1
            elif len(conteo) < self.MAXIMO_VALORES_DE_CONFIGURACION:
                conteo[valor] = 1

    # Celdas que bastan para decidir si una fila interesa. Nueve de cincuenta:
    # con estas se cuentan totales, marcas y categorias de TODA la tienda sin
    # armar el registro completo de cada fila.
    COLUMNAS_PREVIAS = (
        "Product ID", "Product reference code", "SKU ID",
        "Brand ID", "Brand", "Department ID", "Department", "Category ID", "Category",
        # Las medidas van aqui para poder aprender las de CADA CATEGORIA sin
        # armar el registro completo de las 300.000 filas. Un SKU sin peso no
        # se puede despachar, asi que hace falta un respaldo real.
        "Package weight", "Package width", "Package height", "Package length",
    )
    # Tope de combinaciones de medidas por categoria. Sin tope, una categoria
    # con medidas distintas en cada producto haria crecer el contador como el
    # catalogo.
    MAXIMO_MEDIDAS_POR_CATEGORIA = 200
    # De cuantos productos se aprenden los valores por defecto. La moda de
    # "Commercial condition" no necesita 30.000 muestras, y cada muestra cuesta
    # armar el registro entero.
    MUESTRA_DE_CONFIGURACION = 2000

    def _contar_medidas(self, previa):
        """Aprende las medidas que la tienda ya usa, por categoria.

        Un SKU nuevo de una categoria conocida se despacha como sus vecinos.
        Es el ultimo respaldo antes de dejar el peso vacio, que es lo que no
        puede pasar: VTEX no cotiza el envio de un SKU sin peso.
        """
        medidas = (
            texto(previa.get("Package weight")), texto(previa.get("Package width")),
            texto(previa.get("Package height")), texto(previa.get("Package length")),
        )
        if not medidas[0]:
            return
        clave = (texto(previa.get("Department ID")), texto(previa.get("Category ID")))
        for destino, llave in ((self._medidas_por_categoria, clave),
                               (self._medidas_de_la_tienda, "")):
            conteo = destino.setdefault(llave, {})
            if medidas in conteo:
                conteo[medidas] += 1
            elif len(conteo) < self.MAXIMO_MEDIDAS_POR_CATEGORIA:
                conteo[medidas] = 1

    def medidas_de_categoria(self, departamento_id="", categoria_id=""):
        """{weight, width, height, length} de lo que mas se repite en esa
        categoria; si la categoria no tiene, lo de la tienda; si no, vacios."""
        for destino, llave in ((self._medidas_por_categoria,
                                (texto(departamento_id), texto(categoria_id))),
                               (self._medidas_de_la_tienda, "")):
            conteo = destino.get(llave) or {}
            if conteo:
                peso, ancho, alto, largo = max(conteo.items(), key=lambda item: item[1])[0]
                return {"weight": peso, "width": ancho, "height": alto, "length": largo}
        return {"weight": "", "width": "", "height": "", "length": ""}

    def _cargar_productos(self, filas):
        reporte = {}
        categorias = {}
        vistos_producto = set()
        vistos_sku = set()
        estado = {"muestras": 0}

        def decidir(previa):
            """Se ejecuta con 9 celdas por fila. Aqui se cuenta la tienda entera
            y se decide si hace falta el registro completo."""
            producto_id = previa.get("Product ID", "")
            referencia = normalizar_referencia(previa.get("Product reference code"))
            nuevo_producto = bool(producto_id) and producto_id not in vistos_producto
            if nuevo_producto:
                vistos_producto.add(producto_id)
                self.total_productos += 1
                marca = previa.get("Brand", "")
                if marca:
                    self.marcas.setdefault(normalizar(marca), {
                        "Brand ID": previa.get("Brand ID", ""), "Brand": marca})
                clave = (previa.get("Department ID", ""), previa.get("Category ID", ""))
                if clave not in categorias and any(clave):
                    categorias[clave] = {
                        "Department ID": clave[0], "Department": previa.get("Department", ""),
                        "Category ID": clave[1], "Category": previa.get("Category", ""),
                    }
            sku_id = previa.get("SKU ID", "")
            if sku_id and sku_id not in vistos_sku:
                vistos_sku.add(sku_id)
                self.total_skus += 1
                self._contar_medidas(previa)
            if self._interesa(referencia):
                return True
            # Una muestra de filas ajenas, solo para los valores por defecto.
            if nuevo_producto and estado["muestras"] < self.MUESTRA_DE_CONFIGURACION:
                estado["muestras"] += 1
                return True
            return False

        for registro in registros_en_streaming(
                filas, COLUMNAS_PRODUCTOS_Y_SKUS, reporte,
                columnas_previas=self.COLUMNAS_PREVIAS, decidir=decidir):
            self._contar_configuracion(registro)
            producto_id = texto(registro.get("Product ID"))
            referencia = normalizar_referencia(registro.get("Product reference code"))
            if not self._interesa(referencia):
                continue  # era solo una muestra para los valores por defecto
            if producto_id and producto_id not in self.productos_por_id:
                datos = {columna: registro.get(columna, "") for columna in COLUMNAS_NIVEL_PRODUCTO}
                datos["_referencia"] = referencia
                self.productos_por_id[producto_id] = datos
                if referencia:
                    if referencia in self.productos_por_referencia:
                        anterior = self.productos_por_referencia[referencia]["Product ID"]
                        if anterior != producto_id:
                            self.referencias_duplicadas.setdefault(referencia, [anterior]).append(producto_id)
                    else:
                        self.productos_por_referencia[referencia] = datos
            sku_id = texto(registro.get("SKU ID"))
            if not sku_id or sku_id in self.skus_por_id:
                continue
            sku = {columna: registro.get(columna, "") for columna in COLUMNAS_NIVEL_SKU}
            sku["_producto_id"] = producto_id
            sku["_referencia_producto"] = referencia
            sku["_talla"] = normalizar_talla(registro.get("SKU name"))
            self.skus_por_id[sku_id] = sku
            referencia_sku = normalizar_referencia(registro.get("SKU reference code"))
            if referencia_sku:
                self.skus_por_referencia.setdefault(referencia_sku, sku)
            self.skus_por_producto.setdefault(producto_id, []).append(sku)
        self.faltantes["productos"] = reporte.get("faltantes") or []
        self.leidos["productos"] = reporte.get("leidos") or 0
        self.categorias = sorted(
            categorias.values(),
            key=lambda item: (normalizar(item["Department"]), normalizar(item["Category"])),
        )

    def _cargar_especificaciones(self, filas, columnas, columna_id, campos, asignados, etiqueta):
        if not filas:
            return
        registros, _, faltantes = registros_desde_filas(filas, columnas)
        self.faltantes[etiqueta] = faltantes
        self.leidos[etiqueta] = len(registros)
        for registro in registros:
            campo_id = texto(registro.get("ID de campo"))
            nombre = texto(registro.get("Nombre del campo"))
            if not campo_id or not nombre:
                continue
            campo = campos.get(campo_id)
            if campo is None:
                campo = campo_desde_registro(registro)
                campos[campo_id] = campo
            campo["categorias"].add((
                normalizar(registro.get("Departamento")),
                normalizar(registro.get("Categoría")),
            ))
            duenio = texto(registro.get(columna_id))
            valor = texto(registro.get("Valores de especificación"))
            if duenio and valor:
                asignados.setdefault(duenio, {})[campo_id] = {
                    "IDs de especificación": texto(registro.get("IDs de especificación")),
                    "Valores de especificación": valor,
                }

    def _cargar_imagenes(self, filas):
        if not filas:
            return
        registros, _, faltantes = registros_desde_filas(filas, COLUMNAS_IMAGENES)
        self.faltantes["imagenes"] = faltantes
        self.leidos["imagenes"] = len(registros)
        for registro in registros:
            sku_id = texto(registro.get("ID de SKU"))
            if not sku_id:
                continue
            self.imagenes_por_sku.setdefault(sku_id, []).append(registro)

    # -- consultas ---------------------------------------------------------
    @property
    def vacio(self):
        return not self.total_productos

    def producto(self, referencia):
        return self.productos_por_referencia.get(normalizar_referencia(referencia))

    def sku_por_referencia(self, referencia):
        return self.skus_por_referencia.get(normalizar_referencia(referencia))

    def skus_de_producto(self, producto_id):
        return list(self.skus_por_producto.get(texto(producto_id), []))

    def sku_por_talla(self, producto_id, talla):
        talla = normalizar_talla(talla)
        if not talla:
            return None
        for sku in self.skus_de_producto(producto_id):
            if sku.get("_talla") == talla:
                return sku
        return None

    def marca(self, nombre):
        return self.marcas.get(normalizar(nombre))

    def categoria(self, departamento="", categoria=""):
        """La categoria del maestro que corresponde a estos nombres.

        Primero departamento + categoria; si solo viene la categoria, la
        primera que calce por nombre. Nunca se inventa un ID: si el nombre no
        esta en el maestro se devuelve None y el producto queda bloqueado.
        """
        departamento_normalizado = normalizar(departamento)
        categoria_normalizada = normalizar(categoria)
        if not categoria_normalizada and not departamento_normalizado:
            return None
        intentos = [(departamento_normalizado, categoria_normalizada)]
        if departamento_normalizado and categoria_normalizada:
            # El departamento es una suposicion (sale del genero); la categoria
            # es el dato. Una "Camisa" de Niños que en VTEX vive en Hombre
            # tiene que encontrarse igual, no quedarse sin ID.
            intentos.append(("", categoria_normalizada))
        for esperado_departamento, esperada_categoria in intentos:
            for item in self.categorias:
                if esperada_categoria and normalizar(item["Category"]) != esperada_categoria:
                    continue
                if esperado_departamento and normalizar(item["Department"]) != esperado_departamento:
                    continue
                return item
        return None

    def campos_de_categoria(self, campos, departamento, categoria):
        """Los campos que la tienda tiene definidos para esa categoria.

        Si el diccionario no trae esa categoria (porque la exportacion de
        especificaciones es una muestra, o porque la categoria es nueva) se
        devuelven todos: es preferible proponer un campo de mas, que se ve en
        la vista previa, a callar uno que el producto necesita.
        """
        clave = (normalizar(departamento), normalizar(categoria))
        propios = [campo for campo in campos.values() if clave in campo["categorias"]]
        return propios or list(campos.values())

    def campo_por_nombre(self, campos, nombre, departamento="", categoria=""):
        objetivo = normalizar(nombre)
        candidatos = self.campos_de_categoria(campos, departamento, categoria)
        for campo in candidatos:
            if normalizar(campo["Nombre del campo"]) == objetivo:
                return campo
        return None

    def valor_de_campo(self, campo, valor):
        """(id_valor, texto_valor) para un campo de lista. ("", valor) si el
        campo es de texto libre, (None, valor) si el valor no esta en la lista.

        La diferencia importa: un Radio con un valor que no existe en la tienda
        no se carga, y ese es justo el error que hay que avisar antes de bajar
        el archivo, no despues de subirlo.
        """
        valor = texto(valor)
        if not campo or not valor:
            return "", valor
        if not campo["valores"]:
            return "", valor
        encontrado = campo["valores"].get(normalizar(valor))
        if encontrado:
            return encontrado
        return None, valor

    def valor_por_defecto(self, columna, respaldo=""):
        """El valor mas repetido del maestro para una columna de configuracion.

        Sales channels, Unit of measure o Commercial condition dependen de la
        tienda: "Padrão" en una, "Padrao" o "Estandar" en otra. Se copia lo que
        la tienda ya usa en vez de dejarlo escrito en el codigo.

        Sale de un contador que se llena al leer, no de recorrer los productos
        guardados: cuando el maestro se lee acotado a unos pocos codigos, esos
        productos no son una muestra de la tienda.
        """
        conteo = self._conteo_configuracion.get(columna) or {}
        if not conteo:
            return respaldo
        return max(conteo.items(), key=lambda item: item[1])[0]

    def resumen(self):
        return {
            "Productos en el maestro": self.total_productos,
            "SKUs en el maestro": self.total_skus,
            "Marcas": len(self.marcas),
            "Categorias": len(self.categorias),
            "Campos de producto": len(self.campos_producto),
            "Campos de SKU": len(self.campos_sku),
            "SKUs con imagenes": len(self.imagenes_por_sku),
            "Referencias duplicadas": len(self.referencias_duplicadas),
        }


# --- Alertas -------------------------------------------------------------
#
# Cada alerta dice si BLOQUEA la generacion o solo avisa. Un bloqueo es algo
# que dejaria el catalogo de VTEX mal: un producto sin categoria no se puede
# crear, y una referencia repetida apuntaria a dos IDs distintos. Un aviso es
# algo que conviene mirar pero no rompe nada.
NIVEL_ERROR = "ERROR"
NIVEL_AVISO = "WARNING"

ALERTAS = {
    "codigo_no_encontrado": (NIVEL_ERROR, "Código no encontrado"),
    "producto_sin_categoria": (NIVEL_ERROR, "Producto sin categoría VTEX"),
    "producto_sin_marca": (NIVEL_ERROR, "Producto sin marca VTEX"),
    "producto_sin_nombre": (NIVEL_ERROR, "Producto sin nombre"),
    "sin_tallas": (NIVEL_ERROR, "SKU no encontrado"),
    "referencia_duplicada": (NIVEL_ERROR, "Referencia duplicada en el maestro"),
    "codigo_duplicado": (NIVEL_AVISO, "Código duplicado en la selección"),
    "producto_sin_id": (NIVEL_AVISO, "Producto sin ID VTEX (se crea)"),
    "sku_sin_id": (NIVEL_AVISO, "SKU sin ID VTEX (se crea)"),
    "imagen_faltante": (NIVEL_AVISO, "Imagen faltante"),
    "producto_inconsistente": (NIVEL_AVISO, "Producto existente con información inconsistente"),
    "sku_inconsistente": (NIVEL_AVISO, "SKU existente con información inconsistente"),
    "valor_fuera_de_lista": (NIVEL_AVISO, "Valor que no existe en la lista de la tienda"),
    "referencia_sku_repetida": (NIVEL_ERROR, "Referencia de SKU repetida en la carga"),
    "sku_sin_peso": (NIVEL_ERROR, "SKU sin peso ni medidas"),
    "nada_cruzo_con_el_maestro": (NIVEL_ERROR, "Ningún código se encontró en el catálogo maestro"),
}

# Con menos codigos que esto, que ninguno cruce contra el maestro es
# perfectamente normal y no se sospecha nada.
MINIMO_PARA_SOSPECHAR_DESAJUSTE = 5

ESTADO_EXISTENTE = "EXISTENTE"
ESTADO_NUEVO = "NUEVO"
ESTADO_ERROR = "ERROR"
ESTADO_WARNING = "WARNING"

# Como se arma la referencia de un SKU que todavia no existe. El maestro de
# esta tienda usa el propio SKU ID como referencia, y un ID que VTEX aun no ha
# asignado no se puede adivinar: hace falta una referencia propia y estable.
PATRON_REFERENCIA_SKU = "{mod_col}-{talla}"


def referencia_de_sku(mod_col, talla, patron=PATRON_REFERENCIA_SKU, ean=""):
    patron = texto(patron) or PATRON_REFERENCIA_SKU
    modelo, _, color = normalizar_referencia(mod_col).rpartition("-")
    valores = {
        "mod_col": normalizar_referencia(mod_col),
        "modelo": modelo or normalizar_referencia(mod_col),
        "color": color,
        "talla": normalizar_talla(talla),
        "ean": texto(ean),
    }
    try:
        return normalizar_referencia(patron.format(**valores))
    except (KeyError, IndexError):
        return normalizar_referencia(PATRON_REFERENCIA_SKU.format(**valores))


# --- Mapeo de especificaciones ------------------------------------------
#
# Nombre del campo EN LA TIENDA -> llave de la entrada que arma la pantalla.
# Se empareja por NOMBRE contra el diccionario del maestro, nunca por ID: los
# IDs de campo son de cada cuenta de VTEX y escribirlos aqui seria justamente
# el hardcodeo que hay que evitar. Un campo que la tienda no tenga simplemente
# no se emite.
MAPEO_ESPECIFICACIONES_PRODUCTO = (
    ("Modelo", "modelo"),
    ("Color", "color_web"),
    ("Color Comercial", "color_comercial"),
    ("Género", "genero"),
    ("Clase", "clase"),
    ("Tipo de Producto", "tipo_prenda"),
    ("Material", "material"),
    ("Composición", "composicion"),
    ("Temporada", "temporada"),
    ("Guía de Tallas", "guia_tallas"),
    ("Características principales", "caracteristicas"),
    ("Caracteristicas", "caracteristicas"),
    ("Tecnología", "tecnologia"),
    ("Descripción Modelo", "descripcion_modelo"),
    ("Cuidado de lavado", "cuidado_lavado"),
)

# Los SKU solo llevan Talla y Color en esta tienda (verificado: son los unicos
# dos campos de la exportacion de especificaciones de SKU).
MAPEO_ESPECIFICACIONES_SKU = (
    ("Talla", "talla"),
    ("Color", "color_web"),
)


def _opciones(opciones=None):
    base = {
        "patron_referencia_sku": PATRON_REFERENCIA_SKU,
        "actualizar_existentes": False,
        "solo_sin_imagenes": False,
        "maximo_imagenes": 10,
        "activar_producto": "Yes",
        "activar_sku": "Yes",
        # Cuando NINGUN codigo cruza contra el maestro casi siempre es un
        # desajuste (otro archivo, otro formato de referencia), no una tienda
        # vacia. Generar ahi duplicaria el catalogo entero, asi que se bloquea.
        # Esto lo desactiva a mano quien de verdad esta cargando todo nuevo.
        "permitir_todo_nuevo": False,
    }
    base.update(opciones or {})
    return base


def _valor(entrada, llave):
    return texto((entrada or {}).get(llave))


def _alerta(codigo, mod_col, detalle=""):
    nivel, etiqueta = ALERTAS[codigo]
    return {
        "Código": codigo,
        "Nivel": nivel,
        "Alerta": etiqueta,
        "Mod-Col": mod_col,
        "Detalle": detalle,
    }


def plan_de_carga(entradas, maestro, opciones=None):
    """Cruza lo que la app sabe contra el maestro y decide que se crea y que se
    actualiza. No escribe archivos: devuelve el plan para revisarlo.

    `entradas` son dicts armados por la pantalla, uno por Modelo-Color:

        {"mod_col", "nombre", "descripcion", "marca", "departamento",
         "categoria", "color_web", ..., "skus": [{"talla", "ean"}...],
         "imagenes": [url, ...]}

    Devuelve {"productos", "filas", "alertas", "resumen", "bloqueado"}.
    """
    opciones = _opciones(opciones)
    productos = []
    filas = []
    alertas = []
    vistos = set()
    referencias_sku = {}
    for entrada in entradas or []:
        mod_col = normalizar_referencia(entrada.get("mod_col"))
        if not mod_col:
            continue
        if mod_col in vistos:
            alertas.append(_alerta("codigo_duplicado", mod_col,
                                   "Aparece más de una vez en la selección; se usa la primera."))
            continue
        vistos.add(mod_col)
        producto = _resolver_producto(entrada, mod_col, maestro, opciones, alertas)
        _resolver_skus(entrada, producto, maestro, opciones, alertas, referencias_sku)
        _resolver_imagenes(entrada, producto, maestro, opciones, alertas)
        _resolver_medidas(producto, maestro, alertas)
        _resolver_especificaciones(entrada, producto, maestro, alertas)
        productos.append(producto)
        filas.extend(_filas_de_vista_previa(producto))
    _revisar_cruce(productos, maestro, opciones, alertas)
    resumen = _resumen(productos, alertas)
    bloqueado = any(alerta["Nivel"] == NIVEL_ERROR for alerta in alertas)
    return {
        "productos": productos,
        "filas": filas,
        "alertas": alertas,
        "resumen": resumen,
        "bloqueado": bloqueado,
        "opciones": opciones,
    }


def _revisar_cruce(productos, maestro, opciones, alertas):
    """Si NINGUN codigo cruzo, casi siempre es un desajuste, no una tienda vacia.

    Origen: se generaron las planillas con el Product ID en blanco en todas las
    filas. Leido asi parecia que la tienda no tenia esos productos; en realidad
    ninguna referencia habia cruzado. Cada fila sin ID CREA un producto, asi que
    eso duplica en VTEX todo lo que ya estaba cargado, con otra URL y otro ID.

    Un aviso por codigo no servia: con 500 codigos son 500 avisos iguales y
    ninguno dice lo que importa, que es que cruzaron CERO.
    """
    if not productos or len(productos) < MINIMO_PARA_SOSPECHAR_DESAJUSTE:
        return
    if opciones.get("permitir_todo_nuevo"):
        return
    cruzados = sum(1 for producto in productos if producto["producto_id"])
    if cruzados:
        return
    alertas.append(_alerta(
        "nada_cruzo_con_el_maestro", "",
        f"{len(productos):,} códigos y NINGUNO está en el maestro. El maestro tiene "
        f"{maestro.total_productos:,} productos. Antes de generar: comprueba que el archivo sea "
        "la exportación 'Products and SKUs' de VTEX y que los códigos tengan el mismo formato "
        "que su 'Product reference code'. Si de verdad son todos nuevos, marca la casilla "
        "de carga inicial.",
    ))


def _resolver_producto(entrada, mod_col, maestro, opciones, alertas):
    existente = maestro.producto(mod_col)
    modelo, _, color = mod_col.rpartition("-")
    producto = {
        "mod_col": mod_col,
        "modelo": modelo or mod_col,
        "color": color,
        "entrada": entrada,
        "existente": existente,
        "producto_id": texto((existente or {}).get("Product ID")),
        "referencia": mod_col,
        "estado": ESTADO_EXISTENTE if existente else ESTADO_NUEVO,
        "skus": [],
        "imagenes": [],
        "problemas": [],
    }
    if mod_col in maestro.referencias_duplicadas:
        ids = ", ".join(maestro.referencias_duplicadas[mod_col])
        producto["estado"] = ESTADO_ERROR
        producto["problemas"].append(f"La referencia apunta a varios Product ID ({ids}).")
        alertas.append(_alerta("referencia_duplicada", mod_col, f"Product ID: {ids}"))

    if not entrada.get("encontrado", True):
        producto["estado"] = ESTADO_ERROR
        producto["problemas"].append("No se encontró información del código en las fuentes de la app.")
        alertas.append(_alerta("codigo_no_encontrado", mod_col,
                               texto(entrada.get("detalle_origen")) or "Sin datos en Shopify ni en el maestro ARTI."))

    nombre = _valor(entrada, "nombre") or texto((existente or {}).get("Product Name"))
    if not nombre:
        producto["estado"] = ESTADO_ERROR
        producto["problemas"].append("Sin nombre de producto.")
        alertas.append(_alerta("producto_sin_nombre", mod_col))
    producto["nombre"] = nombre

    marca_nombre = _valor(entrada, "marca") or texto((existente or {}).get("Brand"))
    marca = maestro.marca(marca_nombre)
    if marca is None:
        producto["estado"] = ESTADO_ERROR
        producto["problemas"].append(
            f"La marca '{marca_nombre or 'sin marca'}' no existe en el catálogo maestro de VTEX."
        )
        alertas.append(_alerta("producto_sin_marca", mod_col, marca_nombre))
    producto["marca"] = marca or {"Brand ID": "", "Brand": marca_nombre}

    if existente:
        categoria = {
            "Department ID": texto(existente.get("Department ID")),
            "Department": texto(existente.get("Department")),
            "Category ID": texto(existente.get("Category ID")),
            "Category": texto(existente.get("Category")),
        }
        pedida = maestro.categoria(_valor(entrada, "departamento"), _valor(entrada, "categoria"))
        if pedida and pedida["Category ID"] != categoria["Category ID"]:
            alertas.append(_alerta(
                "producto_inconsistente", mod_col,
                f"En VTEX está en {categoria['Department']}/{categoria['Category']} y la app propone "
                f"{pedida['Department']}/{pedida['Category']}. Se respeta la de VTEX.",
            ))
            if producto["estado"] == ESTADO_EXISTENTE:
                producto["estado"] = ESTADO_WARNING
        marca_maestro = normalizar(existente.get("Brand"))
        if marca_nombre and marca_maestro and normalizar(marca_nombre) != marca_maestro:
            alertas.append(_alerta(
                "producto_inconsistente", mod_col,
                f"En VTEX la marca es '{existente.get('Brand')}' y la app trae '{marca_nombre}'. Se respeta la de VTEX.",
            ))
            if producto["estado"] == ESTADO_EXISTENTE:
                producto["estado"] = ESTADO_WARNING
            producto["marca"] = {
                "Brand ID": texto(existente.get("Brand ID")),
                "Brand": texto(existente.get("Brand")),
            }
    else:
        categoria = maestro.categoria(_valor(entrada, "departamento"), _valor(entrada, "categoria"))
        if categoria is None:
            producto["estado"] = ESTADO_ERROR
            producto["problemas"].append(
                f"No hay una categoría de VTEX que se llame "
                f"'{_valor(entrada, 'categoria') or 'sin categoría'}'."
            )
            alertas.append(_alerta("producto_sin_categoria", mod_col,
                                   f"{_valor(entrada, 'departamento')}/{_valor(entrada, 'categoria')}"))
            categoria = {"Department ID": "", "Department": _valor(entrada, "departamento"),
                         "Category ID": "", "Category": _valor(entrada, "categoria")}
        alertas.append(_alerta("producto_sin_id", mod_col, "Se crea un producto nuevo."))
    producto["categoria"] = categoria
    return producto


def _resolver_skus(entrada, producto, maestro, opciones, alertas, referencias_sku):
    mod_col = producto["mod_col"]
    tallas = entrada.get("skus") or []
    if not tallas:
        producto["estado"] = ESTADO_ERROR
        producto["problemas"].append("El producto no tiene ninguna talla para cargar.")
        alertas.append(_alerta("sin_tallas", mod_col,
                               "Sin tallas en Shopify ni en el maestro ARTI."))
        return
    vistas = set()
    for item in tallas:
        talla = normalizar_talla(item.get("talla"))
        if not talla or talla in vistas:
            continue
        vistas.add(talla)
        referencia_declarada = normalizar_referencia(item.get("referencia"))
        sku_existente = None
        if referencia_declarada:
            sku_existente = maestro.sku_por_referencia(referencia_declarada)
        if sku_existente is None and producto["producto_id"]:
            sku_existente = maestro.sku_por_talla(producto["producto_id"], talla)
        if sku_existente is not None and producto["producto_id"] and \
                texto(sku_existente.get("_producto_id")) != producto["producto_id"]:
            alertas.append(_alerta(
                "sku_inconsistente", mod_col,
                f"El SKU {sku_existente.get('SKU ID')} (talla {talla}) pertenece al producto "
                f"{sku_existente.get('_producto_id')} y no a {producto['producto_id']}. No se reutiliza.",
            ))
            sku_existente = None
        if sku_existente is not None:
            referencia = normalizar_referencia(sku_existente.get("SKU reference code")) or \
                texto(sku_existente.get("SKU ID"))
            sku = {
                "talla": talla,
                "sku_id": texto(sku_existente.get("SKU ID")),
                "referencia": referencia,
                "nombre": texto(sku_existente.get("SKU name")) or nombre_de_sku(talla),
                "estado": ESTADO_EXISTENTE,
                "existente": sku_existente,
                "ean": texto(item.get("ean")) or texto(sku_existente.get("EAN/UPC")),
                "imagenes": list(item.get("imagenes") or []),
            }
        else:
            sku = {
                "talla": talla,
                "sku_id": "",
                "referencia": referencia_declarada or referencia_de_sku(
                    mod_col, talla, opciones["patron_referencia_sku"], texto(item.get("ean"))
                ),
                "nombre": nombre_de_sku(talla),
                "estado": ESTADO_NUEVO,
                "existente": None,
                "ean": texto(item.get("ean")),
                "imagenes": list(item.get("imagenes") or []),
            }
            alertas.append(_alerta("sku_sin_id", mod_col, f"Talla {talla}: se crea un SKU nuevo."))
        duenio = referencias_sku.get(sku["referencia"])
        if duenio and duenio != mod_col:
            alertas.append(_alerta(
                "referencia_sku_repetida", mod_col,
                f"La referencia {sku['referencia']} ya la usa {duenio} en esta misma carga.",
            ))
            producto["estado"] = ESTADO_ERROR
        referencias_sku[sku["referencia"]] = mod_col
        producto["skus"].append(sku)


def _resolver_imagenes(entrada, producto, maestro, opciones, alertas):
    generales = [texto(url) for url in (entrada.get("imagenes") or []) if texto(url)]
    maximo = max(0, int(opciones.get("maximo_imagenes") or 0)) or len(generales)
    for sku in producto["skus"]:
        urls = [texto(url) for url in (sku.get("imagenes") or []) if texto(url)] or generales
        urls = urls[:maximo]
        if opciones.get("solo_sin_imagenes") and sku["sku_id"] and maestro.imagenes_por_sku.get(sku["sku_id"]):
            urls = []
        sku["urls_imagenes"] = urls
        producto["imagenes"].extend(urls)
    if not producto["imagenes"]:
        alertas.append(_alerta("imagen_faltante", producto["mod_col"],
                               "No se encontró ninguna foto para este código."))
        if producto["estado"] == ESTADO_EXISTENTE:
            producto["estado"] = ESTADO_WARNING


def _resolver_medidas(producto, maestro, alertas):
    """El peso y las medidas de cada SKU. NUNCA pueden quedar vacios.

    VTEX no puede cotizar el envio de un SKU sin peso, asi que un SKU sin
    medidas es una fila que no sirve. La cadena, de lo mas fiable a lo menos:

    1. Las del propio SKU en VTEX, si ya existe.
    2. Las de otra talla del MISMO producto: se despacha en la misma caja.
    3. Las que trae la app para ese tipo de prenda (tabla de dimensiones).
    4. Las que la tienda ya usa en esa CATEGORIA de VTEX.
    5. Las que la tienda usa en general.

    Si despues de las cinco sigue vacio, se bloquea. Antes salia la fila con el
    peso en blanco y el problema aparecia al subir el archivo.
    """
    hermano = _sku_hermano_con_medidas(producto, maestro)
    del_tipo = producto["entrada"].get("paquete") or {}
    categoria = producto["categoria"]
    de_la_categoria = maestro.medidas_de_categoria(
        categoria.get("Department ID"), categoria.get("Category ID"))
    for sku in producto["skus"]:
        existente = sku.get("existente") or {}
        paquete = {}
        for llave, columna in (("weight", "Package weight"), ("width", "Package width"),
                               ("height", "Package height"), ("length", "Package length")):
            paquete[llave] = (
                texto(existente.get(columna))
                or texto(hermano.get(columna))
                or texto(del_tipo.get(llave))
                or texto(de_la_categoria.get(llave))
            )
        paquete["origen"] = (
            "VTEX (el propio SKU)" if texto(existente.get("Package weight"))
            else "VTEX (otra talla del producto)" if texto(hermano.get("Package weight"))
            else "tabla de dimensiones por tipo" if texto(del_tipo.get("weight"))
            else "VTEX (promedio de la categoría)" if texto(de_la_categoria.get("weight"))
            else ""
        )
        sku["paquete"] = paquete
        if not paquete["weight"]:
            alertas.append(_alerta(
                "sku_sin_peso", producto["mod_col"],
                f"Talla {sku['talla']}: no hay peso ni en VTEX, ni en la tabla de dimensiones "
                f"de '{producto['entrada'].get('tipo_prenda') or 'sin tipo'}', ni en la categoría "
                f"{categoria.get('Category') or 'sin categoría'}. VTEX no puede cotizar su envío.",
            ))
            producto["estado"] = ESTADO_ERROR


def _resolver_especificaciones(entrada, producto, maestro, alertas):
    """Que especificaciones lleva el producto y cada SKU, RESUELTAS.

    Se decide aqui, en el analisis, y no al escribir el archivo: un valor que
    la tienda no admite (un color que no esta en la lista del campo Radio) es
    justo lo que hay que avisar ANTES de bajar el ZIP. Si se resolviera al
    generar, el aviso llegaria cuando VTEX rechace la fila.
    """
    categoria = producto["categoria"]
    departamento = categoria.get("Department", "")
    nombre_categoria = categoria.get("Category", "")
    producto["especificaciones"] = _resolver_campos(
        maestro, maestro.campos_producto, MAPEO_ESPECIFICACIONES_PRODUCTO,
        entrada, departamento, nombre_categoria, producto["mod_col"], alertas,
    )
    for sku in producto["skus"]:
        valores = dict(entrada or {})
        valores["talla"] = sku["talla"]
        sku["especificaciones"] = _resolver_campos(
            maestro, maestro.campos_sku, MAPEO_ESPECIFICACIONES_SKU,
            valores, departamento, nombre_categoria, producto["mod_col"], alertas,
        )


def _resolver_campos(maestro, campos, mapeo, valores, departamento, categoria, mod_col, alertas):
    resueltos = []
    emitidos = set()
    for nombre_campo, llave in mapeo:
        campo = maestro.campo_por_nombre(campos, nombre_campo, departamento, categoria)
        if campo is None or campo["ID de campo"] in emitidos:
            continue
        valor = _valor(valores, llave)
        if not valor:
            continue
        valor_id, valor_texto = maestro.valor_de_campo(campo, valor)
        if valor_id is None:
            alertas.append(_alerta(
                "valor_fuera_de_lista", mod_col,
                f"{campo['Nombre del campo']}: '{valor_texto}' no está en la lista de la tienda. "
                "La especificación no se emite.",
            ))
            continue
        emitidos.add(campo["ID de campo"])
        resueltos.append({"campo": campo, "valor_id": valor_id, "valor": valor_texto})
    return resueltos


def _filas_de_vista_previa(producto):
    filas = []
    for sku in producto["skus"] or [{}]:
        # El estado de la FILA, no el del producto: una talla nueva de un
        # producto que ya existe es una creacion, y verla como "EXISTENTE"
        # esconde justo lo que se va a crear.
        if producto["estado"] in (ESTADO_ERROR, ESTADO_WARNING):
            estado = producto["estado"]
        elif sku.get("estado") == ESTADO_NUEVO or producto["estado"] == ESTADO_NUEVO:
            estado = ESTADO_NUEVO
        else:
            estado = ESTADO_EXISTENTE
        filas.append({
            "Modelo": producto["modelo"],
            "Color": producto["color"],
            "Product Ref": producto["referencia"],
            "Product ID": producto["producto_id"] or "(nuevo)",
            "SKU Ref": sku.get("referencia", ""),
            "SKU ID": sku.get("sku_id") or ("(nuevo)" if sku else ""),
            "Talla": sku.get("talla", ""),
            "Estado": estado,
            "Estado SKU": sku.get("estado", ""),
            "Fotos": len(sku.get("urls_imagenes") or []),
            "Detalle": " ".join(producto["problemas"]),
        })
    return filas


def _resumen(productos, alertas):
    skus = [sku for producto in productos for sku in producto["skus"]]
    imagenes = sum(len(sku.get("urls_imagenes") or []) for producto in productos for sku in producto["skus"])
    return {
        "Productos encontrados": len(productos),
        "Productos existentes": sum(1 for producto in productos if producto["producto_id"]),
        "Productos nuevos": sum(1 for producto in productos if not producto["producto_id"]),
        "SKUs encontrados": len(skus),
        "SKUs existentes": sum(1 for sku in skus if sku["sku_id"]),
        "SKUs nuevos": sum(1 for sku in skus if not sku["sku_id"]),
        "Imagenes": imagenes,
        "SKUs sin peso": sum(1 for sku in skus if not (sku.get("paquete") or {}).get("weight")),
        "Errores": sum(1 for alerta in alertas if alerta["Nivel"] == NIVEL_ERROR),
        "Avisos": sum(1 for alerta in alertas if alerta["Nivel"] == NIVEL_AVISO),
    }


# --- Construccion de las cuatro planillas --------------------------------

def construir_archivos(plan, maestro, opciones=None):
    """{nombre_archivo: {"columnas": (...), "filas": [dict, ...]}}.

    Los cuatro salen del MISMO plan, asi que el Product ID y el SKU ID que
    aparecen en uno son literalmente el mismo objeto que en los otros tres: no
    hay forma de que se desincronicen.
    """
    opciones = _opciones(dict(plan.get("opciones") or {}, **(opciones or {})))
    productos = plan.get("productos") or []
    return {
        ARCHIVO_PRODUCTOS: {
            "columnas": COLUMNAS_PRODUCTOS_Y_SKUS,
            "filas": _filas_productos_y_skus(productos, maestro, opciones),
        },
        ARCHIVO_ESPEC_PRODUCTO: {
            "columnas": COLUMNAS_ESPECIFICACIONES_PRODUCTO,
            "filas": _filas_especificaciones_producto(productos, maestro),
        },
        ARCHIVO_ESPEC_SKU: {
            "columnas": COLUMNAS_ESPECIFICACIONES_SKU,
            "filas": _filas_especificaciones_sku(productos, maestro),
        },
        ARCHIVO_IMAGENES: {
            "columnas": COLUMNAS_IMAGENES,
            "filas": _filas_imagenes(productos),
        },
    }


def _fila_vacia(columnas):
    return {columna: "" for columna in columnas}


def _filas_productos_y_skus(productos, maestro, opciones):
    filas = []
    canales = maestro.valor_por_defecto("Sales channels", "1")
    unidad = maestro.valor_por_defecto("Unit of measure", "un")
    multiplicador = maestro.valor_por_defecto("Unit multiplier", "1")
    condicion = maestro.valor_por_defecto("Commercial condition", "")
    fidelidad = maestro.valor_por_defecto("Loyalty amount", "0")
    mostrar_sin_stock = maestro.valor_por_defecto("Show when out of stock", "No")
    for producto in productos:
        cabecera = _cabecera_producto(producto, maestro, opciones, canales, mostrar_sin_stock)
        for sku in producto["skus"]:
            fila = _fila_vacia(COLUMNAS_PRODUCTOS_Y_SKUS)
            fila.update(cabecera)
            existente = sku.get("existente") or {}
            # Ya resueltas en el plan por `_resolver_medidas`, con su cadena de
            # respaldos y su bloqueo si quedan vacias.
            paquete = sku.get("paquete") or {}
            peso, ancho = texto(paquete.get("weight")), texto(paquete.get("width"))
            alto, largo = texto(paquete.get("height")), texto(paquete.get("length"))
            fila.update({
                "SKU ID": sku["sku_id"],
                "SKU name": sku["nombre"],
                "Activate SKU if possible": texto(existente.get("Activate SKU if possible")) or opciones["activar_sku"],
                "Active SKU": texto(existente.get("Active SKU")) or opciones["activar_sku"],
                "Bundle": texto(existente.get("Bundle")) or "No",
                "SKU reference code": sku["referencia"],
                "EAN/UPC": sku.get("ean", ""),
                "Manufacturer code": texto(existente.get("Manufacturer code")),
                "Package weight": peso,
                "Package width": ancho,
                "Package height": alto,
                "Package length": largo,
                "Actual weight": texto(existente.get("Actual weight")),
                "Actual width": texto(existente.get("Actual width")),
                "Actual height": texto(existente.get("Actual height")),
                "Actual length": texto(existente.get("Actual length")),
                "Cubic Weight": texto(existente.get("Cubic Weight")) or peso_cubico(ancho, alto, largo),
                "Unit of measure": texto(existente.get("Unit of measure")) or unidad,
                "Unit multiplier": texto(existente.get("Unit multiplier")) or multiplicador,
                "Commercial condition": texto(existente.get("Commercial condition")) or condicion,
                "Loyalty amount": texto(existente.get("Loyalty amount")) or fidelidad,
                "Presale date": texto(existente.get("Presale date")),
                "Attachments": texto(existente.get("Attachments")),
                "Accessories": texto(existente.get("Accessories")),
                "Suggestions": texto(existente.get("Suggestions")),
                "Similar products": texto(existente.get("Similar products")),
                "Show together": texto(existente.get("Show together")),
            })
            filas.append(fila)
    return filas


def _sku_hermano_con_medidas(producto, maestro):
    """Las medidas de otra talla del MISMO producto en VTEX.

    Una talla nueva de un producto que ya existe se despacha en la misma caja
    que sus hermanas. Sin esto sale con peso y medidas vacios, y VTEX no puede
    cotizar el envio de ese SKU.
    """
    if not producto.get("producto_id"):
        return {}
    for sku in maestro.skus_de_producto(producto["producto_id"]):
        if texto(sku.get("Package weight")):
            return sku
    return {}


def _cabecera_producto(producto, maestro, opciones, canales, mostrar_sin_stock):
    entrada = producto["entrada"]
    existente = producto.get("existente")
    nombre = producto["nombre"]
    if existente and not opciones.get("actualizar_existentes"):
        # Un producto que ya vive en VTEX se re-emite TAL CUAL. Reescribir el
        # nombre, la URL o la meta description de un producto publicado le
        # cambia el SEO sin que nadie lo haya pedido: eso solo pasa si se marca
        # "actualizar los que ya existen".
        cabecera = {columna: texto(existente.get(columna)) for columna in COLUMNAS_NIVEL_PRODUCTO}
        cabecera["Product ID"] = producto["producto_id"]
        cabecera["Product reference code"] = producto["referencia"]
        return cabecera
    marca = producto["marca"]
    categoria = producto["categoria"]
    descripcion = _valor(entrada, "descripcion") or texto((existente or {}).get("Description"))
    adicional = _valor(entrada, "descripcion_adicional") or descripcion
    cabecera = {columna: texto((existente or {}).get(columna)) for columna in COLUMNAS_NIVEL_PRODUCTO}
    cabecera.update({
        "Product ID": producto["producto_id"],
        "Product Name": nombre,
        "Active product": texto((existente or {}).get("Active product")) or opciones["activar_producto"],
        "Description": descripcion,
        "Additional description": adicional,
        "Brand ID": marca.get("Brand ID", ""),
        "Brand": marca.get("Brand", ""),
        "Department ID": categoria.get("Department ID", ""),
        "Department": categoria.get("Department", ""),
        "Category ID": categoria.get("Category ID", ""),
        "Category": categoria.get("Category", ""),
        "Sales channels": texto((existente or {}).get("Sales channels")) or canales,
        "Product URL": texto((existente or {}).get("Product URL")) or _url_de_producto(nombre, producto["referencia"]),
        "Page Title": texto((existente or {}).get("Page Title")) or _titulo_de_pagina(nombre, producto["color"]),
        "Meta description": texto((existente or {}).get("Meta description")) or _meta_descripcion(nombre, producto["referencia"]),
        "Display on website": texto((existente or {}).get("Display on website")) or "Yes",
        "Show when out of stock": texto((existente or {}).get("Show when out of stock")) or mostrar_sin_stock,
        "Substitute words": texto((existente or {}).get("Substitute words")) or _palabras_sustitutas(producto),
        "Product reference code": producto["referencia"],
    })
    return cabecera


def _url_de_producto(nombre, referencia):
    """La URL con la forma que ya usa la tienda: nombre + referencia.

    Verificado contra el maestro real. VTEX le agrega un sufijo si la URL ya
    existe, asi que para un producto que ya esta cargado NUNCA se recalcula:
    se copia la que trae el maestro.
    """
    partes = [parte for parte in (slug(nombre), slug(referencia)) if parte]
    return "-".join(partes)


def _titulo_de_pagina(nombre, color):
    return " ".join(parte for parte in (texto(nombre), texto(color)) if parte)


def _meta_descripcion(nombre, referencia):
    return (
        f"COMPRA {texto(nombre).upper()} CALIDAD GARANTIZADA. COMPRA FÁCIL DESDE TU CASA "
        f"EN LÍNEA Y A MEJOR PRECIO EN NUESTRA TIENDA VIRTUAL {texto(referencia)}"
    )


def _palabras_sustitutas(producto):
    entrada = producto["entrada"]
    partes = [
        producto["modelo"],
        producto["referencia"],
        _valor(entrada, "nombre_corto") or producto["nombre"],
        producto["marca"].get("Brand", ""),
        producto["categoria"].get("Category", ""),
        producto["categoria"].get("Department", ""),
    ]
    return ",".join(parte for parte in (texto(parte) for parte in partes) if parte)


def _fila_especificacion(columnas, campo, valor_id, valor_texto, asignado):
    fila = _fila_vacia(columnas)
    fila.update({
        "ID de campo": campo["ID de campo"],
        "Nombre del campo": campo["Nombre del campo"],
        "Tipo de campo": campo["Tipo de campo"],
        "IDs de valores de campo": campo["IDs de valores de campo"],
        "Valores de campo": campo["Valores de campo"],
        "IDs de especificación": texto((asignado or {}).get("IDs de especificación")) or texto(valor_id),
        "Valores de especificación": valor_texto,
    })
    return fila


def _filas_especificaciones_producto(productos, maestro):
    filas = []
    for producto in productos:
        categoria = producto["categoria"]
        asignados = maestro.especificaciones_producto.get(producto["producto_id"], {})
        for resuelto in producto.get("especificaciones") or []:
            campo = resuelto["campo"]
            fila = _fila_especificacion(
                COLUMNAS_ESPECIFICACIONES_PRODUCTO, campo, resuelto["valor_id"], resuelto["valor"],
                asignados.get(campo["ID de campo"]),
            )
            fila.update({
                "ID del producto": producto["producto_id"],
                "Nombre del producto": producto["nombre"],
                "Código de referencia del producto": producto["referencia"],
                "ID de marca": producto["marca"].get("Brand ID", ""),
                "Marca": producto["marca"].get("Brand", ""),
                "ID del departamento": categoria.get("Department ID", ""),
                "Departamento": categoria.get("Department", ""),
                "ID de categoría": categoria.get("Category ID", ""),
                "Categoría": categoria.get("Category", ""),
            })
            filas.append(fila)
    return filas


def _filas_especificaciones_sku(productos, maestro):
    filas = []
    for producto in productos:
        categoria = producto["categoria"]
        for sku in producto["skus"]:
            asignados = maestro.especificaciones_sku.get(sku["sku_id"], {})
            for resuelto in sku.get("especificaciones") or []:
                campo = resuelto["campo"]
                fila = _fila_especificacion(
                    COLUMNAS_ESPECIFICACIONES_SKU, campo, resuelto["valor_id"], resuelto["valor"],
                    asignados.get(campo["ID de campo"]),
                )
                fila.update({
                    "ID de SKU": sku["sku_id"],
                    "Nombre de SKU": sku["nombre"],
                    "Código de referencia de SKU": sku["referencia"],
                    "ID de marca": producto["marca"].get("Brand ID", ""),
                    "Marca": producto["marca"].get("Brand", ""),
                    "ID del departamento": categoria.get("Department ID", ""),
                    "Departamento": categoria.get("Department", ""),
                    "ID de categoría": categoria.get("Category ID", ""),
                    "Categoría": categoria.get("Category", ""),
                })
                filas.append(fila)
    return filas


def _filas_imagenes(productos):
    filas = []
    for producto in productos:
        for sku in producto["skus"]:
            for posicion, url in enumerate(sku.get("urls_imagenes") or [], start=1):
                fila = _fila_vacia(COLUMNAS_IMAGENES)
                fila.update({
                    "ID del producto": producto["producto_id"],
                    "Nombre del producto": producto["nombre"],
                    "ID de SKU": sku["sku_id"],
                    "Nombre de SKU": sku["nombre"],
                    "Código de referencia de SKU": sku["referencia"],
                    "ID de la imagen": "",
                    "Nombre de la imagen": slug(sku["nombre"]).upper(),
                    # La tienda guarda todas las fotos de un SKU en la posicion
                    # 0 y las ordena por el Label (verificado: 387 de 499 filas
                    # de la exportacion). Se copia esa convencion.
                    "Posición de la imagen": "0",
                    "Label de la imagen": str(posicion),
                    "Texto de la imagen": producto["nombre"],
                    "Ruta de la imagen": "",
                    "URL de importación de la imagen": url,
                })
                filas.append(fila)
    return filas


def filas_para_hoja(archivo, tabla):
    """Las filas tal como van en la hoja: primero la fila en blanco de la
    exportacion de VTEX, despues la cabecera, despues los datos."""
    columnas = list(tabla["columnas"])
    filas = [[""] * len(columnas) for _ in range(FILAS_VACIAS_ANTES_DE_CABECERA)]
    filas.append(columnas)
    for registro in tabla["filas"]:
        filas.append([texto(registro.get(columna, "")) for columna in columnas])
    return filas
