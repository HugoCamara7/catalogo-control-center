"""Los 4 archivos de carga manual de VTEX para Supermall.pe, armados solos.

Por que existe
--------------
Supermall.pe paso de VTEX a Shopify y la pantalla que armaba las planillas se
retiro entera (CLAUDE.md, seccion 5 sexies bis). Pero la tienda VTEX sigue
recibiendo cargas manuales, y esas cargas se estaban preparando **a mano**:
alguien abria el export de VTEX, buscaba el producto, copiaba el Product ID y
el SKU ID para no duplicarlos, y rellenaba las cuatro planillas columna a
columna. Con miles de codigos eso no se hace: se deja como este.

Lo que faltaba no era la plantilla -- el export de VTEX ya la trae --, era el
**cruce**: quien ya existe en VTEX (y con que ID), quien es nuevo, y de donde
sale la informacion de cada campo. La informacion existe: esta en Shopify
(Columbia.pe, Vans.pe, Rockford.pe...) y en el maestro ARTI. Este modulo es el
puente.

```
Archivo VTEX  ->  Match  ->  Shopify + ARTI  ->  Enriquecimiento  ->  4 archivos
   (IDs)         (quien)      (que dice)          (que falta)         + ZIP
```

Las cuatro planillas, tal como las exporta VTEX
-----------------------------------------------
1. **Products and SKUs** -- una fila por SKU, con las columnas del producto
   repetidas. `Product reference code` es el **codigo Modelo-Color**
   (`HP102011307-251`), que es exactamente la identidad que usa toda esta app
   (`engines/load_status.clave_de_producto`). `SKU name` es `TALLA 39`.
2. **Especificaciones de productos** -- una fila por producto y campo. Puede
   venir partida en VARIAS HOJAS: VTEX corta por el limite de filas de Excel,
   no por contenido, y las hojas no comparten ni un producto. Se concatenan.
3. **Especificaciones de SKUs** -- una fila por SKU y campo. Hoy solo dos
   campos: `Talla` (28) y `Color` (29), los dos `Radio`.
4. **Imagenes** -- una fila por imagen de SKU.

Los dos datos que no son obvios y que hacen que esto funcione
-------------------------------------------------------------
- **El dominio de cada campo viaja en el propio export.** Las columnas
  `IDs de valores de campo` / `Valores de campo` traen la lista COMPLETA de
  valores admitidos con su ID (`632=Zapatos`, `60=Mujer`, `141=39`, `78=Rojo`).
  O sea que un texto se puede traducir a su ID sin llamar a la API de VTEX.
  **Lo que el dominio no tiene, no se inventa**: queda en REVISAR.
- **`IDs de especificacion` significa dos cosas distintas.** En un campo
  `Radio`/`CheckBox` es el ID del VALOR del dominio, y sirve para cualquier
  producto. En un campo `Texto` es el ID de ESA instancia de texto, unico por
  producto: reusarlo en otro producto le escribiria encima. Por eso solo se
  reusa el del mismo producto, y en uno nuevo va vacio.

Reglas que no se negocian
-------------------------
- **No se inventan matches.** La escalera es SKU/RefId -> EAN -> codigo ARTI ->
  Product/SKU ID -> Modelo+Color+Talla, y en cuanto un escalon da mas de un
  candidato el registro queda en **REVISAR**, nunca "el primero que caiga". Un
  ID equivocado en VTEX no es un error: es sobrescribir otro producto.
- **No se inventan IDs.** Ni de producto, ni de SKU, ni de marca, ni de
  categoria, ni de valor de especificacion. Lo que no se pudo resolver sale
  vacio y se reporta. Un `Brand ID` inventado carga el producto bajo otra marca.
- **La estructura de salida es la del archivo de entrada**, columna a columna y
  en su orden: es una plantilla de VTEX y una columna de mas o de menos la
  rechaza. Por eso las cabeceras se leen del propio archivo que sube el usuario
  y solo se cae a las constantes de aqui cuando falta ese archivo.

Sin Streamlit y sin pandas, como el resto de `engines/`. Quien lo usa le pasa
listas de diccionarios y recibe listas de diccionarios.
"""

import re
import unicodedata

# --- Las cuatro planillas ----------------------------------------------------
#
# Copiadas de un export real de supermallpe (septiembre de 2026). Son el
# RESPALDO: cuando el usuario sube el archivo, mandan las cabeceras del archivo.

PRODUCTOS = "productos_skus"
ESPEC_PRODUCTO = "especificaciones_producto"
ESPEC_SKU = "especificaciones_sku"
IMAGENES = "imagenes"

ARCHIVOS = (PRODUCTOS, ESPEC_PRODUCTO, ESPEC_SKU, IMAGENES)

NOMBRES_DE_ARCHIVO = {
    PRODUCTOS: "products-and-skus",
    ESPEC_PRODUCTO: "especificaciones-de-productos",
    ESPEC_SKU: "especificaciones-de-skus",
    IMAGENES: "imagenes",
}

ETIQUETAS = {
    PRODUCTOS: "Products and SKUs",
    ESPEC_PRODUCTO: "Especificaciones de productos",
    ESPEC_SKU: "Especificaciones de SKUs",
    IMAGENES: "Imágenes",
}

COLUMNAS_PRODUCTOS = (
    "Product ID", "Product Name", "Active product", "Description",
    "Additional description", "Brand ID", "Brand", "Department ID",
    "Department", "Category ID", "Category", "Sales channels",
    "Global category ID", "Global category", "Product URL", "Page Title",
    "Meta description", "Display on website", "Show when out of stock",
    "Release date", "Substitute words", "Product reference code", "Tax code",
    "SKU ID", "SKU name", "Activate SKU if possible", "Active SKU", "Bundle",
    "SKU reference code", "EAN/UPC", "Manufacturer code", "Package weight",
    "Package width", "Package height", "Package length", "Actual weight",
    "Actual width", "Actual height", "Actual length", "Cubic Weight",
    "Unit of measure", "Unit multiplier", "Commercial condition",
    "Loyalty amount", "Presale date", "Attachments", "Accessories",
    "Suggestions", "Similar products", "Show together",
)

COLUMNAS_ESPEC_PRODUCTO = (
    "ID del producto", "Nombre del producto", "Código de referencia del producto",
    "ID de marca", "Marca", "ID del departamento", "Departamento",
    "ID de categoría", "Categoría", "ID de campo", "Nombre del campo",
    "Tipo de campo", "IDs de valores de campo", "Valores de campo",
    "IDs de especificación", "Valores de especificación",
)

COLUMNAS_ESPEC_SKU = (
    "ID de SKU", "Nombre de SKU", "Código de referencia de SKU", "ID de marca",
    "Marca", "ID del departamento", "Departamento", "ID de categoría",
    "Categoría", "ID de campo", "Nombre del campo", "Tipo de campo",
    "IDs de valores de campo", "Valores de campo", "IDs de especificación",
    "Valores de especificación",
)

COLUMNAS_IMAGENES = (
    "ID del producto", "Nombre del producto", "ID de SKU", "Nombre de SKU",
    "Código de referencia de SKU", "ID de la imagen", "Nombre de la imagen",
    "Posición de la imagen", "Label de la imagen", "Texto de la imagen",
    "Ruta de la imagen", "URL de importación de la imagen",
)

COLUMNAS = {
    PRODUCTOS: COLUMNAS_PRODUCTOS,
    ESPEC_PRODUCTO: COLUMNAS_ESPEC_PRODUCTO,
    ESPEC_SKU: COLUMNAS_ESPEC_SKU,
    IMAGENES: COLUMNAS_IMAGENES,
}

# La columna con la que se reconoce cada archivo cuando el usuario sube cuatro
# ficheros sin decir cual es cual. Se mira la CABECERA -- ya traducida a
# canonico --, no el nombre del fichero: ese lo pone VTEX con una marca de
# tiempo y el usuario lo renombra.
FIRMAS = (
    # (archivo, columnas que solo tiene ese archivo)
    (PRODUCTOS, ("product id", "sku id", "product reference code")),
    (IMAGENES, ("id de la imagen", "ruta de la imagen")),
    (ESPEC_SKU, ("id de sku", "id de campo")),
    (ESPEC_PRODUCTO, ("id del producto", "id de campo")),
)

# Campos de especificacion de SKU. Son los dos que la tienda tiene hoy.
CAMPO_TALLA = "Talla"
CAMPO_COLOR = "Color"

# Valor que VTEX escribe en una especificacion sin contenido.
VACIO = "---"

# --- Estados del emparejamiento ---------------------------------------------
EXISTE = "Existe en VTEX"
NUEVO = "Nuevo en VTEX"
REVISAR = "REVISAR"

# --- Texto -------------------------------------------------------------------


def texto(valor):
    """El valor como cadena limpia. `None` y `NaN` salen vacios."""
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:  # NaN
        return ""
    return str(valor).strip()


def _sin_acentos(valor):
    descompuesto = unicodedata.normalize("NFD", valor)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def clave(valor):
    """La llave con la que se comparan dos textos: sin acentos, sin dobles
    espacios y en minuscula.

    No se usa para ESCRIBIR nada: lo que sale a los archivos es siempre el
    texto tal cual lo trae la tienda o el maestro.
    """
    limpio = _sin_acentos(texto(valor)).casefold()
    return re.sub(r"\s+", " ", limpio).strip()


def clave_codigo(valor):
    """La llave de un codigo (Modelo-Color, SKU, EAN): sin espacios y en mayuscula.

    Un codigo no lleva acentos, y un espacio de mas dentro de una celda de Excel
    es lo normal.
    """
    return re.sub(r"\s+", "", texto(valor)).upper()


def slug(valor):
    """El `Product URL` de VTEX: minusculas, sin acentos y con guiones.

    Es la URL del producto en la tienda, asi que un producto que YA existe
    conserva la suya: cambiarla rompe el enlace y a VTEX le parece otro producto.
    """
    limpio = _sin_acentos(texto(valor)).casefold()
    limpio = limpio.replace("™", "").replace("®", "")
    limpio = re.sub(r"[^a-z0-9]+", "-", limpio)
    return limpio.strip("-")


def _numero(valor):
    """El valor como numero, o `None`. Acepta la coma decimal."""
    crudo = texto(valor).replace(",", ".")
    if not crudo:
        return None
    try:
        return float(crudo)
    except ValueError:
        return None


def _entero_texto(valor):
    """Un ID tal como se escribe en la planilla: `310669`, no `310669.0`.

    pandas lee una columna de IDs con un hueco como `float`, y ahi cada ID sale
    con `.0` pegado. Un `Product ID` con `.0` no lo reconoce nadie.
    """
    crudo = texto(valor)
    if not crudo:
        return ""
    if re.fullmatch(r"-?\d+\.0+", crudo):
        return crudo.split(".")[0]
    return crudo


