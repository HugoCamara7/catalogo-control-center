"""Configuracion central del catalogo: metafields, tags y handle.

Sin dependencias de Streamlit ni de pandas.

Por que existe
--------------
El motor construia el producto de dos formas distintas y perdia datos por el
camino. Tres causas medidas:

1. **Los metafields del camino directo salian de las columnas del DataFrame.**
   `metafield_columns = [c for c in matrixify_df.columns if ...]`. Si el
   generador no emitia la columna, Shopify nunca recibia el metafield y nadie
   se enteraba. No habia forma de decir "a Vans le corresponde Familia".

2. **El tipo salia del nombre de la columna.** `custom.codigo_modelo_color [id]`
   mandaba `type: "id"` a Shopify. `id` NO es un tipo de metafield: la API lo
   rechaza siempre. Por eso el mismo producto salia bien por Matrixify y sin
   Codigo Modelo-Color por integracion directa.

3. **Los tags eran "el primero que no este vacio", no la union.** "Tags" y
   "Tags adicionales" estaban en la misma lista de alias, asi que con "Tags"
   lleno, "Tags adicionales" se descartaba entero.

Aqui vive UNA tabla: sitio + campo origen -> namespace.key -> tipo -> como se
transforma. Todo lo demas la consulta.
"""

import json
import re
import unicodedata

# --- tipos de Shopify ----------------------------------------------------
TEXTO = "single_line_text_field"
TEXTO_LARGO = "multi_line_text_field"
LISTA_TEXTO = "list.single_line_text_field"
REFERENCIA_PRODUCTO = "product_reference"
LISTA_REFERENCIA_PRODUCTO = "list.product_reference"
REFERENCIA_PAGINA = "page_reference"
REFERENCIA_METAOBJETO = "list.metaobject_reference"

TIPOS_VALIDOS = {
    TEXTO, TEXTO_LARGO, LISTA_TEXTO, REFERENCIA_PRODUCTO,
    LISTA_REFERENCIA_PRODUCTO, REFERENCIA_PAGINA, REFERENCIA_METAOBJETO,
    "number_integer", "number_decimal", "boolean", "json", "url", "color",
    "list.multi_line_text_field", "metaobject_reference",
    "list.product_reference", "file_reference", "list.file_reference",
}

# Tipos que la API directa NO puede escribir: necesitan IDs internos que solo
# Matrixify resuelve. No es un error, es una division de trabajo.
TIPOS_SOLO_MATRIXIFY = {REFERENCIA_PAGINA, "list.page_reference"}

# Lo que aparece entre corchetes en la cabecera de Matrixify y NO es un tipo de
# Shopify. `[id]` marca la columna con la que Matrixify empareja productos.
# Mandarlo como tipo hace que la API rechace el metafield SIEMPRE.
SEUDOTIPOS = {
    "id": TEXTO,
    "identifier": TEXTO,
    "": TEXTO,
}


def _texto(valor):
    if valor is None:
        return ""
    if isinstance(valor, float) and valor != valor:
        return ""
    return str(valor).strip()


def sin_tildes(valor):
    """NFKD y fuera los diacriticos. Conserva la enye como 'n'."""
    texto = unicodedata.normalize("NFKD", _texto(valor))
    return "".join(c for c in texto if not unicodedata.combining(c))


def clave_columna(valor):
    """Forma canonica de un nombre de columna, para comparar alias."""
    return re.sub(r"[^a-z0-9]+", "", sin_tildes(valor).casefold())


