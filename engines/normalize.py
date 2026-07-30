"""Motor de normalizacion y reglas comunes.

Sin dependencias de Streamlit. Texto, columnas, fechas y tallas."""

import math
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import pandas as pd


SIZE_ORDER_GROUPS = [
    ["XXXS", "3XS"],
    ["XXS", "2XS"],
    ["XS"],
    ["S"],
    ["M"],
    ["L"],
    ["XL"],
    ["XXL", "2XL"],
    ["XXXL", "3XL"],
    ["XXXXL", "4XL"],
]

SIZE_ORDER = {}
for idx, group in enumerate(SIZE_ORDER_GROUPS, start=1):
    for value in group:
        SIZE_ORDER[value] = idx

for idx, value in enumerate(["28", "29", "30", "31", "32", "33", "34", "36", "38", "40", "42", "44"], start=100):
    SIZE_ORDER[value] = idx

for idx, value in enumerate(
    ["35", "36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "46", "47"],
    start=200,
):
    SIZE_ORDER[value] = idx

for idx, value in enumerate(
    ["5", "5.5", "6", "6.5", "7", "7.5", "8", "8.5", "9", "9.5", "10", "10.5", "11", "11.5", "12", "13"],
    start=300,
):
    SIZE_ORDER[value] = idx



ARTI_COLUMN_ALIASES_APP = {
    "CODINT_MA": ["CODINT_MA", "codint_ma", "codint", "sku", "sku_producto", "id_producto", "idproducto"],
    "COD MOD COL": ["COD MOD COL", "COD_MOD_COL", "cod_mod_col", "codmod_codcol", "mod_col", "modelo_color", "codigo_modelo_color"],
    "Mod-Col": ["Mod-Col", "MOD_COL", "mod_col", "codmod_codcol", "modelo_color", "codigo_modelo_color"],
    "TALNUM_MA": ["TALNUM_MA", "talnum_ma", "talla_numero", "talla", "size"],
    "MARCA_MA": ["MARCA_MA", "marca_ma", "marca", "brand", "vendor"],
    "ColorNombre": [
        "Color Web", "color_web", "nombre_color", "Nombre Color", "Color Nombre",
        "color_nombre", "desc_color", "descripcion_color", "des_color", "color_descripcion",
        "color_desc", "COLOR_WEB", "NOMBRE_COLOR", "DESC_COLOR", "descol_ma", "nomcol_ma",
        "color_forus", "Color Forus",
    ],
    "Precio": ["Precio", "precio_ma", "precio", "price", "precio_venta", "pvp"],
    "CodBarras": [
        "CodBarras", "codbarras", "CODBARRAS", "cod_barras", "codigo_barras", "codigo_barra",
        "codigo de barras", "codigo de barra", "ean", "EAN", "upc", "UPC", "barcode", "bar_code",
        "cod_ean", "codigo_ean", "gtin", "ean13", "ean_13", "barra", "barras", "codbarra",
        "cod_barra", "codbar", "cod_bar", "codbar_ma", "cod_bar_ma", "CODBAR_MA",
        "COD_BAR_MA", "cod_barr", "codbarr", "cod_barras_ma", "codbarra_ma",
        "codbarras_ma", "barra_ma", "ean_ma", "ean_producto", "ean_prod", "ean_sku",
        "ean13_ma", "gtin_ma", "upc_ma", "upc_producto", "codigo_barras_ma",
        "codigo_barra_producto", "codigo_barras_producto", "codigo_de_barras",
        "codigo_de_barra", "codigo_ean13", "cod_ean13",
    ],
    "NombreModelo": [
        "NombreModelo", "Nombre Modelo", "Nombre del modelo", "Modelo Nombre", "NOMBRE_MODELO",
        "DESC_MODELO", "DESCRIPCION_MODELO", "Descripcion Modelo", "Descripción Modelo",
        "Nombre del Producto", "Nombre Producto", "NOMBRE_PRODUCTO", "Title", "Titulo", "Título",
        "Descripcion Producto", "DESCRIPCION_MA", "MODELO", "nommod_ma", "nom_modelo",
        "desc_modelo", "desmod_ma", "product_name", "modelo_nombre",
    ],
    "DescripcionWeb": [
        "DescripcionWeb", "Descripcion Web", "Descripción Web", "DESCRIPCION_WEB",
        "Product Description", "Descripcion Comercial", "Descripción Comercial",
        "Descripcion", "Descripción", "Body HTML", "BodyHtml",
    ],
    "Caracteristicas": [
        "Caracteristicas", "Características", "CARACTERISTICAS", "Features", "Beneficios",
        "BENEFICIOS", "Bullet", "Bullets", "Descripcion larga", "Descripción larga",
    ],
    "Material": [
        "Material", "MATERIAL", "Materiales", "Materialidad", "Composicion", "Composición",
        "COMPOSICION", "Tipo de Material", "Tipo Material", "Composition",
    ],
    "Cuidado": [
        "Cuidado", "Cuidados", "CUIDADO", "CUIDADOS", "Care", "Instrucciones de cuidado",
        "Lavado", "Washing",
    ],
    "TipoProducto": [
        "TipoProducto", "Tipo Producto", "Tipo De Producto", "Tipo de Producto", "TIPO",
        "TIPO_MA", "Tipo", "Type", "Product Type", "Categoria Producto", "tipo_prenda",
        "Tipo de Prenda", "tipprenda_ma", "prenda",
    ],
    "Categoria": ["Categoria", "Categoría", "CATEGORIA", "Familia", "FAMILIA", "Category"],
    "SubCategoria": [
        "SubCategoria", "Sub Categoria", "Sub Categoría", "SUBCATEGORIA", "SUB CATEGORIA",
        "Subcategory", "Sub Category",
    ],
    "Genero": ["Genero", "Género", "GENERO", "Sexo", "SEXO", "Gender", "genero_ma", "sexo_ma"],
    "Temporada": ["Temporada", "TEMPORADA", "Season", "Coleccion Temporada"],
    "Tecnologia": ["Tecnologia", "Tecnología", "TECNOLOGIA", "TECNOLOGÍA", "Technology", "Tecnologias", "Tecnologías"],
    "Coleccion": ["Coleccion", "Colección", "COLECCION", "Collection"],
    "Ocasion": ["Ocasion", "Ocasión", "OCASION", "Ocasiones", "Occasion"],
    "Deporte": ["Deporte", "DEPORTE", "Sport", "Activity"],
    "Imagen": ["Image Src", "Imagen", "IMAGEN", "Foto", "FOTO", "Url Imagen", "URL Imagen"],
}


_CATALOG_ALIAS_TO_ARTI_TARGET = {
    "mod_col": ["COD MOD COL", "Mod-Col"],
    "sku": ["CODINT_MA"],
    "barcode": ["CodBarras"],
    "size": ["TALNUM_MA"],
    "brand": ["MARCA_MA"],
    "title": ["NombreModelo"],
    "description": ["DescripcionWeb"],
    "features": ["Caracteristicas"],
    "material": ["Material"],
    "care": ["Cuidado"],
    "product_type": ["TipoProducto"],
    "category": ["Categoria"],
    "subcategory": ["SubCategoria"],
    "gender": ["Genero"],
    "color_web": ["ColorNombre"],
    "season": ["Temporada"],
    "collection": ["Coleccion"],
    "occasion": ["Ocasion"],
    "sport": ["Deporte"],
    "technology": ["Tecnologia"],
    "image": ["Imagen"],
    "price": ["Precio"],
}


def normalize_header(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s_\-./]+", "", text)
    text = (
        text.replace("Ã¡", "a")
        .replace("Ã©", "e")
        .replace("Ã­", "i")
        .replace("Ã³", "o")
        .replace("Ãº", "u")
        .replace("Ã±", "n")
    )
    return text


def first_existing_column(df, candidates):
    normalized = {normalize_header(col): col for col in df.columns}
    for candidate in candidates:
        found = normalized.get(normalize_header(candidate))
        if found is not None:
            return found
    return None


def clean_value(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = [clean_value(item) for item in value]
        return " | ".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = [clean_value(item) for item in value.values()]
        return " | ".join(part for part in parts if part)
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def repair_mojibake_text(value):
    text = clean_value(value)
    if not text:
        return text
    markers = ("Ã", "Â", "â")
    if not any(marker in text for marker in markers):
        return text

    def score(candidate):
        return sum(candidate.count(marker) for marker in markers)

    repaired = text
    for _ in range(3):
        candidates = [repaired]
        for source_encoding in ("latin1", "cp1252"):
            try:
                candidate = repaired.encode(source_encoding).decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                continue
            candidates.append(candidate)
        best = min(candidates, key=score)
        if best == repaired:
            break
        repaired = best

    replacements = {
        "â€“": "-",
        "â€”": "-",
        "â€˜": "'",
        "â€™": "'",
        "â€œ": '"',
        "â€�": '"',
        "â€¢": "-",
        "Â·": "-",
    }
    for bad, good in replacements.items():
        repaired = repaired.replace(bad, good)
    accent_lower = {"Á": "á", "É": "é", "Í": "í", "Ó": "ó", "Ú": "ú", "Ñ": "ñ"}
    for upper, lower in accent_lower.items():
        repaired = re.sub(rf"(?<=[a-z]){upper}", lower, repaired)
    repaired = re.sub(
        r"(?<=[a-záéíóúñ])([A-Z])(?=\b)",
        lambda match: match.group(1).lower(),
        repaired,
    )
    return repaired


def repair_mojibake_dataframe(df):
    if df is None:
        return df
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    repaired = df.copy()
    repaired.columns = [repair_mojibake_text(column) for column in repaired.columns]
    for column in repaired.columns:
        repaired[column] = repaired[column].map(
            lambda value: repair_mojibake_text(value)
            if isinstance(value, str) and any(marker in value for marker in ("Ã", "Â", "â"))
            else value
        )
    return repaired


def safe_float_value(value, default=0.0):
    try:
        text = clean_value(value)
        if not text:
            return default
        return float(text.replace(",", "."))
    except (TypeError, ValueError):
        return default


def safe_int_value(value, default=0):
    return int(safe_float_value(value, default))


def looks_like_mod_col(value):
    text = clean_value(value).upper()
    if not text or text.startswith("UNNAMED:"):
        return False
    if normalize_header(text) in {"modcol", "codmodcol", "codigomodelocolor", "codigomodelo"}:
        return False
    return bool(re.fullmatch(r"[A-Z0-9]+(?:[-_ ][A-Z0-9]+)+", text))


def product_lookup_key(value):
    return re.sub(r"[^A-Z0-9]+", "", clean_value(value).upper())


def product_lookup_candidates(value):
    raw = clean_value(value).upper()
    compact = product_lookup_key(raw)
    candidates = [raw, compact]
    stripped_raw = re.sub(r"^[A-Z]{1,4}(?=\d)", "", raw)
    stripped_compact = re.sub(r"^[A-Z]{1,4}(?=\d)", "", compact)
    if stripped_raw != raw:
        candidates.append(stripped_raw)
        candidates.append(product_lookup_key(stripped_raw))
    if stripped_compact != compact:
        candidates.append(stripped_compact)
    return list(dict.fromkeys(candidate for candidate in candidates if clean_value(candidate)))


def variant_mod_col_candidates(variant):
    sku = clean_value((variant or {}).get("Variant SKU")).upper()
    if not sku:
        return []
    candidates = [sku]
    parts = [part for part in re.split(r"[-_ ]+", sku) if part]
    if len(parts) >= 2:
        candidates.append(f"{parts[0]}-{parts[1]}")
    return list(dict.fromkeys(candidate for candidate in candidates if looks_like_mod_col(candidate)))


def coalesce_duplicate_columns(df):
    if df is None or not isinstance(df, pd.DataFrame) or not df.columns.duplicated().any():
        return df
    result = pd.DataFrame(index=df.index)
    for column in dict.fromkeys(df.columns):
        same_name = df.loc[:, df.columns == column]
        if same_name.shape[1] == 1:
            result[column] = same_name.iloc[:, 0]
            continue
        merged = same_name.iloc[:, 0].copy()
        for index in range(1, same_name.shape[1]):
            candidate = same_name.iloc[:, index]
            empty_mask = merged.map(clean_value) == ""
            merged.loc[empty_mask] = candidate.loc[empty_mask]
        result[column] = merged
    return result


def normalize_arti_columns_for_app(df):
    if df is None or df.empty:
        return df
    result = coalesce_duplicate_columns(df).copy()
    for target, aliases in ARTI_COLUMN_ALIASES_APP.items():
        if target not in result.columns:
            result[target] = ""
        for alias in aliases:
            candidate = first_existing_column(result, [alias])
            if candidate is None or candidate == target:
                continue
            fill_mask = result[target].map(clean_value).eq("") & result[candidate].map(clean_value).ne("")
            if fill_mask.any():
                result.loc[fill_mask, target] = result.loc[fill_mask, candidate]
    if "Mod-Col" not in result.columns or result["Mod-Col"].map(clean_value).eq("").all():
        source = first_existing_column(result, ["COD MOD COL"])
        if source is not None:
            result["Mod-Col"] = result[source]
    for target in ARTI_COLUMN_ALIASES_APP:
        if target not in result.columns:
            result[target] = ""
    return result


def expected_catalog_vendors(brand_config):
    values = {
        clean_value(brand_config.get("vendor")).lower(),
        *[clean_value(value).lower() for value in brand_config.get("legacy_vendors", [])],
        *[clean_value(value).lower() for value in brand_config.get("allowed_arti_brands", [])],
    }
    return {value for value in values if value}


def first_row_value(row, columns):
    for column in columns:
        value = clean_value(row.get(column))
        if value:
            return value
    return ""


def parse_publication_date(value):
    text = clean_value(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+(\.0)?", text):
        # Excel serial date fallback.
        try:
            base = datetime(1899, 12, 30, tzinfo=timezone(timedelta(hours=-5)))
            return (base + timedelta(days=float(text))).isoformat()
        except Exception:
            return text
    normalized = text.replace("Z", "+00:00")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}(:\d{2})?", normalized):
        normalized = normalized.replace(" ", "T")
    formats = [
        "%d/%m/%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
    ]
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
        for fmt in formats:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone(timedelta(hours=-5)))
    return parsed.isoformat()


def parse_iso_datetime(value):
    text = clean_value(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_datetime_lima(value):
    parsed = parse_iso_datetime(value)
    if parsed is None:
        return ""
    lima_time = parsed.astimezone(timezone(timedelta(hours=-5)))
    return lima_time.strftime("%d/%m/%Y %H:%M")


def publication_date_from_row(row):
    if "Publication Publish Date" in row.index:
        return parse_publication_date(row.get("Publication Publish Date"))
    return parse_publication_date(
        first_row_value(
            row,
            [
                "Fecha publicacion web",
                "Fecha de publicacion web",
                "Fecha publicación web",
                "Fecha de publicación web",
                "Fecha publicaciÃ³n",
                "Fecha publicacion",
                "Fecha de publicaciÃ³n",
                "Fecha de publicacion",
                "Publish Date",
                "Publication Date",
                "Published At",
            ],
        )
    )


def normalize_size(value):
    text = clean_value(value).upper()
    if text in {"NAN", "NONE", "NULL", "NA", "N/A", "#N/A", "#N/D", "#ND", "SIN TALLA"}:
        return ""
    text = text.replace("TALLA", "").replace("SIZE", "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace(",", ".")
    aliases = {
        "OS": "O/S",
        "UNICA": "O/S",
        "ÃšNICA": "O/S",
        "ÃƒÅ¡NICA": "O/S",
        "EXTRA SMALL": "XS",
        "SX": "XS",
        "SMALL": "S",
        "MEDIUM": "M",
        "LARGE": "L",
        "EXTRA LARGE": "XL",
        "X SMALL": "XS",
        "X LARGE": "XL",
        "2 EXTRA LARGE": "XXL",
        "3 EXTRA LARGE": "XXXL",
    }
    return aliases.get(text, text)


def _size_lookup_keys(value):
    keys = []
    raw = clean_value(value).upper()
    normalized = clean_value(normalize_size(value)).upper()
    aliases = {
        "SX": "XS",
        "XS": "SX",
        "OS": "O/S",
        "O/S": "OS",
        "UNICA": "O/S",
        "ÃšNICA": "O/S",
        "ÃƒÅ¡NICA": "O/S",
        "TALLA UNICA": "O/S",
        "TALLA ÃšNICA": "O/S",
        "TALLA ÃƒÅ¡NICA": "O/S",
        "0": "O/S",
        "000": "O/S",
    }
    for key in (raw, normalized, aliases.get(raw, ""), aliases.get(normalized, "")):
        if key and key not in keys:
            keys.append(key)
    return keys


def _set_row_by_size_keys(mapping, size, row):
    for key in _size_lookup_keys(size):
        mapping.setdefault(key, row)


def _row_by_size_keys(mapping, size):
    for key in _size_lookup_keys(size):
        row = mapping.get(key)
        if row is not None:
            return row
    return None


def size_sort_key(size):
    normalized = normalize_size(size)
    if normalized in SIZE_ORDER:
        return (0, SIZE_ORDER[normalized], normalized)
    if re.fullmatch(r"\d+(\.\d+)?", normalized):
        return (1, float(normalized), normalized)
    return (9, 9999, normalized)


def slugify(value):
    text = clean_value(value).lower()
    text = (
        text.replace("Ã¡", "a")
        .replace("Ã©", "e")
        .replace("Ã­", "i")
        .replace("Ã³", "o")
        .replace("Ãº", "u")
        .replace("Ã±", "n")
    )
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "producto"