# --- El export sale en el IDIOMA del admin ------------------------------------
#
# El pack de muestra vino con la planilla de productos en INGLES (`Product ID`,
# `Product Name`, `Yes`) y el export real de la tienda sale en ESPANOL (`ID del
# producto`, `Nombre del producto`, `Si`). Son las MISMAS 50 columnas, en el
# MISMO orden: lo unico que cambia es como se llaman.
#
# Asi que el nombre de una columna **no es su identidad**. El motor trabaja con
# un nombre CANONICO y aqui estan sus sinonimos; al leer se traduce a canonico y
# al escribir se vuelve a los nombres del archivo QUE SUBIO EL USUARIO -- que es
# la plantilla que su VTEX espera de vuelta.
#
# Las otras tres planillas ya venian en espanol en la muestra, asi que ahi el
# canonico ES el espanol. Si alguna sale en ingles, se agrega su fila aqui y no
# hay que tocar nada mas.
SINONIMOS_DE_COLUMNA = (
    # (canonico, otros nombres...)
    ("Product ID", "ID del producto"),
    ("Product Name", "Nombre del producto"),
    ("Active product", "Producto activo"),
    ("Description", "Descripción"),
    ("Additional description", "Descripción adicional"),
    ("Brand ID", "ID de marca"),
    ("Brand", "Marca"),
    ("Department ID", "ID del departamento"),
    ("Department", "Departamento"),
    ("Category ID", "ID de categoría"),
    ("Category", "Categoría"),
    ("Sales channels", "Políticas comerciales"),
    ("Global category ID", "ID de categoría global"),
    ("Global category", "Categoría global"),
    ("Product URL", "URL del producto"),
    ("Page Title", "Título de la página"),
    ("Meta description", "Metadescripción"),
    ("Display on website", "Mostrar en el sitio web"),
    ("Show when out of stock", "Mostrar cuando no tenga stock"),
    ("Release date", "Fecha de release"),
    ("Substitute words", "Palabras sustitutas"),
    ("Product reference code", "Código de referencia del producto"),
    ("Tax code", "Código fiscal"),
    ("SKU ID", "ID de SKU"),
    ("SKU name", "Nombre de SKU"),
    ("Activate SKU if possible", "Activar SKU si es posible"),
    ("Active SKU", "SKU activo"),
    ("Bundle", "Kit"),
    ("SKU reference code", "Código de referencia de SKU"),
    ("EAN/UPC",),
    ("Manufacturer code", "Código del fabricante"),
    ("Package weight", "Peso del paquete"),
    ("Package width", "Anchura del paquete"),
    ("Package height", "Altura del paquete"),
    ("Package length", "Longitud del paquete"),
    ("Actual weight", "Peso real"),
    ("Actual width", "Anchura real"),
    ("Actual height", "Altura real"),
    ("Actual length", "Longitud real"),
    ("Cubic Weight", "Peso cúbico"),
    ("Unit of measure", "Unidad de medida"),
    ("Unit multiplier", "Multiplicador de unidad"),
    ("Commercial condition", "Condición comercial"),
    ("Loyalty amount", "Valor de fidelidad"),
    ("Presale date", "Fecha de preventa"),
    ("Attachments", "Anexos"),
    ("Accessories", "Accesorios"),
    ("Suggestions", "Sugerencias"),
    ("Similar products", "Productos similares"),
    ("Show together", "Mostrar juntos"),
)

# `clave(nombre traducido o no) -> nombre canonico`, **solo de la planilla de
# productos**. La traduccion es POR ARCHIVO y no global: `ID de SKU` es un
# sinonimo de `SKU ID` en la planilla de productos, pero en la de
# especificaciones de SKU es su propia columna canonica. Con una tabla global,
# traducirla ahi le cambiaba el nombre y el indice se quedaba vacio.
_CANONICO_DE = {}
for _fila_de_sinonimos in SINONIMOS_DE_COLUMNA:
    for _nombre in _fila_de_sinonimos:
        _CANONICO_DE[clave(_nombre)] = _fila_de_sinonimos[0]

# Las otras tres planillas ya venian en espanol, asi que ahi el canonico ES el
# nombre del archivo y no hay nada que traducir. Cuando alguna salga en otro
# idioma, se le agrega su tabla aqui.
SINONIMOS_POR_ARCHIVO = {PRODUCTOS: _CANONICO_DE}


def canonico(nombre, archivo=PRODUCTOS):
    """El nombre con el que el motor conoce esa columna de ESE archivo.

    Una columna que no esta en la tabla se queda como esta: una columna nueva de
    VTEX tiene que llegar igual al archivo de salida, no desaparecer.
    """
    tabla = SINONIMOS_POR_ARCHIVO.get(archivo)
    if not tabla:
        return texto(nombre)
    return tabla.get(clave(nombre), texto(nombre))


def traducir_fila(fila, archivo=PRODUCTOS):
    """La fila con las columnas de ese archivo en nombre canonico."""
    if archivo not in SINONIMOS_POR_ARCHIVO:
        return dict(fila or {})
    return {canonico(nombre, archivo): valor
            for nombre, valor in (fila or {}).items()}


# Los valores de si/no tambien salen en el idioma del admin (`Yes`/`Sí`). La
# FORMA se toma del propio export -- se escribe exactamente lo que la tienda ya
# usa -- y esta tabla solo dice cual de las dos es cual.
VALORES_AFIRMATIVOS = frozenset({"yes", "si", "true", "1", "y", "s"})

# Las columnas de si/no que la app escribe, y con que las rellena.
COLUMNAS_AFIRMATIVAS = ("Active product", "Display on website",
                        "Activate SKU if possible", "Active SKU")
COLUMNAS_NEGATIVAS = ("Bundle",)


def es_afirmativo(valor):
    return clave(valor).replace("í", "i") in VALORES_AFIRMATIVOS


# --- El catalogo maestro -----------------------------------------------------

# Las columnas del archivo de productos cuyo valor se copia tal cual de lo que
# la tienda ya usa. Son decisiones de la tienda, no del catalogo: inventarlas
# cambiaria como se vende el producto.
COLUMNAS_HEREDADAS = (
    "Sales channels", "Unit of measure", "Unit multiplier",
    "Commercial condition", "Loyalty amount", "Show when out of stock",
    "Tax code",
)

COLUMNAS_DE_MEDIDA = (
    "Package weight", "Package width", "Package height", "Package length",
)


class Campo:
    """Un campo de especificacion, con su dominio de valores.

    `valores` es `{clave(texto): [id, ...]}`. Una lista y no un id porque el
    export trae etiquetas REPETIDAS con ids distintos (`Mujer` es 60 y 61, `0`
    es 98 y 99). Se queda con el PRIMERO -- que es determinista y es el que la
    tienda ya usa en sus productos -- y el resto queda para poder avisar.
    """

    __slots__ = ("id", "nombre", "tipo", "ids_dominio", "valores_dominio", "valores")

    def __init__(self, id_campo, nombre, tipo, ids_dominio, valores_dominio):
        self.id = id_campo
        self.nombre = nombre
        self.tipo = tipo
        self.ids_dominio = ids_dominio
        self.valores_dominio = valores_dominio
        self.valores = {}
        for identificador, valor in zip(ids_dominio, valores_dominio):
            self.valores.setdefault(clave(valor), []).append(identificador)

    @property
    def es_lista(self):
        return clave(self.tipo) in ("radio", "checkbox", "combo")

    def id_de(self, valor):
        """`(id, ambiguo)` para un texto. `("", False)` si el dominio no lo tiene."""
        opciones = self.valores.get(clave(valor)) or []
        if not opciones:
            return "", False
        return opciones[0], len(opciones) > 1


# Lo unico que se lee de la fila cruda de un producto despues de indexarla. El
# resto no se guarda: el export REAL son 177 MB y guardar las 50 columnas de
# cada fila deja el maestro entero residente en `session_state`, que es de donde
# el contenedor de 1 GB **para toda la app** se muere sin dejar traza.
COLUMNAS_QUE_SE_CONSERVAN_DEL_PRODUCTO = (
    "Similar products", "Global category ID", "Global category", "Release date",
    "Page Title", "Meta description",
)
COLUMNAS_QUE_SE_CONSERVAN_DEL_SKU = ("SKU reference code",) + COLUMNAS_DE_MEDIDA


def _recortar(fila, columnas):
    return {columna: texto(fila.get(columna)) for columna in columnas}


class Producto:
    """Un producto del maestro de VTEX, con sus SKUs y sus imagenes."""

    __slots__ = ("id", "nombre", "referencia", "modelo", "marca_id", "marca",
                 "departamento_id", "departamento", "categoria_id", "categoria",
                 "url", "fila", "skus")

    def __init__(self, fila):
        self.fila = _recortar(fila, COLUMNAS_QUE_SE_CONSERVAN_DEL_PRODUCTO)
        self.id = _entero_texto(fila.get("Product ID"))
        self.nombre = texto(fila.get("Product Name"))
        self.referencia = clave_codigo(fila.get("Product reference code"))
        self.modelo = modelo_de_referencia(self.referencia)
        self.marca_id = _entero_texto(fila.get("Brand ID"))
        self.marca = texto(fila.get("Brand"))
        self.departamento_id = _entero_texto(fila.get("Department ID"))
        self.departamento = texto(fila.get("Department"))
        self.categoria_id = _entero_texto(fila.get("Category ID"))
        self.categoria = texto(fila.get("Category"))
        self.url = texto(fila.get("Product URL"))
        self.skus = []


class Sku:
    """Un SKU del maestro, colgado de su producto."""

    __slots__ = ("id", "nombre", "referencia", "ean", "codigo_fabricante",
                 "producto_id", "talla", "fila")

    def __init__(self, fila, producto_id):
        self.fila = _recortar(fila, COLUMNAS_QUE_SE_CONSERVAN_DEL_SKU)
        self.id = _entero_texto(fila.get("SKU ID"))
        self.nombre = texto(fila.get("SKU name"))
        self.referencia = clave_codigo(fila.get("SKU reference code"))
        self.ean = clave_codigo(fila.get("EAN/UPC"))
        self.codigo_fabricante = clave_codigo(fila.get("Manufacturer code"))
        self.producto_id = producto_id
        self.talla = talla_de_nombre_de_sku(self.nombre)


def modelo_de_referencia(referencia):
    """`HP102011307-251` -> `HP102011307`. El codigo de modelo, sin el color."""
    codigo = clave_codigo(referencia)
    return codigo.rsplit("-", 1)[0] if "-" in codigo else codigo


_PREFIJO_TALLA = re.compile(r"^\s*talla\s+", re.IGNORECASE)


def talla_de_nombre_de_sku(nombre):
    """`TALLA 39` -> `39`. Lo que no lleva el prefijo se devuelve tal cual."""
    crudo = texto(nombre)
    sin_prefijo = _PREFIJO_TALLA.sub("", crudo)
    return sin_prefijo.strip()


def nombre_de_sku(talla):
    """`39` -> `TALLA 39`. Es como se llaman TODOS los SKU de esta tienda."""
    return "TALLA %s" % texto(talla).upper()