# --- la tabla ------------------------------------------------------------
# origen: alias aceptados en el Excel, en orden de preferencia.
# sitios: None = todos. Un conjunto = solo esos.
CAMPO = "campo"
CAMPOS = [
    # clave interna, namespace.key, tipo, alias de entrada, sitios, transformacion
    ("codigo_modelo_color", "custom.codigo_modelo_color", TEXTO,
     ["Mod-Col", "COD MOD COL", "Codigo Modelo-Color", "Código Modelo-Color",
      "codigo_modelo_color", "COD_MOD_COL"], None, "mayusculas"),
    ("marca", "custom.marca", TEXTO, ["Marca", "Vendor", "Brand"], None, "texto"),
    # Categoria = la CLASE (Vestuario, Calzado, Accesorios).
    ("categoria", "custom.categoria", TEXTO,
     ["Categoria", "Categoría", "Category", "Clase"], None, "texto"),
    # Subcategoria = el TIPO DE PRENDA. Son el mismo dato con dos nombres, asi
    # que ambos metafields leen los dos juegos de alias: llene el brand la
    # columna que llene, los dos salen con valor.
    ("subcategoria", "custom.subcategoria", TEXTO,
     ["Subcategoria", "Subcategoría", "Sub Categoria", "Sub Categoría", "Subcategory",
      "Tipo de prenda", "Tipo de Prenda", "Tipo prenda"], None, "texto"),
    ("tipo", "custom.tipo", TEXTO,
     ["Tipo de prenda", "Tipo de Prenda", "Tipo prenda", "Tipo",
      "Subcategoria", "Subcategoría", "Sub Categoria", "Type"], None, "texto"),
    ("genero", "custom.genero", TEXTO, ["Genero", "Género", "Gender"], None, "texto"),
    ("color_forus", "custom.color_forus", TEXTO,
     ["Color Forus", "Color", "Color Web"], None, "texto"),
    ("grupo_color", "custom.grupo_color", TEXTO, ["Grupo Color", "Grupo de Color"], None, "texto"),
    ("nombre_corto", "custom.nombre_corto", TEXTO, ["Nombre Corto", "Nombre corto"], None, "texto"),
    ("descripcion_corta", "custom.descripcion_corta", TEXTO,
     ["Descripcion Corta", "Descripción Corta"], None, "texto"),
    ("materialidad", "custom.materialidad", TEXTO,
     ["Materialidad", "Material Principal", "Materiales"], None, "texto"),
    ("tecnologia", "custom.tecnologia", LISTA_TEXTO,
     ["Tecnologia", "Tecnología", "Tecnologias", "Tecnologías",
      "METAFIELD TECNOLOGIAS", "METAFIELD TECNOLOGÍAS"], {"columbia"}, "lista_json"),
    ("tecnologia_texto", "custom.tecnologia", TEXTO,
     ["Tecnologia", "Tecnología", "Tecnologias", "Tecnologías"],
     {"rockford", "vans", "hush_puppies", "patagonia", "sorel"}, "lista_pipe"),
    # SIBLINGS. Los criterios son los mismos en los cuatro sitios: la app
    # relaciona los colores del mismo modelo, el brand no los llena.
    #
    # Son CUATRO metafields, no dos, y cada uno con su tipo. El mismo
    # `custom.siblings` estaba declarado como `list.product_reference` en el
    # mantenedor y en la API, pero como `single_line_text_field` en otras
    # cuatro rutas. Shopify rechaza la que no coincide con la definicion, y de
    # ahi que unos siblings llegaran y otros no segun por donde pasara la carga.
    #
    # theme.*  -> lo que lee el tema de la tienda: handles en texto.
    # custom.* -> la relacion de verdad: referencias al producto.
    ("siblings", "custom.siblings", LISTA_REFERENCIA_PRODUCTO,
     ["Siblings", "Productos relacionados"], None, "lista_json"),
    ("siblings_color", "custom.siblings_color", TEXTO,
     ["Siblings Color", "Color Sibling"], None, "texto"),
    ("siblings_tema", "theme.siblings", LISTA_TEXTO,
     ["Siblings", "Productos relacionados"], None, "lista_json"),
    ("siblings_color_tema", "theme.siblings_color", TEXTO,
     ["Siblings Color", "Color Sibling"], None, "texto"),
    ("estilo", "custom.estilo", TEXTO, ["Estilo"], {"hush_puppies"}, "texto"),
    ("categoria_de_tecnologia", "custom.categoria_de_tecnologia", TEXTO,
     ["Categoria de Tecnologia", "Categoría de Tecnología"], {"hush_puppies"}, "texto"),
    ("composicion", "custom.composicion", TEXTO_LARGO,
     ["Composicion", "Composición", "Materiales", "Materialidad"], {"vans"}, "texto"),
    ("codigo_de_referencia", "custom.codigo_de_referencia", TEXTO,
     ["Codigo de Referencia", "Código de Referencia"], {"vans"}, "texto"),
    # Vans: faltaba por completo. Sin esto no hay columna, ni validacion, ni
    # metafield, ni salida a Matrixify.
    ("familia", "custom.familia", TEXTO,
     ["Familia", "Family", "Familia de Producto"], {"vans"}, "texto"),
]


