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
    "features": [
        "Caracteristicas", "Características", "Features", "Beneficios", "Bullets",
        "Listado de características", "Listado de caracteristicas", "Descripcion corta",
        "Descripción corta",
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
        "received": "polo, polos, camiseta, t-shirt, tshirt",
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
        "received": "poleron, polerón, hoodie, sweatshirt",
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
        "received": "gorro, beanie, sombrero, jockey",
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
        "received": "mochila, backpack, bolso, cartera, bag",
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
        issues.append({"field": "Tipo de prenda", "level": "advertencia", "message": "Tipo no reconocido en diccionario."})
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