class CatalogoVTEX:
    """El maestro: lo que VTEX ya tiene, indexado para emparejar.

    Todo lo que hace falta para no duplicar un producto sale de aqui: los
    Product ID y SKU ID que hay que REUSAR, los IDs de marca y de categoria que
    no se pueden inventar, y el dominio de cada especificacion.
    """

    def __init__(self):
        self.productos = {}              # product_id -> Producto
        self.por_referencia = {}         # Mod-Col -> [Producto]
        # Por MODELO, o sea el codigo sin el color. Es lo que hace que el
        # ultimo escalon de la escalera cueste una busqueda y no un recorrido
        # del maestro entero: con 9.000 fichas y 20.000 productos eso son 180
        # millones de vueltas, y el maestro no cambia entre una ficha y otra.
        self.por_modelo = {}             # Modelo -> [Producto]
        self.skus = {}                   # sku_id -> Sku
        self.sku_por_referencia = {}     # RefId -> [Sku]
        self.sku_por_ean = {}            # EAN -> [Sku]
        self.sku_por_fabricante = {}     # Manufacturer code -> [Sku]
        self.marcas = {}                 # clave(marca) -> (id, nombre)
        self.categorias = {}             # (clave(dept), clave(cat)) -> (dept_id, dept, cat_id, cat)
        self.categorias_por_departamento = {}   # clave(dept) -> [(cat_id, cat)]
        self.departamentos = {}          # clave(dept) -> (id, nombre)
        # Dos indices por cada juego de campos, y hacen falta los dos:
        #  - por ID: es la LISTA de campos de la categoria, y ahi no se puede
        #    deduplicar por nombre porque la tienda tiene TRES campos que se
        #    llaman "Tecnologia " (26, 94 y 117). Con un indice por nombre se
        #    escribirian dos filas de menos.
        #  - por nombre: es como se BUSCA un campo para ponerle un valor.
        self.campos_de_producto = {}     # categoria_id -> {id_campo: Campo}
        self.campos_de_sku = {}          # categoria_id -> {id_campo: Campo}
        self.campos_producto_por_nombre = {}  # categoria_id -> {clave(nombre): Campo}
        self.campos_sku_por_nombre = {}
        self.campos_producto_globales = {}   # clave(nombre) -> Campo
        self.campos_sku_globales = {}
        self.campos_producto_globales_por_id = {}
        self.campos_sku_globales_por_id = {}
        # Solo el `IDs de especificacion` de cada (producto, campo), no la fila
        # entera: en el export real son ~1.000.000 de filas de 16 columnas.
        self.especificaciones_de_producto = {}   # (product_id, clave(campo)) -> id
        # De las imagenes solo hace falta saber que direcciones tiene ya cada
        # SKU, para no cargar la misma foto dos veces, y cuantas son.
        self.imagenes_de_sku = {}        # sku_id -> [{Ruta, URL de importacion}]
        # La cabecera TAL CUAL la trae el archivo del usuario: es la plantilla
        # que su VTEX espera de vuelta, y sale en el idioma de su admin.
        self.cabeceras = {}              # archivo -> tuple(columnas del archivo)
        # `canonico -> nombre en ESE archivo`. El motor trabaja en canonico y
        # esto es lo que lo devuelve al idioma del export al escribir.
        self.nombres_de_columna = {}     # archivo -> {canonico: nombre original}
        # El "si" y el "no" tal y como los escribe la tienda (`Yes`/`Sí`).
        self.afirmativo = ""
        self.negativo = ""
        self.dimensiones = {}            # (clave(dept), clave(cat)) -> dict de medidas
        self.dimensiones_por_defecto = {}
        self.valores_por_defecto = {}    # columna -> valor mas repetido
        self.avisos = []

    # -- consulta ---------------------------------------------------------
    def producto_por_referencia(self, referencia):
        return self.por_referencia.get(clave_codigo(referencia)) or []

    def campo_de_producto(self, categoria_id, nombre):
        por_categoria = self.campos_producto_por_nombre.get(_entero_texto(categoria_id)) or {}
        return por_categoria.get(clave(nombre)) or self.campos_producto_globales.get(clave(nombre))

    def campo_de_sku(self, categoria_id, nombre):
        por_categoria = self.campos_sku_por_nombre.get(_entero_texto(categoria_id)) or {}
        return por_categoria.get(clave(nombre)) or self.campos_sku_globales.get(clave(nombre))

    def campos_de_la_categoria(self, categoria_id, de_sku=False):
        """Los campos de esa categoria, en el orden en el que VTEX los exporto.

        Si la categoria no esta en el maestro -- una categoria a la que todavia
        no se ha cargado nada -- se cae al juego global, que es la union de lo
        que se ha visto. Es menos preciso, pero una planilla sin ni una fila de
        especificacion deja el producto sin genero, sin tipo y sin color.
        """
        fuente = self.campos_de_sku if de_sku else self.campos_de_producto
        globales = (self.campos_sku_globales_por_id if de_sku
                    else self.campos_producto_globales_por_id)
        por_categoria = fuente.get(_entero_texto(categoria_id))
        campos = list((por_categoria or globales).values())
        campos.sort(key=lambda campo: _orden_de_campo(campo.id))
        return campos

    def columna(self, archivo, nombre_canonico):
        """Como se llama esa columna en el archivo que subio el usuario."""
        return (self.nombres_de_columna.get(archivo) or {}).get(
            nombre_canonico, nombre_canonico)

    def como_el_export(self, archivo, fila):
        """La fila, con las columnas en el orden y el idioma del export.

        El motor entero trabaja en nombre canonico; esta es la UNICA puerta por
        la que la salida vuelve al idioma del archivo del usuario. Una plantilla
        de VTEX con una columna que no reconoce la rechaza el importador.
        """
        nombres = self.nombres_de_columna.get(archivo) or {}
        salida = {}
        for columna in self.cabeceras.get(archivo) or COLUMNAS[archivo]:
            salida[columna] = ""
        for nombre_canonico, valor in fila.items():
            salida[nombres.get(nombre_canonico, nombre_canonico)] = valor
        return salida

    def si(self):
        """El "sí" de este export (`Yes`, `Sí`...), o el de la plantilla."""
        return self.afirmativo or "Yes"

    def no(self):
        return self.negativo or "No"

    def medidas_de(self, departamento, categoria):
        """Las medidas de empaque que la tienda ya usa para esa categoria.

        No se inventan: son las mas repetidas del propio maestro. Sin dato para
        la categoria se cae a las mas repetidas de la tienda entera, y eso se
        REPORTA -- un peso de empaque equivocado es un costo de envio equivocado.
        """
        medidas = self.dimensiones.get((clave(departamento), clave(categoria)))
        if medidas:
            return dict(medidas), False
        return dict(self.dimensiones_por_defecto), True


def _orden_de_campo(id_campo):
    try:
        return (0, int(id_campo))
    except (TypeError, ValueError):
        return (1, texto(id_campo))


def _acumular(indice, llave, valor):
    if not llave:
        return
    indice.setdefault(llave, []).append(valor)


def _mas_repetido(valores):
    conteo = {}
    for valor in valores:
        if not texto(valor):
            continue
        conteo[texto(valor)] = conteo.get(texto(valor), 0) + 1
    if not conteo:
        return ""
    return max(conteo.items(), key=lambda par: (par[1], par[0]))[0]


def reconocer_archivo(columnas):
    """Que planilla es, mirando su cabecera. `""` si no es ninguna de las cuatro."""
    columnas = list(columnas or ())
    # Se prueba con los nombres TAL CUAL y tambien traducidos: el export de
    # productos sale en el idioma del admin, y las otras tres planillas no se
    # traducen (ahi el canonico es su propio nombre).
    presentes = {clave(columna) for columna in columnas}
    presentes |= {clave(canonico(columna)) for columna in columnas}
    for archivo, firma in FIRMAS:
        if all(columna in presentes for columna in firma):
            return archivo
    return ""


def _fuentes_de(archivos, nombre):
    """Las fuentes de una planilla, admitiendo las dos formas de pasarla.

    - `{archivo: [fila, fila, ...]}` -- la lista ya materializada, que es lo
      comodo para una prueba.
    - `{archivo: [iterable, iterable]}` -- un iterable POR HOJA, que es lo que
      usa la pantalla.

    La segunda no es un capricho: el export real son **177 MB**, y
    materializarlo como listas de diccionarios son **1,7 GB medidos** con un
    contenedor que da **1 GB para toda la app**. Es la regla de la seccion 5
    nonies de CLAUDE.md -- ningun archivo del usuario se materializa entero: se
    recorre y solo se conserva lo que se va a usar.

    Se distinguen por el primer elemento: un diccionario es una fila.
    """
    fuentes = (archivos or {}).get(nombre)
    if not fuentes:
        return []
    if isinstance(fuentes, dict):
        return [[fuentes]]
    primero = fuentes[0] if isinstance(fuentes, (list, tuple)) else None
    if isinstance(primero, dict):
        return [fuentes]
    return list(fuentes)


def _recorrer(catalogo, archivos, nombre, indexar, progreso=None):
    """Pasa cada fila por `indexar` sin quedarse con ninguna.

    La cabecera se toma de la primera fila y **se guarda**: es la que manda al
    escribir la salida, porque una planilla de VTEX con una columna de mas o de
    menos la rechaza el importador.
    """
    leidas = 0
    for fuente in _fuentes_de(archivos, nombre):
        for fila in fuente:
            leidas += 1
            # El aviso cada 20.000 filas, no en cada una: con 1.000.000 de filas
            # llamar a la pantalla por cada una cuesta mas que leerlas.
            if progreso and leidas % 20000 == 0:
                progreso(nombre, leidas)
            if nombre not in catalogo.cabeceras:
                catalogo.cabeceras[nombre] = tuple(fila.keys())
                catalogo.nombres_de_columna[nombre] = {
                    canonico(columna, nombre): columna for columna in fila.keys()}
            indexar(catalogo, traducir_fila(fila, nombre))
    if progreso and leidas:
        progreso(nombre, leidas)


def leer_catalogo(archivos, progreso=None):
    """Indexa las cuatro planillas y **no se queda con el archivo**.

    Las hojas de un mismo archivo se recorren una detras de otra: VTEX parte el
    export de especificaciones por el limite de filas de Excel, no por
    contenido, y las hojas no comparten ni un producto.

    `progreso(planilla, filas)` es opcional y **nunca puede tumbar la lectura**:
    el catalogo real son cuatro archivos de cientos de miles de filas y un
    spinner mudo durante minutos se lee como "se colgo".
    """
    catalogo = CatalogoVTEX()
    acumulado = _AcumuladorDeMedidas()
    aviso = _aviso_seguro(progreso)
    _recorrer(catalogo, archivos, PRODUCTOS,
              lambda c, fila: _indexar_producto(c, fila, acumulado), aviso)
    acumulado.volcar(catalogo)
    _recorrer(catalogo, archivos, ESPEC_PRODUCTO,
              lambda c, fila: _indexar_especificacion(c, fila, de_sku=False), aviso)
    _recorrer(catalogo, archivos, ESPEC_SKU,
              lambda c, fila: _indexar_especificacion(c, fila, de_sku=True), aviso)
    _recorrer(catalogo, archivos, IMAGENES, _indexar_imagen, aviso)
    return catalogo


def _aviso_seguro(progreso):
    """El aviso de avance, envuelto para que un fallo suyo no corte la lectura."""
    if not progreso:
        return None

    def avisar(planilla, filas):
        try:
            progreso(planilla, filas)
        except Exception:  # noqa: BLE001
            pass

    return avisar


class _AcumuladorDeMedidas:
    """Cuenta las medidas y los ajustes de la tienda mientras se recorre.

    Va aparte del catalogo porque solo vive durante la lectura: lo que queda
    guardado es el resultado -- las mas repetidas por categoria --, no los
    contadores de 160.000 filas.
    """

    __slots__ = ("por_categoria", "globales", "heredadas")

    def __init__(self):
        self.por_categoria = {}
        self.globales = {columna: {} for columna in COLUMNAS_DE_MEDIDA}
        self.heredadas = {columna: {} for columna in COLUMNAS_HEREDADAS}

    def anotar(self, fila):
        llave = (clave(fila.get("Department")), clave(fila.get("Category")))
        acumulado = self.por_categoria.setdefault(
            llave, {columna: {} for columna in COLUMNAS_DE_MEDIDA})
        for columna in COLUMNAS_DE_MEDIDA:
            valor = texto(fila.get(columna))
            if valor:
                acumulado[columna][valor] = acumulado[columna].get(valor, 0) + 1
                self.globales[columna][valor] = self.globales[columna].get(valor, 0) + 1
        for columna in COLUMNAS_HEREDADAS:
            valor = texto(fila.get(columna))
            if valor:
                self.heredadas[columna][valor] = self.heredadas[columna].get(valor, 0) + 1

    def aprender_si_y_no(self, catalogo, fila):
        """El "sí" y el "no" con la forma EXACTA que usa este export.

        Se toman del propio archivo en vez de escribir `Yes` a pelo: el export
        real sale en el idioma del admin y un `Yes` en una planilla en espanol
        deja el producto sin activar.
        """
        if not catalogo.afirmativo:
            for columna in COLUMNAS_AFIRMATIVAS:
                valor = texto(fila.get(columna))
                if valor and es_afirmativo(valor):
                    catalogo.afirmativo = valor
                    break
        if not catalogo.negativo:
            for columna in COLUMNAS_NEGATIVAS + COLUMNAS_AFIRMATIVAS:
                valor = texto(fila.get(columna))
                if valor and not es_afirmativo(valor):
                    catalogo.negativo = valor
                    break

    def volcar(self, catalogo):
        for llave, acumulado in self.por_categoria.items():
            resueltas = {c: _mas_repetido(v) for c, v in acumulado.items()}
            if any(resueltas.values()):
                catalogo.dimensiones[llave] = resueltas
        catalogo.dimensiones_por_defecto = {
            c: _mas_repetido(v) for c, v in self.globales.items()}
        catalogo.valores_por_defecto = {
            c: _mas_repetido(v) for c, v in self.heredadas.items()}