class Campo:
    """Una fila de la tabla, ya resuelta."""

    __slots__ = ("clave", "namespace", "key", "tipo", "alias", "sitios", "transformacion")

    def __init__(self, clave, ruta, tipo, alias, sitios, transformacion):
        self.clave = clave
        self.namespace, _, self.key = ruta.partition(".")
        self.tipo = tipo
        self.alias = list(alias)
        self.sitios = set(sitios) if sitios else None
        self.transformacion = transformacion

    @property
    def columna(self):
        """Cabecera de Matrixify para este metafield."""
        return f"Metafield: {self.namespace}.{self.key} [{self.tipo}]"

    def aplica_a(self, sitio):
        if self.sitios is None:
            return True
        return _texto(sitio).casefold().replace(" ", "_") in self.sitios

    def escribible_por_api(self):
        return self.tipo not in TIPOS_SOLO_MATRIXIFY

    def __repr__(self):
        return f"<Campo {self.namespace}.{self.key} {self.tipo}>"


CAMPOS_POR_CLAVE = {}
for _fila in CAMPOS:
    _campo = Campo(*_fila)
    CAMPOS_POR_CLAVE[_campo.clave] = _campo


def campos_para_sitio(sitio):
    """Los metafields que le corresponden a este sitio. Ni mas ni menos."""
    return [c for c in CAMPOS_POR_CLAVE.values() if c.aplica_a(sitio)]


def campo_por_columna(columna):
    """Encuentra el campo a partir de una cabecera 'Metafield: ns.key [tipo]'."""
    namespace, key = namespace_key(columna)
    if not namespace or not key:
        return None
    for campo in CAMPOS_POR_CLAVE.values():
        if campo.namespace == namespace and campo.key == key:
            return campo
    return None


# --- tipos ---------------------------------------------------------------
def namespace_key(columna):
    texto = _texto(columna)
    if not texto.startswith("Metafield: "):
        return "", ""
    nombre = re.sub(r"\s*\[.+?\]\s*$", "", texto.replace("Metafield: ", "", 1)).strip()
    if "." not in nombre:
        return "", ""
    namespace, key = nombre.split(".", 1)
    return namespace.strip(), key.strip()


def tipo_shopify(columna):
    """El tipo REAL que acepta Shopify para esta columna.

    Prioridad: la tabla central. Si la columna no esta en la tabla, se lee de
    los corchetes, traduciendo los seudotipos de Matrixify (`[id]`) a un tipo
    valido. Devolver "id" hacia que la API rechazara el metafield siempre.
    """
    campo = campo_por_columna(columna)
    if campo is not None:
        return campo.tipo
    match = re.search(r"\[(.+?)\]$", _texto(columna))
    declarado = (match.group(1) if match else "").strip()
    if declarado in SEUDOTIPOS:
        return SEUDOTIPOS[declarado]
    if declarado not in TIPOS_VALIDOS:
        return TEXTO
    return declarado


def es_seudotipo(columna):
    """True si la cabecera declara algo que Shopify no aceptaria."""
    match = re.search(r"\[(.+?)\]$", _texto(columna))
    declarado = (match.group(1) if match else "").strip()
    return declarado in SEUDOTIPOS or declarado not in TIPOS_VALIDOS


