"""
Central business rules for Catalog Control Center.

This module is intentionally free of Streamlit and Shopify API calls. It can be
used by the app, tests, GitHub Actions, and template generators without touching
live stores.
"""

import html
import re
import unicodedata


def normalize_text(value):
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    text = re.sub(r"\s+", " ", text)
    return text


def normalize_key(value):
    text = unicodedata.normalize("NFKD", normalize_text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def slugify_catalog_value(value):
    text = unicodedata.normalize("NFKD", normalize_text(value)).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text


def build_catalog_handle(product_type="", gender="", brand="", mod_col=""):
    """Technical handle rule: tipo de prenda + genero + marca + codigo modelo-color."""
    parts = [product_type, gender, brand, mod_col]
    handle = slugify_catalog_value(" ".join(normalize_text(part) for part in parts if normalize_text(part)))
    return handle or slugify_catalog_value(mod_col)


def normalize_size(value):
    text = normalize_text(value).upper()
    text = text.replace("TALLA", "").replace("SIZE", "").strip()
    text = re.sub(r"\s+", "", text)
    replacements = {
        "OS": "Talla Unica",
        "O/S": "Talla Unica",
        "ONE": "Talla Unica",
        "ONESIZE": "Talla Unica",
        "U": "Talla Unica",
    }
    return replacements.get(text, normalize_text(value))


INVALID_SIZE_VALUES = {
    "",
    "-",
    ".",
    "0",
    "00",
    "000",
    "K",
    "N/A",
    "NA",
    "SIN TALLA",
    "NO APLICA",
}


def is_invalid_size_for_creation(value):
    size = normalize_key(normalize_size(value)).upper()
    raw = normalize_text(value).upper().replace(" ", "")
    return raw in INVALID_SIZE_VALUES or size in {normalize_key(v).upper() for v in INVALID_SIZE_VALUES}


CATALOG_FIELD_ALIASES = {
    "mod_col": [
        "Mod-Col", "COD MOD COL", "COD_MOD_COL", "Codigo modelo color", "Codigo Modelo Color",
        "Codigo Modelo-Color", "Cod Mod Col", "Modelo Color", "Modelo-Color", "codmod_codcol",
        "mod_col", "modelo_color", "codigo_modelo_color", "Código Modelo Color",
    ],
    "model_code": ["Codigo modelo", "Codigo Modelo", "Modelo", "CODIGO_MODELO", "COD_MOD", "codmod"],
    "color_code": ["Codigo color", "Codigo Color", "CODIGO_COLOR", "COD_COL", "codcol"],
    "sku": ["SKU", "CODINT_MA", "Cod Int", "Codigo Interno", "Codigo SKU", "Variant SKU", "sku variante"],
    "barcode": [
        "EAN", "Barcode", "CodBarras", "Codigo de barras", "Codigo barra", "Variant Barcode",
        "Codigo de barra variante (EAN/UPC/ISBN)", "CODBARRAS", "COD_BAR_MA",
    ],
    "size": ["Talla", "TALNUM_MA", "Size", "Option1 Value", "Variant Option1 Value"],
    "brand": ["Marca", "MARCA_MA", "Vendor", "Brand", "Marca Web"],
    "title": [
        "Title", "Titulo", "Titulo Web", "Título", "Nombre Web", "Nombre del Producto",
        "Nombre Producto", "NombreModelo", "Nombre Modelo", "Nombre del modelo", "Modelo Nombre",
        "DESC_MODELO", "DESCRIPCION_MODELO", "Descripcion Modelo", "Descripción Modelo",
        "DESCRIPCION_MA", "nommod_ma", "nom_modelo", "desc_modelo", "desmod_ma",
        "product_name", "modelo_nombre",
    ],
    "description": [
        "Body HTML", "DescripcionWeb", "Descripcion Web", "Descripción Web", "Product Description",
        "Description", "Descripcion", "Descripción", "Descripcion Comercial",
        "Descripción Comercial", "Descripcion larga", "Descripción larga",
    ],
    # OJO: "Descripcion corta" NO va aqui. Es el metafield custom.descripcion_corta
    # y tiene su propia entrada. Mientras estuvo como alias de features, una
    # columna "Descripcion corta" en el input se consumia como bullets del Body
    # HTML y el metafield llegaba vacio a Shopify.
    "features": [
        "Caracteristicas", "Características", "Features", "Beneficios", "Bullets",
        "Listado de características", "Listado de caracteristicas",
    ],
    "short_name": ["Nombre corto", "Nombre Corto", "Nombre breve", "Short name"],
    "short_description": [
        "Descripcion corta", "Descripción corta", "Descripcion Corta", "Descripción Corta",
        "Short description",
    ],
    "material": [
        "Material", "Materiales", "Materialidad", "Composicion", "Composición", "Composition",
        "Tipo de Material", "Material principal", "Material Principal", "Composicion del Producto",
    ],
    "care": [
        "Cuidado", "Cuidados", "Care", "Care Instructions", "Instrucciones de cuidado",
        "Lavado", "Mantenimiento", "Indicaciones de cuidado",
    ],
    "product_type": [
        "TipoProducto", "Tipo Producto", "Tipo De Producto", "Tipo de Producto", "Tipo de Prenda",
        "Tipo Prenda", "TIPO", "TIPO_MA", "Tipo", "Type", "Product Type", "tipprenda_ma", "prenda",
    ],
    "category": ["Categoria", "Categoría", "CATEGORIA", "Familia", "FAMILIA", "Category"],
    "subcategory": [
        "SubCategoria", "Sub Categoria", "Sub Categoría", "SUBCATEGORIA", "SUB CATEGORIA",
        "Subcategory", "Sub Category",
    ],
    "gender": ["Genero", "Género", "GENERO", "Sexo", "SEXO", "Gender", "genero_ma", "sexo_ma", "Publico"],
    "age_group": ["Grupo edad", "Grupo de edad", "Age Group", "Edad", "Rango Edad"],
    "color_web": [
        "Color Web", "Color Forus", "Grupo Color", "ColorNombre", "Nombre Color", "Color Nombre",
        "Color Comercial", "desc_color", "descripcion_color", "descol_ma", "nomcol_ma",
    ],
    "season": ["Temporada", "TEMPORADA", "Season", "Coleccion Temporada"],
    "collection": ["Coleccion", "Colección", "COLECCION", "Collection"],
    "occasion": ["Ocasion", "Ocasión", "OCASION", "Occasion"],
    "sport": ["Deporte", "DEPORTE", "Sport", "Activity"],
    "technology": ["Tecnologia", "Tecnología", "Tecnologias", "Tecnologías", "Technology", "TECHNOLOGY"],
    "image": ["Image Src", "Imagen", "IMAGEN", "Foto", "FOTO", "Url Imagen", "URL Imagen"],
    "price": ["Precio", "PRECIO", "Variant Price", "Price", "precio_ma", "precio_venta", "pvp"],
    "compare_at": ["Compare At Price", "Precio Compare At", "PRECIO_ANTES", "Precio Regular"],
}


def aliases_for(field, fallback=None):
    values = list(CATALOG_FIELD_ALIASES.get(field, []))
    for item in fallback or []:
        if item not in values:
            values.append(item)
    return values


PRODUCT_TYPE_RULES = [
    {
        "received": "zapatilla, zapatillas, footwear, sneaker, sneakers, calzado",
        "normalized": "Zapatilla",
        "singular": "Zapatilla",
        "plural": "Zapatillas",
        "category": "Calzado",
        "subcategory": "Zapatillas",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Zapatilla Hombre Konos",
    },
    {
        "received": "casaca, chaqueta, jacket, parka",
        "normalized": "Casaca",
        "singular": "Casaca",
        "plural": "Casacas",
        "category": "Vestuario",
        "subcategory": "Casacas",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Casaca Impermeable Mujer",
    },
    {
        "received": "polo, polos, camiseta, t-shirt, tshirt, polera, poleras, remera, remeras",
        "normalized": "Polo",
        "singular": "Polo",
        "plural": "Polos",
        "category": "Vestuario",
        "subcategory": "Polos",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Polo Hombre",
    },
    {
        "received": "poleron, polerón, hoodie, sweatshirt, hoody",
        "normalized": "Poleron",
        "singular": "Poleron",
        "plural": "Polerones",
        "category": "Vestuario",
        "subcategory": "Polerones",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Poleron Mujer",
    },
    {
        "received": "pantalon, pantalones, pants, jogger, joggers, buzo, leggings, legging",
        "normalized": "Pantalon",
        "singular": "Pantalon",
        "plural": "Pantalones",
        "category": "Vestuario",
        "subcategory": "Pantalones",
        "size_guide_family": "Vestuario",
        "size_guide_group": "BOTTOMS",
        "can_one_size": False,
        "examples": "Pantalon Trekking Mujer",
    },
    {
        "received": "short, shorts, bermuda, bermudas, falda, faldas",
        "normalized": "Short",
        "singular": "Short",
        "plural": "Shorts",
        "category": "Vestuario",
        "subcategory": "Shorts",
        "size_guide_family": "Vestuario",
        "size_guide_group": "BOTTOMS",
        "can_one_size": False,
        "examples": "Short Hombre Outdoor",
    },
    {
        "received": "gorro, gorros, beanie",
        "normalized": "Gorro",
        "singular": "Gorro",
        "plural": "Gorros",
        "category": "Accesorios",
        "subcategory": "Gorros",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Gorro Cachalot",
    },
    {
        "received": "bolso, bolsos, cartera, carteras, bag",
        "normalized": "Bolso",
        "singular": "Bolso",
        "plural": "Bolsos",
        "category": "Accesorios",
        "subcategory": "Bolsos",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Bolso Outdoor",
    },
    {
        "received": "slip on, slip-on",
        "normalized": "Slip On",
        "singular": "Slip On",
        "plural": "Slip Ons",
        "category": "Calzado",
        "subcategory": "Slip Ons",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Slip On Vans",
    },
    {
        "received": "crema renovadora, renovador, cleaner",
        "normalized": "Crema renovadora",
        "singular": "Crema renovadora",
        "plural": "Cremas renovadoras",
        "category": "Accesorios",
        "subcategory": "Cuidado",
        "size_guide_family": "Sin guia",
        "can_one_size": True,
        "examples": "Crema renovadora cuero",
    },
    {
        "received": "polar, polares, fleece, microfleece, micropolar",
        "normalized": "Polar",
        "singular": "Polar",
        "plural": "Polares",
        "category": "Vestuario",
        "subcategory": "Polares",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Polar Mujer Benton Springs",
    },
    {
        "received": "chaleco, chalecos, vest",
        "normalized": "Chaleco",
        "singular": "Chaleco",
        "plural": "Chalecos",
        "category": "Vestuario",
        "subcategory": "Chalecos",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Chaleco Hombre Powder Lite",
    },
    {
        "received": "camisa, camisas, shirt",
        "normalized": "Camisa",
        "singular": "Camisa",
        "plural": "Camisas",
        "category": "Vestuario",
        "subcategory": "Camisas",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Camisa Hombre Silver Ridge",
    },
    {
        "received": "interior termico, interiores termicos, interior térmico, interiores térmicos, primera capa, baselayer, base layer",
        "normalized": "Interior Termico",
        "singular": "Interior Termico",
        "plural": "Interiores Termicos",
        "category": "Vestuario",
        "subcategory": "Interiores Termicos",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Interior Termico Hombre Midweight",
    },
    {
        "received": "ropa de bano, ropas de bano, ropa de baño, ropas de baño, traje de bano, traje de baño, swimwear, bikini, malla",
        "normalized": "Ropa de Bano",
        "singular": "Ropa de Bano",
        "plural": "Ropas de Bano",
        "category": "Vestuario",
        "subcategory": "Ropas de Bano",
        "size_guide_family": "Vestuario",
        "size_guide_group": "BOTTOMS",
        "can_one_size": False,
        "examples": "Ropa de Bano Hombre",
    },
    {
        "received": "guante, guantes, glove, gloves, mitones, miton",
        "normalized": "Guante",
        "singular": "Guante",
        "plural": "Guantes",
        "category": "Accesorios",
        "subcategory": "Guantes",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Guantes Unisex Powder Lite",
    },
    {
        "received": "cuellera, cuelleras, cuello, cuellos, neck gaiter, bandana",
        "normalized": "Cuellera",
        "singular": "Cuellera",
        "plural": "Cuelleras",
        "category": "Accesorios",
        "subcategory": "Cuelleras",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Cuellera Unisex",
    },
    {
        "received": "chullo, chullos, gorro andino",
        "normalized": "Chullo",
        "singular": "Chullo",
        "plural": "Chullos",
        "category": "Accesorios",
        "subcategory": "Chullos",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Chullo Unisex",
    },
    {
        "received": "sombrero, sombreros, hat, bucket hat, jockey",
        "normalized": "Sombrero",
        "singular": "Sombrero",
        "plural": "Sombreros",
        "category": "Accesorios",
        "subcategory": "Sombreros",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Sombrero Unisex Bora Bora",
    },
    {
        "received": "mochila, mochilas, backpack, morral",
        "normalized": "Mochila",
        "singular": "Mochila",
        "plural": "Mochilas",
        "category": "Accesorios",
        "subcategory": "Mochilas",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Mochila Unisex Atlas Explorer",
    },
    {
        "received": "maletin, maletines, maletín, maletines, briefcase, portafolio",
        "normalized": "Maletin",
        "singular": "Maletin",
        "plural": "Maletines",
        "category": "Accesorios",
        "subcategory": "Maletines",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Maletin Unisex",
    },
    {
        "received": "neceser, neceseres, cosmetiquero, toiletry",
        "normalized": "Neceser",
        "singular": "Neceser",
        "plural": "Neceseres",
        "category": "Accesorios",
        "subcategory": "Neceseres",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Neceser Unisex",
    },
    {
        "received": "canguro, canguros, rinonera, riñonera, banano, waist pack",
        "normalized": "Canguro",
        "singular": "Canguro",
        "plural": "Canguros",
        "category": "Accesorios",
        "subcategory": "Canguros",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Canguro Unisex",
    },
    {
        "received": "correa, correas, cinturon, cinturón, belt",
        "normalized": "Correa",
        "singular": "Correa",
        "plural": "Correas",
        "category": "Accesorios",
        "subcategory": "Correas",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Correa Unisex",
    },

    # --- ampliacion del diccionario (agosto 2026) ------------------------
    # Del analisis de los catalogos reales de los cuatro sitios. Cubre los 20
    # tipos que la propia data/tipos_shopify.xlsx de la app no reconocia, y que
    # eran el grueso de las advertencias de "tipo no reconocido".
    #
    # Criterio acordado: el canonico va en PLURAL (3 de 4 sitios ya lo usan;
    # Vans escribe en singular y sus formas quedan como sinonimos).
    #
    # Calzado tenia solo 2 tipos (Zapatillas y Slip Ons) pese a ser marcas de
    # calzado. De ahi salia el grueso de los avisos.
    #
    # Ningun alias puede apuntar a dos tipos: hay una prueba que lo comprueba.
    # Por eso NO se agregaron tipos que ya tenian dueno en el diccionario:
    #   buzo/buzos   -> ya es Pantalones (encajaria en Polerones)
    #   chaqueta     -> ya es Casaca
    #   falda        -> ya es Short
    #   cartera      -> ya es Bolso
    #   t-shirt      -> ya es Polo
    #   hoodie       -> ya es Poleron (solo faltaba la forma "hoody")
    # Y "Poleras" no se creo como tipo aparte: el analisis ya habia decidido
    # que Polos = Poleras, asi que sus formas son sinonimos de Polo.
    # Las tres primeras son decisiones de criterio del negocio, no tecnicas.
    {
        "received": "sweater, sweaters, chompa, chompas, jersey, jerseys, pullover",
        "normalized": "Sweater",
        "singular": "Sweater",
        "plural": "Sweaters",
        "category": "Vestuario",
        "subcategory": "Sweaters",
        "size_guide_family": "Vestuario",
        "can_one_size": False,
        "examples": "Sweater Mujer",
    },
    {
        "received": "blusa, blusas, blouse",
        "normalized": "Blusa",
        "singular": "Blusa",
        "plural": "Blusas",
        "category": "Vestuario",
        "subcategory": "Blusas",
        "size_guide_family": "Vestuario",
        "can_one_size": False,
        "examples": "Blusa Mujer",
    },
    {
        "received": "jean, jeans, pantalon jean, denim",
        "normalized": "Jean",
        "singular": "Jean",
        "plural": "Jeans",
        "category": "Vestuario",
        "subcategory": "Jeans",
        "size_guide_family": "Vestuario",
        "can_one_size": False,
        "examples": "Jean Hombre",
    },
    {
        "received": "enterizo, enterizos, overol, overoles, jardinera, jardineras, mameluco, jumpsuit",
        "normalized": "Enterizo",
        "singular": "Enterizo",
        "plural": "Enterizos",
        "category": "Vestuario",
        "subcategory": "Enterizos",
        "size_guide_family": "Vestuario",
        "can_one_size": False,
        "examples": "Enterizo Mujer",
    },
    {
        "received": "chaleco polar, chalecos polares",
        "normalized": "Chaleco Polar",
        "singular": "Chaleco Polar",
        "plural": "Chalecos Polares",
        "category": "Vestuario",
        "subcategory": "Chalecos Polares",
        "size_guide_family": "Vestuario",
        "can_one_size": False,
        "examples": "Chaleco Polar Hombre",
    },
    {
        "received": "bota, botas, boot, boots",
        "normalized": "Bota",
        "singular": "Bota",
        "plural": "Botas",
        "category": "Calzado",
        "subcategory": "Botas",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Bota Hombre",
    },
    {
        "received": "botin, botines, bootie, booties",
        "normalized": "Botin",
        "singular": "Botin",
        "plural": "Botines",
        "category": "Calzado",
        "subcategory": "Botines",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Botin Mujer",
    },
    {
        "received": "sandalia, sandalias, sandal, sandals",
        "normalized": "Sandalia",
        "singular": "Sandalia",
        "plural": "Sandalias",
        "category": "Calzado",
        "subcategory": "Sandalias",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Sandalia Mujer",
    },
    {
        "received": "pantufla, pantuflas, slipper, slippers",
        "normalized": "Pantufla",
        "singular": "Pantufla",
        "plural": "Pantuflas",
        "category": "Calzado",
        "subcategory": "Pantuflas",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Pantufla Unisex",
    },
    {
        "received": "zapato, zapatos, shoe, shoes",
        "normalized": "Zapato",
        "singular": "Zapato",
        "plural": "Zapatos",
        "category": "Calzado",
        "subcategory": "Zapatos",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Zapato Hombre",
    },
    {
        "received": "mocasin, mocasines, loafer, loafers",
        "normalized": "Mocasin",
        "singular": "Mocasin",
        "plural": "Mocasines",
        "category": "Calzado",
        "subcategory": "Mocasines",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Mocasin Hombre",
    },
    {
        "received": "ballerina, ballerinas, guillermina, guilleminas, guillerminas, flat, flats",
        "normalized": "Ballerina",
        "singular": "Ballerina",
        "plural": "Ballerinas",
        "category": "Calzado",
        "subcategory": "Ballerinas",
        "size_guide_family": "Calzado",
        "can_one_size": False,
        "examples": "Ballerina Mujer",
    },
    {
        "received": "media, medias, calcetin, calcetines, sock, socks",
        "normalized": "Media",
        "singular": "Media",
        "plural": "Medias",
        "category": "Accesorios",
        "subcategory": "Medias",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Medias Unisex",
    },
    {
        "received": "pasamontana, pasamontanas, balaclava, balaclavas",
        "normalized": "Pasamontana",
        "singular": "Pasamontana",
        "plural": "Pasamontanas",
        "category": "Accesorios",
        "subcategory": "Pasamontanas",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Pasamontana Unisex",
    },
    {
        "received": "lente, lentes, lentes de sol, gafa, gafas, gafas de sol, sunglasses",
        "normalized": "Lente de Sol",
        "singular": "Lente de Sol",
        "plural": "Lentes de Sol",
        "category": "Accesorios",
        "subcategory": "Lentes de Sol",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Lentes de Sol Unisex",
    },
    {
        "received": "billetera, billeteras, wallet, wallets, monedero, monederos",
        "normalized": "Billetera",
        "singular": "Billetera",
        "plural": "Billeteras",
        "category": "Accesorios",
        "subcategory": "Billeteras",
        "size_guide_family": "Accesorios",
        "can_one_size": True,
        "examples": "Billetera Hombre",
    },
    {
        "received": "botella, botellas, bottle, termo, termos",
        "normalized": "Botella",
        "singular": "Botella",
        "plural": "Botellas",
        "category": "Accesorios",
        "subcategory": "Botellas",
        "size_guide_family": "Sin guia",
        "can_one_size": True,
        "examples": "Botella Termica",
    },
    {
        "received": "cooler, coolers, conservadora, conservadoras",
        "normalized": "Cooler",
        "singular": "Cooler",
        "plural": "Coolers",
        "category": "Accesorios",
        "subcategory": "Coolers",
        "size_guide_family": "Sin guia",
        "can_one_size": True,
        "examples": "Cooler Portatil",
    },
    {
        "received": "baston, bastones, trekking pole, trekking poles",
        "normalized": "Baston",
        "singular": "Baston",
        "plural": "Bastones",
        "category": "Accesorios",
        "subcategory": "Bastones",
        "size_guide_family": "Sin guia",
        "can_one_size": True,
        "examples": "Bastones de Trekking",
    },
    {
        "received": "cuchilla, cuchillas, cuchillo, cuchillos, navaja, navajas, knife",
        "normalized": "Cuchilla",
        "singular": "Cuchilla",
        "plural": "Cuchillas",
        "category": "Accesorios",
        "subcategory": "Cuchillas",
        "size_guide_family": "Sin guia",
        "can_one_size": True,
        "examples": "Cuchilla Multiuso",
    },
    {
        "received": "funda para lata, fundas para lata, portalata, portalatas, can cooler",
        "normalized": "Funda para Lata",
        "singular": "Funda para Lata",
        "plural": "Fundas para Lata",
        "category": "Accesorios",
        "subcategory": "Fundas para Lata",
        "size_guide_family": "Sin guia",
        "can_one_size": True,
        "examples": "Funda para Lata",
    },

    # --- vestidos (septiembre 2026) --------------------------------------
    # "VESTIDOS" bloqueaba una carga de Rockford y parecia una restriccion de
    # la marca. No lo era: el diccionario NO tenia ningun tipo para vestido,
    # ni en singular ni en plural ni en ingles. Rockford admite Vestuario
    # (COMMERCIAL_BRAND_ALLOWED_CLASSES), asi que en cuanto el tipo existe lo
    # acepta igual que Columbia, Vans o Hush Puppies Kids: el filtro por marca
    # es por CATEGORIA, nunca por tipo.
    #
    # Va con size_guide_group explicito. Sin el, "vestido" no cae ni en
    # bottom_markers ni en top_markers de resolve_size_guide, el grupo queda
    # vacio y las guias de TOPS y BOTTOMS empatan en prioridad 95: la elegida
    # depende del orden de la lista, no del producto. TOPS es la que mide
    # busto y cintura, que es como se talla un vestido.
    #
    # "falda" NO se toca aqui: sigue siendo alias de Short por decision previa
    # del diccionario, y moverla es una decision de negocio aparte.
    {
        "received": "vestido, vestidos, dress, dresses",
        "normalized": "Vestido",
        "singular": "Vestido",
        "plural": "Vestidos",
        "category": "Vestuario",
        "subcategory": "Vestidos",
        "size_guide_family": "Vestuario",
        "size_guide_group": "TOPS",
        "can_one_size": False,
        "examples": "Vestido Mujer Terra",
    },
]


def normalize_product_type(value):
    key = normalize_key(value)
    if not key:
        return None
    for rule in PRODUCT_TYPE_RULES:
        candidates = [rule["normalized"], rule["singular"], rule["plural"], rule["received"]]
        candidate_keys = []
        for candidate in candidates:
            candidate_keys.extend(normalize_key(part) for part in re.split(r"[,;/|]", candidate))
        if key in candidate_keys:
            return dict(rule)
    return None


SIZE_GUIDE_RULES = [
    {
        "priority": 100,
        "brand": "Columbia",
        "category": "Calzado",
        "gender": "Hombre",
        "guide": "CLB_HOMBRE_CALZADO",
        "family": "Calzado",
        "status": "active",
    },
    {
        "priority": 100,
        "brand": "Columbia",
        "category": "Calzado",
        "gender": "Mujer",
        "guide": "CLB_MUJER_CALZADO",
        "family": "Calzado",
        "status": "active",
    },
    {
        "priority": 95,
        "brand": "Columbia",
        "category": "Vestuario",
        "gender": "Mujer",
        "group": "TOPS",
        "guide": "CLB_MUJER_TOPS",
        "family": "Vestuario",
        "status": "active",
    },
    {
        "priority": 95,
        "brand": "Columbia",
        "category": "Vestuario",
        "gender": "Hombre",
        "group": "TOPS",
        "guide": "CLB_HOMBRE_TOPS",
        "family": "Vestuario",
        "status": "active",
    },
    {
        "priority": 95,
        "brand": "Columbia",
        "category": "Vestuario",
        "gender": "Mujer",
        "group": "BOTTOMS",
        "guide": "CLB_MUJER_BOTTOMS",
        "family": "Vestuario",
        "status": "active",
    },
    {
        "priority": 95,
        "brand": "Columbia",
        "category": "Vestuario",
        "gender": "Hombre",
        "group": "BOTTOMS",
        "guide": "CLB_HOMBRE_BOTTOMS",
        "family": "Vestuario",
        "status": "active",
    },
    {
        "priority": 60,
        "brand": "*",
        "category": "Accesorios",
        "gender": "*",
        "guide": "",
        "family": "Accesorios",
        "status": "review",
    },
]


def resolve_size_guide(brand="", category="", product_type="", gender="", age_group="", current_guide=""):
    category_key = normalize_key(category)
    gender_key = normalize_key(gender)
    guide_key = normalize_key(current_guide)
    known_guides = {
        normalize_key(rule.get("guide", ""))
        for rule in SIZE_GUIDE_RULES
        if normalize_text(rule.get("guide", ""))
    }
    product_rule = normalize_product_type(product_type)
    product_group = (product_rule or {}).get("size_guide_group", "")
    if not product_group and category_key == "vestuario":
        product_type_key = normalize_key(product_type)
        bottom_markers = {
            "pantalon", "pantalones", "pants", "jogger", "joggers", "buzo",
            "leggings", "legging", "short", "shorts", "bermuda", "bermudas",
            "falda", "faldas",
        }
        top_markers = {
            "casaca", "casacas", "chaqueta", "jacket", "parka", "polo",
            "polos", "camiseta", "poleron", "polerones", "hoodie",
            "sweatshirt", "camisa", "blusa", "chaleco", "vest",
        }
        if product_type_key in {normalize_key(item) for item in bottom_markers}:
            product_group = "BOTTOMS"
        elif product_type_key in {normalize_key(item) for item in top_markers}:
            product_group = "TOPS"
    if guide_key:
        if known_guides and guide_key not in known_guides:
            return {
                "guide": "",
                "rule": "current_guide_unknown",
                "match_level": "blocked",
                "warning": "Guia de tallas no existe en el diccionario permitido.",
                "status": "blocked",
            }
        if category_key == "calzado" and (
            "vestuario" in guide_key or "top" in guide_key or "bottom" in guide_key
        ):
            return {
                "guide": "",
                "rule": "current_guide_conflict",
                "match_level": "blocked",
                "warning": "Guia de vestuario no compatible con calzado.",
                "status": "blocked",
            }
        if category_key == "vestuario" and (
            "calzado" in guide_key or "zapato" in guide_key or "zapatilla" in guide_key or "footwear" in guide_key
        ):
            return {
                "guide": "",
                "rule": "current_guide_conflict",
                "match_level": "blocked",
                "warning": "Guia de calzado no compatible con vestuario.",
                "status": "blocked",
            }
        if category_key == "vestuario" and product_group == "TOPS" and "bottom" in guide_key:
            return {
                "guide": "",
                "rule": "current_guide_conflict",
                "match_level": "blocked",
                "warning": "Guia de bottoms no compatible con prenda superior.",
                "status": "blocked",
            }
        if category_key == "vestuario" and product_group == "BOTTOMS" and "top" in guide_key:
            return {
                "guide": "",
                "rule": "current_guide_conflict",
                "match_level": "blocked",
                "warning": "Guia de tops no compatible con prenda inferior.",
                "status": "blocked",
            }
    candidates = []
    for rule in SIZE_GUIDE_RULES:
        if rule["status"] == "inactive":
            continue
        brand_ok = rule["brand"] == "*" or normalize_key(rule["brand"]) == normalize_key(brand)
        category_ok = normalize_key(rule["category"]) == category_key
        gender_ok = rule["gender"] == "*" or normalize_key(rule["gender"]) == gender_key
        group_ok = not rule.get("group") or not product_group or rule.get("group") == product_group
        if brand_ok and category_ok and gender_ok and group_ok:
            candidates.append(rule)
    if not candidates:
        return {
            "guide": "",
            "rule": "no_confident_rule",
            "match_level": "none",
            "warning": "Sin regla confiable; requiere revision.",
            "status": "warning",
        }
    selected = sorted(candidates, key=lambda item: item["priority"], reverse=True)[0]
    return {
        "guide": selected["guide"],
        "rule": f"{selected['brand']} + {selected['category']} + {selected['gender']}",
        "match_level": "high" if selected["guide"] else "review",
        "warning": "" if selected["guide"] else "Accesorio o categoria sin guia automatica.",
        "status": "approved" if selected["guide"] else "warning",
    }


INPUT_COLUMNS = [
    ("Mod-Col", "Identificacion", True, "Codigo modelo-color. Ej: 2092991-NRY"),
    ("Codigo modelo", "Identificacion", False, "Modelo sin color."),
    ("Codigo color", "Identificacion", False, "Codigo color fuente."),
    ("Marca", "Marca y clasificacion", True, "Columbia, Rockford, Hush Puppies, Vans."),
    ("Genero", "Marca y clasificacion", True, "Hombre, Mujer, Unisex, Nino, Nina."),
    ("Categoria", "Marca y clasificacion", True, "Calzado, Vestuario, Accesorios."),
    ("Sub Categoria", "Marca y clasificacion", False, "Casacas, Zapatillas, Polos."),
    ("Tipo de prenda", "Marca y clasificacion", True, "Debe terminar pluralizado hacia Shopify."),
    ("Color web", "Marca y clasificacion", True, "Nombre visible del color, no solo codigo."),
    ("Title", "Descripcion y contenido", True, "Nombre comercial final en Shopify."),
    ("Body HTML", "Descripcion y contenido", False, "HTML final si ya viene armado."),
    ("Descripcion", "Descripcion y contenido", False, "Descripcion base."),
    ("Caracteristicas", "Descripcion y contenido", False, "Beneficios/caracteristicas."),
    ("Materiales", "Descripcion y contenido", False, "Composicion o materiales."),
    ("Cuidados", "Descripcion y contenido", False, "Instrucciones de cuidado."),
    ("Talla", "Variantes y tallas", True, "Talla real de BigQuery/ARTI."),
    ("SKU", "Variantes y tallas", True, "SKU/Cod Int obligatorio por variante."),
    ("EAN", "Variantes y tallas", False, "Codigo de barras si existe."),
    ("Precio", "Precios", True, "Precio final."),
    ("Compare At Price", "Precios", False, "Precio antes si aplica."),
    ("Stock disponible", "Inventario", False, "Stock eComm referencial."),
    ("Tecnologia", "Tecnologias y metacampos", False, "Separar por coma. Ej: Omni-Tech, Omni-Grip."),
    ("Logo tecnologia", "Tecnologias y metacampos", False, "GIDs o nombres de metaobjetos."),
    ("Guia de tallas", "Guia de talla", False, "Guia Shopify o vacio para resolver."),
    ("Tags sugeridos", "SEO y tags", False, "Tags separados por coma."),
    ("Handle sugerido", "Campo tecnico autogenerado", False, "No llenar manualmente. Se arma como tipo de prenda + genero + marca + Mod-Col."),
    ("SEO Title", "SEO y tags", False, "Titulo SEO opcional."),
    ("SEO Description", "SEO y tags", False, "Descripcion SEO opcional."),
    ("Fecha publicacion", "Programacion", False, "yyyy-mm-dd hh:mm."),
    ("Observaciones", "Control", False, "Notas de revision."),
]


def input_dictionary_rows():
    rows = []
    for column, group, required, help_text in INPUT_COLUMNS:
        rows.append(
            {
                "Nombre exacto": column,
                "Grupo": group,
                "Descripcion": help_text,
                "Tipo de dato": "Texto" if column not in {"Precio", "Compare At Price", "Stock disponible"} else "Numero",
                "Formato permitido": "Libre controlado",
                "Ejemplo correcto": example_for_column(column),
                "Ejemplo incorrecto": "",
                "Obligatorio": "SI" if required else "NO",
                "Valores permitidos": allowed_values_for_column(column),
                "Regla de validacion": validation_rule_for_column(column),
                "Transformacion": transformation_for_column(column),
                "Destino Shopify": shopify_target_for_column(column),
                "Si esta vacio": "Bloquea" if required else "Advertencia o autocompletado",
                "Mensaje": "Campo obligatorio faltante" if required else "Revisar si aplica",
            }
        )
    return rows


def example_for_column(column):
    return {
        "Mod-Col": "2092991-NRY",
        "Marca": "Columbia",
        "Genero": "Mujer",
        "Categoria": "Vestuario",
        "Tipo de prenda": "Casacas",
        "Color web": "Negro",
        "Title": "Casaca Impermeable Mujer Arcadia II",
        "Talla": "M",
        "SKU": "5327440",
        "EAN": "7800000000000",
        "Precio": "299.90",
        "Tecnologia": "Omni-Tech, Omni-Shield",
        "Handle sugerido": "casacas-mujer-columbia-2092991-nry",
    }.get(column, "")


def allowed_values_for_column(column):
    if column == "Marca":
        return "Columbia, Rockford, Hush Puppies, Vans, Patagonia, Sorel, Mountain Hardwear"
    if column == "Genero":
        return "Hombre, Mujer, Unisex, Nino, Nina, Bebe"
    if column == "Categoria":
        return "Calzado, Vestuario, Accesorios"
    return ""


def validation_rule_for_column(column):
    if column == "Talla":
        return "No crear K, 0, 000 ni vacios; usar solo tallas existentes en BigQuery/ARTI."
    if column == "SKU":
        return "Obligatorio por variante. No se envia variante sin SKU."
    if column == "Guia de tallas":
        return "Debe ser compatible con categoria/genero; contradicciones bloquean."
    if column == "Body HTML":
        return "Solo etiquetas seguras; no scripts/styles/eventos."
    if column == "Handle sugerido":
        return "Autogenerado por la app; no requiere carga del Brand Manager."
    return "Normalizar espacios, tildes y valores equivalentes."


def transformation_for_column(column):
    if column == "Tipo de prenda":
        return "Normaliza y pluraliza para Shopify."
    if column in {"Materiales", "Cuidados", "Caracteristicas"}:
        return "Puede construir Body HTML por secciones."
    if column == "Tecnologia":
        return "Convierte a list.single_line_text_field y resuelve logo metaobjeto si existe."
    if column == "Handle sugerido":
        return "Se arma con tipo de prenda + genero + marca + codigo modelo-color."
    return "Se limpia y se usa en validacion/carga."


def shopify_target_for_column(column):
    mapping = {
        "Title": "Product.title",
        "Body HTML": "Product.bodyHtml",
        "Marca": "Product.vendor + custom.marca",
        "Tipo de prenda": "Product.productType + custom.tipo",
        "Tags sugeridos": "Product.tags",
        "SKU": "Variant.sku",
        "EAN": "Variant.barcode",
        "Precio": "Variant.price",
        "Tecnologia": "custom.tecnologia",
        "Logo tecnologia": "custom.logo",
        "Materiales": "custom.materialidad / Body HTML",
        "Guia de tallas": "custom.guia_de_tallas",
    }
    return mapping.get(column, "Campo auxiliar / reporte")


def validate_catalog_row(row):
    issues = []
    normalized = {}
    for column, _, required, _ in INPUT_COLUMNS:
        value = normalize_text(row.get(column, "")) if hasattr(row, "get") else ""
        normalized[column] = value
        if required and not value:
            issues.append({"field": column, "level": "bloqueo", "message": "Campo obligatorio vacio."})
    if is_invalid_size_for_creation(normalized.get("Talla")):
        issues.append({"field": "Talla", "level": "bloqueo", "message": "Talla invalida para creacion."})
    type_rule = normalize_product_type(normalized.get("Tipo de prenda"))
    if not type_rule:
        # Se nombra el tipo que fallo. Antes el mensaje era generico y la marca
        # no sabia cual de sus valores corregir.
        tipo_recibido = normalize_text(normalized.get("Tipo de prenda"))
        detalle = f'"{tipo_recibido}" no esta en el diccionario de tipos.' if tipo_recibido else "Tipo de prenda vacio."
        issues.append({"field": "Tipo de prenda", "level": "advertencia", "message": detalle})
    size_decision = resolve_size_guide(
        brand=normalized.get("Marca"),
        category=normalized.get("Categoria"),
        product_type=normalized.get("Tipo de prenda"),
        gender=normalized.get("Genero"),
        current_guide=normalized.get("Guia de tallas"),
    )
    if size_decision["status"] == "blocked":
        issues.append({"field": "Guia de tallas", "level": "bloqueo", "message": size_decision["warning"]})
    return {"normalized": normalized, "issues": issues, "size_guide_decision": size_decision}


def sanitize_body_html(value):
    """Conservative sanitizer for preview/reporting, not a full browser parser."""
    text = normalize_text(value)
    if not text:
        return "", []
    changes = []
    cleaned = re.sub(r"<\s*(script|style)[^>]*>.*?<\s*/\s*\1\s*>", "", text, flags=re.I | re.S)
    if cleaned != text:
        changes.append("Se eliminaron script/style.")
    cleaned2 = re.sub(r"\s+on[a-z]+\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.I | re.S)
    if cleaned2 != cleaned:
        changes.append("Se eliminaron eventos HTML.")
    allowed = {"p", "br", "ul", "ol", "li", "strong", "b", "em", "i", "section", "div", "h3"}

    def repl(match):
        slash, tag = match.group(1), match.group(2).lower()
        if tag not in allowed:
            changes.append(f"Etiqueta no permitida removida: {tag}")
            return html.escape(match.group(0))
        return f"<{slash}{tag}>"

    cleaned3 = re.sub(r"<\s*(/?)\s*([a-z0-9]+)(?:\s+[^>]*)?>", repl, cleaned2, flags=re.I)
    cleaned3 = re.sub(r"(<br>\s*){3,}", "<br><br>", cleaned3)
    return cleaned3, list(dict.fromkeys(changes))