def _indexar_producto(catalogo, fila, acumulado):
    """Una fila de `Products and SKUs`: es un SKU con su producto repetido."""
    product_id = _entero_texto(fila.get("Product ID"))
    if not product_id:
        return
    producto = catalogo.productos.get(product_id)
    if producto is None:
        producto = Producto(fila)
        catalogo.productos[product_id] = producto
        _acumular(catalogo.por_referencia, producto.referencia, producto)
        _acumular(catalogo.por_modelo, producto.modelo, producto)
        if producto.marca:
            catalogo.marcas.setdefault(clave(producto.marca),
                                       (producto.marca_id, producto.marca))
        if producto.categoria:
            llave = (clave(producto.departamento), clave(producto.categoria))
            catalogo.categorias.setdefault(
                llave,
                (producto.departamento_id, producto.departamento,
                 producto.categoria_id, producto.categoria),
            )
            catalogo.departamentos.setdefault(
                clave(producto.departamento),
                (producto.departamento_id, producto.departamento))
            por_departamento = catalogo.categorias_por_departamento.setdefault(
                clave(producto.departamento), [])
            if (producto.categoria_id, producto.categoria) not in por_departamento:
                por_departamento.append((producto.categoria_id, producto.categoria))
    sku_id = _entero_texto(fila.get("SKU ID"))
    if sku_id and sku_id not in catalogo.skus:
        sku = Sku(fila, product_id)
        catalogo.skus[sku_id] = sku
        producto.skus.append(sku)
        _acumular(catalogo.sku_por_referencia, sku.referencia, sku)
        _acumular(catalogo.sku_por_ean, sku.ean, sku)
        _acumular(catalogo.sku_por_fabricante, sku.codigo_fabricante, sku)
    acumulado.anotar(fila)
    acumulado.aprender_si_y_no(catalogo, fila)


# Los nombres de campo cuyo `IDs de especificacion` hace falta recordar. Es el
# id de ESA instancia de texto en ESE producto, y solo sirve para volver a
# escribir el mismo campo del mismo producto. Guardarlos todos son 1.060.000
# entradas en el export real -- cientos de MB -- de las que se leen 18.
_CAMPOS_CON_ID_QUE_SE_GUARDA = None


def _campo_guarda_su_id(nombre):
    global _CAMPOS_CON_ID_QUE_SE_GUARDA
    if _CAMPOS_CON_ID_QUE_SE_GUARDA is None:
        _CAMPOS_CON_ID_QUE_SE_GUARDA = {clave(n) for n in CAMPOS_DESDE_LA_FICHA}
    return clave(nombre) in _CAMPOS_CON_ID_QUE_SE_GUARDA


def _indexar_especificacion(catalogo, fila, de_sku):
    """Una fila de especificacion: el campo con su dominio, y su valor.

    El objeto `Campo` se construye **solo la primera vez que aparece** ese campo
    en esa categoria. Construirlo en cada fila es rehacer el diccionario de sus
    330 valores de dominio 1.060.000 veces: medido, 146 s de los que 140 eran
    esto.
    """
    nombre = texto(fila.get("Nombre del campo"))
    if not nombre:
        return
    categoria_id = _entero_texto(fila.get("ID de categoría"))
    id_campo = _entero_texto(fila.get("ID de campo"))
    destino = catalogo.campos_de_sku if de_sku else catalogo.campos_de_producto
    por_nombre = (catalogo.campos_sku_por_nombre if de_sku
                  else catalogo.campos_producto_por_nombre)
    globales = catalogo.campos_sku_globales if de_sku else catalogo.campos_producto_globales
    globales_por_id = (catalogo.campos_sku_globales_por_id if de_sku
                       else catalogo.campos_producto_globales_por_id)
    de_la_categoria = destino.setdefault(categoria_id, {})
    campo = de_la_categoria.get(id_campo)
    ids_dominio = None
    if campo is None or not campo.valores:
        ids_dominio = _lista(fila.get("IDs de valores de campo"))
        # Se queda el que trae dominio: una fila cualquiera puede venir con las
        # dos columnas vacias y borraria la lista de valores.
        if campo is None or ids_dominio:
            campo = Campo(id_campo, nombre, texto(fila.get("Tipo de campo")),
                          ids_dominio, _lista(fila.get("Valores de campo")))
            for indice, llave in ((de_la_categoria, id_campo),
                                  (globales_por_id, id_campo),
                                  (por_nombre.setdefault(categoria_id, {}), clave(nombre)),
                                  (globales, clave(nombre))):
                anterior = indice.get(llave)
                if anterior is None or (not anterior.valores and campo.valores):
                    indice[llave] = campo
    # El ID de instancia solo hace falta para los campos de TEXTO de un producto
    # que la app sabe rellenar: es con lo que VTEX actualiza ese texto en vez de
    # crear otro. En los de SKU no se usa -- ahi los dos campos son `Radio` y su
    # ID sale del dominio.
    if de_sku or not _campo_guarda_su_id(nombre):
        return
    identidad = _entero_texto(fila.get("ID del producto"))
    valor = _entero_texto(fila.get("IDs de especificación"))
    if identidad and valor:
        catalogo.especificaciones_de_producto.setdefault((identidad, clave(nombre)), valor)


def _indexar_imagen(catalogo, fila):
    """De una imagen solo se guarda su DIRECCION y su SKU.

    Con eso se responden las dos preguntas que hay que responder: cuantas tiene
    ya ese SKU -- para no empezar la numeracion encima de las suyas -- y si la
    que se va a cargar es una que ya esta -- para no publicar la misma foto dos
    veces. El resto de la fila no lo lee nadie, y en el export real son 640.000
    filas de 12 columnas.
    """
    sku_id = _entero_texto(fila.get("ID de SKU"))
    if not sku_id:
        return
    direccion = (texto(fila.get("Ruta de la imagen"))
                 or texto(fila.get("URL de importación de la imagen")))
    catalogo.imagenes_de_sku.setdefault(sku_id, []).append(direccion)


def _lista(valor):
    """La lista separada por comas de una celda del export."""
    crudo = texto(valor)
    if not crudo:
        return []
    return [parte.strip() for parte in crudo.split(",")]


# --- El emparejamiento -------------------------------------------------------
#
# La escalera que pidio el usuario, en su orden. Cada escalon dice POR QUE se
# emparejo: cuando un producto salga raro, la pregunta va a ser "por que la app
# creyo que este era ese", y tiene que poder responderse sin abrir VTEX.

POR_REFERENCIA_SKU = "SKU/RefId"
POR_EAN = "EAN"
POR_CODIGO_ARTI = "Código ARTI (Modelo-Color)"
POR_ID_VTEX = "Product/SKU ID del archivo"
POR_MODELO_COLOR_TALLA = "Modelo+Color+Talla"
POR_TALLA = "Talla dentro del producto"

ESCALERA = (POR_REFERENCIA_SKU, POR_EAN, POR_CODIGO_ARTI, POR_ID_VTEX,
            POR_MODELO_COLOR_TALLA)

AMBIGUO = "Más de un producto de VTEX responde al mismo dato"
AMBIGUO_SKU = "Más de un SKU de VTEX responde al mismo dato"
SIN_MARCA_VTEX = "La marca no existe en VTEX"
SIN_CATEGORIA_VTEX = "No hay categoría en VTEX para ese tipo de prenda"
SIN_TALLAS = "El producto no trae ninguna talla"
SIN_TITULO = "Sin nombre de producto"
SIN_CODIGO = "Sin código Modelo-Color"


def _unicos(productos):
    """Los productos distintos, por ID y conservando el orden de llegada."""
    vistos, salida = set(), []
    for producto in productos:
        if producto.id in vistos:
            continue
        vistos.add(producto.id)
        salida.append(producto)
    return salida


def _candidatos_por_escalon(ficha, catalogo):
    """`[(criterio, [Producto, ...]), ...]` en el orden de la escalera.

    Un escalon que no encuentra nada no corta la busqueda: se pasa al
    siguiente. Un escalon que encuentra DOS productos distintos si corta, y
    manda el registro a REVISAR -- ese es justo el caso en el que "el primero
    que caiga" escribiria encima de otro producto.
    """
    variantes = ficha.get("Variantes") or []
    escalones = []

    por_refid = []
    for variante in variantes:
        for sku in catalogo.sku_por_referencia.get(clave_codigo(variante.get("SKU"))) or []:
            producto = catalogo.productos.get(sku.producto_id)
            if producto is not None:
                por_refid.append(producto)
    escalones.append((POR_REFERENCIA_SKU, _unicos(por_refid)))

    por_ean = []
    for variante in variantes:
        for sku in catalogo.sku_por_ean.get(clave_codigo(variante.get("EAN"))) or []:
            producto = catalogo.productos.get(sku.producto_id)
            if producto is not None:
                por_ean.append(producto)
    escalones.append((POR_EAN, _unicos(por_ean)))

    codigo = clave_codigo(ficha.get("Mod-Col"))
    por_codigo = list(catalogo.producto_por_referencia(codigo))
    for sku in catalogo.sku_por_fabricante.get(codigo) or []:
        producto = catalogo.productos.get(sku.producto_id)
        if producto is not None:
            por_codigo.append(producto)
    escalones.append((POR_CODIGO_ARTI, _unicos(por_codigo)))

    # El ID que venga escrito en el archivo del usuario. No se busca: se
    # comprueba que exista, porque un ID que no esta en el maestro es un ID
    # equivocado y cargar con el sobrescribe otro producto.
    por_id = []
    pedido = _entero_texto(ficha.get("Product ID"))
    if pedido and pedido in catalogo.productos:
        por_id.append(catalogo.productos[pedido])
    for variante in variantes:
        sku = catalogo.skus.get(_entero_texto(variante.get("SKU ID")))
        if sku is not None:
            producto = catalogo.productos.get(sku.producto_id)
            if producto is not None:
                por_id.append(producto)
    escalones.append((POR_ID_VTEX, _unicos(por_id)))

    # Modelo + Color. Es el codigo partido: sirve cuando el Mod-Col no coincide
    # exactamente pero el modelo y el color si -- un separador distinto, un cero
    # a la izquierda. El color se compara por su NOMBRE ademas de por su codigo.
    #
    # Va por el indice `por_modelo`, no recorriendo el maestro: el maestro no
    # cambia entre una ficha y otra, y recorrerlo por ficha son 180 millones de
    # vueltas con una carga real.
    por_modelo = []
    modelo = clave_codigo(ficha.get("Modelo")) or modelo_de_referencia(codigo)
    color = clave(ficha.get("Color"))
    color_codigo = clave_codigo(ficha.get("Color codigo"))
    if modelo and len(modelo) >= 4:
        for producto in catalogo.por_modelo.get(modelo) or []:
            resto = producto.referencia[len(modelo):].lstrip("-")
            if not resto:
                continue
            if resto == color_codigo or (color and clave(resto) == color):
                por_modelo.append(producto)
    escalones.append((POR_MODELO_COLOR_TALLA, _unicos(por_modelo)))
    return escalones