# --- valores -------------------------------------------------------------
def separar_lista(valor):
    """Parte por '|' respetando el uso decimal (5|3-oz = 5.3 oz).

    Un '|' entre digitos NO corta: en Materiales aparece como coma decimal.
    """
    texto = _texto(valor)
    if not texto:
        return []
    marcado = re.sub(r"(?<=\d)\|(?=\d)", "\x00", texto)
    partes = [p.replace("\x00", "|").strip() for p in marcado.split("|")]
    return [p for p in partes if p]


def transformar(campo, valor):
    """Deja el valor en la forma que espera Shopify para ese tipo."""
    texto = _texto(valor)
    if not texto:
        return ""
    modo = getattr(campo, "transformacion", "texto")
    if modo == "mayusculas":
        return texto.upper()
    if modo == "lista_json":
        items = separar_lista(texto) or [texto]
        return json.dumps(items, ensure_ascii=False)
    if modo == "lista_pipe":
        items = separar_lista(texto) or [texto]
        return " | ".join(items)
    return texto


def valor_de_entrada(fila, campo):
    """El valor del Excel para este campo, probando los alias en orden.

    Acepta tambien la propia cabecera de Matrixify, para poder releer un
    archivo ya generado.
    """
    if not isinstance(fila, dict):
        return ""
    indice = {clave_columna(k): v for k, v in fila.items()}
    for alias in list(campo.alias) + [campo.columna]:
        valor = _texto(indice.get(clave_columna(alias)))
        if valor:
            return valor
    return ""


def build_metafields(fila, sitio):
    """Los metafields del producto, listos para la API.

    Devuelve solo los que CORRESPONDEN al sitio y TIENEN valor. Un campo que no
    aplica a la marca no se rellena; uno que aplica y trae dato no se pierde.
    """
    salida = []
    for campo in campos_para_sitio(sitio):
        valor = transformar(campo, valor_de_entrada(fila, campo))
        if not valor:
            continue
        salida.append({
            "clave": campo.clave,
            "namespace": campo.namespace,
            "key": campo.key,
            "type": campo.tipo,
            "value": valor,
            "columna": campo.columna,
            "escribible_por_api": campo.escribible_por_api(),
        })
    return salida


def metafields_perdidos(fila, sitio, payload):
    """Campos con dato en el input que NO llegarian a Shopify.

    Esta es la validacion que pedia el usuario: detectar el problema ANTES de
    crear productos, no despues de mirarlos en Shopify.

    payload: lo que se va a enviar. Se acepta la lista de build_metafields o un
    dict {"namespace.key": valor}.
    """
    enviados = set()
    for item in payload or []:
        if isinstance(item, dict):
            ns = _texto(item.get("namespace"))
            key = _texto(item.get("key"))
            if ns and key and _texto(item.get("value")):
                enviados.add(f"{ns}.{key}")
        elif isinstance(payload, dict):
            break
    if isinstance(payload, dict):
        enviados = {k for k, v in payload.items() if _texto(v)}

    perdidos = []
    for campo in campos_para_sitio(sitio):
        valor = valor_de_entrada(fila, campo)
        if not valor:
            continue
        ruta = f"{campo.namespace}.{campo.key}"
        if ruta in enviados:
            continue
        perdidos.append({
            "campo": campo.clave,
            "metafield": ruta,
            "tipo": campo.tipo,
            "valor_input": valor,
            "motivo": ("solo lo escribe Matrixify" if not campo.escribible_por_api()
                       else "tiene dato en el input pero no llegaria a Shopify"),
        })
    return perdidos


# --- tags ----------------------------------------------------------------
# Columnas del Excel con tags que el usuario escribe A MANO. Se SUMAN, nunca se
# reemplazan entre si.
COLUMNAS_TAGS_BASE = ["Tags", "Etiquetas", "Product Tags", "Shopify Tags", "Tag"]
COLUMNAS_TAGS_EXTRA = ["Tags adicionales", "Tags sugeridos", "Tags extra",
                       "Etiquetas adicionales"]