def emparejar_producto(ficha, catalogo):
    """`(producto, criterio, motivo)` para una ficha.

    `producto` es `None` cuando no existe en VTEX (es nuevo) o cuando hay que
    revisarlo; los dos casos se distinguen por `motivo`.
    """
    for criterio, candidatos in _candidatos_por_escalon(ficha, catalogo):
        if not candidatos:
            continue
        if len(candidatos) > 1:
            detalle = ", ".join(p.id for p in candidatos[:5])
            return None, criterio, "%s (%s): %s" % (AMBIGUO, criterio, detalle)
        return candidatos[0], criterio, ""
    return None, "", ""


def emparejar_sku(variante, producto, catalogo):
    """`(sku, criterio, motivo)` de una talla dentro de un producto ya resuelto.

    Se busca SOLO dentro del producto: un RefId que apunte a otro producto no
    es este SKU, y usarlo movería la talla de sitio.
    """
    if producto is None:
        return None, "", ""
    escalones = (
        (POR_REFERENCIA_SKU,
         [s for s in producto.skus if s.referencia and s.referencia == clave_codigo(variante.get("SKU"))]),
        (POR_EAN,
         [s for s in producto.skus if s.ean and s.ean == clave_codigo(variante.get("EAN"))]),
        (POR_ID_VTEX,
         [s for s in producto.skus if s.id and s.id == _entero_texto(variante.get("SKU ID"))]),
        (POR_TALLA,
         [s for s in producto.skus if s.talla and clave(s.talla) == clave(variante.get("Talla"))]),
    )
    for criterio, candidatos in escalones:
        if not candidatos:
            continue
        if len(candidatos) > 1:
            detalle = ", ".join(s.id for s in candidatos[:5])
            return None, criterio, "%s (%s): %s" % (AMBIGUO_SKU, criterio, detalle)
        return candidatos[0], criterio, ""
    return None, "", ""


def emparejar(fichas, catalogo, nombres_de_tipo=None):
    """El cruce entero: una entrada por ficha, con su estado y el de cada talla.

    No escribe nada. Lo que sale de aqui es lo que la pantalla enseña como
    "excepciones": todo lo que quede en REVISAR.

    **Aqui se resuelve tambien el arbol** -- marca, departamento y categoria de
    VTEX --, no al generar. La pantalla pide revisar las excepciones ANTES de
    generar: un producto cuya categoria no se pudo resolver tiene que salir en
    esa lista, no aparecer despues como una fila que se cayo del archivo sin que
    nadie la hubiera visto.
    """
    salida = []
    for ficha in fichas or []:
        codigo = clave_codigo(ficha.get("Mod-Col"))
        producto, criterio, motivo = emparejar_producto(ficha, catalogo)
        bloqueos = []
        if not codigo:
            bloqueos.append(SIN_CODIGO)
        if not texto(ficha.get("Title")):
            bloqueos.append(SIN_TITULO)
        if not (ficha.get("Variantes") or []):
            bloqueos.append(SIN_TALLAS)
        if motivo:
            bloqueos.append(motivo)

        variantes = []
        for variante in ficha.get("Variantes") or []:
            sku, criterio_sku, motivo_sku = emparejar_sku(variante, producto, catalogo)
            if motivo_sku:
                bloqueos.append(motivo_sku)
            variantes.append({
                "Talla": texto(variante.get("Talla")),
                "SKU ARTI": texto(variante.get("SKU")),
                "EAN": texto(variante.get("EAN")),
                "SKU ID": sku.id if sku is not None else "",
                "Criterio": criterio_sku,
                "Estado": REVISAR if motivo_sku else (EXISTE if sku is not None else NUEVO),
                "_sku": sku,
                "_variante": variante,
            })

        contexto = preparar_contexto(ficha, producto, catalogo, nombres_de_tipo)
        bloqueos.extend(contexto.motivos)

        if bloqueos:
            estado = REVISAR
        elif producto is not None:
            estado = EXISTE
        else:
            estado = NUEVO
        salida.append({
            "Mod-Col": codigo,
            "Nombre": texto(ficha.get("Title")),
            "Marca": texto(ficha.get("Marca")),
            "Estado": estado,
            "Criterio": criterio,
            "Product ID": producto.id if producto is not None else "",
            "Motivos": " · ".join(dict.fromkeys(bloqueos)),
            "Tallas": len(variantes),
            "Tallas nuevas": sum(1 for v in variantes if v["Estado"] == NUEVO),
            "Departamento": contexto.departamento,
            "Categoria": contexto.categoria,
            "Variantes": variantes,
            "_producto": producto,
            "_ficha": ficha,
            "_contexto": contexto,
        })
    return salida


def resumen_del_emparejamiento(emparejados):
    """Los numeros del cruce. Reparten el total y suman el total."""
    resumen = {
        "Productos": len(emparejados or []),
        EXISTE: 0, NUEVO: 0, REVISAR: 0,
        "SKU existentes": 0, "SKU nuevos": 0,
        "Por criterio": {},
    }
    for entrada in emparejados or []:
        resumen[entrada["Estado"]] = resumen.get(entrada["Estado"], 0) + 1
        if entrada["Criterio"]:
            resumen["Por criterio"][entrada["Criterio"]] = (
                resumen["Por criterio"].get(entrada["Criterio"], 0) + 1)
        for variante in entrada["Variantes"]:
            if variante["Estado"] == EXISTE:
                resumen["SKU existentes"] += 1
            elif variante["Estado"] == NUEVO:
                resumen["SKU nuevos"] += 1
    return resumen


def filas_de_excepciones(emparejados):
    """Solo lo que hay que mirar. Lo correcto no se revisa.

    Es el filtro que pidio el usuario: de una carga de miles, la pantalla
    enseña las decenas que no se pudieron resolver solas.
    """
    filas = []
    for entrada in emparejados or []:
        if entrada["Estado"] != REVISAR:
            continue
        filas.append({
            "Mod-Col": entrada["Mod-Col"],
            "Nombre": entrada["Nombre"],
            "Marca": entrada["Marca"],
            "Product ID": entrada["Product ID"],
            "Criterio": entrada["Criterio"],
            "Qué revisar": entrada["Motivos"],
        })
    return filas


# --- De que dato sale cada especificacion ------------------------------------
#
# El nombre del campo en VTEX, y de donde sale su valor en la ficha consolidada
# de Shopify + ARTI. Lo que no esta aqui sale `---`, que es exactamente lo que
# escribe el export de VTEX para una especificacion sin contenido.
#
# Un nombre que se repite en varios campos -- la tienda tiene TRES "Tecnologia "
# (26, 94 y 117) -- se rellena SOLO en el de ID mas bajo. Escribir el mismo
# valor en los tres no es enriquecer: es triplicar el dato en la ficha.
CAMPOS_DESDE_LA_FICHA = {
    "Tipo de Producto": "Tipo",
    "Género": "Genero",
    "Clase": "Clase",
    "Color": "Color",
    "Color Comercial": "Color comercial",
    "Modelo": "Modelo",
    "Temporada": "Temporada",
    "Colecciones": "Coleccion",
    "Ocasión": "Ocasion",
    "Deportes": "Deporte",
    "Actividad": "Actividad",
    "Material": "Material",
    "Composición": "Composicion",
    "Cuidado de lavado": "Cuidados",
    "Caracteristicas": "Caracteristicas",
    "Características principales": "Caracteristicas",
    "Descripción Modelo": "Descripcion corta",
    "Tecnología": "Tecnologia",
    "Guía de Tallas": "Guia de tallas",
    "Producto Nuevo": "Producto nuevo",
}

# Los departamentos son el GENERO, no la marca ni la clase. Salen del propio
# maestro (Hombre 25, Mujer 1, Ninos 46, Accesorios 59): aqui solo se dice con
# que genero se busca cada uno. Un genero que no cae en ninguno -- Unisex -- NO
# se adivina: el producto queda en REVISAR con su motivo.
DEPARTAMENTO_POR_GENERO = {
    "hombre": "Hombre",
    "masculino": "Hombre",
    "mujer": "Mujer",
    "femenino": "Mujer",
    "nino": "Niños",
    "nina": "Niños",
    "ninos": "Niños",
    "ninas": "Niños",
    "ninos unisex": "Niños",
    "infantil": "Niños",
    "kids": "Niños",
}

# La clase que manda sobre el genero: un gorro es de Accesorios aunque sea de
# hombre, que es como esta armado el arbol de esta tienda.
DEPARTAMENTO_POR_CLASE = {"accesorios": "Accesorios"}

DIVISOR_PESO_CUBICO = 4800.0


def _peso_cubico(medidas):
    """El peso volumetrico, con la formula que usa la propia tienda.

    Comprobado contra el export: 34 x 49.5 x 14 / 4800 = 4,9088, que es
    exactamente lo que trae la columna. No se copia el del maestro porque las
    medidas pueden venir de otra categoria.
    """
    ancho = _numero(medidas.get("Package width"))
    alto = _numero(medidas.get("Package height"))
    largo = _numero(medidas.get("Package length"))
    if None in (ancho, alto, largo):
        return ""
    return ("%.4f" % (ancho * alto * largo / DIVISOR_PESO_CUBICO)).rstrip("0").rstrip(".")


def resolver_departamento(ficha, catalogo):
    """`(dept_id, nombre, motivo)`. Sin respuesta clara, motivo y nada mas."""
    clase = clave(ficha.get("Clase"))
    buscado = DEPARTAMENTO_POR_CLASE.get(clase) or DEPARTAMENTO_POR_GENERO.get(
        clave(ficha.get("Genero")))
    if not buscado:
        return "", "", "No se puede saber el departamento: género %r, clase %r" % (
            texto(ficha.get("Genero")) or "vacío", texto(ficha.get("Clase")) or "vacía")
    encontrado = catalogo.departamentos.get(clave(buscado))
    if not encontrado:
        return "", "", "El departamento %r no existe en VTEX" % buscado
    return encontrado[0], encontrado[1], ""


def resolver_categoria(ficha, catalogo, departamento, nombres_de_tipo=None):
    """`(cat_id, nombre, motivo)` para el tipo de prenda dentro del departamento.

    El arbol de VTEX es Departamento (genero) -> Categoria (tipo de prenda). La
    categoria se busca por NOMBRE entre las que ese departamento ya tiene, con
    los sinonimos del diccionario de tipos de la app -- que se INYECTA, para que
    sea el mismo que decide el `Type` de Shopify. Dos diccionarios de tipos se
    separan sin que nadie lo note; ya paso una vez en este repositorio.
    """
    candidatas = catalogo.categorias_por_departamento.get(clave(departamento)) or []
    if not candidatas:
        return "", "", "El departamento %r no tiene categorías en el archivo de VTEX" % departamento
    nombres = [texto(ficha.get("Tipo"))]
    if nombres_de_tipo:
        nombres.extend(nombres_de_tipo(ficha.get("Tipo")) or [])
    nombres = [n for n in dict.fromkeys(nombres) if texto(n)]
    for nombre in nombres:
        for categoria_id, categoria in candidatas:
            if clave(categoria) == clave(nombre):
                return categoria_id, categoria, ""
    # Plural y singular. `Zapatos` en VTEX, `Zapato` en el diccionario.
    for nombre in nombres:
        llave = clave(nombre).rstrip("s")
        for categoria_id, categoria in candidatas:
            if clave(categoria).rstrip("s") == llave and llave:
                return categoria_id, categoria, ""
    return "", "", "%s: %r no está entre las categorías de %s" % (
        SIN_CATEGORIA_VTEX, texto(ficha.get("Tipo")) or "sin tipo", departamento)


def resolver_marca(ficha, catalogo):
    """`(brand_id, nombre, motivo)`. Una marca que no esta en VTEX no se crea."""
    marca = texto(ficha.get("Marca"))
    if not marca:
        return "", "", "El producto no tiene marca"
    encontrada = catalogo.marcas.get(clave(marca))
    if not encontrada:
        return "", "", "%s: %r. Créala en VTEX antes de cargar." % (SIN_MARCA_VTEX, marca)
    return encontrada[0], encontrada[1], ""


class Contexto:
    """Lo que el producto necesita para escribirse, ya resuelto.

    Se calcula UNA vez por producto y lo usan los cuatro archivos: sin esto,
    cada archivo resolveria la categoria por su cuenta y podrian discrepar --
    un producto en la categoria 41 en la planilla de productos y en la 42 en la
    de especificaciones es un producto que VTEX carga mal.
    """

    __slots__ = ("producto", "ficha", "catalogo", "product_id", "nombre",
                 "referencia", "marca_id", "marca", "departamento_id",
                 "departamento", "categoria_id", "categoria", "url", "medidas",
                 "medidas_heredadas", "motivos", "nuevo")

    def __init__(self, catalogo=None):
        self.catalogo = catalogo
        self.motivos = []
        self.medidas_heredadas = False

    def especificacion_anterior(self, nombre_del_campo):
        """El `IDs de especificacion` que ese producto ya tenia para ese campo.

        En un campo de TEXTO ese id es el de esa instancia y solo vale para el
        mismo producto: reusarlo en otro le escribiria encima.
        """
        if self.catalogo is None or not self.product_id:
            return ""
        return self.catalogo.especificaciones_de_producto.get(
            (self.product_id, clave(nombre_del_campo)), "")


def preparar_contexto(ficha, producto, catalogo, nombres_de_tipo=None):
    """Resuelve marca, arbol, URL y medidas de un producto emparejado.

    Un producto que YA existe en VTEX conserva lo suyo: su ID, su URL, su marca
    y su categoria. Cambiarlas desde aqui seria mover de sitio un producto que
    alguien ya reviso, y la URL ademas es el enlace publico.
    """
    contexto = Contexto(catalogo)
    contexto.ficha = ficha
    contexto.producto = producto
    contexto.nuevo = producto is None
    contexto.referencia = clave_codigo(ficha.get("Mod-Col"))
    contexto.nombre = texto(ficha.get("Title")) or (producto.nombre if producto else "")
    if producto is not None:
        contexto.product_id = producto.id
        contexto.marca_id, contexto.marca = producto.marca_id, producto.marca
        contexto.departamento_id = producto.departamento_id
        contexto.departamento = producto.departamento
        contexto.categoria_id, contexto.categoria = producto.categoria_id, producto.categoria
        contexto.url = producto.url or slug("%s %s" % (contexto.nombre, contexto.referencia))
    else:
        contexto.product_id = ""
        contexto.marca_id, contexto.marca, motivo = resolver_marca(ficha, catalogo)
        if motivo:
            contexto.motivos.append(motivo)
        contexto.departamento_id, contexto.departamento, motivo = resolver_departamento(
            ficha, catalogo)
        if motivo:
            contexto.motivos.append(motivo)
        contexto.categoria_id, contexto.categoria = "", ""
        if contexto.departamento:
            contexto.categoria_id, contexto.categoria, motivo = resolver_categoria(
                ficha, catalogo, contexto.departamento, nombres_de_tipo)
            if motivo:
                contexto.motivos.append(motivo)
        contexto.url = slug("%s %s" % (contexto.nombre, contexto.referencia))
    contexto.medidas, contexto.medidas_heredadas = catalogo.medidas_de(
        contexto.departamento, contexto.categoria)
    return contexto


# --- Los cuatro archivos -----------------------------------------------------


def _fila_vacia(archivo, catalogo):
    """Una fila con TODAS las columnas del archivo, en nombre CANONICO.

    Se escribe en canonico y se traduce al idioma del export justo al salir
    (`como_el_export`): asi el motor no tiene que saber en que idioma vino.
    """
    columnas = catalogo.cabeceras.get(archivo) or COLUMNAS[archivo]
    return {canonico(columna, archivo): "" for columna in columnas}


def _similares(contexto):
    """Los SKU hermanos, tal y como los tenia el producto en VTEX.

    Solo para los que YA existen: en uno nuevo los IDs todavia no existen, y
    escribir ahi los de otro producto lo enlazaria con el producto equivocado.
    """
    if contexto.producto is None:
        return ""
    return texto(contexto.producto.fila.get("Similar products"))


def _substitute_words(contexto, ficha):
    """La cadena de busqueda de VTEX, con la forma que ya usa la tienda:
    `MODELO,MOD-COL,Nombre corto,Marca,Categoria,Departamento`."""
    partes = [
        texto(ficha.get("Modelo")) or contexto.referencia.split("-")[0],
        contexto.referencia,
        texto(ficha.get("Nombre corto")) or contexto.nombre,
        contexto.marca,
        contexto.categoria,
        contexto.departamento,
    ]
    return ",".join(parte for parte in partes if parte)


def _meta_descripcion(contexto):
    return ("COMPRA %s CALIDAD GARANTIZADA. COMPRA FÁCIL DESDE TU CASA EN LÍNEA "
            "Y A MEJOR PRECIO EN NUESTRA TIENDA VIRTUAL %s"
            % (contexto.nombre.upper(), contexto.referencia))


def _referencia_de_sku(variante, contexto, modo):
    """El `SKU reference code` de un SKU NUEVO.

    En este catalogo los SKU existentes tienen `RefId == SKU ID`, y ese numero
    lo asigna VTEX: para un SKU nuevo es imposible saberlo de antemano. Las tres
    salidas posibles, y la que viene por defecto:

    - `arti` (por defecto): el SKU del maestro. Es el codigo real del ERP, y
      ademas hace que la SIGUIENTE carga empareje por el primer escalon de la
      escalera sin tener que adivinar nada.
    - `codigo`: `MODCOL-TALLA`. Sirve cuando el maestro no trae SKU.
    - `vacio`: se deja que VTEX lo resuelva.
    """
    if modo == "vacio":
        return ""
    sku = texto(variante.get("SKU"))
    if modo == "arti" and sku:
        return sku
    return "%s-%s" % (contexto.referencia, texto(variante.get("Talla")).upper())


def construir_productos(contextos, catalogo, referencia_sku="arti"):
    """La planilla `Products and SKUs`: una fila por SKU."""
    filas = []
    for contexto, entrada in contextos:
        ficha = contexto.ficha
        heredado = catalogo.valores_por_defecto
        base = _fila_vacia(PRODUCTOS, catalogo)
        base.update({
            "Product ID": contexto.product_id,
            "Product Name": contexto.nombre,
            "Active product": catalogo.si(),
            "Description": texto(ficha.get("Body HTML")),
            "Additional description": texto(ficha.get("Body HTML")),
            "Brand ID": contexto.marca_id,
            "Brand": contexto.marca,
            "Department ID": contexto.departamento_id,
            "Department": contexto.departamento,
            "Category ID": contexto.categoria_id,
            "Category": contexto.categoria,
            "Sales channels": heredado.get("Sales channels", ""),
            "Product URL": contexto.url,
            "Page Title": contexto.nombre,
            "Meta description": _meta_descripcion(contexto),
            "Display on website": catalogo.si(),
            "Show when out of stock": heredado.get("Show when out of stock", catalogo.no()),
            "Substitute words": _substitute_words(contexto, ficha),
            "Product reference code": contexto.referencia,
            "Tax code": heredado.get("Tax code", ""),
            "Similar products": _similares(contexto),
        })
        if contexto.producto is not None:
            # Lo que ya tiene la tienda y no sale del catalogo de Shopify. La
            # fecha de publicacion y la categoria global son de VTEX: pisarlas
            # con un vacio las borraria.
            for columna in ("Global category ID", "Global category", "Release date",
                            "Page Title", "Meta description"):
                valor = texto(contexto.producto.fila.get(columna))
                if valor:
                    base[columna] = valor
        for variante in entrada["Variantes"]:
            sku = variante["_sku"]
            fila = dict(base)
            medidas = dict(contexto.medidas)
            if sku is not None:
                # Las medidas del SKU que ya existe mandan sobre el promedio de
                # la categoria: alguien las puso a proposito.
                for columna in COLUMNAS_DE_MEDIDA:
                    valor = texto(sku.fila.get(columna))
                    if valor:
                        medidas[columna] = valor
            fila.update({
                "SKU ID": sku.id if sku is not None else "",
                "SKU name": sku.nombre if sku is not None else nombre_de_sku(variante["Talla"]),
                "Activate SKU if possible": catalogo.si(),
                "Active SKU": catalogo.si(),
                "Bundle": catalogo.no(),
                "SKU reference code": (
                    sku.fila.get("SKU reference code") if sku is not None
                    else _referencia_de_sku(variante["_variante"], contexto, referencia_sku)),
                "EAN/UPC": texto(variante.get("EAN")),
                "Manufacturer code": contexto.referencia,
                "Unit of measure": heredado.get("Unit of measure", "un"),
                "Unit multiplier": heredado.get("Unit multiplier", "1"),
                "Commercial condition": heredado.get("Commercial condition", ""),
                "Loyalty amount": heredado.get("Loyalty amount", "0"),
            })
            fila.update(medidas)
            fila["Cubic Weight"] = _peso_cubico(medidas)
            filas.append(catalogo.como_el_export(PRODUCTOS, fila))
    return filas


def _valor_de_campo(campo, contexto, ficha, ya_escritos):
    """`(ids, valores, motivo)` para un campo de especificacion de producto."""
    origen = CAMPOS_DESDE_LA_FICHA.get(clave_de_campo(campo.nombre))
    if not origen:
        return "", VACIO, ""
    if clave_de_campo(campo.nombre) in ya_escritos:
        # El segundo y el tercer campo que se llaman igual se dejan vacios.
        return "", VACIO, ""
    valor = texto(ficha.get(origen))
    if not valor:
        return "", VACIO, ""
    ya_escritos.add(clave_de_campo(campo.nombre))
    if campo.es_lista:
        identificador, ambiguo = campo.id_de(valor)
        if not identificador:
            return "", VACIO, (
                "%r no está entre los valores admitidos del campo %r" % (valor, campo.nombre))
        aviso = ("El campo %r tiene más de un valor %r en VTEX; se usa el %s"
                 % (campo.nombre, valor, identificador)) if ambiguo else ""
        return identificador, valor, aviso
    # Campo de texto: el ID es el de ESA instancia, y solo vale para el mismo
    # producto. En uno nuevo va vacio y VTEX lo crea.
    return contexto.especificacion_anterior(campo.nombre), valor, ""


def clave_de_campo(nombre):
    """La llave con la que se busca un campo en `CAMPOS_DESDE_LA_FICHA`."""
    return texto(nombre).strip()