def separar_tags(valor):
    texto = _texto(valor)
    if not texto:
        return []
    return [p.strip() for p in re.split(r"[,;|\n]", texto) if p.strip()]


def tags_genericos(fila, sitio=""):
    """Tags que el motor genera solo, a partir de lo que ya sabe del producto.

    Antes no existian: los tags salian unicamente del Excel, y por eso Rockford
    creaba productos sin Hombre/Mujer, sin Vestuario y sin el tipo de prenda.
    """
    indice = {clave_columna(k): v for k, v in (fila or {}).items()}

    def leer(*alias):
        for a in alias:
            valor = _texto(indice.get(clave_columna(a)))
            if valor:
                return valor
        return ""

    salida = []
    for valor in (
        leer("Genero", "Género", "Gender"),
        leer("Categoria", "Categoría", "Category"),
        leer("Subcategoria", "Subcategoría", "Subcategory"),
        leer("Tipo", "Tipo de prenda", "Type"),
        leer("Marca", "Vendor", "Brand"),
        leer("Color Forus", "Color", "Color Web"),
        leer("Mod-Col", "COD MOD COL", "Codigo Modelo-Color", "Código Modelo-Color"),
    ):
        salida.extend(separar_tags(valor))
    return salida


def build_tags(fila, sitio="", reglas_sitio=None):
    """Tags finales = genericos + reglas del sitio + adicionales del Excel.

    La regla que hay que respetar: **los adicionales SUMAN, nunca reemplazan**.
    Antes "Tags" y "Tags adicionales" competian por el mismo hueco y ganaba el
    primero no vacio, asi que con "Tags" lleno los adicionales se perdian
    enteros.

    Se conserva el orden de aparicion y se quitan repetidos sin distinguir
    mayusculas ni tildes.
    """
    indice = {clave_columna(k): v for k, v in (fila or {}).items()}
    bruto = list(tags_genericos(fila, sitio))
    for columna in COLUMNAS_TAGS_BASE:
        bruto.extend(separar_tags(indice.get(clave_columna(columna))))
    for tag in (reglas_sitio or []):
        bruto.extend(separar_tags(tag))
    for columna in COLUMNAS_TAGS_EXTRA:
        bruto.extend(separar_tags(indice.get(clave_columna(columna))))

    vistos = set()
    salida = []
    for tag in bruto:
        marca = clave_columna(tag)
        if not marca or marca in vistos:
            continue
        vistos.add(marca)
        salida.append(tag)
    return salida


def tags_a_texto(tags):
    return ", ".join(tags or [])


# --- handle --------------------------------------------------------------
def slug(valor):
    """Minusculas, sin tildes, separado por guiones, sin dobles ni sobrantes."""
    texto = sin_tildes(valor).casefold()
    texto = texto.replace("ñ", "n").replace("&", " y ")
    texto = re.sub(r"[^a-z0-9]+", "-", texto)
    return re.sub(r"-{2,}", "-", texto).strip("-")


def build_handle(nombre, genero="", mod_col="", color=""):
    """Handle unico y estable: Nombre + Genero + Mod-Col + Color.

    El Codigo Modelo-Color NUNCA reemplaza al nombre del producto: se agrega
    despues. Antes habia dos constructores y uno descartaba el nombre, asi que
    el mismo producto salia con handles distintos segun el camino.

    Sin nombre, el Mod-Col es lo unico que queda: mejor un handle feo que uno
    vacio, que Shopify rechazaria.
    """
    partes = []
    for valor in (nombre, genero, mod_col, color):
        pieza = slug(valor)
        if not pieza:
            continue
        # No repetir una parte que ya esta contenida en el handle.
        if pieza in partes:
            continue
        partes.append(pieza)
    handle = "-".join(partes)
    handle = re.sub(r"-{2,}", "-", handle).strip("-")
    return handle or slug(mod_col)