def construir_especificaciones_de_producto(contextos, catalogo, avisos=None):
    """La planilla de especificaciones de producto: una fila por campo.

    Se emiten TODOS los campos de la categoria, no solo los que se rellenan:
    asi es como los exporta VTEX, y una planilla con menos campos de los que la
    categoria tiene deja el resto sin tocar en vez de vaciarlo.

    Es un GENERADOR: una carga de 9.000 productos son **477.000 filas de 16
    columnas**, y tenerlas todas vivas a la vez costaba **847 MB medidos** de
    los 1.024 que da el contenedor PARA TODA LA APP. Quien la escribe la
    recorre y no se queda con ninguna.
    """
    for contexto, _entrada in contextos:
        if not contexto.categoria_id:
            continue
        ficha = contexto.ficha
        ya_escritos = set()
        for campo in catalogo.campos_de_la_categoria(contexto.categoria_id, de_sku=False):
            identificador, valor, motivo = _valor_de_campo(campo, contexto, ficha, ya_escritos)
            if motivo:
                _anotar_aviso(avisos, contexto.referencia, campo.nombre, motivo)
            fila = _fila_vacia(ESPEC_PRODUCTO, catalogo)
            fila.update({
                "ID del producto": contexto.product_id,
                "Nombre del producto": contexto.nombre,
                "Código de referencia del producto": contexto.referencia,
                "ID de marca": contexto.marca_id,
                "Marca": contexto.marca,
                "ID del departamento": contexto.departamento_id,
                "Departamento": contexto.departamento,
                "ID de categoría": contexto.categoria_id,
                "Categoría": contexto.categoria,
                "ID de campo": campo.id,
                "Nombre del campo": campo.nombre,
                "Tipo de campo": campo.tipo,
                "IDs de valores de campo": ",".join(campo.ids_dominio),
                "Valores de campo": ",".join(campo.valores_dominio),
                "IDs de especificación": identificador,
                "Valores de especificación": valor,
            })
            yield catalogo.como_el_export(ESPEC_PRODUCTO, fila)


def construir_especificaciones_de_sku(contextos, catalogo, avisos=None):
    """La planilla de especificaciones de SKU: `Talla` y `Color`, por SKU.

    Las dos son campos `Radio`, asi que su valor va con el ID del dominio. Una
    talla que la tienda no tiene dada de alta **no se inventa**: sale avisada, y
    lo que hay que hacer es crear ese valor en VTEX. Cargarla con un ID
    cualquiera publicaria otra talla.
    """
    for contexto, entrada in contextos:
        if not contexto.categoria_id:
            continue
        ficha = contexto.ficha
        for variante in entrada["Variantes"]:
            sku = variante["_sku"]
            sku_id = sku.id if sku is not None else ""
            nombre = sku.nombre if sku is not None else nombre_de_sku(variante["Talla"])
            referencia = (texto(sku.fila.get("SKU reference code")) if sku is not None
                          else texto(variante.get("SKU ARTI")))
            for nombre_campo, valor in ((CAMPO_TALLA, variante["Talla"]),
                                        (CAMPO_COLOR, texto(ficha.get("Color")))):
                campo = catalogo.campo_de_sku(contexto.categoria_id, nombre_campo)
                if campo is None:
                    _anotar_aviso(avisos, contexto.referencia, nombre_campo,
                                  "El campo %r no existe en la categoría %r"
                                  % (nombre_campo, contexto.categoria))
                    continue
                identificador, ambiguo = campo.id_de(valor) if texto(valor) else ("", False)
                if texto(valor) and not identificador:
                    _anotar_aviso(
                        avisos, contexto.referencia, nombre_campo,
                        "%r no está dado de alta como %s en VTEX: créalo antes de cargar"
                        % (texto(valor), nombre_campo.lower()))
                elif ambiguo:
                    _anotar_aviso(
                        avisos, contexto.referencia, nombre_campo,
                        "%r tiene más de un valor en VTEX; se usa el %s"
                        % (texto(valor), identificador))
                fila = _fila_vacia(ESPEC_SKU, catalogo)
                fila.update({
                    "ID de SKU": sku_id,
                    "Nombre de SKU": nombre,
                    "Código de referencia de SKU": referencia,
                    "ID de marca": contexto.marca_id,
                    "Marca": contexto.marca,
                    "ID del departamento": contexto.departamento_id,
                    "Departamento": contexto.departamento,
                    "ID de categoría": contexto.categoria_id,
                    "Categoría": contexto.categoria,
                    "ID de campo": campo.id,
                    "Nombre del campo": campo.nombre,
                    "Tipo de campo": campo.tipo,
                    "IDs de valores de campo": ",".join(campo.ids_dominio),
                    "Valores de campo": ",".join(campo.valores_dominio),
                    "IDs de especificación": identificador,
                    "Valores de especificación": texto(valor) or VACIO,
                })
                yield catalogo.como_el_export(ESPEC_SKU, fila)


def construir_imagenes(contextos, catalogo, imagenes_por_sku=0):
    """La planilla de imagenes: una fila por imagen y por SKU.

    En VTEX la imagen cuelga del SKU, no del producto, asi que la misma foto se
    repite en todas las tallas -- que es exactamente lo que hace el export de la
    tienda. El nombre del media es el de la talla (`TALLA-39`), tambien como la
    tienda.

    **La URL de Shopify va en `URL de importación de la imagen`.** Esa columna
    existe para eso: VTEX se la descarga. `Ruta de la imagen` es la que YA tiene
    la tienda y solo se conserva; escribir ahi una URL de Shopify no importaria
    nada.

    Una imagen que el SKU ya tiene con la misma direccion no se repite: VTEX la
    cargaria dos veces y la ficha saldria con la foto duplicada.
    """
    for contexto, entrada in contextos:
        urls = [texto(url) for url in (contexto.ficha.get("Imagenes") or []) if texto(url)]
        if imagenes_por_sku:
            urls = urls[:imagenes_por_sku]
        if not urls:
            continue
        for variante in entrada["Variantes"]:
            sku = variante["_sku"]
            sku_id = sku.id if sku is not None else ""
            nombre_sku = sku.nombre if sku is not None else nombre_de_sku(variante["Talla"])
            referencia = (texto(sku.fila.get("SKU reference code")) if sku is not None
                          else texto(variante.get("SKU ARTI")))
            existentes = catalogo.imagenes_de_sku.get(sku_id) or []
            ya_estan = set(existentes)
            siguiente = len(existentes)
            for url in urls:
                if url in ya_estan:
                    continue
                siguiente += 1
                fila = _fila_vacia(IMAGENES, catalogo)
                fila.update({
                    "ID del producto": contexto.product_id,
                    "Nombre del producto": contexto.nombre,
                    "ID de SKU": sku_id,
                    "Nombre de SKU": nombre_sku,
                    "Código de referencia de SKU": referencia,
                    "ID de la imagen": "",
                    "Nombre de la imagen": slug(nombre_sku).upper(),
                    "Posición de la imagen": "0",
                    "Label de la imagen": str(siguiente),
                    "Texto de la imagen": "",
                    "Ruta de la imagen": "",
                    "URL de importación de la imagen": url,
                })
                yield catalogo.como_el_export(IMAGENES, fila)


def generar(emparejados, catalogo, referencia_sku="arti",
            imagenes_por_sku=0, incluir_revisar=False):
    """Los cuatro archivos, mas el parte de lo que quedo fuera.

    `incluir_revisar` en `False` -- que es lo normal -- deja FUERA del archivo
    todo lo que no se pudo resolver solo. Un producto con la categoria sin
    resolver cargado igual entra en la categoria equivocada, y eso en VTEX no se
    deshace desde una planilla.

    Devuelve `(tablas, incidencias, resumen)`.
    """
    contextos, fuera, avisos = [], [], []
    for entrada in emparejados or []:
        if entrada["Estado"] == REVISAR and not incluir_revisar:
            fuera.append({"Mod-Col": entrada["Mod-Col"], "Nombre": entrada["Nombre"],
                          "Motivo": entrada["Motivos"]})
            continue
        contexto = entrada["_contexto"]
        if contexto.medidas_heredadas and contexto.nuevo:
            avisos.append({
                "Mod-Col": contexto.referencia, "Campo": "Package weight",
                "Aviso": "Sin medidas para %s / %s: se usan las más repetidas de la tienda"
                         % (contexto.departamento or "sin departamento",
                            contexto.categoria or "sin categoría")})
        contextos.append((contexto, entrada))

    # La planilla de productos SI se materializa: son una fila por SKU -- 72.000
    # en una carga de 9.000 productos -- y la validacion la cruza consigo misma
    # varias veces. Las otras tres no: la de especificaciones sola son 477.000
    # filas y 847 MB medidos.
    productos = construir_productos(contextos, catalogo, referencia_sku=referencia_sku)
    apuntados = dict.fromkeys(
        (texto(a["Mod-Col"]), texto(a["Campo"]), texto(a["Aviso"])) for a in avisos)
    tablas = {
        PRODUCTOS: productos,
        ESPEC_PRODUCTO: Filas(lambda: construir_especificaciones_de_producto(
            contextos, catalogo, apuntados)),
        ESPEC_SKU: Filas(lambda: construir_especificaciones_de_sku(
            contextos, catalogo, apuntados)),
        IMAGENES: Filas(lambda: construir_imagenes(
            contextos, catalogo, imagenes_por_sku=imagenes_por_sku)),
    }
    resumen = {
        "Productos en el archivo": len(contextos),
        "Productos fuera": len(fuera),
        "Filas de SKU": len(productos),
        "Productos que se crean": sum(1 for c, _ in contextos if c.nuevo),
        "Productos que se actualizan": sum(1 for c, _ in contextos if not c.nuevo),
        "SKU que se crean": sum(
            1 for _c, e in contextos for v in e["Variantes"] if v["Estado"] == NUEVO),
        # Los conteos de las tres planillas salen de RECORRERLAS, que es un
        # recorrido mas pero ni una fila guardada. Se hace aqui y no en la
        # pantalla para que el numero que se enseña y el archivo no puedan
        # discrepar. De paso, este recorrido es el que llena los avisos.
        "Filas de especificación de producto": len(tablas[ESPEC_PRODUCTO]),
        "Filas de especificación de SKU": len(tablas[ESPEC_SKU]),
        "Filas de imagen": len(tablas[IMAGENES]),
    }
    incidencias = {"fuera": fuera, "avisos": agrupar_avisos(apuntados)}
    resumen["Avisos"] = len(incidencias["avisos"])
    return tablas, incidencias, resumen


def _anotar_aviso(avisos, referencia, campo, motivo):
    """Anota un aviso de forma IDEMPOTENTE.

    Las planillas son generadores y se recorren mas de una vez -- una para
    validar y otra para escribir --, asi que un `append` contaria cada aviso
    dos veces. La clave es el propio aviso, asi que repetirlo no suma.
    """
    if avisos is None:
        return
    avisos[(texto(referencia), texto(campo), texto(motivo))] = None


class Filas:
    """Las filas de una planilla: se recorren varias veces y no se guardan.

    Cada recorrido vuelve a generarlas. Cuesta rehacerlas -- 3,7 s medidos con
    9.000 productos -- y ahorra los **847 MB** que costaba tenerlas vivas, con
    un contenedor de 1 GB para toda la app. `len()` tambien recorre: por eso
    los conteos del resumen salen de otra parte y no de aqui.
    """

    __slots__ = ("_fabrica",)

    def __init__(self, fabrica):
        self._fabrica = fabrica

    def __iter__(self):
        return iter(self._fabrica())

    def __len__(self):
        return sum(1 for _fila in self)

    def __bool__(self):
        for _fila in self:
            return True
        return False


# Cuantos codigos se nombran en un aviso agrupado. Con mas, la celda deja de
# poder leerse y el que la mira ya tiene lo que necesita para ir a buscarlos.
CODIGOS_POR_AVISO = 8


def agrupar_avisos(avisos):
    """Un aviso por CAUSA, no uno por producto.

    Medido a la escala del export real: una talla que la tienda no tiene dada
    de alta produce un aviso por cada SKU que la usa -- 144.000 filas en una
    carga de 9.000 productos. Eso no se lee, y ademas cuesta memoria justo en el
    peor momento. La causa es UNA: falta ese valor en VTEX.

    Se conserva el orden de la primera aparicion, para que dos ejecuciones de la
    misma carga den el mismo informe -- es la misma regla que ya costo un
    arreglo en `avisos_de_talla_a_issues`.
    """
    if isinstance(avisos, dict):
        avisos = [{"Mod-Col": referencia, "Campo": campo, "Aviso": motivo}
                  for referencia, campo, motivo in avisos]
    agrupados = {}
    for aviso in avisos or []:
        llave = (texto(aviso.get("Campo")), texto(aviso.get("Aviso")))
        entrada = agrupados.get(llave)
        if entrada is None:
            entrada = {"Campo": llave[0], "Aviso": llave[1], "Productos": 0,
                       "Mod-Col": ""}
            agrupados[llave] = entrada
            entrada["_codigos"] = []
        entrada["Productos"] += 1
        if len(entrada["_codigos"]) < CODIGOS_POR_AVISO:
            entrada["_codigos"].append(texto(aviso.get("Mod-Col")))
    salida = []
    for entrada in agrupados.values():
        codigos = entrada.pop("_codigos")
        entrada["Mod-Col"] = ", ".join(codigos)
        if entrada["Productos"] > len(codigos):
            entrada["Mod-Col"] += " y %d mas" % (entrada["Productos"] - len(codigos))
        salida.append(entrada)
    return salida


# --- Validacion --------------------------------------------------------------
#
# Es una FOTO de los archivos que se van a subir: solo lee lo que ya esta
# escrito en ellos, no vuelve a consultar Shopify ni ARTI. Si fuera una segunda
# fuente de verdad, el panel y el archivo podrian decir cosas distintas.

BLOQUEA = "Bloquea la carga"
AVISA = "Aviso"


# Cuantos hallazgos del MISMO tipo se listan. Con una carga rota de verdad --
# una categoria que no existe -- el mismo hallazgo sale una vez por producto:
# 72.000 filas que no se leen y que ademas cuestan memoria justo al final. El
# numero total se conserva y se dice.
HALLAZGOS_POR_TIPO = 200


def _anotar(hallazgos, gravedad, tipo, detalle, referencia=""):
    vistos = hallazgos.conteo if isinstance(hallazgos, _Hallazgos) else None
    if vistos is not None:
        vistos[tipo] = vistos.get(tipo, 0) + 1
        if vistos[tipo] > HALLAZGOS_POR_TIPO:
            return
    hallazgos.append({"Gravedad": gravedad, "Revisar": tipo,
                      "Mod-Col": referencia, "Detalle": detalle})


class _Hallazgos(list):
    """Los hallazgos con su cuenta por tipo, para poder acotar sin mentir."""

    def __init__(self):
        super().__init__()
        self.conteo = {}

    def cerrar(self):
        for tipo, veces in self.conteo.items():
            if veces > HALLAZGOS_POR_TIPO:
                self.append({
                    "Gravedad": AVISA, "Revisar": tipo, "Mod-Col": "",
                    "Detalle": "y %d más del mismo tipo (se listan los primeros %d)"
                               % (veces - HALLAZGOS_POR_TIPO, HALLAZGOS_POR_TIPO)})
        return self


OBLIGATORIAS_PRODUCTO = (
    "Product Name", "Brand ID", "Department ID", "Category ID",
    "Product reference code", "SKU name",
)


def validar(tablas, catalogo):
    """Todo lo que puede salir mal en una carga de VTEX, antes de subirla.

    Las tablas llegan ya en el idioma del export -- son las que se van a
    escribir --, asi que se traducen a canonico para leerlas. Validar sobre los
    nombres del archivo obligaria a escribir cada comprobacion dos veces.
    """
    hallazgos = _Hallazgos()
    productos = [traducir_fila(fila, PRODUCTOS) for fila in tablas.get(PRODUCTOS) or []]

    # 1. Duplicados. Es LA regla: el mismo Mod-Col en dos productos son dos
    # fichas separadas en la tienda, y dos veces el mismo SKU es una variante
    # duplicada que ademas se lleva el stock.
    por_referencia = {}
    skus_vistos = {}
    for fila in productos:
        referencia = clave_codigo(fila.get("Product reference code"))
        product_id = _entero_texto(fila.get("Product ID"))
        por_referencia.setdefault(referencia, set()).add(product_id)
        llave = (referencia, clave(fila.get("SKU name")))
        skus_vistos[llave] = skus_vistos.get(llave, 0) + 1
    for referencia, ids in por_referencia.items():
        if len(ids) > 1:
            _anotar(hallazgos, BLOQUEA, "Product ID",
                    "El mismo código sale con %d Product ID distintos: %s"
                    % (len(ids), ", ".join(sorted(i or "(nuevo)" for i in ids))), referencia)
    for (referencia, talla), veces in skus_vistos.items():
        if veces > 1:
            _anotar(hallazgos, BLOQUEA, "SKU duplicado",
                    "La talla %r sale %d veces en el mismo producto" % (talla, veces),
                    referencia)
    # Un SKU ID que aparece en dos productos distintos lo MUEVE de producto.
    por_sku_id = {}
    for fila in productos:
        sku_id = _entero_texto(fila.get("SKU ID"))
        if sku_id:
            por_sku_id.setdefault(sku_id, set()).add(
                clave_codigo(fila.get("Product reference code")))
    for sku_id, referencias in por_sku_id.items():
        if len(referencias) > 1:
            _anotar(hallazgos, BLOQUEA, "SKU ID repetido",
                    "El SKU %s sale en %d productos: %s"
                    % (sku_id, len(referencias), ", ".join(sorted(referencias))))

    # 2. Campos obligatorios, IDs y coherencia con el arbol de VTEX.
    for fila in productos:
        referencia = clave_codigo(fila.get("Product reference code"))
        for columna in OBLIGATORIAS_PRODUCTO:
            if not texto(fila.get(columna)):
                _anotar(hallazgos, BLOQUEA, "Campo obligatorio",
                        "%s vacío" % columna, referencia)
        product_id = _entero_texto(fila.get("Product ID"))
        if product_id and product_id not in catalogo.productos:
            _anotar(hallazgos, BLOQUEA, "Product ID",
                    "El Product ID %s no está en el archivo de VTEX" % product_id, referencia)
        sku_id = _entero_texto(fila.get("SKU ID"))
        if sku_id and sku_id not in catalogo.skus:
            _anotar(hallazgos, BLOQUEA, "SKU ID",
                    "El SKU ID %s no está en el archivo de VTEX" % sku_id, referencia)
        if sku_id and product_id:
            sku = catalogo.skus.get(sku_id)
            if sku is not None and sku.producto_id != product_id:
                _anotar(hallazgos, BLOQUEA, "SKU ID",
                        "El SKU %s es del producto %s, no del %s"
                        % (sku_id, sku.producto_id, product_id), referencia)
        marca = clave(fila.get("Brand"))
        if marca and marca not in catalogo.marcas:
            _anotar(hallazgos, BLOQUEA, "Marca",
                    "La marca %r no existe en VTEX" % texto(fila.get("Brand")), referencia)
        llave_categoria = (clave(fila.get("Department")), clave(fila.get("Category")))
        if any(llave_categoria) and llave_categoria not in catalogo.categorias:
            _anotar(hallazgos, BLOQUEA, "Categoría",
                    "%s / %s no es una categoría de VTEX"
                    % (texto(fila.get("Department")), texto(fila.get("Category"))), referencia)
        if not texto(fila.get("Package weight")):
            _anotar(hallazgos, AVISA, "Medidas",
                    "Sin peso de empaque: el costo de envío saldrá mal", referencia)

    # 3. Que cada producto tenga sus especificaciones y que sus IDs cuadren.
    referencias_productos = {clave_codigo(f.get("Product reference code")) for f in productos}
    con_especificacion = {
        clave_codigo(traducir_fila(f, ESPEC_PRODUCTO).get("Código de referencia del producto"))
        for f in tablas.get(ESPEC_PRODUCTO) or []}
    for referencia in sorted(referencias_productos - con_especificacion):
        _anotar(hallazgos, AVISA, "Especificaciones",
                "El producto no lleva ninguna fila de especificación", referencia)
    for fila in tablas.get(ESPEC_PRODUCTO) or []:
        fila = traducir_fila(fila, ESPEC_PRODUCTO)
        valor = texto(fila.get("Valores de especificación"))
        campo_tipo = clave(fila.get("Tipo de campo"))
        if valor and valor != VACIO and campo_tipo in ("radio", "checkbox", "combo"):
            if not texto(fila.get("IDs de especificación")):
                _anotar(hallazgos, BLOQUEA, "Especificación",
                        "%r no tiene ID de valor en el campo %r: VTEX lo rechaza"
                        % (valor, texto(fila.get("Nombre del campo"))),
                        clave_codigo(fila.get("Código de referencia del producto")))

    # 4. Las tallas: cada SKU del archivo de productos tiene que llevar su
    # especificacion de Talla, o la variante sale sin talla en la tienda.
    tallas_declaradas = set()
    for fila in tablas.get(ESPEC_SKU) or []:
        fila = traducir_fila(fila, ESPEC_SKU)
        if clave(fila.get("Nombre del campo")) == clave(CAMPO_TALLA):
            tallas_declaradas.add(
                (clave(fila.get("Nombre de SKU")),
                 clave_codigo(fila.get("Código de referencia de SKU"))))
    for fila in productos:
        llave = (clave(fila.get("SKU name")), clave_codigo(fila.get("SKU reference code")))
        if llave not in tallas_declaradas:
            _anotar(hallazgos, AVISA, "Talla",
                    "El SKU %r no lleva especificación de talla" % texto(fila.get("SKU name")),
                    clave_codigo(fila.get("Product reference code")))

    # 5. Imagenes.
    for fila in tablas.get(IMAGENES) or []:
        fila = traducir_fila(fila, IMAGENES)
        url = texto(fila.get("URL de importación de la imagen"))
        ruta = texto(fila.get("Ruta de la imagen"))
        if not url and not ruta:
            _anotar(hallazgos, BLOQUEA, "Imagen",
                    "Fila de imagen sin URL de importación ni ruta",
                    texto(fila.get("Nombre del producto")))
        elif url and not url.lower().startswith(("http://", "https://")):
            _anotar(hallazgos, BLOQUEA, "Imagen",
                    "La URL de importación no es una dirección web: %r" % url,
                    texto(fila.get("Nombre del producto")))
    con_imagen = {clave_codigo(traducir_fila(f, IMAGENES).get("Código de referencia de SKU"))
                  for f in tablas.get(IMAGENES) or []}
    sin_imagen = sorted({
        clave_codigo(f.get("Product reference code")) for f in productos
        if not _entero_texto(f.get("SKU ID"))
        and clave_codigo(f.get("SKU reference code")) not in con_imagen})
    for referencia in sin_imagen:
        _anotar(hallazgos, AVISA, "Imagen",
                "Producto nuevo sin ninguna imagen: entraría a la tienda sin foto", referencia)
    return hallazgos.cerrar()


def resumen_de_validacion(hallazgos):
    """`(bloqueos, avisos)`."""
    bloqueos = sum(1 for h in hallazgos or [] if h["Gravedad"] == BLOQUEA)
    return bloqueos, len(hallazgos or []) - bloqueos
