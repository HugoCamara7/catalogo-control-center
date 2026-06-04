import io
import base64
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

from generate_columbia_matrixify import (
    SITE_CONFIGS,
    build_columbia_matrixify,
    build_matrixify_updates,
    get_brand_config,
    input_brand_report,
    is_internal_k_size,
    is_one_size,
    is_zero_size,
    read_arti_source,
)
from shopify_api import (
    DEFAULT_API_VERSION,
    ShopifyApiError,
    fetch_metaobject_definitions,
    fetch_metaobjects,
    fetch_product_options_and_variants,
    fetch_products,
    file_create,
    metafields_set,
    normalize_shop_domain,
    product_create,
    product_create_media,
    product_delete_media,
    product_options_reorder,
    publishable_publish,
    product_set_files,
    product_update,
    product_variants_bulk_create,
    product_variants_bulk_reorder,
    staged_upload_image,
    test_connection,
    wait_file_statuses,
    wait_media_statuses,
)

try:
    from shopify_api import fetch_metaobjects_for_definition, fetch_metafield_definition
except ImportError:
    fetch_metaobjects_for_definition = None
    fetch_metafield_definition = None


APP_TITLE = "Catalogo Control Center"
DEFAULT_ARTI_PATH = "data/arti.xlsx"
DEFAULT_ARTI_CSV_PATH = "data/arti.csv"
DEFAULT_ARTI_ZIP_PATH = "data/arti.zip"
DEFAULT_MATRIXIFY_PATH = "data/matrixify_modelo.xlsx"
FORUS_LOGO_PATH = Path("assets/forus_logo.png")
SHOPIFY_LOGO_PATH = Path("assets/shopify_logo.png")

MATRIXIFY_COLUMNS = [
    "Command",
    "Handle",
    "Title",
    "Body HTML",
    "Vendor",
    "Type",
    "Tags",
    "Status",
    "Published",
    "Option1 Name",
    "Option1 Value",
    "Option2 Name",
    "Option2 Value",
    "Variant SKU",
    "Variant Barcode",
    "Variant Price",
    "Variant Compare At Price",
    "Variant Inventory Qty",
    "Variant Inventory Tracker",
    "Variant Inventory Policy",
    "Variant Fulfillment Service",
    "Variant Requires Shipping",
    "Variant Taxable",
    "Variant Weight",
    "Variant Weight Unit",
    "Image Src",
    "Image Position",
    "Metafield: custom.estilo [single_line_text_field]",
    "Metafield: custom.color [single_line_text_field]",
]

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


def normalize_header(value):
    text = str(value or "").strip().lower()
    text = re.sub(r"[\s_\-./]+", "", text)
    text = (
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
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
    if pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def looks_like_mod_col(value):
    text = clean_value(value).upper()
    if not text or text.startswith("UNNAMED:"):
        return False
    if normalize_header(text) in {"modcol", "codmodcol", "codigomodelocolor", "codigomodelo"}:
        return False
    return bool(re.fullmatch(r"[A-Z0-9]+(?:[-_ ][A-Z0-9]+)+", text))


def product_lookup_key(value):
    return re.sub(r"[^A-Z0-9]+", "", clean_value(value).upper())


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


def publication_date_from_row(row):
    if "Publication Publish Date" in row.index:
        return parse_publication_date(row.get("Publication Publish Date"))
    return parse_publication_date(
        first_row_value(
            row,
            [
                "Fecha publicación",
                "Fecha publicacion",
                "Fecha de publicación",
                "Fecha de publicacion",
                "Publish Date",
                "Publication Date",
                "Published At",
            ],
        )
    )


def normalize_size(value):
    text = clean_value(value).upper()
    text = text.replace("TALLA", "").replace("SIZE", "").strip()
    text = re.sub(r"\s+", " ", text)
    text = text.replace(",", ".")
    aliases = {
        "EXTRA SMALL": "XS",
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
        text.replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
    )
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "producto"


def read_excel(uploaded_file):
    return pd.read_excel(uploaded_file, dtype=object).dropna(how="all")


def read_excel_path(path):
    return pd.read_excel(path, dtype=object).dropna(how="all")


def get_bigquery_config():
    config = {}
    try:
        if "bigquery" in st.secrets:
            config.update(dict(st.secrets["bigquery"]))
        if "gcp_service_account" in st.secrets:
            config["service_account_info"] = dict(st.secrets["gcp_service_account"])
    except Exception:
        return {}

    service_account_json = config.pop("service_account_json", None)
    if service_account_json and "service_account_info" not in config:
        config["service_account_info"] = json.loads(service_account_json)
    return config


def is_bigquery_configured(config):
    if not config:
        return False
    enabled = str(config.get("enabled", "true")).strip().lower()
    if enabled in ("0", "false", "no", "off"):
        return False
    has_query = bool(str(config.get("query", "")).strip())
    service_project = ""
    if isinstance(config.get("service_account_info"), dict):
        service_project = str(config["service_account_info"].get("project_id", "")).strip()
    has_project = bool(str(config.get("project_id", "")).strip() or service_project)
    table = str(config.get("table", "")).strip()
    has_full_table = table.count(".") == 2
    has_split_table = has_project and bool(str(config.get("dataset", "")).strip() and table)
    has_table = has_full_table or has_split_table
    return has_query or has_table


def get_shopify_config(site_key):
    config = {}
    try:
        shopify_sites = st.secrets.get("shopify_sites", {})
        if site_key in shopify_sites:
            config.update(dict(shopify_sites[site_key]))
    except Exception:
        return {}

    return {
        "shop_domain": normalize_shop_domain(config.get("shop_domain") or config.get("domain")),
        "client_id": clean_value(config.get("client_id")),
        "client_secret": clean_value(config.get("client_secret")),
        "admin_access_token": clean_value(
            config.get("admin_access_token") or config.get("access_token") or config.get("token")
        ),
        "api_version": clean_value(config.get("api_version")) or DEFAULT_API_VERSION,
    }


def is_shopify_configured(config):
    has_token = bool(config.get("admin_access_token"))
    has_client_credentials = bool(config.get("client_id") and config.get("client_secret"))
    return bool(config.get("shop_domain") and (has_token or has_client_credentials))


def read_arti_for_app(brand_config):
    arti_df, source = read_arti_source(
        bigquery_config=get_bigquery_config(),
        allow_local_fallback=False,
        brand_config=brand_config,
    )
    return arti_df.dropna(how="all"), source


def detect_input_columns(df):
    return {
        "style": first_existing_column(df, ["style", "estilo", "modelo", "codigo", "sku padre", "parent sku", "item"]),
        "title": first_existing_column(df, ["title", "titulo", "producto", "descripcion", "description", "nombre"]),
        "vendor": first_existing_column(df, ["vendor", "marca", "brand"]),
        "type": first_existing_column(df, ["type", "tipo", "categoria", "category"]),
        "color": first_existing_column(df, ["color", "colour"]),
        "price": first_existing_column(df, ["price", "precio", "precio venta", "variant price", "pvp"]),
        "barcode": first_existing_column(df, ["barcode", "ean", "upc", "codigo barra", "codigo de barra"]),
        "sku": first_existing_column(df, ["sku", "variant sku", "codigo sku"]),
        "image": first_existing_column(df, ["image src", "imagen", "image", "url imagen", "foto"]),
        "tags": first_existing_column(df, ["tags", "etiquetas"]),
        "body": first_existing_column(df, ["body html", "descripcion larga", "body", "detalle"]),
    }


def detect_arti_columns(df):
    return {
        "style": first_existing_column(df, ["style", "estilo", "modelo", "codigo", "sku padre", "parent sku", "item"]),
        "size": first_existing_column(df, ["size", "talla", "tallas"]),
        "sku": first_existing_column(df, ["sku", "variant sku", "codigo sku", "codigo"]),
        "barcode": first_existing_column(df, ["barcode", "ean", "upc", "codigo barra", "codigo de barra"]),
        "color": first_existing_column(df, ["color", "colour"]),
    }


def build_arti_lookup(arti_df, arti_cols):
    if not arti_cols["style"] or not arti_cols["size"]:
        return {}

    lookup = defaultdict(list)
    for _, row in arti_df.iterrows():
        style = clean_value(row.get(arti_cols["style"]))
        size = normalize_size(row.get(arti_cols["size"]))
        if not style or not size:
            continue

        item = {
            "size": size,
            "sku": clean_value(row.get(arti_cols["sku"])) if arti_cols["sku"] else "",
            "barcode": clean_value(row.get(arti_cols["barcode"])) if arti_cols["barcode"] else "",
            "color": clean_value(row.get(arti_cols["color"])) if arti_cols["color"] else "",
        }
        lookup[style.upper()].append(item)

    for style, rows in lookup.items():
        seen = set()
        unique_rows = []
        for item in sorted(rows, key=lambda value: size_sort_key(value["size"])):
            key = item["size"]
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append(item)
        lookup[style] = unique_rows

    return lookup


def manual_sizes_from_text(value):
    text = clean_value(value)
    if not text:
        return []
    parts = re.split(r"[,;/|]+", text)
    return sorted({normalize_size(part) for part in parts if normalize_size(part)}, key=size_sort_key)


def row_value(row, column_name):
    if not column_name:
        return ""
    return clean_value(row.get(column_name))


def build_matrixify(input_df, arti_df, default_sizes_text):
    input_cols = detect_input_columns(input_df)
    arti_cols = detect_arti_columns(arti_df)
    arti_lookup = build_arti_lookup(arti_df, arti_cols)
    default_sizes = manual_sizes_from_text(default_sizes_text)

    output_rows = []
    issues = []

    if not input_cols["style"]:
        raise ValueError("No pude detectar la columna de estilo/modelo/codigo en el input.")

    for row_number, (_, row) in enumerate(input_df.iterrows(), start=2):
        style = row_value(row, input_cols["style"])
        if not style:
            issues.append({"Fila input": row_number, "Problema": "Sin estilo/modelo/codigo", "Valor": ""})
            continue

        title = row_value(row, input_cols["title"]) or style
        vendor = row_value(row, input_cols["vendor"])
        product_type = row_value(row, input_cols["type"])
        color = row_value(row, input_cols["color"])
        price = row_value(row, input_cols["price"])
        image = row_value(row, input_cols["image"])
        tags = row_value(row, input_cols["tags"])
        body = row_value(row, input_cols["body"])
        base_sku = row_value(row, input_cols["sku"]) or style
        base_barcode = row_value(row, input_cols["barcode"])

        matched_variants = arti_lookup.get(style.upper(), [])
        if matched_variants:
            variants = matched_variants
        else:
            variants = [
                {"size": size, "sku": f"{base_sku}-{size}", "barcode": base_barcode, "color": color}
                for size in default_sizes
            ]
            issues.append(
                {
                    "Fila input": row_number,
                    "Problema": "No hubo match en arti; se usaron tallas manuales",
                    "Valor": style,
                }
            )

        if not variants:
            issues.append({"Fila input": row_number, "Problema": "Sin tallas para expandir", "Valor": style})
            continue

        handle_parts = [vendor, title, style, color]
        handle = slugify("-".join(part for part in handle_parts if part))

        for variant_index, variant in enumerate(sorted(variants, key=lambda value: size_sort_key(value["size"])), start=1):
            variant_color = variant.get("color") or color
            output_rows.append(
                {
                    "Command": "MERGE",
                    "Handle": handle,
                    "Title": title if variant_index == 1 else "",
                    "Body HTML": body if variant_index == 1 else "",
                    "Vendor": vendor if variant_index == 1 else "",
                    "Type": product_type if variant_index == 1 else "",
                    "Tags": tags if variant_index == 1 else "",
                    "Status": "Active" if variant_index == 1 else "",
                    "Published": "TRUE" if variant_index == 1 else "",
                    "Option1 Name": "Talla",
                    "Option1 Value": variant["size"],
                    "Option2 Name": "Color" if variant_color else "",
                    "Option2 Value": variant_color,
                    "Variant SKU": variant.get("sku") or f"{base_sku}-{variant['size']}",
                    "Variant Barcode": variant.get("barcode") or base_barcode,
                    "Variant Price": price,
                    "Variant Compare At Price": "",
                    "Variant Inventory Qty": 0,
                    "Variant Inventory Tracker": "shopify",
                    "Variant Inventory Policy": "deny",
                    "Variant Fulfillment Service": "manual",
                    "Variant Requires Shipping": "TRUE",
                    "Variant Taxable": "TRUE",
                    "Variant Weight": "",
                    "Variant Weight Unit": "kg",
                    "Image Src": image if variant_index == 1 else "",
                    "Image Position": 1 if image and variant_index == 1 else "",
                    "Metafield: custom.estilo [single_line_text_field]": style if variant_index == 1 else "",
                    "Metafield: custom.color [single_line_text_field]": color if variant_index == 1 else "",
                }
            )

    output_df = pd.DataFrame(output_rows).reindex(columns=MATRIXIFY_COLUMNS)
    issues_df = pd.DataFrame(issues, columns=["Fila input", "Problema", "Valor"])
    return output_df, issues_df, input_cols, arti_cols


def to_excel_bytes(matrixify_df, issues_df, input_cols, arti_cols):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrixify_df.to_excel(writer, index=False, sheet_name="Matrixify")
        issues_df.to_excel(writer, index=False, sheet_name="Revision")
        pd.DataFrame(
            [
                {"Archivo": "Input", "Campo": key, "Columna detectada": value or ""}
                for key, value in input_cols.items()
            ]
            + [
                {"Archivo": "Arti", "Campo": key, "Columna detectada": value or ""}
                for key, value in arti_cols.items()
            ]
        ).to_excel(writer, index=False, sheet_name="Mapeo detectado")

        for sheet_name, width in {"Matrixify": 24, "Revision": 38, "Mapeo detectado": 28}.items():
            ws = writer.book[sheet_name]
            ws.freeze_panes = "A2"
            for column_cells in ws.columns:
                ws.column_dimensions[column_cells[0].column_letter].width = width

    buffer.seek(0)
    return buffer


def columbia_to_excel_bytes(matrixify_df, summary_df, issues_df, type_warnings_df=None, skipped_df=None, sial_df=None):
    matrixify_df = coalesce_duplicate_columns(matrixify_df)
    summary_df = coalesce_duplicate_columns(summary_df)
    issues_df = coalesce_duplicate_columns(issues_df)
    type_warnings_df = coalesce_duplicate_columns(type_warnings_df)
    skipped_df = coalesce_duplicate_columns(skipped_df)
    sial_df = coalesce_duplicate_columns(sial_df)
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrixify_df.to_excel(writer, index=False, sheet_name="Products")
        summary_df.to_excel(writer, index=False, sheet_name="Resumen")
        issues_df.to_excel(writer, index=False, sheet_name="Revision")
        if sial_df is not None:
            sial_df.to_excel(writer, index=False, sheet_name="Carga Sial")
        if type_warnings_df is not None:
            type_warnings_df.to_excel(writer, index=False, sheet_name="Tipos nuevos")
        if skipped_df is not None:
            skipped_df.to_excel(writer, index=False, sheet_name="Omitidos sin cambios")

        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                sheet.column_dimensions[column_cells[0].column_letter].width = 18

    buffer.seek(0)
    return buffer


def update_to_excel_bytes(matrixify_df, issues_df):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrixify_df.to_excel(writer, index=False, sheet_name="Products")
        issues_df.to_excel(writer, index=False, sheet_name="Revision")
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                sheet.column_dimensions[column_cells[0].column_letter].width = 22
    buffer.seek(0)
    return buffer


def dataframe_to_excel_bytes(sheets):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            safe_name = sheet_name[:31]
            df.to_excel(writer, index=False, sheet_name=safe_name)
        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for column_cells in sheet.columns:
                sheet.column_dimensions[column_cells[0].column_letter].width = 22
    buffer.seek(0)
    return buffer


def _split_tags(value):
    return [tag.strip() for tag in clean_value(value).split(",") if tag.strip()]


def _join_tags(values):
    return ", ".join(dict.fromkeys(tag for tag in values if clean_value(tag)))


def _split_semicolon_values(value):
    return [item.strip() for item in re.split(r"[;\n\r]+", clean_value(value)) if item.strip()]


def _product_lookup_from_shopify(records):
    by_key = {}
    by_handle = {}

    def add_key(value, record):
        key = clean_value(value).upper()
        compact_key = product_lookup_key(key)
        for candidate in (key, compact_key):
            if candidate and candidate not in by_key:
                by_key[candidate] = record

    for record in records:
        key = clean_value(record.get("Mod-Col")).upper()
        handle = clean_value(record.get("Handle"))
        add_key(key, record)
        for variant in record.get("Variants") or []:
            for candidate in variant_mod_col_candidates(variant):
                add_key(candidate, record)
        if handle and handle not in by_handle:
            by_handle[handle] = record
    return by_key, by_handle


def _source_key_for_update(row):
    for column in ("Mod-Col", "COD MOD COL", "Metafield: custom.codigo_modelo_color [id]"):
        value = clean_value(row.get(column))
        if value:
            return value.upper()
    return ""


def normalize_photo_update_input(df):
    if df is None:
        return None
    source = df.dropna(how="all").copy()
    if source.empty:
        return source

    mod_col = first_existing_column(
        source,
        [
            "Mod-Col",
            "Mod Col",
            "COD MOD COL",
            "Codigo Modelo Color",
            "Código Modelo Color",
            "codigo_modelo_color",
            "Modelo Color",
            "Modelo-Color",
        ],
    )
    if mod_col:
        source["Mod-Col"] = source[mod_col]
        return source

    first_column = source.columns[0]
    values = []
    if looks_like_mod_col(first_column):
        values.append(first_column)
    values.extend(source[first_column].dropna().tolist())
    values = [clean_value(value).upper() for value in values if clean_value(value)]
    return pd.DataFrame({"Mod-Col": values})


def build_shopify_update_preview(
    shopify_products,
    update_input_df,
    operation,
    brand_config,
    tag_mode="merge",
    image_mode="replace",
    only_missing_images=True,
    body_mode="from_input",
):
    by_key, by_handle = _product_lookup_from_shopify(shopify_products)
    rows = []
    issues = []
    operation = clean_value(operation)

    if operation == "siblings":
        products_df = pd.DataFrame(shopify_products)
        if products_df.empty:
            return pd.DataFrame(), pd.DataFrame([{"Problema": "Shopify no devolvio productos"}]), pd.DataFrame()
        products_df["__MODEL"] = products_df["Mod-Col"].map(lambda value: clean_value(value).upper().rsplit("-", 1)[0])
        siblings_by_model = (
            products_df[products_df["__MODEL"] != ""]
            .groupby("__MODEL")["Handle"]
            .apply(lambda values: ", ".join(dict.fromkeys(clean_value(value) for value in values if clean_value(value))))
            .to_dict()
        )
        custom_siblings_by_model = (
            products_df[products_df["__MODEL"] != ""]
            .groupby("__MODEL")["Product ID"]
            .apply(lambda values: json.dumps(list(dict.fromkeys(clean_value(value) for value in values if clean_value(value)))))
            .to_dict()
        )
        for _, product in products_df.iterrows():
            new_value = siblings_by_model.get(product["__MODEL"], "")
            custom_new_value = custom_siblings_by_model.get(product["__MODEL"], "[]")
            current_theme = clean_value(product.get("Siblings"))
            current_custom = clean_value(product.get("Custom Siblings"))
            if not new_value or (current_theme == new_value and current_custom == custom_new_value):
                continue
            rows.append(
                {
                    "Accion": "Actualizar",
                    "Sitio": brand_config["site_label"],
                    "Operacion": "siblings",
                    "Mod-Col": product.get("Mod-Col"),
                    "Product ID": product.get("Product ID"),
                    "Handle": product.get("Handle"),
                    "Campo": "Metafield: theme.siblings + Metafield: custom.siblings",
                    "Valor actual": f"theme: {current_theme} | custom: {current_custom}",
                    "Valor nuevo": new_value,
                    "Valor nuevo custom": custom_new_value,
                    "Metafield: theme.siblings [single_line_text_field]": new_value,
                    "Metafield: custom.siblings [list.product_reference]": custom_new_value,
                    "Estado": "OK",
                    "Observacion": f"{len(_split_tags(new_value))} handles del mismo modelo",
                }
            )
        return pd.DataFrame(rows), pd.DataFrame(issues), pd.DataFrame()

    if operation == "photos":
        update_input_df = normalize_photo_update_input(update_input_df)
    source_df = update_input_df.dropna(how="all").copy() if update_input_df is not None else pd.DataFrame()
    if operation == "photos" and source_df.empty:
        source_df = pd.DataFrame(shopify_products)

    matrixify_rows = []
    for input_index, row in source_df.iterrows():
        key = _source_key_for_update(row)
        handle = clean_value(row.get("Handle"))
        product = by_key.get(key) or by_key.get(product_lookup_key(key)) or by_handle.get(handle)
        if not product:
            issues.append({"Mod-Col": key, "Handle": handle, "Problema": "No se encontro producto en Shopify", "Fila": input_index + 2})
            continue

        product_id = product.get("Product ID")
        product_key = key or clean_value(product.get("Mod-Col")).upper()
        if operation == "tags":
            tags_col = first_existing_column(source_df, ["Tags", "tags", "Etiquetas"])
            if not tags_col:
                issues.append({"Mod-Col": product_key, "Handle": product.get("Handle"), "Problema": "No se encontro columna Tags"})
                continue
            current_tags = _split_tags(product.get("Tags"))
            incoming_tags = _split_tags(row.get(tags_col))
            new_tags = _join_tags(incoming_tags if tag_mode == "replace" else current_tags + incoming_tags)
            rows.append(
                {
                    "Accion": "Actualizar",
                    "Sitio": brand_config["site_label"],
                    "Operacion": "tags",
                    "Mod-Col": product_key,
                    "Product ID": product_id,
                    "Handle": product.get("Handle"),
                    "Campo": "Tags",
                    "Valor actual": product.get("Tags"),
                    "Valor nuevo": new_tags,
                    "Estado": "OK",
                    "Observacion": "REPLACE seguro: se envia la lista final completa",
                }
            )
        elif operation == "title":
            title_col = first_existing_column(source_df, ["Title", "Titulo", "Título", "Nombre"])
            if not title_col:
                issues.append({"Mod-Col": product_key, "Handle": product.get("Handle"), "Problema": "No se encontro columna Title"})
                continue
            new_title = clean_value(row.get(title_col))
            rows.append(
                {
                    "Accion": "Actualizar",
                    "Sitio": brand_config["site_label"],
                    "Operacion": "title",
                    "Mod-Col": product_key,
                    "Product ID": product_id,
                    "Handle": product.get("Handle"),
                    "Campo": "Title",
                    "Valor actual": product.get("Title"),
                    "Valor nuevo": new_title,
                    "Estado": "OK",
                    "Observacion": "",
                }
            )
        elif operation == "body":
            if body_mode == "from_input":
                from generate_columbia_matrixify import build_body_html

                new_body = build_body_html(row)
                if not new_body:
                    issues.append({"Mod-Col": product_key, "Handle": product.get("Handle"), "Problema": "No hay contenido para Body HTML"})
                    continue
            else:
                issues.append({"Mod-Col": product_key, "Handle": product.get("Handle"), "Problema": "Correccion desde catalogo todavia requiere Matrixify local"})
                continue
            rows.append(
                {
                    "Accion": "Actualizar",
                    "Sitio": brand_config["site_label"],
                    "Operacion": "body",
                    "Mod-Col": product_key,
                    "Product ID": product_id,
                    "Handle": product.get("Handle"),
                    "Campo": "Body HTML",
                    "Valor actual": product.get("Body HTML"),
                    "Valor nuevo": new_body,
                    "Estado": "OK",
                    "Observacion": "Incluye Caracteristicas, Material y Cuidado separados",
                }
            )
        elif operation == "photos":
            current_images = clean_value(product.get("Image Src"))
            if only_missing_images and current_images:
                continue
            from generate_columbia_matrixify import brand_image_config, image_candidates

            row_brand_config = brand_image_config(row.get("Marca") or product.get("Vendor"), brand_config)
            urls = image_candidates(product_key, row_brand_config)
            urls_text = "; ".join(urls)
            rows.append(
                {
                    "Accion": "Sincronizar Shopify" if image_mode == "replace" else "Agregar fotos Shopify",
                    "Sitio": brand_config["site_label"],
                    "Operacion": "photos",
                    "Mod-Col": product_key,
                    "Product ID": product_id,
                    "Handle": product.get("Handle"),
                    "Campo": "Fotos",
                    "Valor actual": current_images,
                    "Valor nuevo": urls_text,
                    "Modo fotos": image_mode,
                    "Media IDs": product.get("Media IDs"),
                    "Estado": "OK",
                    "Observacion": "REPLACE elimina fotos actuales antes de subir las 10 URLs nuevas; MERGE agrega las URLs nuevas.",
                }
            )
            matrixify_rows.append(
                {
                    "ID": product.get("Legacy ID"),
                    "Handle": product.get("Handle"),
                    "Command": "MERGE",
                    "Image Src": urls_text,
                    "Image Command": "REPLACE" if image_mode == "replace" else "MERGE",
                    "Image Position": "",
                    "Image Alt Text": product.get("Title"),
                }
            )

    return pd.DataFrame(rows), pd.DataFrame(issues), pd.DataFrame(matrixify_rows)


def apply_shopify_preview(shopify_config, preview_df):
    results = []
    for _, row in preview_df.iterrows():
        status = "OK"
        message = ""
        try:
            operation = clean_value(row.get("Operacion"))
            product_id = clean_value(row.get("Product ID"))
            if operation == "tags":
                product_update(shopify_config, product_id, tags=_split_tags(row.get("Valor nuevo")))
            elif operation == "title":
                product_update(shopify_config, product_id, title=clean_value(row.get("Valor nuevo")))
            elif operation == "body":
                product_update(shopify_config, product_id, body_html=clean_value(row.get("Valor nuevo")))
            elif operation == "photos":
                image_urls = _split_semicolon_values(row.get("Valor nuevo"))
                media_ids = _split_semicolon_values(row.get("Media IDs"))
                image_mode = clean_value(row.get("Modo fotos")).lower() or "replace"
                message = _sync_product_photos_direct(
                    shopify_config,
                    product_id,
                    image_urls,
                    existing_media_ids=media_ids,
                    image_mode=image_mode,
                    alt_text=clean_value(row.get("Handle")) or clean_value(row.get("Mod-Col")),
                )
            elif operation == "siblings":
                sibling_value = clean_value(row.get("Valor nuevo"))
                custom_sibling_value = clean_value(
                    row.get("Valor nuevo custom") or row.get("Metafield: custom.siblings [list.product_reference]")
                )
                if not custom_sibling_value:
                    custom_sibling_value = "[]"
                metafields_set(
                    shopify_config,
                    [
                        {
                            "ownerId": product_id,
                            "namespace": "theme",
                            "key": "siblings",
                            "type": "single_line_text_field",
                            "value": sibling_value,
                        },
                        {
                            "ownerId": product_id,
                            "namespace": "custom",
                            "key": "siblings",
                            "type": "list.product_reference",
                            "value": custom_sibling_value,
                        }
                    ],
                )
            else:
                status = "OMITIDO"
                message = "Operacion no habilitada para escritura directa"
        except Exception as exc:
            status = "ERROR"
            message = str(exc)
        results.append(
            {
                "Mod-Col": row.get("Mod-Col"),
                "Handle": row.get("Handle"),
                "Operacion": row.get("Operacion"),
                "Campo": row.get("Campo"),
                "Resultado": status,
                "Mensaje": message,
            }
        )
    return pd.DataFrame(results)


def shopify_products_to_matrixify_df(shopify_products):
    default_columns = [
        "ID",
        "Handle",
        "Command",
        "Title",
        "Body HTML",
        "Vendor",
        "Type",
        "Tags",
        "Image Src",
        "Variant SKU",
        "Variant Barcode",
        "Variant Inventory Item ID",
        "Variant ID",
        "Variant Image",
        "Metafield: custom.codigo_modelo_color [id]",
        "Metafield: theme.siblings [single_line_text_field]",
        "Metafield: theme.siblings_color [single_line_text_field]",
        "Metafield: custom.siblings [single_line_text_field]",
        "Metafield: custom.siblings_color [single_line_text_field]",
    ]
    try:
        if Path(DEFAULT_MATRIXIFY_PATH).exists():
            default_columns = list(pd.read_excel(DEFAULT_MATRIXIFY_PATH, sheet_name="Products", nrows=0).columns)
    except Exception:
        pass
    for column in (
        "Metafield: theme.siblings [single_line_text_field]",
        "Metafield: theme.siblings_color [single_line_text_field]",
        "Metafield: custom.siblings [single_line_text_field]",
        "Metafield: custom.siblings_color [single_line_text_field]",
    ):
        if column not in default_columns:
            default_columns.append(column)

    rows = []
    for product in shopify_products:
        variants = product.get("Variants") or [{}]
        for index, variant in enumerate(variants):
            row = {column: "" for column in default_columns}
            row.update(
                {
                    "ID": product.get("Legacy ID"),
                    "Handle": product.get("Handle"),
                    "Command": "MERGE",
                    "Title": product.get("Title") if index == 0 else "",
                    "Body HTML": product.get("Body HTML") if index == 0 else "",
                    "Vendor": product.get("Vendor") if index == 0 else "",
                    "Type": product.get("Type") if index == 0 else "",
                    "Tags": product.get("Tags") if index == 0 else "",
                    "Image Src": product.get("Image Src") if index == 0 else "",
                    "Variant SKU": variant.get("Variant SKU", ""),
                    "Variant Barcode": variant.get("Variant Barcode", ""),
                    "Variant Inventory Item ID": variant.get("Variant Inventory Item ID", ""),
                    "Variant ID": variant.get("Variant ID", ""),
                    "Variant Image": variant.get("Variant Image", ""),
                    "Metafield: custom.codigo_modelo_color [id]": product.get("Mod-Col") if index == 0 else "",
                    "Metafield: theme.siblings [single_line_text_field]": product.get("Siblings") if index == 0 else "",
                    "Metafield: theme.siblings_color [single_line_text_field]": product.get("Siblings Color") if index == 0 else "",
                    "Metafield: custom.siblings [single_line_text_field]": (
                        product.get("Custom Siblings") or product.get("Siblings")
                    )
                    if index == 0
                    else "",
                    "Metafield: custom.siblings_color [single_line_text_field]": (
                        product.get("Custom Siblings Color") or product.get("Siblings Color")
                    )
                    if index == 0
                    else "",
                }
            )
            rows.append(row)
    return pd.DataFrame(rows, columns=default_columns)


STOCK_QUERY_DEFAULT = """
WITH stock_base AS (
  SELECT
    fecha_corte,
    id_producto,
    conca || '-' || talla AS key_producto,
    codigo_tienda,
    stock_tiendas,
    stock_bodega
  FROM `forus-analitica-prod-datalake.bronze.stg_pe_central_stock_bi`
  WHERE fecha_corte = (
    SELECT MAX(fecha_corte)
    FROM `forus-analitica-prod-datalake.bronze.stg_pe_central_stock_bi`
    WHERE EXTRACT(YEAR FROM fecha_corte) = EXTRACT(YEAR FROM CURRENT_DATE())
  )
)
SELECT
  fecha_corte,
  ANY_VALUE(id_producto) AS id_producto,
  UPPER(TRIM(key_producto)) AS key_producto,
  SUM(COALESCE(stock_tiendas, 0)) AS stock_tiendas,
  SUM(COALESCE(stock_bodega, 0)) AS stock_bodega,
  SUM(COALESCE(stock_tiendas, 0) + COALESCE(stock_bodega, 0)) AS stock_total
FROM stock_base
GROUP BY fecha_corte, key_producto
"""


def read_current_stock_from_bigquery(bigquery_config):
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError("Faltan dependencias de BigQuery para leer stock.") from exc

    config = dict(bigquery_config or {})
    credentials_info = config.get("service_account_info")
    credentials = None
    project_id = clean_value(config.get("project_id"))
    if credentials_info:
        credentials = service_account.Credentials.from_service_account_info(dict(credentials_info))
        project_id = project_id or credentials.project_id

    job_project_id = clean_value(config.get("job_project_id")) or project_id
    client = bigquery.Client(project=job_project_id or None, credentials=credentials)
    query = clean_value(config.get("stock_query")) or STOCK_QUERY_DEFAULT
    job_config = bigquery.QueryJobConfig(use_legacy_sql=False)
    df = client.query(query, job_config=job_config, location=clean_value(config.get("location")) or None).to_dataframe()
    for column in ("fecha_corte", "id_producto", "key_producto", "stock_tiendas", "stock_bodega", "stock_total"):
        if column not in df.columns:
            df[column] = 0 if column.startswith("stock_") else ""
    df["key_producto"] = df["key_producto"].map(lambda value: clean_value(value).upper())
    for column in ("stock_tiendas", "stock_bodega", "stock_total"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
    return df


def stock_key_from_parts(mod_col, size):
    mod_col = clean_value(mod_col).upper()
    size = clean_value(normalize_size(size)).upper()
    return f"{mod_col}-{size}" if mod_col and size else ""


def filter_visible_kpi_sizes(df):
    if df is None or df.empty or "Mod-Col KPI" not in df.columns or "Talla KPI" not in df.columns:
        return df
    result = df.copy()
    result = result[~result["Talla KPI"].map(is_internal_k_size)].copy()
    keep_parts = []
    for _, group in result.groupby("Mod-Col KPI", dropna=False):
        has_one_size = group["Talla KPI"].map(is_one_size).any()
        if has_one_size:
            group = group[~group["Talla KPI"].map(is_zero_size)].copy()
        keep_parts.append(group)
    if not keep_parts:
        return result.iloc[0:0].copy()
    return pd.concat(keep_parts, ignore_index=True)


def valid_kpi_price(value):
    text = clean_value(value)
    if not text:
        return False
    try:
        return float(text.replace(",", ".")) > 0
    except ValueError:
        return False


def flatten_shopify_for_kpis(shopify_products):
    product_rows = []
    variant_rows = []
    for product in shopify_products or []:
        mod_col = clean_value(product.get("Mod-Col")).upper()
        status = clean_value(product.get("Status")).upper()
        online_url = clean_value(product.get("Online Store URL"))
        variants = product.get("Variants") or []
        has_price = any(valid_kpi_price(variant.get("Variant Price")) for variant in variants)
        product_rows.append(
            {
                "Mod-Col": mod_col,
                "Handle": clean_value(product.get("Handle")),
                "Title": clean_value(product.get("Title")),
                "Status": status,
                "Publicado": "SI" if online_url else "",
                "Visible": status == "ACTIVE" and (bool(online_url) or not online_url),
                "Tiene precio": has_price,
                "Fotos": len([url for url in clean_value(product.get("Image Src")).split(";") if clean_value(url)]),
            }
        )
        for variant in variants:
            variant_rows.append(
                {
                    "Mod-Col": mod_col,
                    "Handle": clean_value(product.get("Handle")),
                    "Status": status,
                    "Publicado": "SI" if online_url else "",
                    "Variant SKU": clean_value(variant.get("Variant SKU")),
                    "Variant Price": clean_value(variant.get("Variant Price")),
                    "Tiene precio": valid_kpi_price(variant.get("Variant Price")),
                }
            )
    return pd.DataFrame(product_rows), pd.DataFrame(variant_rows)


def build_catalog_kpis(arti_df, stock_df, shopify_products, brand_config):
    arti = arti_df.copy() if isinstance(arti_df, pd.DataFrame) else pd.DataFrame()
    stock = stock_df.copy() if isinstance(stock_df, pd.DataFrame) else pd.DataFrame()
    allowed = set(brand_config.get("allowed_arti_brands") or [])
    if "MARCA_MA" in arti.columns and allowed:
        arti = arti[arti["MARCA_MA"].map(lambda value: clean_value(value).upper()).isin(allowed)].copy()
    if "Mod-Col" not in arti.columns:
        arti["Mod-Col"] = ""
    if "COD MOD COL" not in arti.columns:
        arti["COD MOD COL"] = ""
    for column in ("CODINT_MA", "TALNUM_MA", "MARCA_MA"):
        if column not in arti.columns:
            arti[column] = ""

    arti["Mod-Col KPI"] = arti["Mod-Col"].where(arti["Mod-Col"].map(clean_value) != "", arti["COD MOD COL"])
    arti["Mod-Col KPI"] = arti["Mod-Col KPI"].map(lambda value: clean_value(value).upper())
    arti["Talla KPI"] = arti["TALNUM_MA"].map(normalize_size)
    arti["Stock Key"] = arti.apply(lambda row: stock_key_from_parts(row.get("Mod-Col KPI"), row.get("Talla KPI")), axis=1)
    expected = arti[(arti["Mod-Col KPI"] != "") & (arti["Stock Key"] != "")].copy()
    expected = filter_visible_kpi_sizes(expected)

    if stock.empty:
        stock = pd.DataFrame(columns=["key_producto", "stock_tiendas", "stock_bodega", "stock_total", "fecha_corte"])
    stock["key_producto"] = stock["key_producto"].map(lambda value: clean_value(value).upper())
    expected = expected.merge(
        stock[["key_producto", "stock_tiendas", "stock_bodega", "stock_total", "fecha_corte"]],
        how="left",
        left_on="Stock Key",
        right_on="key_producto",
    )
    for column in ("stock_tiendas", "stock_bodega", "stock_total"):
        expected[column] = pd.to_numeric(expected[column], errors="coerce").fillna(0)

    products_df, variants_df = flatten_shopify_for_kpis(shopify_products)
    shopify_model_keys = {clean_value(value).upper() for value in products_df.get("Mod-Col", pd.Series(dtype=object)) if clean_value(value)}
    shopify_variant_skus = {clean_value(value) for value in variants_df.get("Variant SKU", pd.Series(dtype=object)) if clean_value(value)}
    product_status_by_key = products_df.drop_duplicates("Mod-Col").set_index("Mod-Col").to_dict("index") if not products_df.empty and "Mod-Col" in products_df.columns else {}

    expected["SKU"] = expected["CODINT_MA"].map(clean_value)
    expected["Con stock"] = expected["stock_total"] > 0
    expected["Producto creado Shopify"] = expected["Mod-Col KPI"].map(lambda value: value in shopify_model_keys)
    expected["Variante creada Shopify"] = expected["SKU"].map(lambda value: value in shopify_variant_skus)
    expected["Status Shopify"] = expected["Mod-Col KPI"].map(lambda value: clean_value(product_status_by_key.get(value, {}).get("Status")))
    expected["Visible Shopify"] = expected["Status Shopify"].map(lambda value: clean_value(value).upper() == "ACTIVE")
    expected["Fotos Shopify"] = expected["Mod-Col KPI"].map(lambda value: int(product_status_by_key.get(value, {}).get("Fotos") or 0))

    model_stock = (
        expected.groupby("Mod-Col KPI", as_index=False)
        .agg(
            Marca=("MARCA_MA", "first"),
            Stock_total=("stock_total", "sum"),
            Tallas_BigQuery=("Talla KPI", "nunique"),
            Tallas_con_stock=("Con stock", "sum"),
            Producto_creado=("Producto creado Shopify", "max"),
            Visible_Shopify=("Visible Shopify", "max"),
            Fotos_Shopify=("Fotos Shopify", "max"),
        )
    )
    model_stock["Debe estar visible"] = model_stock["Stock_total"] > 0
    model_stock["Estado"] = model_stock.apply(
        lambda row: (
            "OK visible con stock"
            if row["Debe estar visible"] and row["Visible_Shopify"]
            else "Con stock no visible"
            if row["Debe estar visible"] and not row["Visible_Shopify"]
            else "Sin stock visible"
            if not row["Debe estar visible"] and row["Visible_Shopify"]
            else "OK apagado sin stock"
        ),
        axis=1,
    )

    missing_models = model_stock[(model_stock["Debe estar visible"]) & (~model_stock["Producto_creado"])].copy()
    stock_not_visible = model_stock[
        (model_stock["Debe estar visible"]) & (model_stock["Producto_creado"]) & (~model_stock["Visible_Shopify"])
    ].copy()
    no_stock_visible = model_stock[(~model_stock["Debe estar visible"]) & (model_stock["Visible_Shopify"])].copy()
    missing_stock_variants = expected[(expected["Con stock"]) & (~expected["Variante creada Shopify"])].copy()
    models_with_missing_stock_variants = {
        clean_value(value)
        for value in missing_stock_variants.get("Mod-Col KPI", pd.Series(dtype=object)).dropna()
    }
    model_stock["Variantes_stock_incompletas"] = model_stock["Mod-Col KPI"].map(
        lambda value: clean_value(value) in models_with_missing_stock_variants
    )

    price_by_model = (
        variants_df.groupby("Mod-Col", as_index=False)["Tiene precio"].max()
        if not variants_df.empty and "Mod-Col" in variants_df.columns
        else pd.DataFrame(columns=["Mod-Col", "Tiene precio"])
    )
    no_price_models = model_stock[model_stock["Producto_creado"] & model_stock["Debe estar visible"]].merge(
        price_by_model,
        how="left",
        left_on="Mod-Col KPI",
        right_on="Mod-Col",
    )
    no_price_models["Tiene precio"] = no_price_models["Tiene precio"].fillna(False)
    no_price_models = no_price_models[~no_price_models["Tiene precio"]].copy()
    no_photo_models = model_stock[
        model_stock["Debe estar visible"] & model_stock["Producto_creado"] & (model_stock["Fotos_Shopify"] <= 0)
    ].copy()
    no_price_keys = {clean_value(value) for value in no_price_models.get("Mod-Col KPI", pd.Series(dtype=object))}
    model_stock["Sin_precio_shopify"] = model_stock["Mod-Col KPI"].map(lambda value: clean_value(value) in no_price_keys)
    no_photo_keys = {clean_value(value) for value in no_photo_models.get("Mod-Col KPI", pd.Series(dtype=object))}
    model_stock["Sin_foto_shopify"] = model_stock["Mod-Col KPI"].map(lambda value: clean_value(value) in no_photo_keys)
    model_stock["Listo_venta"] = (
        model_stock["Debe estar visible"]
        & model_stock["Producto_creado"]
        & model_stock["Visible_Shopify"]
        & ~model_stock["Sin_precio_shopify"]
        & ~model_stock["Sin_foto_shopify"]
    )

    kpis = {
        "modelos_con_stock": int(model_stock["Debe estar visible"].sum()),
        "modelos_creados_shopify": int((model_stock["Debe estar visible"] & model_stock["Producto_creado"]).sum()),
        "cobertura_shopify": float((model_stock["Debe estar visible"] & model_stock["Producto_creado"]).sum() / model_stock["Debe estar visible"].sum()) if model_stock["Debe estar visible"].sum() else 0,
        "modelos_pendientes": int(len(missing_models)),
        "con_stock_no_visibles": int(len(stock_not_visible)),
        "sin_stock_visibles": int(len(no_stock_visible)),
        "modelos_variantes_incompletas": int(model_stock["Variantes_stock_incompletas"].sum()),
        "productos_creados_sin_stock": int((model_stock["Producto_creado"] & ~model_stock["Debe estar visible"]).sum()),
        "productos_visibles": int((model_stock["Debe estar visible"] & model_stock["Visible_Shopify"]).sum()),
        "modelos_listos_venta": int(model_stock["Listo_venta"].sum()),
        "modelos_sin_precio": int(len(no_price_models)),
        "modelos_sin_foto": int(len(no_photo_models)),
    }
    model_stock["Creado_con_stock"] = model_stock["Debe estar visible"] & model_stock["Producto_creado"]
    brand_summary = (
        model_stock.groupby("Marca", as_index=False)
        .agg(
            Modelos_con_stock=("Debe estar visible", "sum"),
            Creados_Shopify=("Creado_con_stock", "sum"),
            Pendientes_creacion=("Producto_creado", lambda values: 0),
            Stock_total=("Stock_total", "sum"),
        )
    )
    if not brand_summary.empty:
        brand_summary["Pendientes_creacion"] = brand_summary["Modelos_con_stock"] - brand_summary["Creados_Shopify"]
        brand_summary["Cobertura"] = brand_summary.apply(
            lambda row: row["Creados_Shopify"] / row["Modelos_con_stock"] if row["Modelos_con_stock"] else 0,
            axis=1,
        )

    action_rows = []
    for _, row in missing_models.iterrows():
        action_rows.append({"Mod-Col": row["Mod-Col KPI"], "Marca": row["Marca"], "Problema": "Modelo con stock no creado", "Accion sugerida": "Pedir input al Brand Manager", "Stock total": row["Stock_total"]})
    for _, row in stock_not_visible.iterrows():
        action_rows.append({"Mod-Col": row["Mod-Col KPI"], "Marca": row["Marca"], "Problema": "Con stock no visible", "Accion sugerida": "Activar/publicar o revisar bloqueo en Shopify", "Stock total": row["Stock_total"]})
    for _, row in no_stock_visible.iterrows():
        action_rows.append({"Mod-Col": row["Mod-Col KPI"], "Marca": row["Marca"], "Problema": "Sin stock visible", "Accion sugerida": "Apagar producto en Shopify", "Stock total": row["Stock_total"]})
    for _, row in no_price_models.iterrows():
        action_rows.append({"Mod-Col": row["Mod-Col KPI"], "Marca": row["Marca"], "Problema": "Creado con stock sin precio", "Accion sugerida": "Cargar precio en Shopify", "Stock total": row["Stock_total"]})
    for _, row in no_photo_models.iterrows():
        action_rows.append({"Mod-Col": row["Mod-Col KPI"], "Marca": row["Marca"], "Problema": "Modelo con stock sin foto", "Accion sugerida": "Solicitar fotos al Brand Manager", "Stock total": row["Stock_total"]})

    actions_df = pd.DataFrame(action_rows)
    missing_stock_variants_export = (
        missing_stock_variants[["Mod-Col KPI", "MARCA_MA", "Talla KPI", "SKU", "stock_total"]]
        .rename(columns={"Mod-Col KPI": "Mod-Col", "Talla KPI": "Talla", "stock_total": "Stock total"})
        if not missing_stock_variants.empty
        else pd.DataFrame(columns=["Mod-Col", "MARCA_MA", "Talla", "SKU", "Stock total"])
    )
    return {
        "kpis": kpis,
        "model_stock": model_stock,
        "brand_summary": brand_summary,
        "actions": actions_df,
        "missing_stock_variants": missing_stock_variants_export,
        "no_price_models": no_price_models,
        "no_photo_models": no_photo_models,
        "stock_not_visible": stock_not_visible,
        "no_stock_visible": no_stock_visible,
    }


def siblings_by_model_from_shopify(shopify_products):
    products_df = pd.DataFrame(shopify_products)
    if products_df.empty or "Mod-Col" not in products_df.columns or "Handle" not in products_df.columns:
        return {}
    products_df["__MODEL"] = products_df["Mod-Col"].map(lambda value: clean_value(value).upper().rsplit("-", 1)[0])
    return (
        products_df[products_df["__MODEL"] != ""]
        .groupby("__MODEL")["Handle"]
        .apply(lambda values: ", ".join(dict.fromkeys(clean_value(value) for value in values if clean_value(value))))
        .to_dict()
    )


def apply_shopify_siblings_to_matrixify(matrixify_df, shopify_products):
    siblings_map = siblings_by_model_from_shopify(shopify_products)
    if matrixify_df is None or matrixify_df.empty or not siblings_map:
        return matrixify_df
    df = matrixify_df.copy()
    key_column = "Metafield: custom.codigo_modelo_color [id]"
    siblings_column = "Metafield: theme.siblings [single_line_text_field]"
    custom_siblings_column = "Metafield: custom.siblings [single_line_text_field]"
    if key_column not in df.columns:
        return df
    for column in (siblings_column, custom_siblings_column):
        if column not in df.columns:
            df[column] = ""

    def sibling_value(row):
        key = clean_value(row.get(key_column)).upper()
        if not key:
            return row.get(siblings_column)
        model = key.rsplit("-", 1)[0]
        return siblings_map.get(model, row.get(siblings_column) or row.get(custom_siblings_column))

    top_rows = df["Handle"].map(clean_value) != ""
    values = df.loc[top_rows].apply(sibling_value, axis=1)
    df.loc[top_rows, siblings_column] = values
    df.loc[top_rows, custom_siblings_column] = values
    return df


def _product_gid(value):
    text = clean_value(value)
    if not text:
        return ""
    if text.startswith("gid://"):
        return text
    return f"gid://shopify/Product/{text}"


def _metafield_type_from_column(column):
    match = re.search(r"\[(.+?)\]$", clean_value(column))
    if not match:
        return "single_line_text_field"
    return match.group(1)


def _metafield_can_write_direct(column):
    namespace, key = _metafield_namespace_key(column)
    field_type = _metafield_type_from_column(column)
    if field_type in ("page_reference", "list.page_reference"):
        return False, f"{namespace}.{key} requiere IDs internos de Shopify; se mantiene para Matrixify"
    return True, ""


def _logo_lookup_keys(record):
    keys = set()
    candidates = [
        record.get("handle"),
        record.get("displayName"),
    ]
    for field in record.get("fields") or []:
        candidates.append(field.get("value"))
        reference = field.get("reference") or {}
        image = reference.get("image") or {}
        candidates.append(reference.get("url"))
        candidates.append(image.get("url"))
        for referenced_node in ((field.get("references") or {}).get("nodes")) or []:
            referenced_image = referenced_node.get("image") or {}
            candidates.append(referenced_node.get("url"))
            candidates.append(referenced_image.get("url"))

    expanded_candidates = []
    for candidate in candidates:
        expanded_candidates.append(candidate)
        text = clean_value(candidate).lower()
        if not text:
            continue
        parsed_path = unquote(urlparse(text).path or "")
        if parsed_path:
            filename = Path(parsed_path).stem
            if filename:
                expanded_candidates.append(filename)

    for candidate in expanded_candidates:
        text = clean_value(candidate).lower()
        if not text:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
        compact = re.sub(r"[^a-z0-9]+", "", text)
        for key in (text, normalized, compact):
            if key:
                keys.add(key)
                keys.add(f"logo.{key}")
                keys.add(f"{key}-clb")
                keys.add(f"logo.{key}-clb")
        if normalized.endswith("-clb"):
            base = normalized[:-4]
            keys.update({base, f"logo.{base}"})
        if text.startswith("logo."):
            bare = text.split(".", 1)[1]
            keys.add(bare)
            if bare.endswith("-clb"):
                keys.add(bare[:-4])
    return keys


def _logo_reference_candidates(reference, handle=""):
    values = [reference, handle]
    candidates = set()
    for value in values:
        text = clean_value(value).lower()
        if not text:
            continue
        if text.startswith("logo."):
            text = text.split(".", 1)[1]
        base_values = {text}
        if text.endswith("-clb"):
            base_values.add(text[:-4])
        for base in list(base_values):
            normalized = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
            compact = re.sub(r"[^a-z0-9]+", "", base)
            spaced = normalized.replace("-", " ")
            for item in (base, normalized, compact, spaced):
                if item:
                    candidates.add(item)
                    candidates.add(f"logo.{item}")
                    candidates.add(f"{item}-clb")
                    candidates.add(f"logo.{item}-clb")
    return {candidate.lower() for candidate in candidates if candidate}


def _metaobject_gid_lookup(shopify_config, metaobject_type):
    cache_key = f"metaobject_lookup_{clean_value(metaobject_type)}"
    if cache_key not in st.session_state:
        records = fetch_metaobjects(shopify_config, metaobject_type)
        lookup = {}
        for record in records:
            gid = clean_value(record.get("id"))
            if not gid:
                continue
            for key in _logo_lookup_keys(record):
                lookup[key.lower()] = gid
        st.session_state[cache_key] = lookup
    return st.session_state[cache_key]


def _all_metaobject_gid_lookup(shopify_config):
    cache_key = "metaobject_lookup_all"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    by_handle = {}
    by_reference = {}
    definitions = fetch_metaobject_definitions(shopify_config)
    for definition in definitions:
        metaobject_type = clean_value(definition.get("type"))
        if not metaobject_type:
            continue
        try:
            lookup = _metaobject_gid_lookup(shopify_config, metaobject_type)
        except Exception:
            continue
        for handle, gid in lookup.items():
            by_handle.setdefault(handle.lower(), gid)
            by_reference[f"{metaobject_type}.{handle}".lower()] = gid

    st.session_state[cache_key] = {"by_handle": by_handle, "by_reference": by_reference}
    return st.session_state[cache_key]


def _metaobject_definition_ids_from_metafield(shopify_config, namespace, key):
    cache_key = f"metafield_definition_metaobjects_{namespace}_{key}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    definition_ids = []
    if fetch_metafield_definition is None:
        st.session_state[cache_key] = definition_ids
        return definition_ids
    try:
        definition = fetch_metafield_definition(shopify_config, "PRODUCT", namespace, key)
    except Exception:
        definition = {}
    for validation in definition.get("validations") or []:
        name = clean_value(validation.get("name"))
        value = clean_value(validation.get("value"))
        if name not in ("metaobject_definition_id", "metaobject_definition_ids") or not value:
            continue
        try:
            parsed_value = json.loads(value)
            if isinstance(parsed_value, list):
                definition_ids.extend(clean_value(item) for item in parsed_value if clean_value(item))
            elif clean_value(parsed_value):
                definition_ids.append(clean_value(parsed_value))
        except Exception:
            definition_ids.extend(
                clean_value(item)
                for item in re.split(r"[,|\s]+", value)
                if clean_value(item).startswith("gid://shopify/MetaobjectDefinition/")
            )
    st.session_state[cache_key] = list(dict.fromkeys(definition_ids))
    return st.session_state[cache_key]


def _metaobject_gid_lookup_for_metafield(shopify_config, namespace, key):
    cache_key = f"metaobject_lookup_metafield_{namespace}_{key}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    lookup = {}
    if fetch_metaobjects_for_definition is None:
        st.session_state[cache_key] = lookup
        return lookup
    for definition_id in _metaobject_definition_ids_from_metafield(shopify_config, namespace, key):
        try:
            records = fetch_metaobjects_for_definition(shopify_config, definition_id)
        except Exception:
            continue
        for record in records:
            gid = clean_value(record.get("id"))
            if not gid:
                continue
            for lookup_key in _logo_lookup_keys(record):
                lookup[lookup_key.lower()] = gid
    st.session_state[cache_key] = lookup
    return lookup


def _resolve_metaobject_reference_value(shopify_config, column, value):
    text = clean_value(value)
    field_type = _metafield_type_from_column(column)
    if field_type not in ("metaobject_reference", "list.metaobject_reference") or not text:
        return text

    references = [item.strip() for item in text.split(",") if item.strip()]
    gids = []
    missing = []
    for reference in references:
        if reference.startswith("gid://shopify/Metaobject/"):
            gids.append(reference)
            continue
        if "." not in reference:
            missing.append(reference)
            continue
        metaobject_type, handle = reference.split(".", 1)
        try:
            lookup = _metaobject_gid_lookup(shopify_config, metaobject_type)
        except Exception:
            lookup = {}
        gid = ""
        for candidate in _logo_reference_candidates(reference, handle):
            gid = lookup.get(candidate)
            if gid:
                break
        if not gid:
            namespace, key = _metafield_namespace_key(column)
            metafield_lookup = _metaobject_gid_lookup_for_metafield(shopify_config, namespace, key)
            for candidate in _logo_reference_candidates(reference, handle):
                gid = metafield_lookup.get(candidate)
                if gid:
                    break
        if not gid:
            fallback_lookup = _all_metaobject_gid_lookup(shopify_config)
            for candidate in _logo_reference_candidates(reference, handle):
                gid = fallback_lookup["by_reference"].get(candidate) or fallback_lookup["by_handle"].get(candidate)
                if gid:
                    break
        if gid:
            gids.append(gid)
        else:
            missing.append(reference)

    if missing:
        raise ValueError(f"No encontre metaobjects para: {', '.join(missing)}")
    if field_type == "list.metaobject_reference":
        return json.dumps(gids, ensure_ascii=False)
    return gids[0] if gids else ""


def _shopify_image_url(value):
    url = _normalize_legacy_image_url(value)
    prefix = "https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/"
    if url.startswith(prefix):
        return "https://s3.amazonaws.com/ecom-imagenes.forus-digital.xyz.peru/" + url[len(prefix):]
    return url


def _normalize_legacy_image_url(value):
    url = clean_value(value)
    replacements = {
        "COLUMBIA%20SHOPIFY": "COLUMBIA",
        "ROCKFORD%20SHOPIFY": "ROCKFORD",
        "HUSH%20PUPPIES%20SHOPIFY": "HUSH%20PUPPIES",
        "VANS%20SHOPIFY": "VANS",
        "KEDS%20SHOPIFY": "KEDS",
        "PATAGONIA%20SHOPIFY": "PATAGONIA",
        "SOREL%20SHOPIFY": "SOREL",
        "MOUNTAIN%20HARDWEAR%20SHOPIFY": "MOUNTAIN%20HARDWEAR",
        "COLUMBIA SHOPIFY": "COLUMBIA",
        "ROCKFORD SHOPIFY": "ROCKFORD",
        "HUSH PUPPIES SHOPIFY": "HUSH PUPPIES",
        "VANS SHOPIFY": "VANS",
        "KEDS SHOPIFY": "KEDS",
        "PATAGONIA SHOPIFY": "PATAGONIA",
        "SOREL SHOPIFY": "SOREL",
        "MOUNTAIN HARDWEAR SHOPIFY": "MOUNTAIN HARDWEAR",
    }
    for old, new in replacements.items():
        url = url.replace(f"/{old}/", f"/{new}/")
    return url


def _image_url_candidates(value):
    original = clean_value(value)
    normalized = _normalize_legacy_image_url(original)
    converted = _shopify_image_url(original)
    return list(dict.fromkeys([url for url in (converted, normalized, original) if url]))


def _url_is_reachable_image(url, timeout=8):
    headers = {"User-Agent": "Mozilla/5.0", "Range": "bytes=0-512"}
    for method in ("HEAD", "GET"):
        request = Request(url, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                content_type = clean_value(response.headers.get("Content-Type")).lower()
                return response.status < 400 and content_type.startswith("image/")
        except HTTPError as exc:
            if exc.code in (403, 405) and method == "HEAD":
                continue
            return False
        except (URLError, TimeoutError, OSError):
            return False
    return False


def _first_reachable_image_url(value):
    candidates = _image_url_candidates(value)
    for url in candidates:
        if _url_is_reachable_image(url):
            return url, ""
    return "", candidates[0] if candidates else clean_value(value)


def _download_image_bytes(value):
    last_error = ""
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in _image_url_candidates(value):
        try:
            request = Request(url, headers=headers)
            with urlopen(request, timeout=30) as response:
                content_type = clean_value(response.headers.get("Content-Type")).lower()
                if response.status >= 400 or not content_type.startswith("image/"):
                    last_error = f"{url}: no es imagen valida"
                    continue
                data = response.read()
                if not data:
                    last_error = f"{url}: imagen vacia"
                    continue
                filename = Path(unquote(urlparse(url).path or "")).name or "product_image.jpg"
                return data, content_type.split(";")[0], filename, url
        except Exception as exc:
            last_error = f"{url}: {exc}"
    raise ShopifyApiError(last_error or "No se pudo descargar la imagen")


def _file_status_summary(file_statuses):
    ready = []
    failed = []
    pending = []
    for file_node in file_statuses or []:
        status = clean_value(file_node.get("fileStatus")).upper()
        if status == "READY":
            ready.append(file_node)
        elif status == "FAILED":
            failed.append(file_node)
        else:
            pending.append(file_node)
    return ready, failed, pending


def _file_cdn_url(file_node):
    image = file_node.get("image") or {}
    preview = file_node.get("preview") or {}
    preview_image = preview.get("image") or {}
    return clean_value(image.get("url")) or clean_value(preview_image.get("url"))


def _product_set_files_with_fallback(shopify_config, product_gid, product_files):
    try:
        product_set_files(shopify_config, product_gid, product_files)
        return "productSet staged"
    except Exception as product_set_exc:
        cdn_files = []
        file_errors = []
        for product_file in product_files:
            try:
                created = file_create(
                    shopify_config,
                    product_file.get("originalSource"),
                    alt=product_file.get("alt"),
                    content_type=product_file.get("contentType") or "IMAGE",
                )
                file_ids = [clean_value(file_node.get("id")) for file_node in created if clean_value(file_node.get("id"))]
                statuses = wait_file_statuses(shopify_config, file_ids) if file_ids else created
                ready_files, failed_files, pending_files = _file_status_summary(statuses)
                if failed_files:
                    file_errors.append(f"{product_file.get('filename')}: archivo fallido")
                    continue
                if pending_files and not ready_files:
                    file_errors.append(f"{product_file.get('filename')}: archivo en procesamiento")
                    continue
                source_node = (ready_files or statuses or created or [{}])[0]
                cdn_url = _file_cdn_url(source_node)
                if not cdn_url:
                    file_errors.append(f"{product_file.get('filename')}: sin URL CDN")
                    continue
                cdn_files.append(
                    {
                        "originalSource": cdn_url,
                        "alt": product_file.get("alt"),
                        "filename": product_file.get("filename"),
                        "contentType": "IMAGE",
                        "duplicateResolutionMode": "APPEND_UUID",
                    }
                )
            except Exception as exc:
                file_errors.append(f"{product_file.get('filename')}: {exc}")
        if cdn_files:
            product_set_files(shopify_config, product_gid, cdn_files)
            if file_errors:
                raise ShopifyApiError(
                    f"productSet staged fallo ({product_set_exc}); fallback CDN parcial: {' | '.join(file_errors[:3])}"
                )
            return "fileCreate CDN"
        raise ShopifyApiError(f"productSet staged fallo: {product_set_exc}; fallback sin archivos: {' | '.join(file_errors[:3])}")


def _sync_product_photos_direct(shopify_config, product_gid, image_urls, existing_media_ids=None, image_mode="replace", alt_text=""):
    existing_media_ids = existing_media_ids or []
    image_urls = [url for url in image_urls[:10] if clean_value(url)]
    image_mode = clean_value(image_mode).lower() or "replace"
    product_files = []
    image_errors = []

    for image_index, raw_image_url in enumerate(image_urls, start=1):
        try:
            image_bytes, mime_type, filename, _ = _download_image_bytes(raw_image_url)
            resource_url = staged_upload_image(shopify_config, filename, mime_type, image_bytes)
            product_files.append(
                {
                    "originalSource": resource_url,
                    "alt": clean_value(alt_text),
                    "filename": filename,
                    "contentType": "IMAGE",
                    "duplicateResolutionMode": "APPEND_UUID",
                }
            )
        except Exception as exc:
            image_errors.append(f"foto {image_index}: {exc}")

    if not product_files:
        raise ShopifyApiError("No se pudo subir ninguna foto nueva. " + " | ".join(image_errors[:3]))

    route = _product_set_files_with_fallback(shopify_config, product_gid, product_files)
    deleted_count = 0
    delete_note = ""
    if image_mode == "replace" and existing_media_ids:
        try:
            deleted = product_delete_media(shopify_config, product_gid, existing_media_ids)
            deleted_count = len(deleted)
        except Exception as exc:
            detail = clean_value(exc).lower()
            if "do not exist" in detail or "does not exist" in detail:
                deleted_count = len(existing_media_ids)
                delete_note = " Las fotos anteriores ya no existian despues del reemplazo."
            else:
                raise

    message = (
        f"{deleted_count} fotos anteriores eliminadas. "
        f"{len(product_files)} fotos nuevas inyectadas por API ({route})."
        if image_mode == "replace"
        else f"{len(product_files)} fotos nuevas agregadas por API ({route})."
    )
    if delete_note:
        message += delete_note
    if image_errors:
        message += f" No se cargaron {len(image_errors)} de {len(image_urls)} URLs: {' | '.join(image_errors[:3])}"
    return message


def _media_status_summary(media_statuses):
    ready = []
    failed = []
    pending = []
    for media in media_statuses or []:
        status = clean_value(media.get("status")).upper()
        if status == "READY":
            ready.append(media)
        elif status == "FAILED":
            failed.append(media)
        else:
            pending.append(media)
    return ready, failed, pending


def _media_error_text(media):
    errors = media.get("mediaErrors") or []
    if not errors:
        return clean_value(media.get("status")) or "sin detalle"
    messages = []
    for error in errors[:2]:
        detail = clean_value(error.get("message")) or clean_value(error.get("details")) or clean_value(error.get("code"))
        if detail:
            messages.append(detail)
    return "; ".join(messages) if messages else "sin detalle"


def _metafield_value_for_api(column, value, shopify_config=None):
    text = clean_value(value)
    field_type = _metafield_type_from_column(column)
    if field_type in ("metaobject_reference", "list.metaobject_reference"):
        if shopify_config is None:
            return text
        return _resolve_metaobject_reference_value(shopify_config, column, text)
    if field_type.startswith("list.") and text and not text.startswith("["):
        items = [item.strip() for item in text.split(",") if item.strip()]
        return json.dumps(items, ensure_ascii=False)
    if field_type == "boolean":
        lowered = text.lower()
        if lowered in ("true", "1", "yes", "si", "sí"):
            return "true"
        if lowered in ("false", "0", "no"):
            return "false"
    return text


def _metafield_namespace_key(column):
    text = clean_value(column)
    if not text.startswith("Metafield: "):
        return "", ""
    name = re.sub(r"\s*\[.+?\]\s*$", "", text.replace("Metafield: ", "", 1)).strip()
    if "." not in name:
        return "", ""
    namespace, key = name.split(".", 1)
    return namespace.strip(), key.strip()


def _top_product_rows(matrixify_df):
    if matrixify_df.empty or "Handle" not in matrixify_df.columns:
        return pd.DataFrame()
    df = matrixify_df.copy()
    df["__HANDLE"] = df["Handle"].map(clean_value)
    df = df[df["__HANDLE"] != ""].copy()
    return df.drop_duplicates(subset=["__HANDLE"], keep="first").copy()


def _variant_rows_for_handle(matrixify_df, handle):
    if matrixify_df.empty or "Handle" not in matrixify_df.columns:
        return pd.DataFrame()
    current_handle = ""
    matching_indexes = []
    target_handle = clean_value(handle)
    for index, row in matrixify_df.iterrows():
        row_handle = clean_value(row.get("Handle"))
        if row_handle:
            current_handle = row_handle
        if current_handle == target_handle:
            matching_indexes.append(index)
    return matrixify_df.loc[matching_indexes].copy() if matching_indexes else pd.DataFrame()


def _valid_price(value):
    text = clean_value(value)
    if not text:
        return ""
    try:
        if float(text.replace(",", ".")) <= 0:
            return ""
    except Exception:
        pass
    return text


def _variant_bulk_input_from_row(row, option_id=None, option_name=None, fallback_price=None, fallback_compare_at_price=None):
    size = clean_value(row.get("Option1 Value"))
    if not size:
        return None

    option_name = clean_value(option_name) or clean_value(row.get("Option1 Name")) or "Talla"
    option_value = {"name": size}
    if clean_value(option_id):
        option_value["optionId"] = clean_value(option_id)
    else:
        option_value["optionName"] = option_name
    variant = {
        "optionValues": [option_value]
    }
    price = _valid_price(row.get("Variant Price")) or _valid_price(fallback_price)
    compare_at_price = _valid_price(row.get("Variant Compare At Price")) or _valid_price(fallback_compare_at_price)
    barcode = clean_value(row.get("Variant Barcode"))
    sku = clean_value(row.get("Variant SKU"))
    if price:
        variant["price"] = price
    if compare_at_price:
        variant["compareAtPrice"] = compare_at_price
    if barcode:
        variant["barcode"] = barcode
    if sku:
        variant["inventoryItem"] = {"sku": sku, "tracked": True}
    return variant


def _missing_variant_inputs(product_variant_rows, option_id=None, option_name=None, fallback_price=None, fallback_compare_at_price=None):
    if product_variant_rows.empty:
        return []

    existing_skus = set()
    existing_sizes = set()
    for _, row in product_variant_rows.iterrows():
        if not clean_value(row.get("Variant ID")):
            continue
        sku = clean_value(row.get("Variant SKU")).upper()
        size = clean_value(row.get("Option1 Value")).upper()
        if sku:
            existing_skus.add(sku)
        if size:
            existing_sizes.add(size)

    variants = []
    seen_keys = set()
    for _, variant_row in product_variant_rows.iterrows():
        if clean_value(variant_row.get("Variant ID")):
            continue
        sku = clean_value(variant_row.get("Variant SKU"))
        size = clean_value(variant_row.get("Option1 Value"))
        if not size:
            continue
        if sku and sku.upper() in existing_skus:
            continue
        if size.upper() in existing_sizes:
            continue
        dedupe_key = (sku.upper(), size.upper())
        if dedupe_key in seen_keys:
            continue
        payload = _variant_bulk_input_from_row(
            variant_row,
            option_id=option_id,
            option_name=option_name,
            fallback_price=fallback_price,
            fallback_compare_at_price=fallback_compare_at_price,
        )
        if payload:
            variants.append(payload)
            seen_keys.add(dedupe_key)
    return variants


def _all_variant_inputs(product_variant_rows, option_id=None, option_name=None, fallback_price=None, fallback_compare_at_price=None):
    variants = []
    seen_keys = set()
    for _, variant_row in product_variant_rows.iterrows():
        sku = clean_value(variant_row.get("Variant SKU"))
        size = clean_value(variant_row.get("Option1 Value"))
        if not size:
            continue
        dedupe_key = (sku.upper(), size.upper())
        if dedupe_key in seen_keys:
            continue
        payload = _variant_bulk_input_from_row(
            variant_row,
            option_id=option_id,
            option_name=option_name,
            fallback_price=fallback_price,
            fallback_compare_at_price=fallback_compare_at_price,
        )
        if payload:
            variants.append(payload)
            seen_keys.add(dedupe_key)
    return variants


def _size_option_from_product_data(product_data, fallback_name="Talla"):
    options = product_data.get("options") or []
    fallback = clean_value(fallback_name).lower()
    for option in options:
        if clean_value(option.get("name")).lower() == fallback:
            return option
    for option in options:
        if clean_value(option.get("name")).lower() in ("talla", "size", "title"):
            return option
    return options[0] if options else {}


def _existing_sizes_from_product_data(product_data, option_name):
    sizes = set()
    for variant in ((product_data.get("variants") or {}).get("nodes")) or []:
        size = _selected_option_value(variant, option_name)
        if size:
            sizes.add(size.upper())
    return sizes


def _price_fallback_from_product_data(product_data):
    for variant in ((product_data.get("variants") or {}).get("nodes")) or []:
        price = _valid_price(variant.get("price"))
        if price:
            return price, _valid_price(variant.get("compareAtPrice"))
    return "", ""


def _price_fallback_from_rows(product_variant_rows):
    for _, row in product_variant_rows.iterrows():
        price = _valid_price(row.get("Variant Price"))
        if price:
            return price, _valid_price(row.get("Variant Compare At Price"))
    return "", ""


def _missing_variant_inputs_from_shopify(product_variant_rows, product_data):
    if product_variant_rows.empty:
        return []
    requested_option_name = clean_value(product_variant_rows.iloc[0].get("Option1 Name")) or "Talla"
    size_option = _size_option_from_product_data(product_data, requested_option_name)
    option_id = clean_value(size_option.get("id"))
    option_name = clean_value(size_option.get("name")) or requested_option_name
    existing_sizes = _existing_sizes_from_product_data(product_data, option_name)
    fallback_price, fallback_compare_at_price = _price_fallback_from_product_data(product_data)

    variants = []
    seen_sizes = set()
    for _, variant_row in product_variant_rows.iterrows():
        size = clean_value(variant_row.get("Option1 Value"))
        if not size:
            continue
        size_key = size.upper()
        if size_key in existing_sizes or size_key in seen_sizes:
            continue
        payload = _variant_bulk_input_from_row(
            variant_row,
            option_id=option_id,
            option_name=option_name,
            fallback_price=fallback_price,
            fallback_compare_at_price=fallback_compare_at_price,
        )
        if payload:
            variants.append(payload)
            seen_sizes.add(size_key)
    return variants


def _variant_option_values(product_variant_rows):
    values = []
    for _, row in product_variant_rows.iterrows():
        size = clean_value(row.get("Option1 Value"))
        if size and size not in values:
            values.append(size)
    return values


def _ordered_sizes_from_rows(product_variant_rows):
    if product_variant_rows.empty:
        return []
    ordered = []
    for _, row in product_variant_rows.iterrows():
        size = clean_value(row.get("Option1 Value"))
        if size and size not in ordered:
            ordered.append(size)
    return ordered


def _selected_option_value(variant, option_name):
    expected = clean_value(option_name).lower()
    for option in variant.get("selectedOptions") or []:
        if clean_value(option.get("name")).lower() == expected:
            return clean_value(option.get("value"))
    if (variant.get("selectedOptions") or []):
        return clean_value((variant.get("selectedOptions") or [{}])[0].get("value"))
    return ""


def _reorder_product_sizes(shopify_config, product_gid, product_variant_rows):
    ordered_sizes = _ordered_sizes_from_rows(product_variant_rows)
    if not product_gid or len(ordered_sizes) < 2:
        return ""

    product_data = fetch_product_options_and_variants(shopify_config, product_gid)
    options = product_data.get("options") or []
    variants = ((product_data.get("variants") or {}).get("nodes")) or []
    if not options or not variants:
        return ""

    option_name = clean_value(product_variant_rows.iloc[0].get("Option1 Name")) or "Talla"
    size_option = None
    for option in options:
        if clean_value(option.get("name")).lower() == option_name.lower():
            size_option = option
            break
    if size_option is None:
        size_option = options[0]
        option_name = clean_value(size_option.get("name")) or option_name

    existing_values = [
        clean_value(option_value.get("name"))
        for option_value in size_option.get("optionValues") or []
        if clean_value(option_value.get("name"))
    ]
    values_in_order = [size for size in ordered_sizes if size in existing_values]
    values_in_order.extend(value for value in existing_values if value not in values_in_order)

    variant_by_size = {}
    for variant in variants:
        size = _selected_option_value(variant, option_name)
        if size and size not in variant_by_size:
            variant_by_size[size] = variant.get("id")
    variant_order = [size for size in ordered_sizes if size in variant_by_size]
    variant_order.extend(size for size in variant_by_size if size not in variant_order)
    if len(variant_order) < len(ordered_sizes):
        missing_sizes = [size for size in ordered_sizes if size not in variant_by_size]
        raise ShopifyApiError(f"No se puede ordenar porque faltan variantes creadas: {', '.join(missing_sizes)}")
    positions = [
        {"id": variant_by_size[size], "position": position}
        for position, size in enumerate(variant_order, start=1)
        if clean_value(variant_by_size.get(size))
    ]
    if not positions:
        raise ShopifyApiError("No se encontraron variantes para ordenar.")
    product_variants_bulk_reorder(shopify_config, product_gid, positions)

    verified_product = fetch_product_options_and_variants(shopify_config, product_gid)
    verified_variants = ((verified_product.get("variants") or {}).get("nodes")) or []
    verified_sizes = [
        _selected_option_value(variant, option_name)
        for variant in verified_variants
        if _selected_option_value(variant, option_name)
    ]
    expected_prefix = [size for size in ordered_sizes if size in verified_sizes]
    if verified_sizes[: len(expected_prefix)] != expected_prefix:
        raise ShopifyApiError(
            f"Shopify no confirmo el orden. Esperado: {', '.join(expected_prefix)}. Actual: {', '.join(verified_sizes[:len(expected_prefix)])}"
        )
    return "orden obligatorio de variantes confirmado"


def apply_full_product_updates(shopify_config, matrixify_df):
    rows = []
    product_rows = _top_product_rows(matrixify_df)
    metafield_columns = [
        column
        for column in matrixify_df.columns
        if clean_value(column).startswith("Metafield: ")
        and column not in (
            "Metafield: custom.guia_de_tallas [page_reference]",
        )
    ]

    for _, row in product_rows.iterrows():
        handle = clean_value(row.get("Handle"))
        product_id = clean_value(row.get("ID"))
        product_gid = _product_gid(product_id)
        product_messages = []
        product_status = "OK"
        product_variant_rows = _variant_rows_for_handle(matrixify_df, handle)

        try:
            status = clean_value(row.get("Status")).upper()
            if status == "ACTIVE":
                shopify_status = "ACTIVE"
            elif status == "DRAFT":
                shopify_status = "DRAFT"
            else:
                shopify_status = None

            if product_gid:
                product_update(
                    shopify_config,
                    product_gid,
                    title=clean_value(row.get("Title")) or None,
                    body_html=clean_value(row.get("Body HTML")) or None,
                    tags=_split_tags(row.get("Tags")) if clean_value(row.get("Tags")) else None,
                    vendor=clean_value(row.get("Vendor")) or None,
                    product_type=clean_value(row.get("Type")) or None,
                    status=shopify_status,
                )
                product_messages.append("Producto actualizado")
            else:
                created_product = product_create(
                    shopify_config,
                    title=clean_value(row.get("Title")) or handle,
                    handle=handle or None,
                    body_html=clean_value(row.get("Body HTML")) or None,
                    tags=_split_tags(row.get("Tags")) if clean_value(row.get("Tags")) else None,
                    vendor=clean_value(row.get("Vendor")) or None,
                    product_type=clean_value(row.get("Type")) or None,
                    status=shopify_status or "ACTIVE",
                    option_name=clean_value(row.get("Option1 Name")) or "Talla",
                    option_values=_variant_option_values(product_variant_rows),
                )
                product_gid = clean_value(created_product.get("id"))
                product_id = clean_value(created_product.get("legacyResourceId")) or product_id
                product_messages.append("Producto nuevo creado")

            publish_date = publication_date_from_row(row)
            if shopify_status != "DRAFT":
                try:
                    publishable_publish(shopify_config, product_gid, publish_date=publish_date)
                    if publish_date:
                        product_messages.append(f"Publicacion programada: {publish_date}")
                    else:
                        product_messages.append("Publicado en Online Store")
                except Exception as exc:
                    product_status = "PARCIAL"
                    product_messages.append(f"Error publicacion: {exc}")

            metafields = []
            skipped_metafields = []
            metafield_errors = []
            for column in metafield_columns:
                value = clean_value(row.get(column))
                if value == "":
                    continue
                namespace, key = _metafield_namespace_key(column)
                if not namespace or not key:
                    continue
                can_write, skip_reason = _metafield_can_write_direct(column)
                if not can_write:
                    skipped_metafields.append(skip_reason)
                    continue
                try:
                    api_value = _metafield_value_for_api(column, value, shopify_config)
                except Exception as exc:
                    metafield_errors.append(f"{namespace}.{key}: {exc}")
                    continue
                metafields.append(
                    {
                        "ownerId": product_gid,
                        "namespace": namespace,
                        "key": key,
                        "type": _metafield_type_from_column(column),
                        "value": api_value,
                    }
                )
            if metafields:
                metafield_ok = 0
                for metafield in metafields:
                    try:
                        metafields_set(shopify_config, [metafield])
                        metafield_ok += 1
                    except Exception as exc:
                        metafield_errors.append(f"{metafield['namespace']}.{metafield['key']}: {exc}")
                if metafield_ok:
                    product_messages.append(f"{metafield_ok} metafields actualizados")
                if metafield_errors:
                    product_status = "PARCIAL"
                    product_messages.append("Errores metafields: " + " | ".join(metafield_errors[:5]))
                if skipped_metafields:
                    product_status = "PARCIAL" if product_status == "OK" else product_status
                    product_messages.append("Metafields omitidos: " + " | ".join(dict.fromkeys(skipped_metafields)))
            elif metafield_errors:
                product_status = "PARCIAL"
                product_messages.append("Errores metafields: " + " | ".join(metafield_errors[:5]))

            raw_image_urls = [url.strip() for url in clean_value(row.get("Image Src")).split(";") if url.strip()]
            if raw_image_urls:
                try:
                    existing_media_ids = [
                        media_id.strip()
                        for media_id in clean_value(row.get("Media IDs")).split(";")
                        if media_id.strip()
                    ]
                    if clean_value(row.get("Image Command")).upper() == "REPLACE" and existing_media_ids:
                        product_delete_media(shopify_config, product_gid, existing_media_ids)
                        product_messages.append(f"{len(existing_media_ids)} fotos anteriores eliminadas")
                    product_files = []
                    image_errors = []
                    for image_index, raw_image_url in enumerate(raw_image_urls[:10], start=1):
                        try:
                            image_bytes, mime_type, filename, source_url = _download_image_bytes(raw_image_url)
                            resource_url = staged_upload_image(shopify_config, filename, mime_type, image_bytes)
                            product_files.append(
                                {
                                    "originalSource": resource_url,
                                    "alt": clean_value(row.get("Image Alt Text")) or clean_value(row.get("Title")),
                                    "filename": filename,
                                    "contentType": "IMAGE",
                                    "duplicateResolutionMode": "APPEND_UUID",
                                }
                            )
                        except Exception as exc:
                            image_errors.append(f"foto {image_index}: {exc}")
                    if product_files:
                        route = _product_set_files_with_fallback(shopify_config, product_gid, product_files)
                        product_messages.append(f"{len(product_files)} fotos enviadas por {route}")
                    if image_errors:
                        product_status = "PARCIAL"
                        product_messages.append(
                            f"Fotos no cargadas: {len(image_errors)} de {min(len(raw_image_urls), 10)}. "
                            f"Detalle: {' | '.join(image_errors[:3])}"
                        )
                except Exception as exc:
                    product_status = "PARCIAL"
                    product_messages.append(f"Error fotos: {exc}")

            product_data_for_variants = fetch_product_options_and_variants(shopify_config, product_gid)
            if clean_value(row.get("ID")):
                missing_variants = _missing_variant_inputs_from_shopify(
                    product_variant_rows,
                    product_data_for_variants,
                )
            else:
                size_option = _size_option_from_product_data(
                    product_data_for_variants,
                    clean_value(row.get("Option1 Name")) or "Talla",
                )
                fallback_price, fallback_compare_at_price = _price_fallback_from_rows(product_variant_rows)
                missing_variants = _all_variant_inputs(
                    product_variant_rows,
                    option_id=clean_value(size_option.get("id")),
                    option_name=clean_value(size_option.get("name")) or clean_value(row.get("Option1 Name")) or "Talla",
                    fallback_price=fallback_price,
                    fallback_compare_at_price=fallback_compare_at_price,
                )
            if missing_variants:
                try:
                    created_variants = []
                    variant_errors = []
                    for variant_input in missing_variants:
                        size_label = ", ".join(
                            clean_value(option.get("name"))
                            for option in variant_input.get("optionValues", [])
                            if clean_value(option.get("name"))
                        )
                        try:
                            created_variants.extend(
                                product_variants_bulk_create(
                                    shopify_config,
                                    product_gid,
                                    [variant_input],
                                    strategy="REMOVE_STANDALONE_VARIANT" if not clean_value(row.get("ID")) else None,
                                )
                            )
                        except Exception as exc:
                            variant_errors.append(f"{size_label or 'variante'}: {exc}")
                    if created_variants:
                        product_messages.append(
                            f"{len(created_variants)} variantes creadas de {len(missing_variants)} faltantes"
                        )
                    if variant_errors:
                        product_status = "PARCIAL"
                        product_messages.append("Errores variantes: " + " | ".join(variant_errors[:5]))
                except Exception as exc:
                    product_status = "PARCIAL"
                    product_messages.append(f"Error variantes: {exc}")

            try:
                reorder_message = _reorder_product_sizes(shopify_config, product_gid, product_variant_rows)
                if reorder_message:
                    product_messages.append(reorder_message)
            except Exception as exc:
                product_status = "PARCIAL"
                product_messages.append(f"Error orden tallas: {exc}")

            rows.append(
                {
                    "Handle": handle,
                    "ID": product_id,
                    "Resultado": product_status,
                    "Mensaje": ". ".join(product_messages) or "Sin cambios aplicados",
                }
            )
        except Exception as exc:
            rows.append({"Handle": handle, "ID": product_id, "Resultado": "ERROR", "Mensaje": str(exc)})
    return pd.DataFrame(rows)


SITE_UI_CONFIG = {
    "Columbia.pe": {
        "brand_name": "Columbia",
        "logo_path": "assets/brands/columbia.png",
        "primary_color": "#004B8D",
        "accent_color": "#009FE3",
        "shopify_store": "columbiape.myshopify.com",
    },
    "Rockford.pe": {
        "brand_name": "Rockford",
        "logo_path": "assets/brands/rockford.png",
        "primary_color": "#0B2345",
        "accent_color": "#B0895B",
        "shopify_store": "rockfordpe.myshopify.com",
    },
    "HushPuppies.pe": {
        "brand_name": "Hush Puppies",
        "logo_path": "assets/brands/hushpuppies.png",
        "primary_color": "#4B2E1F",
        "accent_color": "#C49A6C",
        "shopify_store": "hushpuppiespe.myshopify.com",
    },
    "Vans.pe": {
        "brand_name": "Vans",
        "logo_path": "assets/brands/vans.png",
        "primary_color": "#111827",
        "accent_color": "#D71920",
        "shopify_store": "vans-dev.myshopify.com",
    },
    "Patagonia.pe": {
        "brand_name": "Patagonia",
        "logo_path": "assets/brands/patagonia.png",
        "primary_color": "#1D4E89",
        "accent_color": "#F15A24",
        "shopify_store": "patagoniape.myshopify.com",
    },
    "Sorel.pe": {
        "brand_name": "Sorel",
        "logo_path": "assets/brands/sorel.png",
        "primary_color": "#111827",
        "accent_color": "#C2410C",
        "shopify_store": "sorelpe.myshopify.com",
    },
    "MountainHardwear.pe": {
        "brand_name": "Mountain Hardwear",
        "logo_path": "assets/brands/mountainhardwear.png",
        "primary_color": "#B91C1C",
        "accent_color": "#111827",
        "shopify_store": "mountainhardwearpe.myshopify.com",
    },
}


def image_data_uri(path):
    path = Path(path)
    if not path.exists():
        return ""
    suffix = path.suffix.lower().replace(".", "")
    mime_by_suffix = {
        "jpg": "jpeg",
        "jpeg": "jpeg",
        "png": "png",
        "webp": "webp",
        "gif": "gif",
    }
    mime = mime_by_suffix.get(suffix, "png")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/{mime};base64,{encoded}"


def resolve_logo_path(path):
    path = Path(path)
    if path.exists():
        return str(path)

    folder = path.parent
    stem = path.stem
    aliases = {
        "mountainhardwear": ["mhw", "mountainhardwear"],
        "hushpuppies": ["hushpuppies", "hush_puppies"],
    }
    stems = [stem, f"logo_{stem}"]
    for alias in aliases.get(stem, []):
        stems.extend([alias, f"logo_{alias}"])

    for candidate_stem in dict.fromkeys(stems):
        for suffix in ("png", "jpg", "jpeg", "webp"):
            candidate = folder / f"{candidate_stem}.{suffix}"
            if candidate.exists():
                return str(candidate)

    wanted_keys = {re.sub(r"[^a-z0-9]+", "", stem.lower())}
    for alias in aliases.get(stem, []):
        wanted_keys.add(re.sub(r"[^a-z0-9]+", "", alias.lower()))
    if folder.exists():
        for candidate in folder.iterdir():
            if not candidate.is_file() or candidate.suffix.lower().replace(".", "") not in ("png", "jpg", "jpeg", "webp"):
                continue
            candidate_key = candidate.stem.lower()
            candidate_key = re.sub(r"^logo[_-]*", "", candidate_key)
            candidate_key = re.sub(r"\.(png|jpg|jpeg|webp)$", "", candidate_key)
            candidate_key = re.sub(r"[^a-z0-9]+", "", candidate_key)
            if candidate_key in wanted_keys:
                return str(candidate)
    return str(path)


def brand_logo_stem_for_name(brand_name):
    normalized = re.sub(r"[^a-z0-9]+", "", clean_value(brand_name).lower())
    logo_stems = {
        "columbia": "columbia",
        "rockford": "rockford",
        "patagonia": "patagonia",
        "sorel": "sorel",
        "mountainhardwear": "mountainhardwear",
        "hushpuppies": "hushpuppies",
        "hushpuppieskids": "hpk",
        "accesorioshp": "hushpuppies",
        "keds": "keds",
        "vans": "vans",
    }
    return logo_stems.get(normalized, normalized)


def brand_logo_path_for_name(brand_name):
    stem = brand_logo_stem_for_name(brand_name)
    return resolve_logo_path(f"assets/brands/{stem}.png")


def render_html(html, sidebar=False):
    target = st.sidebar if sidebar else st
    if hasattr(target, "html"):
        target.html(html)
    else:
        target.markdown(html, unsafe_allow_html=True)


def get_site_config(brand_config, shopify_config=None):
    if isinstance(brand_config, str):
        selected_site = brand_config
        site_key = next(
            (key for key, config in SITE_CONFIGS.items() if config["site_label"] == selected_site),
            selected_site,
        )
        brand_config = get_brand_config(site_key)
    ui_config = SITE_UI_CONFIG.get(brand_config["site_label"], {}).copy()
    ui_config.setdefault("brand_name", brand_config["label"])
    ui_config.setdefault("logo_path", ui_config.get("logo") or f"assets/brands/{brand_config['site_key']}.png")
    ui_config["logo"] = ui_config["logo_path"]
    ui_config.setdefault("primary_color", "#17269A")
    ui_config.setdefault("accent_color", "#009FE3")
    ui_config["site_label"] = brand_config["site_label"]
    ui_config["allowed_brands"] = brand_config.get("allowed_arti_brands", [])
    ui_config["output_file"] = brand_config.get("output_filename", "")
    ui_config["shopify_store"] = clean_value((shopify_config or {}).get("shop_domain")) or ui_config.get("shopify_store", "")
    ui_config["api_version"] = clean_value((shopify_config or {}).get("api_version")) or DEFAULT_API_VERSION
    return ui_config


def inject_custom_css(config):
    site_logo_src = image_data_uri(resolve_logo_path(config.get("logo_path") or config.get("logo", "")))
    site_logo_css = f'url("{site_logo_src}")' if site_logo_src else "none"
    site_label_css = clean_value(config.get("site_label")).replace("\\", "\\\\").replace('"', '\\"')
    st.markdown(
        f"""
        <style>
        :root {{
            --brand-primary: {config["primary_color"]};
            --brand-accent: {config["accent_color"]};
            --site-logo-url: {site_logo_css};
            --site-label: "{site_label_css}";
            --brand-soft: color-mix(in srgb, var(--brand-accent) 12%, white);
            --forus-blue: #17269A;
            --shopify-green: #95BF47;
            --bg-main: #F6F8FC;
            --card-bg: #FFFFFF;
            --text-main: #0F172A;
            --text-muted: #64748B;
        }}
        .stApp {{ background: var(--bg-main); color: var(--text-main); }}
        header[data-testid="stHeader"] {{
            display: none;
        }}
        div[data-testid="stToolbar"],
        div[data-testid="stDecoration"],
        #MainMenu,
        footer {{
            visibility: hidden;
            height: 0;
        }}
        .block-container {{
            max-width: 1180px;
            padding-top: 26px;
            padding-bottom: 34px;
        }}
        button[kind="header"],
        button[kind="headerNoPadding"],
        button[data-testid="stBaseButton-header"],
        button[data-testid="stBaseButton-headerNoPadding"],
        button[data-testid="stExpandSidebarButton"],
        button[data-testid="stSidebarCollapseButton"],
        button[data-testid="collapsedControl"],
        div[data-testid="collapsedControl"] {{
            display: none !important;
            pointer-events: none !important;
        }}
        section[data-testid="stSidebar"] {{
            background: #F3F6FB;
            border-right: 1px solid #DDE6F2;
            display: block !important;
            visibility: visible !important;
            min-width: 360px !important;
            width: 360px !important;
            max-width: 360px !important;
            transform: translateX(0) !important;
            position: fixed !important;
            left: 0 !important;
            top: 0 !important;
            bottom: 0 !important;
            z-index: 999 !important;
        }}
        section[data-testid="stSidebar"] > div {{
            padding: 28px 18px;
            width: 360px !important;
            overflow-y: auto !important;
        }}
        div[data-testid="stSidebarContent"] {{
            width: 360px !important;
        }}
        [data-testid="stSidebar"][aria-expanded="false"],
        [data-testid="stSidebar"][aria-hidden="true"] {{
            display: block !important;
            visibility: visible !important;
            transform: translateX(0) !important;
            margin-left: 0 !important;
        }}
        section[data-testid="stSidebar"] + div,
        div[data-testid="stAppViewContainer"] > .main {{
            margin-left: 360px !important;
        }}
        @media (max-width: 900px) {{
            section[data-testid="stSidebar"],
            section[data-testid="stSidebar"] > div,
            div[data-testid="stSidebarContent"] {{
                min-width: 330px !important;
                width: 330px !important;
                max-width: 330px !important;
            }}
            section[data-testid="stSidebar"] + div,
            div[data-testid="stAppViewContainer"] > .main {{
                margin-left: 330px !important;
            }}
        }}
        section[data-testid="stSidebar"] p,
        section[data-testid="stSidebar"] label,
        section[data-testid="stSidebar"] span {{
            color: #172554;
        }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] span,
        section[data-testid="stSidebar"] div[data-baseweb="select"] input,
        section[data-testid="stSidebar"] div[data-baseweb="popover"] span {{
            color: #0F172A !important;
        }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div,
        section[data-testid="stSidebar"] details,
        section[data-testid="stSidebar"] .stButton button {{
            border-radius: 18px;
        }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
            min-height: 56px;
            background: #FFFFFF;
            border: 1px solid #DDE6F2;
            box-shadow: 0 10px 22px rgba(15,23,42,0.07);
            padding-left: 12px;
        }}
        section[data-testid="stSidebar"] .stSelectbox label,
        section[data-testid="stSidebar"] .stRadio label {{
            color: #5B6B86 !important;
            font-weight: 800;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card {{
            position: relative;
            margin: 6px 0 24px;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card::after {{
            content: "Sitio activo";
            position: absolute;
            left: 108px;
            top: 18px;
            z-index: 3;
            color: #172554;
            font-size: 13px;
            line-height: 1;
            font-weight: 950;
            pointer-events: none;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card::before {{
            content: "";
            position: absolute;
            left: 18px;
            top: 50%;
            width: 72px;
            height: 46px;
            transform: translateY(-50%);
            border-radius: 13px;
            background-color: #F8FAFC;
            background-image: var(--site-logo-url);
            background-repeat: no-repeat;
            background-position: center;
            background-size: contain;
            border: 1px solid #E2E8F0;
            z-index: 2;
            pointer-events: none;
        }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
            min-height: 78px;
            border-radius: 20px;
            align-items: center;
            justify-content: center;
            text-align: center;
            border-color: #DDE6F2;
            box-shadow: 0 12px 24px rgba(15,23,42,0.06);
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"] > div {{
            padding-left: 108px;
            padding-right: 36px;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"] {{
            position: relative;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"]::before {{
            content: var(--site-label);
            position: absolute;
            left: 108px;
            right: 48px;
            top: 37px;
            z-index: 3;
            color: #0F172A;
            font-size: 18px;
            line-height: 1.15;
            font-weight: 950;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: clip;
            pointer-events: none;
        }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div > div:first-child {{
            flex: 1 1 auto;
            justify-content: center;
        }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] > div > div:first-child > div {{
            width: 100%;
            text-align: center;
        }}
        section[data-testid="stSidebar"] div[data-baseweb="select"] span {{
            color: #0F172A !important;
            font-size: 18px;
            font-weight: 900;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"] span,
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"] input {{
            color: transparent !important;
            caret-color: transparent !important;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"] > div *:not(svg):not(path) {{
            color: transparent !important;
            text-shadow: none !important;
        }}
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"] svg,
        section[data-testid="stSidebar"] .st-key-site_picker_card div[data-baseweb="select"] path {{
            color: #0F172A !important;
            fill: #0F172A !important;
        }}
        .forus-sidebar {{
            border-radius: 24px;
            padding: 22px 20px;
            margin: 2px 0 28px;
            background: #FFFFFF;
            border: 1px solid #DDE6F2;
            box-shadow: 0 12px 24px rgba(15,23,42,0.08);
        }}
        .forus-logo {{
            font-size: 30px;
            line-height: 1;
            font-weight: 900;
            letter-spacing: -0.06em;
            color: #17269A;
        }}
        .forus-tagline {{
            margin-top: 5px;
            color: #17269A;
            font-size: 9px;
            letter-spacing: 0.28em;
            font-weight: 900;
        }}
        .sidebar-brand-card {{
            display: none;
            border-radius: 22px;
            padding: 14px;
            margin: 12px 0 16px;
            background: #FFFFFF;
            border: 1px solid #DDE6F2;
            box-shadow: 0 12px 24px rgba(15,23,42,0.06);
        }}
        .sidebar-brand-logo {{
            min-height: 66px;
            display: grid;
            place-items: center;
        }}
        .sidebar-brand-logo img {{
            max-width: 150px;
            max-height: 54px;
            object-fit: contain;
        }}
        .sidebar-brand-name {{
            color: var(--brand-primary) !important;
            font-size: 18px;
            line-height: 1.15;
            text-align: center;
            font-weight: 900;
            margin: 0;
        }}
        .sidebar-brand-caption {{
            color: #64748B !important;
            font-size: 11px;
            text-align: center;
            margin: 8px 0 0;
            font-weight: 800;
        }}
        .sidebar-card {{
            border-radius: 22px;
            padding: 22px 20px;
            margin: 18px 0 24px;
            background: #FFFFFF;
            border: 1px solid #DDE6F2;
            box-shadow: 0 12px 24px rgba(15,23,42,0.06);
        }}
        .sidebar-label {{
            margin: 18px 0 10px;
            font-size: 14px;
            text-transform: none;
            letter-spacing: 0;
            color: #5B6B86;
            font-weight: 900;
        }}
        .sidebar-value {{
            margin: 0;
            font-size: 16px;
            line-height: 1.6;
            color: #172554 !important;
            font-weight: 800;
        }}
        .active-site-card {{
            display: grid;
            place-items: center;
            border-radius: 20px;
            padding: 12px 14px;
            margin: 12px 0 22px;
            background: #FFFFFF;
            border: 1px solid #DDE6F2;
            box-shadow: 0 12px 24px rgba(15,23,42,0.06);
        }}
        .active-site-logo {{
            width: 100%;
            min-width: 0;
            height: 54px;
            display: grid;
            place-items: center;
            border-radius: 14px;
            background: #F8FAFC;
            border: 1px solid #E2E8F0;
            overflow: hidden;
        }}
        .active-site-logo img {{
            max-width: 150px;
            max-height: 42px;
            object-fit: contain;
        }}
        .active-site-name {{
            margin: 2px 0 0;
            color: #0F172A !important;
            font-size: 18px;
            line-height: 1.1;
            font-weight: 950;
        }}
        .allowed-logo-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
        }}
        .allowed-logo-chip {{
            min-height: 66px;
            display: grid;
            place-items: center;
            padding: 12px 8px;
            border-radius: 16px;
            background: #FFFFFF;
            border: 1px solid #DDE6F2;
            box-shadow: 0 10px 20px rgba(15,23,42,0.05);
        }}
        .allowed-logo-chip.primary {{
            border-color: #93C5FD;
            box-shadow: 0 0 0 1px #BFDBFE, 0 10px 20px rgba(23,38,154,0.08);
        }}
        .allowed-logo-chip img {{
            max-width: 104px;
            max-height: 40px;
            object-fit: contain;
        }}
        .allowed-logo-chip span {{
            max-width: 100%;
            color: #172554 !important;
            font-size: 10px;
            line-height: 1.15;
            text-align: center;
            font-weight: 950;
            text-transform: uppercase;
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] {{
            display: grid;
            gap: 10px;
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label {{
            min-height: 58px;
            border-radius: 18px;
            border: 1px solid #DDE6F2;
            background: #FFFFFF;
            box-shadow: 0 10px 22px rgba(15,23,42,0.06);
            padding: 8px 16px;
            margin: 0;
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) {{
            border-color: #93C5FD;
            box-shadow: 0 0 0 1px #BFDBFE, 0 10px 22px rgba(23,38,154,0.08);
        }}
        section[data-testid="stSidebar"] div[role="radiogroup"] label p {{
            color: #172554 !important;
            font-size: 16px;
            font-weight: 850;
        }}
        .st-key-shopify_sidebar_card {{
            border-radius: 24px;
            background: #FFFFFF;
            border: 1px solid #DDE6F2;
            padding: 20px;
            margin-top: 18px;
            box-shadow: 0 12px 24px rgba(15,23,42,0.08);
        }}
        .st-key-shopify_sidebar_card h3 {{
            margin: 0;
            color: #0F172A;
            font-size: 19px;
            font-weight: 950;
        }}
        .shopify-card-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 16px;
        }}
        .shopify-config-box {{
            border-radius: 18px;
            background: #ECFDF5;
            border: 1px solid #BBF7D0;
            padding: 16px;
            color: #047857;
            font-size: 14px;
            line-height: 1.55;
            font-weight: 800;
            margin-bottom: 14px;
        }}
        .shopify-meta {{
            color: #64748B !important;
            font-size: 13px;
            margin: 0 0 14px;
        }}
        .top-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 18px;
            border: 1px solid #DDE6F2;
            border-radius: 0;
            background: white;
            padding: 22px 28px;
            margin: 0 0 16px;
            box-shadow: none;
        }}
        .brand-lockup {{
            display: flex;
            align-items: center;
            gap: 16px;
            min-width: 0;
        }}
        .brand-logo-card {{
            width: 92px;
            height: 58px;
            border: 1px solid #E2E8F0;
            border-radius: 18px;
            display: grid;
            place-items: center;
            background: #FFFFFF;
            overflow: hidden;
            flex: 0 0 auto;
        }}
        .brand-logo-card img {{
            max-width: 82px;
            max-height: 42px;
            object-fit: contain;
        }}
        .brand-fallback {{
            color: var(--brand-primary);
            font-weight: 900;
            font-size: 14px;
            text-align: center;
            padding: 0 6px;
        }}
        .header-eyebrow {{
            color: var(--brand-accent);
            font-size: 11px;
            font-weight: 900;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            margin: 0;
        }}
        .header-title {{
            margin: 3px 0 2px;
            font-size: 28px;
            line-height: 1.15;
            font-weight: 900;
            color: #0F172A;
            letter-spacing: 0;
        }}
        .header-subtitle {{
            margin: 0;
            color: var(--text-muted);
            font-size: 13px;
            line-height: 1.45;
        }}
        .shopify-lockup {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 0 0 auto;
        }}
        .shopify-bag {{
            width: 44px;
            height: 44px;
            border-radius: 16px;
            display: grid;
            place-items: center;
            background: var(--shopify-green);
            color: white;
            font-size: 23px;
            font-weight: 900;
            font-style: italic;
        }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 5px 10px;
            font-size: 11px;
            font-weight: 900;
            background: #ECFDF5;
            color: #047857;
            border: 1px solid #A7F3D0;
            white-space: nowrap;
        }}
        .status-badge.blue {{
            background: #EFF6FF;
            color: #17269A;
            border-color: #BFDBFE;
        }}
        .status-badge.warn {{
            background: #FFFBEB;
            color: #B45309;
            border-color: #FDE68A;
        }}
        .matrix-stepper {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 12px;
            margin: 0 0 24px;
            border: 1px solid #DDE6F2;
            border-radius: 28px;
            padding: 18px;
            background: #FFFFFF;
            box-shadow: 0 12px 24px rgba(15,23,42,0.06);
        }}
        .step-card {{
            min-height: 74px;
            border-radius: 18px;
            background: #F8FAFC;
            border: 1px solid #E8EEF7;
            padding: 14px;
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .step-card.current {{
            border-color: #BFDBFE;
            background: #EFF6FF;
        }}
        .step-index {{
            display: inline-grid;
            place-items: center;
            width: 40px;
            height: 40px;
            border-radius: 999px;
            background: #FFFFFF;
            color: var(--brand-primary);
            border: 1px solid #DDE6F2;
            font-size: 15px;
            font-weight: 900;
            box-shadow: 0 7px 15px rgba(15,23,42,0.08);
        }}
        .step-title {{
            margin: 0 0 2px;
            color: #0F172A;
            font-size: 16px;
            font-weight: 900;
        }}
        .step-caption {{
            margin: 0;
            color: var(--text-muted);
            font-size: 12px;
        }}
        .section-card {{
            border: 1px solid #DDE6F2;
            border-radius: 26px;
            background: white;
            padding: 26px 28px;
            margin: 0 0 24px;
            box-shadow: 0 12px 24px rgba(15,23,42,0.06);
            overflow: visible;
        }}
        .section-card h2 {{
            color: #0F172A;
            margin: 0 0 8px;
            font-size: 24px;
            line-height: 1.2;
            font-weight: 900;
            letter-spacing: 0;
        }}
        .section-card.action-card h2 {{
            color: #FFFFFF;
        }}
        .section-card.action-card p {{
            color: #E0E7FF;
        }}
        .section-card.action-card {{
            padding: 20px 22px;
            margin-bottom: 12px;
        }}
        .section-card p, .section-card .caption {{
            color: var(--text-muted);
            font-size: 13px;
        }}
        .source-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 14px;
            margin-top: 22px;
        }}
        .metric-grid {{
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 12px;
            margin-top: 16px;
        }}
        .source-card, .metric-card, .check-item {{
            border: 1px solid #E2E8F0;
            border-radius: 18px;
            background: #F8FAFC;
            padding: 18px 20px;
        }}
        .source-card b, .metric-card b {{
            display: block;
            color: #0F172A;
            font-size: 13px;
            margin-bottom: 4px;
        }}
        .source-card span, .metric-card span, .check-item {{
            color: var(--text-muted);
            font-size: 12px;
        }}
        .source-card strong {{
            display: block;
            color: #0F172A;
            font-size: 18px;
            margin-top: 8px;
            font-weight: 900;
        }}
        .st-key-sources_upload_panel {{
            border: 1px solid #DDE6F2;
            border-radius: 26px;
            background: #FFFFFF;
            padding: 26px 28px;
            margin: 0 0 24px;
            box-shadow: 0 12px 24px rgba(15,23,42,0.06);
        }}
        .st-key-sources_upload_panel h2 {{
            color: #0F172A;
            margin: 0 0 8px;
            font-size: 24px;
            line-height: 1.2;
            font-weight: 900;
            letter-spacing: 0;
        }}
        .st-key-sources_upload_panel p {{
            color: var(--text-muted);
            font-size: 13px;
            margin: 0;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] {{
            border: 0 !important;
            border-radius: 0 !important;
            padding: 0 !important;
            background: transparent !important;
            box-shadow: none !important;
            margin-top: 0;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] section {{
            border: 0 !important;
            background: transparent !important;
            padding: 0 !important;
            min-height: 0 !important;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] button {{
            border-radius: 18px !important;
            background: var(--forus-blue) !important;
            color: #FFFFFF !important;
            border: 1px solid var(--forus-blue) !important;
            box-shadow: 0 10px 20px rgba(23,38,154,0.24);
            min-height: 52px;
            min-width: 190px;
            padding: 0 24px !important;
            font-size: 0 !important;
            font-weight: 900 !important;
            width: 100%;
            display: inline-flex !important;
            align-items: center !important;
            justify-content: center !important;
            gap: 10px !important;
            overflow: hidden !important;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] button * {{
            display: none !important;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] button::before {{
            content: "⇧";
            font-size: 18px !important;
            color: #FFFFFF !important;
            line-height: 1;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] button::after {{
            content: "Cargar input";
            font-size: 15px !important;
            color: #FFFFFF !important;
            line-height: 1;
            white-space: nowrap;
        }}
        .st-key-catalog_upload_slot div[data-testid="stFileUploader"] button::after {{
            content: "Subir Catalogo Matrixify";
            font-size: 15px !important;
            color: #FFFFFF !important;
            line-height: 1;
            white-space: nowrap;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] [data-testid="stFileUploaderFileName"] {{
            display: block !important;
            color: #0F172A !important;
            font-weight: 800;
            margin-top: 8px;
        }}
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] small,
        .st-key-sources_upload_panel div[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] {{
            display: none !important;
        }}
        .metric-card strong {{
            display: block;
            margin-top: 4px;
            color: #0F172A;
            font-size: 18px;
            line-height: 1;
            font-weight: 900;
        }}
        .metric-card span {{
            display: block;
            min-height: 30px;
            line-height: 1.35;
        }}
        .kpi-hero {{
            display:flex;
            align-items:flex-start;
            justify-content:space-between;
            gap:18px;
            margin-bottom:20px;
        }}
        .kpi-title h2 {{
            margin:0;
            color:#0F172A;
            font-size:30px;
            font-weight:950;
        }}
        .kpi-title p {{
            margin:8px 0 0;
            color:#64748B;
            font-size:13px;
            font-weight:750;
        }}
        .kpi-card-grid {{
            display:grid;
            grid-template-columns:repeat(4,minmax(0,1fr));
            gap:14px;
            margin:18px 0 22px;
        }}
        .kpi-card {{
            display:flex;
            align-items:center;
            gap:16px;
            min-height:96px;
            padding:18px 20px;
            border-radius:14px;
            background:#FFFFFF;
            border:1px solid #DDE6F2;
            box-shadow:0 12px 26px rgba(15,23,42,0.07);
        }}
        .kpi-icon {{
            width:54px;
            height:54px;
            min-width:54px;
            display:grid;
            place-items:center;
            border-radius:50%;
            font-size:23px;
            font-weight:950;
        }}
        .kpi-card span {{
            display:block;
            color:#334155;
            font-size:13px;
            font-weight:900;
            margin-bottom:5px;
        }}
        .kpi-card strong {{
            display:block;
            color:#0F172A;
            font-size:30px;
            line-height:1;
            font-weight:950;
        }}
        .kpi-card.blue .kpi-icon {{ background:#EAF2FF; color:#2563EB; }}
        .kpi-card.green .kpi-icon {{ background:#EAF8EF; color:#16A34A; }}
        .kpi-card.purple .kpi-icon {{ background:#F1EAFF; color:#6D28D9; }}
        .kpi-card.orange .kpi-icon {{ background:#FFF3E4; color:#EA580C; }}
        .kpi-card.cyan .kpi-icon {{ background:#E8F7FB; color:#0891B2; }}
        .kpi-card.lime .kpi-icon {{ background:#ECFDF3; color:#15803D; }}
        .kpi-card.red .kpi-icon {{ background:#FEECEF; color:#DC2626; }}
        .kpi-card.slate .kpi-icon {{ background:#EEF2F7; color:#334155; }}
        .kpi-panel {{
            border-radius:16px;
            background:#FFFFFF;
            border:1px solid #DDE6F2;
            box-shadow:0 12px 26px rgba(15,23,42,0.06);
            padding:18px;
            margin:14px 0;
        }}
        .kpi-panel h3 {{
            margin:0 0 14px;
            color:#172554;
            font-size:20px;
            font-weight:950;
        }}
        .brand-kpi-table {{
            width:100%;
            border-collapse:separate;
            border-spacing:0;
            overflow:hidden;
            border:1px solid #E2E8F0;
            border-radius:14px;
            background:#FFFFFF;
        }}
        .brand-kpi-table th,
        .brand-kpi-table td {{
            padding:14px 16px;
            border-bottom:1px solid #E2E8F0;
            color:#172554;
            font-size:13px;
            text-align:left;
        }}
        .brand-kpi-table th {{
            background:#F8FAFC;
            color:#475569;
            font-weight:950;
        }}
        .brand-kpi-table tr:last-child td {{ border-bottom:0; }}
        .brand-cell {{
            display:flex;
            align-items:center;
            gap:12px;
            font-weight:900;
        }}
        .brand-cell img {{
            width:44px;
            height:28px;
            object-fit:contain;
        }}
        .coverage-track {{
            height:8px;
            border-radius:999px;
            background:#E8EDF4;
            overflow:hidden;
            min-width:96px;
        }}
        .coverage-bar {{
            height:100%;
            border-radius:999px;
            background:#16C55D;
        }}
        .coverage-cell {{
            display:flex;
            align-items:center;
            gap:10px;
            color:#16A34A !important;
            font-weight:950;
        }}
        .kpi-chart-grid {{
            display:grid;
            grid-template-columns:repeat(2,minmax(0,1fr));
            gap:16px;
            margin:18px 0;
        }}
        .chart-card {{
            min-height:360px;
            border-radius:14px;
            background:#FFFFFF;
            border:1px solid #DDE6F2;
            box-shadow:0 12px 26px rgba(15,23,42,0.06);
            padding:18px 20px 20px;
        }}
        .chart-head {{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:10px;
            margin-bottom:18px;
        }}
        .chart-title {{
            display:flex;
            align-items:center;
            gap:10px;
            color:#172554;
            font-size:20px;
            font-weight:950;
        }}
        .chart-action {{
            display:none;
        }}
        .bar-stage {{
            height:250px;
            display:flex;
            align-items:flex-end;
            gap:12px;
            padding:16px 8px 4px;
            border-bottom:1px solid #DDE6F2;
            background:repeating-linear-gradient(to top, transparent 0, transparent 48px, #E8EEF7 49px);
        }}
        .bar-item {{
            flex:1;
            min-width:0;
            display:flex;
            flex-direction:column;
            align-items:center;
            justify-content:flex-end;
            gap:7px;
            height:100%;
        }}
        .bar-value {{
            color:#0B5CF6;
            font-size:12px;
            font-weight:950;
        }}
        .bar-fill {{
            width:64%;
            min-height:3px;
            border-radius:7px 7px 0 0;
            background:linear-gradient(180deg,#2563FF 0%,#0958D9 100%);
            box-shadow:0 8px 18px rgba(37,99,255,0.22);
        }}
        .bar-fill.purple {{
            background:linear-gradient(180deg,#6D5BFF 0%,#3D2CCF 100%);
        }}
        .bar-label {{
            min-height:46px;
            display:flex;
            flex-direction:column;
            align-items:center;
            justify-content:flex-start;
            gap:5px;
            color:#172554;
            font-size:10px;
            line-height:1.1;
            text-align:center;
            font-weight:850;
        }}
        .table-pager {{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            margin-top:14px;
        }}
        .pager-note {{
            color:#64748B;
            font-size:12px;
            font-weight:750;
        }}
        .bar-item {{
            position:relative;
            cursor:pointer;
            outline:none;
        }}
        .bar-item:hover .bar-fill,
        .bar-item:focus .bar-fill {{
            transform:scaleY(1.04);
            filter:saturate(1.2);
            box-shadow:0 12px 28px rgba(37,99,255,0.32);
        }}
        .bar-item:hover .bar-value,
        .bar-item:focus .bar-value {{
            color:#003BDB;
            transform:translateY(-2px);
        }}
        .bar-fill {{
            transition:transform .18s ease, filter .18s ease, box-shadow .18s ease;
            transform-origin:bottom;
        }}
        .bar-value {{
            transition:transform .18s ease, color .18s ease;
        }}
        .bar-tooltip {{
            position:absolute;
            left:50%;
            bottom:calc(100% + 8px);
            transform:translateX(-50%) translateY(6px);
            min-width:138px;
            padding:10px 12px;
            border-radius:10px;
            background:#0F172A;
            color:#FFFFFF;
            font-size:12px;
            line-height:1.25;
            font-weight:850;
            opacity:0;
            pointer-events:none;
            z-index:8;
            box-shadow:0 12px 24px rgba(15,23,42,0.2);
            transition:opacity .16s ease, transform .16s ease;
        }}
        .bar-tooltip strong {{
            display:block;
            color:#FFFFFF;
            font-size:15px;
            margin-top:3px;
        }}
        .bar-tooltip::after {{
            content:"";
            position:absolute;
            left:50%;
            top:100%;
            transform:translateX(-50%);
            border:7px solid transparent;
            border-top-color:#0F172A;
        }}
        .bar-item:hover .bar-tooltip,
        .bar-item:focus .bar-tooltip {{
            opacity:1;
            transform:translateX(-50%) translateY(0);
        }}
        .bar-label-icon {{
            color:#17269A;
            font-size:16px;
            line-height:1;
        }}
        .kpi-table-card {{
            border-radius:14px;
            background:#FFFFFF;
            border:1px solid #DDE6F2;
            box-shadow:0 12px 26px rgba(15,23,42,0.06);
            padding:18px;
            margin:16px 0;
        }}
        .kpi-table-head {{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:16px;
            margin-bottom:14px;
        }}
        .kpi-table-title {{
            display:flex;
            align-items:center;
            gap:10px;
            color:#172554;
            font-size:20px;
            font-weight:950;
        }}
        .kpi-table-controls {{
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            margin:12px 0 16px;
        }}
        .kpi-filter-button {{
            min-width:120px;
            height:38px;
            display:inline-flex;
            align-items:center;
            justify-content:center;
            gap:8px;
            border-radius:8px;
            border:1px solid #DDE6F2;
            color:#172554;
            background:#FFFFFF;
            font-size:13px;
            font-weight:900;
        }}
        .kpi-table {{
            width:100%;
            border-collapse:separate;
            border-spacing:0;
            border:1px solid #E2E8F0;
            border-radius:12px;
            overflow:hidden;
        }}
        .kpi-table th,
        .kpi-table td {{
            padding:13px 14px;
            border-bottom:1px solid #E2E8F0;
            border-right:1px solid #E2E8F0;
            color:#172554;
            font-size:13px;
            text-align:left;
        }}
        .kpi-table th {{
            background:#F8FAFC;
            color:#64748B;
            font-weight:950;
        }}
        .kpi-table tr:last-child td {{ border-bottom:0; }}
        .kpi-table th:last-child,
        .kpi-table td:last-child {{ border-right:0; }}
        .row-index {{
            display:inline-grid;
            place-items:center;
            width:24px;
            height:24px;
            border-radius:8px;
            background:#F1F5F9;
            color:#172554;
            font-size:12px;
            font-weight:900;
        }}
        .problem-dot {{
            display:inline-block;
            width:8px;
            height:8px;
            border-radius:50%;
            background:#F43F5E;
            margin-right:8px;
            box-shadow:0 0 0 3px #FFE4E6;
        }}
        .action-chip {{
            display:inline-flex;
            align-items:center;
            gap:8px;
        }}
        .action-chip::before {{
            content:"";
            width:22px;
            height:22px;
            border-radius:50%;
            background:#EAF2FF;
            border:1px solid #BFDBFE;
        }}
        .stock-badge {{
            display:inline-flex;
            min-width:34px;
            justify-content:center;
            padding:4px 10px;
            border-radius:999px;
            color:#E11D48;
            background:#FFE8EE;
            font-weight:950;
        }}
        @media (max-width: 1100px) {{
            .kpi-chart-grid {{ grid-template-columns:1fr; }}
        }}
        @media (max-width: 1100px) {{
            .kpi-card-grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
        }}
        .st-key-action_panel .stButton button {{
            width: auto;
            min-width: 180px;
            min-height: 48px;
            background: var(--forus-blue) !important;
            color: #FFFFFF !important;
            border-color: var(--forus-blue) !important;
            box-shadow: 0 10px 22px rgba(23,38,154,0.22);
        }}
        .base-status-card {{
            border: 1px solid #DDE6F2;
            border-radius: 22px;
            background: #FFFFFF;
            padding: 18px;
            margin: 0 0 22px;
            box-shadow: 0 10px 22px rgba(15,23,42,0.05);
        }}
        .base-status-head {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            margin-bottom: 14px;
        }}
        .base-status-head h3 {{
            margin: 0;
            color: #0F172A;
            font-size: 18px;
            font-weight: 950;
        }}
        .base-status-grid {{
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 12px;
        }}
        .base-status-item {{
            border: 1px solid #E2E8F0;
            border-radius: 18px;
            background: #F8FAFC;
            padding: 14px 16px;
        }}
        .base-status-item b {{
            display: block;
            color: #0F172A;
            font-size: 13px;
            margin-bottom: 6px;
        }}
        .base-status-item span {{
            display: block;
            color: #64748B;
            font-size: 12px;
            line-height: 1.35;
            min-height: 30px;
        }}
        .wide-checklist {{
            border: 1px solid #DDE6F2;
            border-radius: 26px;
            background: #FFFFFF;
            padding: 22px;
            margin: 0 0 24px;
            box-shadow: 0 10px 22px rgba(15,23,42,0.05);
        }}
        .wide-checklist h2 {{
            margin: 0 0 6px;
            color: #0F172A;
            font-size: 22px;
            font-weight: 950;
        }}
        .wide-checklist p {{
            margin: 0 0 16px;
            color: #64748B;
            font-size: 13px;
        }}
        .wide-checklist-grid {{
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: 10px;
        }}
        .wide-checklist-item {{
            border: 1px solid #E2E8F0;
            border-radius: 16px;
            background: #F8FAFC;
            padding: 14px;
            color: #475569;
            font-size: 12px;
            line-height: 1.35;
        }}
        .chip-row {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
        }}
        .chip {{
            border-radius: 999px;
            padding: 6px 10px;
            background: var(--brand-soft);
            border: 1px solid color-mix(in srgb, var(--brand-accent) 34%, white);
            color: var(--brand-primary);
            font-size: 11px;
            font-weight: 900;
        }}
        .benefits-wrap {{
            display: none;
        }}
        .upload-shell {{
            border: 1px solid #DDE6F2;
            border-radius: 26px;
            background: linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%);
            padding: 26px 28px 22px;
            margin: 0 0 18px;
            box-shadow: 0 18px 38px rgba(15,23,42,0.07);
            position: relative;
            overflow: hidden;
        }}
        .st-key-input_upload_panel {{
            border: 1px solid #DDE6F2;
            border-radius: 26px;
            background: linear-gradient(180deg, #FFFFFF 0%, #FBFDFF 100%);
            padding: 26px 28px 24px;
            margin: 0 0 24px;
            box-shadow: 0 18px 38px rgba(15,23,42,0.07);
            position: relative;
            overflow: hidden;
        }}
        .st-key-input_upload_panel::after {{
            content: "XLS";
            position: absolute;
            right: 24px;
            top: 24px;
            width: 56px;
            height: 56px;
            border-radius: 18px;
            display: grid;
            place-items: center;
            color: var(--brand-primary);
            background: var(--brand-soft);
            border: 1px solid color-mix(in srgb, var(--brand-accent) 30%, white);
            font-weight: 900;
            font-size: 17px;
        }}
        .st-key-input_upload_panel h2 {{
            margin: 0 0 8px;
            font-size: 25px;
            color: #0F172A;
            font-weight: 900;
            letter-spacing: 0;
        }}
        .st-key-input_upload_panel p {{
            color: var(--text-muted);
            font-size: 13px;
            margin-bottom: 14px;
        }}
        .st-key-input_upload_panel div[data-testid="stRadio"] {{
            margin: 14px 0 10px;
            padding: 14px 16px;
            border: 1px solid #E2E8F0;
            border-radius: 18px;
            background: #F8FAFC;
        }}
        .st-key-input_upload_panel div[data-testid="stFileUploader"] {{
            margin-top: 12px;
        }}
        .upload-shell::after {{
            content: "";
            position: absolute;
            width: 180px;
            height: 180px;
            right: -70px;
            top: -90px;
            border-radius: 999px;
            background: color-mix(in srgb, var(--brand-accent) 14%, transparent);
            pointer-events: none;
        }}
        .upload-title-row {{
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 18px;
            margin-bottom: 18px;
            position: relative;
            z-index: 1;
        }}
        .upload-title-row h2 {{
            margin: 0 0 8px;
            font-size: 25px;
            line-height: 1.15;
            color: #0F172A;
            font-weight: 900;
        }}
        .upload-title-row p {{
            margin: 0;
            color: var(--text-muted);
            font-size: 13px;
            line-height: 1.5;
        }}
        .upload-icon {{
            width: 52px;
            height: 52px;
            border-radius: 18px;
            display: grid;
            place-items: center;
            color: var(--brand-primary);
            background: var(--brand-soft);
            border: 1px solid color-mix(in srgb, var(--brand-accent) 30%, white);
            font-weight: 900;
            font-size: 22px;
        }}
        .upload-note {{
            border: 1px dashed color-mix(in srgb, var(--brand-accent) 45%, white);
            background: #F8FBFF;
            border-radius: 20px;
            padding: 15px 18px;
            margin-bottom: 12px;
            color: #475569;
            font-size: 13px;
            font-weight: 700;
            position: relative;
            z-index: 1;
        }}
        div[data-testid="stFileUploader"] {{
            border: 1px dashed color-mix(in srgb, var(--brand-accent) 52%, white) !important;
            border-radius: 22px !important;
            padding: 14px !important;
            background: #FFFFFF !important;
            box-shadow: inset 0 0 0 1px rgba(255,255,255,0.65);
        }}
        div[data-testid="stFileUploader"] section {{
            border: 0 !important;
            background: #F1F5F9 !important;
            border-radius: 16px !important;
            padding: 18px !important;
        }}
        div[data-testid="stFileUploader"] button {{
            border-radius: 12px !important;
            background: #FFFFFF !important;
            color: var(--brand-primary) !important;
            border: 1px solid #CBD5E1 !important;
            font-weight: 900 !important;
        }}
        div[data-testid="stFileUploader"] small,
        div[data-testid="stFileUploader"] span {{
            color: #64748B !important;
            font-weight: 700;
        }}
        div[data-testid="stRadio"] {{
            background: transparent;
            margin-bottom: 10px;
        }}
        div[data-testid="stRadio"] label p {{
            color: #172554 !important;
            font-weight: 800;
        }}
        div[data-testid="stDataFrame"] {{
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid #E2E8F0;
        }}
        .stButton button, .stDownloadButton button {{
            border-radius: 18px;
            font-weight: 800;
            border-color: var(--brand-primary);
        }}
        .stButton button[kind="primary"], .stDownloadButton button[kind="primary"] {{
            background: var(--brand-primary);
            border-color: var(--brand-primary);
        }}
        @media (max-width: 900px) {{
            .top-header {{ align-items: flex-start; flex-direction: column; }}
            .matrix-stepper, .source-grid, .metric-grid {{ grid-template-columns: 1fr; }}
            .shopify-lockup {{ width: 100%; justify-content: space-between; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def inject_styles(config=None):
    inject_custom_css(config or get_site_config(get_brand_config()))


def render_sidebar_brand():
    forus_src = image_data_uri(FORUS_LOGO_PATH)
    logo_html = (
        f'<img src="{forus_src}" alt="Forus" style="max-width:138px;max-height:54px;object-fit:contain;">'
        if forus_src
        else '<div class="forus-logo">FORUS</div><div class="forus-tagline">CONSUMER FANATIC</div>'
    )
    render_html(f'<div class="forus-sidebar">{logo_html}</div>', sidebar=True)


def render_sidebar_brand_card(config):
    brand_src = image_data_uri(resolve_logo_path(config.get("logo_path") or config.get("logo", "")))
    brand_html = (
        f'<img src="{brand_src}" alt="{config["brand_name"]}">'
        if brand_src
        else f'<p class="sidebar-brand-name">{config["brand_name"]}</p>'
    )
    render_html(
        f"""
        <div class="sidebar-brand-card">
            <div class="sidebar-brand-logo">{brand_html}</div>
            <p class="sidebar-brand-caption">{config["site_label"]}</p>
        </div>
        """,
        sidebar=True,
    )


def render_active_site_card(config):
    brand_name = escape(clean_value(config.get("brand_name")) or "Sitio")
    brand_src = image_data_uri(resolve_logo_path(config.get("logo_path") or config.get("logo", "")))
    logo_html = (
        f'<img src="{brand_src}" alt="{brand_name}">'
        if brand_src
        else f'<span>{brand_name[:2].upper()}</span>'
    )
    render_html(
        f"""
        <div class="active-site-card">
            <div class="active-site-logo">{logo_html}</div>
        </div>
        """,
        sidebar=True,
    )


def render_allowed_brands_card(brand_config):
    allowed_brands = list(brand_config["allowed_arti_brands"])
    primary_brand = brand_config["label"].upper()
    ordered_allowed = [primary_brand] + [brand for brand in allowed_brands if brand != primary_brand]
    chips = []
    rendered_logo_stems = set()
    for index, brand in enumerate(ordered_allowed):
        clean_brand = clean_value(brand)
        logo_stem = brand_logo_stem_for_name(clean_brand)
        if logo_stem in rendered_logo_stems:
            continue
        rendered_logo_stems.add(logo_stem)
        brand_src = image_data_uri(brand_logo_path_for_name(clean_brand))
        brand_label = escape(clean_brand.title())
        visual = f'<img src="{brand_src}" alt="{brand_label}">' if brand_src else f"<span>{brand_label}</span>"
        primary_class = " primary" if not chips else ""
        chips.append(
            f"""
            <div class="allowed-logo-chip{primary_class}" title="{brand_label}">
                {visual}
            </div>
            """
        )
    render_html(
        f"""
        <p class="sidebar-label">Marca(s) permitidas</p>
        <div class="allowed-logo-grid">
            {''.join(chips)}
        </div>
        """,
        sidebar=True,
    )


def render_sidebar(config, shopify_config=None, bigquery_ready=False, input_loaded=False):
    render_sidebar_brand_card(config)
    if shopify_config is not None:
        render_sidebar_status(config, shopify_config, bigquery_ready, input_loaded=input_loaded)


def render_sidebar_status(config, shopify_config, bigquery_ready, input_loaded=False):
    input_state = "Cargado" if input_loaded else "Pendiente"
    render_html(
        f"""
        <div class="sidebar-card">
            <p class="sidebar-label">Estado operativo</p>
            <p class="sidebar-value">Marca activa: {config["brand_name"]}</p>
            <p class="sidebar-value">Input comercial: {input_state}</p>
            <p class="sidebar-value">Salida: {config["output_file"]}</p>
        </div>
        """,
        sidebar=True,
    )


def render_sidebar_shopify_card(config, shopify_config):
    configured = is_shopify_configured(shopify_config)
    state = "OK" if configured else "Pend."
    domain = clean_value(shopify_config.get("shop_domain")) or config.get("shopify_store") or "No configurado"
    render_html(
        f"""
        <div class="shopify-card-head">
            <h3>Shopify API</h3>
            <span class="status-badge">{state}</span>
        </div>
        <div class="shopify-config-box">Configurado:<br>{domain}</div>
        <p class="shopify-meta">Admin API {config["api_version"]} · Token en Secrets</p>
        """,
        sidebar=True,
    )


def render_top_header(config):
    brand_src = image_data_uri(resolve_logo_path(config.get("logo_path") or config.get("logo", "")))
    shopify_src = image_data_uri(SHOPIFY_LOGO_PATH)
    brand_html = (
        f'<img src="{brand_src}" alt="{config["brand_name"]}">'
        if brand_src
        else f'<div class="brand-fallback">{config["brand_name"]}</div>'
    )
    shopify_html = (
        f'<img src="{shopify_src}" alt="Shopify" style="max-width:44px;max-height:44px;object-fit:contain;">'
        if shopify_src
        else '<div class="shopify-bag">S</div>'
    )
    render_html(
        f"""
        <div class="top-header">
            <div class="brand-lockup">
                <div class="brand-logo-card">{brand_html}</div>
                <div>
                    <p class="header-eyebrow">Catalogo Control Center</p>
                    <h1 class="header-title">{config["site_label"]} &rarr; Shopify</h1>
                    <p class="header-subtitle">Convierte el input comercial en un Excel Matrixify validado usando BigQuery como fuente maestra.</p>
                </div>
            </div>
            <div class="shopify-lockup">
                <span class="status-badge blue">BigQuery activo</span>
                <span class="status-badge">Shopify conectado</span>
                {shopify_html}
            </div>
        </div>
        """,
    )


def render_header(brand_config=None):
    render_top_header(get_site_config(brand_config or get_brand_config()))


def render_stepper(config, current_step=1):
    steps = [
        ("Input", "Archivo comercial"),
        ("BigQuery", "Fuente maestra"),
        ("Validacion", "Reglas y cruces"),
        ("Shopify", "Sincronizacion final"),
    ]
    items = []
    for index, (title, caption) in enumerate(steps, start=1):
        current = " current" if index == current_step else ""
        status = "Actual" if index == 1 else ("OK" if index == 2 else ("Revisar" if index == 3 else "Pend."))
        tone = "blue" if index == 1 else ("" if index == 2 else (" warn" if index == 3 else " blue"))
        items.append(
            f"""
            <div class="step-card{current}">
                <span class="step-index">{index}</span>
                <div style="min-width:0;flex:1;">
                    <p class="step-title">{title}</p>
                    <p class="step-caption">{caption}</p>
                </div>
                <span class="status-badge{tone}">{status}</span>
            </div>
            """
        )
    render_html(f'<div class="matrix-stepper">{"".join(items)}</div>')


def current_flow_step():
    if st.session_state.get("complete_apply_result_df") is not None or st.session_state.get("shopify_apply_result_df") is not None:
        return 4
    if st.session_state.get("complete_matrixify_df") is not None or st.session_state.get("shopify_preview_df") is not None:
        return 3
    if st.session_state.get("input_loaded") or st.session_state.get("input") is not None or st.session_state.get("input_row_count"):
        return 2
    return 1


def render_sources_card(config, bigquery_ready, arti_source="", template_source="Shopify API", input_count=0, shopify_count=0, arti_count=0):
    bigquery_config = get_bigquery_config()
    project = clean_value(bigquery_config.get("project_id"))
    if not project and isinstance(bigquery_config.get("service_account_info"), dict):
        project = clean_value(bigquery_config["service_account_info"].get("project_id"))
    dataset = clean_value(bigquery_config.get("dataset"))
    table = clean_value(bigquery_config.get("table")) or "ARTI"
    table_label = table if table.count(".") == 2 else ".".join(part for part in [project, dataset, table] if part)
    input_text = f"{input_count:,} productos detectados" if input_count else "Pendiente de carga"
    shopify_text = f"{shopify_count:,} productos sincronizados" if shopify_count else (config["shopify_store"] or template_source)
    arti_text = f"{arti_count:,} filas BigQuery" if arti_count else "Tabla central enlazada"
    render_html(
        f"""
        <div>
            <div>
                <h2>Archivos y fuentes cargadas</h2>
                <p>Resumen limpio de lo que la app usara para preparar la carga.</p>
            </div>
            <div class="source-grid">
                <div class="source-card" style="background:#EFF6FF;border-color:#BFDBFE;"><b>Input productos</b><span>{input_text}</span></div>
                <div class="source-card" style="background:#ECFDF5;border-color:#BBF7D0;"><b>Shopify API</b><span>{shopify_text}</span></div>
                <div class="source-card"><b>ARTI BigQuery</b><span>{arti_text}</span></div>
            </div>
        </div>
        """,
    )


def render_operational_status(config, shopify_config, bigquery_ready, input_loaded):
    render_html(
        f"""
        <div class="section-card">
            <h2>Estado operativo</h2>
            <div class="check-item">Shopify API: {"Conectado" if is_shopify_configured(shopify_config) else "Pendiente"}</div>
            <div class="check-item">BigQuery: {"Activo" if bigquery_ready else "Respaldo local"}</div>
            <div class="check-item">Marca activa: {config["brand_name"]}</div>
            <div class="check-item">Input comercial: {"Cargado" if input_loaded else "Pendiente"}</div>
        </div>
        """,
    )


def render_summary_metrics(metrics):
    items = "".join(
        f'<div class="metric-card"><span>{label}</span><strong>{value}</strong></div>'
        for label, value in metrics
    )
    render_html(f'<div class="section-card"><h2>Resumen bases</h2><p>Datos principales</p><div class="metric-grid">{items}</div></div>')


def render_preview_table(input_df):
    total = len(input_df) if input_df is not None else 0
    shown = min(total, 20)
    render_html(
        f"""
        <div class="section-card">
            <div style="display:flex;align-items:center;justify-content:space-between;gap:16px;">
                <div>
                    <h2>Vista previa del input</h2>
                    <p>Primeras filas detectadas antes de analizar. Mostrando {shown} de {total} productos.</p>
                </div>
                <span class="status-badge blue">Preview</span>
            </div>
        </div>
        """,
    )
    if input_df is not None and not input_df.empty:
        st.dataframe(input_df.head(20), use_container_width=True, height=330)


def render_validations_card():
    render_html(
        """
        <div class="wide-checklist">
            <h2>Checklist</h2>
            <p>Estado de preparacion</p>
            <div class="wide-checklist-grid">
                <div class="wide-checklist-item">SKU, barcode y talla obligatorios.</div>
                <div class="wide-checklist-item">Vendor validado contra marcas permitidas.</div>
                <div class="wide-checklist-item">Cruce automatico con BigQuery.</div>
                <div class="wide-checklist-item">Reporte de errores antes de exportar.</div>
            </div>
        </div>
        """,
    )


def render_analyze_card(config):
    render_html(
        f"""
        <div class="section-card action-card" style="background:var(--forus-blue);border-color:var(--forus-blue);">
            <p style="color:#BFDBFE;font-size:12px;font-weight:900;letter-spacing:.22em;text-transform:uppercase;margin:0 0 10px;">Siguiente accion</p>
            <h2>Analizar y preparar carga</h2>
            <p>Cuando el input este correcto, genera la estructura Matrixify y la hoja Carga Sial.</p>
        </div>
        """,
    )


def render_matrixify_result_card(ready=False):
    state = "Listo para descargar" if ready else "Pendiente de analisis"
    tone = "" if ready else " warn"
    render_html(
        f"""
        <div class="section-card">
            <h2>Archivo Matrixify</h2>
            <p>La estructura queda lista para revisar, descargar y sincronizar con Shopify.</p>
            <span class="status-badge{tone}">{state}</span>
        </div>
        """,
    )


def render_base_status_card(setup_rows):
    cards = []
    for row in setup_rows:
        status = clean_value(row.get("Estado"))
        tone = "" if status.upper().startswith("OK") else " warn"
        cards.append(
            f"""
            <div class="base-status-item">
                <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;">
                    <b>{row.get("Base", "")}</b>
                    <span class="status-badge{tone}">{status}</span>
                </div>
                <span>{row.get("Ruta", "")}</span>
            </div>
            """
        )
    render_html(
        f"""
        <div class="base-status-card">
            <div class="base-status-head">
                <h3>Estado de bases</h3>
                <span class="status-badge blue">Fuentes listas</span>
            </div>
            <div class="base-status-grid">{"".join(cards)}</div>
        </div>
        """
    )


def render_input_upload_card():
    st.markdown(
        """
        <h2>Input comercial</h2>
        <p>Sube el archivo comercial para analizar productos, variantes, precios y estructura Sial. Arrastra tu archivo o seleccionalo; formatos permitidos: .xlsx, .xls.</p>
        """,
        unsafe_allow_html=True,
    )


def format_kpi_number(value):
    if isinstance(value, str):
        return value
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return clean_value(value)


def render_kpi_cards(kpis):
    cards = [
        ("Modelos con stock", kpis["modelos_con_stock"], "blue", "&#9633;"),
        ("Creados Shopify", kpis["modelos_creados_shopify"], "green", "&#9635;"),
        ("Cobertura", f"{kpis['cobertura_shopify']:.0%}", "purple", "%"),
        ("Pendientes creacion", kpis["modelos_pendientes"], "orange", "!"),
        ("Creados sin stock", kpis["productos_creados_sin_stock"], "cyan", "&#9636;"),
        ("Sin foto Shopify", kpis["modelos_sin_foto"], "lime", "&#9673;"),
        ("Productos visibles", kpis["productos_visibles"], "green", "&#9711;"),
        ("Visibles sin stock", kpis["sin_stock_visibles"], "orange", "&#9888;"),
        ("Sin precio Shopify", kpis["modelos_sin_precio"], "red", "$"),
    ]
    html = "".join(
        f"""
        <div class="kpi-card {tone}">
            <div class="kpi-icon">{icon}</div>
            <div><span>{label}</span><strong>{format_kpi_number(value)}</strong></div>
        </div>
        """
        for label, value, tone, icon in cards
    )
    render_html(f'<div class="kpi-card-grid">{html}</div>')


def short_problem_label(value):
    text = clean_value(value)
    mapping = {
        "Con stock no visible": "Stock no visible",
        "Modelo con stock no creado": "No creado",
        "Modelo con stock sin foto": "Sin foto",
        "Creado con stock sin precio": "Sin precio",
        "Sin stock visible": "Visible sin stock",
    }
    return mapping.get(text, text[:18])


def render_brand_summary_table(brand_summary):
    if brand_summary is None or brand_summary.empty:
        return
    rows = []
    for index, row in brand_summary.reset_index(drop=True).iterrows():
        brand = clean_value(row.get("Marca"))
        logo_src = image_data_uri(brand_logo_path_for_name(brand))
        logo_html = f'<img src="{logo_src}" alt="{escape(brand)}">' if logo_src else ""
        coverage = float(row.get("Cobertura") or 0)
        coverage_pct = max(0, min(100, coverage * 100))
        rows.append(
            f"""
            <tr>
                <td>{index + 1}</td>
                <td><div class="brand-cell">{logo_html}<span>{escape(brand.title())}</span></div></td>
                <td>{format_kpi_number(row.get("Modelos_con_stock"))}</td>
                <td style="color:#16A34A;font-weight:950;">{format_kpi_number(row.get("Creados_Shopify"))}</td>
                <td style="color:#EA580C;font-weight:950;">{format_kpi_number(row.get("Pendientes_creacion"))}</td>
                <td>{format_kpi_number(row.get("Stock_total"))}</td>
                <td>
                    <div class="coverage-cell">
                        <div class="coverage-track"><div class="coverage-bar" style="width:{coverage_pct:.0f}%;"></div></div>
                        <span>{coverage_pct:.1f}%</span>
                    </div>
                </td>
            </tr>
            """
        )
    render_html(
        f"""
        <div class="kpi-panel">
            <h3>Resumen por marca</h3>
            <table class="brand-kpi-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Marca</th>
                        <th>Modelos con stock</th>
                        <th>Creados Shopify</th>
                        <th>Pendientes creacion</th>
                        <th>Stock total</th>
                        <th>Cobertura</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """
    )


def render_kpi_bar_chart(title, rows, icon="&#9661;", purple=False):
    rows = list(rows or [])
    max_value = max([float(row.get("value") or 0) for row in rows] or [1]) or 1
    bars = []
    for row in rows:
        value = float(row.get("value") or 0)
        height = max(3, int((value / max_value) * 190)) if value else 3
        label = escape(clean_value(row.get("label")))
        short_label = escape(clean_value(row.get("short")) or clean_value(row.get("label")))
        label_html = "<br>".join(short_label.split(" "))
        value_text = format_kpi_number(value)
        bar_class = "bar-fill purple" if purple else "bar-fill"
        bars.append(
            f"""
            <div class="bar-item" tabindex="0" aria-label="{label}: {value_text}">
                <div class="bar-tooltip">{label}<strong>{value_text}</strong></div>
                <div class="bar-value">{value_text}</div>
                <div class="{bar_class}" style="height:{height}px;"></div>
                <div class="bar-label">
                    <span class="bar-label-icon">{row.get("icon", "")}</span>
                    <span>{label_html}</span>
                </div>
            </div>
            """
        )
    return f"""
    <div class="chart-card">
        <div class="chart-head">
            <div class="chart-title"><span>{icon}</span><span>{escape(title)}</span></div>
        </div>
        <div class="bar-stage">{''.join(bars)}</div>
    </div>
    """


def render_kpi_chart_grid(funnel_rows, pareto_rows):
    render_html(
        f"""
        <div class="kpi-chart-grid">
            {render_kpi_bar_chart("Funnel de catalogo", funnel_rows, icon="&#9661;")}
            {render_kpi_bar_chart("Pareto de problemas", pareto_rows, icon="&#9638;", purple=True)}
        </div>
        """
    )


def render_actions_table(actions_df, key_prefix):
    actions_df = actions_df.copy() if isinstance(actions_df, pd.DataFrame) else pd.DataFrame()
    render_html(
        """
        <div class="kpi-table-card">
            <div class="kpi-table-head">
                <div class="kpi-table-title"><span>▣</span><span>Pendientes accionables</span></div>
            </div>
        </div>
        """
    )
    if actions_df.empty:
        st.success("No hay pendientes accionables con la regla actual.")
        return actions_df

    control_left, control_problem, control_brand, control_right = st.columns([1.8, 1.1, 1.0, 0.7])
    with control_left:
        search = st.text_input(
            "Buscar pendientes",
            placeholder="Buscar por Mod-Col, marca o problema...",
            label_visibility="collapsed",
            key=f"{key_prefix}_actions_search",
        )
    with control_problem:
        problems = ["Todos"] + sorted(actions_df["Problema"].dropna().map(clean_value).unique().tolist())
        selected_problem = st.selectbox(
            "Filtrar",
            problems,
            label_visibility="collapsed",
            key=f"{key_prefix}_actions_filter",
        )
    with control_brand:
        brands = ["Todas"] + sorted(actions_df["Marca"].dropna().map(clean_value).unique().tolist())
        selected_brand = st.selectbox(
            "Marca",
            brands,
            label_visibility="collapsed",
            key=f"{key_prefix}_actions_brand",
        )
    with control_right:
        page_size = st.selectbox(
            "Filas",
            [12, 25, 50, 100, "Todos"],
            label_visibility="collapsed",
            key=f"{key_prefix}_actions_rows",
        )

    filtered = actions_df.copy()
    if search:
        needle = clean_value(search).lower()
        filtered = filtered[
            filtered.apply(lambda row: needle in " ".join(clean_value(value).lower() for value in row.values), axis=1)
        ].copy()
    if selected_problem != "Todos":
        filtered = filtered[filtered["Problema"].map(clean_value) == selected_problem].copy()
    if selected_brand != "Todas":
        filtered = filtered[filtered["Marca"].map(clean_value) == selected_brand].copy()

    page_key = f"{key_prefix}_actions_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    if page_size == "Todos":
        page_size_int = len(filtered) or 1
        total_pages = 1
        st.session_state[page_key] = 1
    else:
        page_size_int = int(page_size)
        total_pages = max(1, (len(filtered) + page_size_int - 1) // page_size_int)
        st.session_state[page_key] = min(max(1, int(st.session_state[page_key])), total_pages)
    start = (st.session_state[page_key] - 1) * page_size_int
    visible = filtered.iloc[start : start + page_size_int].copy()
    rows = []
    for index, row in visible.reset_index(drop=True).iterrows():
        rows.append(
            f"""
            <tr>
                <td><span class="row-index">{start + index + 1}</span></td>
                <td><strong>{escape(clean_value(row.get("Mod-Col")))}</strong></td>
                <td>{escape(clean_value(row.get("Marca")))}</td>
                <td><span class="problem-dot"></span>{escape(clean_value(row.get("Problema")))}</td>
                <td><span class="action-chip">{escape(clean_value(row.get("Accion sugerida")))}</span></td>
                <td style="text-align:center;"><span class="stock-badge">{format_kpi_number(row.get("Stock total"))}</span></td>
            </tr>
            """
        )
    render_html(
        f"""
        <div class="kpi-table-card" style="margin-top:0;">
            <table class="kpi-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Mod-Col</th>
                        <th>Marca</th>
                        <th>Problema</th>
                        <th>Accion sugerida</th>
                        <th>Stock total</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """
    )
    pager_left, pager_mid, pager_right = st.columns([1.4, 1, 1.4])
    with pager_left:
        st.caption(f"Mostrando {len(visible)} de {len(filtered)} resultados filtrados.")
    with pager_mid:
        c1, c2, c3 = st.columns([1, 1.2, 1])
        with c1:
            if st.button("‹", key=f"{key_prefix}_actions_prev", disabled=st.session_state[page_key] <= 1):
                st.session_state[page_key] -= 1
                st.rerun()
        with c2:
            st.markdown(
                f"<div style='text-align:center;color:#172554;font-weight:950;padding-top:8px;'>"
                f"{st.session_state[page_key]} / {total_pages}</div>",
                unsafe_allow_html=True,
            )
        with c3:
            if st.button("›", key=f"{key_prefix}_actions_next", disabled=st.session_state[page_key] >= total_pages):
                st.session_state[page_key] += 1
                st.rerun()
    return filtered


def render_missing_variants_table(missing_variants_df, key_prefix):
    if missing_variants_df is None or missing_variants_df.empty:
        return pd.DataFrame()
    df = missing_variants_df.copy()
    control_left, control_mid, control_right = st.columns([2.0, 1.1, 0.8])
    with control_left:
        search = st.text_input(
            "Buscar variantes",
            placeholder="Buscar por Mod-Col, marca, talla o SKU...",
            label_visibility="collapsed",
            key=f"{key_prefix}_variants_search",
        )
    with control_mid:
        brands = ["Todas"] + sorted(df["MARCA_MA"].dropna().map(clean_value).unique().tolist())
        selected_brand = st.selectbox(
            "Filtrar marca",
            brands,
            label_visibility="collapsed",
            key=f"{key_prefix}_variants_brand",
        )
    with control_right:
        page_size = st.selectbox(
            "Filas",
            [12, 25, 50, 100, "Todas"],
            label_visibility="collapsed",
            key=f"{key_prefix}_variants_rows",
        )

    filtered = df.copy()
    if search:
        needle = clean_value(search).lower()
        filtered = filtered[
            filtered.apply(lambda row: needle in " ".join(clean_value(value).lower() for value in row.values), axis=1)
        ].copy()
    if selected_brand != "Todas":
        filtered = filtered[filtered["MARCA_MA"].map(clean_value) == selected_brand].copy()

    page_key = f"{key_prefix}_variants_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 1
    if page_size == "Todas":
        page_size_int = len(filtered) or 1
        total_pages = 1
        st.session_state[page_key] = 1
    else:
        page_size_int = int(page_size)
        total_pages = max(1, (len(filtered) + page_size_int - 1) // page_size_int)
        st.session_state[page_key] = min(max(1, int(st.session_state[page_key])), total_pages)
    start = (st.session_state[page_key] - 1) * page_size_int
    visible = filtered.iloc[start : start + page_size_int].copy()
    rows = []
    for index, row in visible.reset_index(drop=True).iterrows():
        rows.append(
            f"""
            <tr>
                <td><span class="row-index">{start + index + 1}</span></td>
                <td><strong>{escape(clean_value(row.get("Mod-Col")))}</strong></td>
                <td>{escape(clean_value(row.get("MARCA_MA")))}</td>
                <td>{escape(clean_value(row.get("Talla")))}</td>
                <td>{escape(clean_value(row.get("SKU")))}</td>
                <td style="text-align:center;"><span class="stock-badge">{format_kpi_number(row.get("Stock total"))}</span></td>
            </tr>
            """
        )
    render_html(
        f"""
        <div class="kpi-table-card">
            <div class="kpi-table-head">
                <div class="kpi-table-title"><span>&#9635;</span><span>Detalle de variantes con stock incompletas</span></div>
            </div>
            <table class="kpi-table">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Mod-Col</th>
                        <th>Marca</th>
                        <th>Talla</th>
                        <th>SKU</th>
                        <th>Stock total</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
        </div>
        """
    )
    pager_left, pager_mid, pager_right = st.columns([1.4, 1, 1.4])
    with pager_left:
        st.caption(f"Mostrando {len(visible)} de {len(filtered)} variantes filtradas. Este detalle no cuenta como KPI principal.")
    with pager_mid:
        c1, c2, c3 = st.columns([1, 1.2, 1])
        with c1:
            if st.button("‹", key=f"{key_prefix}_variants_prev", disabled=st.session_state[page_key] <= 1):
                st.session_state[page_key] -= 1
                st.rerun()
        with c2:
            st.markdown(
                f"<div style='text-align:center;color:#172554;font-weight:950;padding-top:8px;'>"
                f"{st.session_state[page_key]} / {total_pages}</div>",
                unsafe_allow_html=True,
            )
        with c3:
            if st.button("›", key=f"{key_prefix}_variants_next", disabled=st.session_state[page_key] >= total_pages):
                st.session_state[page_key] += 1
                st.rerun()
    return filtered


def render_catalog_kpi_dashboard(ui_config, brand_config, shopify_config, bigquery_ready):
    render_html(
        """
        <div class="kpi-hero">
            <div class="kpi-title">
                <h2>Dashboard Shopify</h2>
                <p>Control por codigo modelo-color: stock BigQuery, creacion Shopify, visibilidad y precio.</p>
            </div>
        </div>
        """
    )

    if not bigquery_ready:
        st.error("BigQuery no esta configurado. Para KPIs se necesita leer stock actual y ARTI.")
        return
    if not is_shopify_configured(shopify_config):
        st.error("Shopify API no esta configurado para este sitio.")
        return

    run_key = f"kpi_result_{brand_config['site_key']}"
    if st.button("Actualizar diagnostico KPIs", type="primary"):
        with st.spinner("Leyendo ARTI/BigQuery, stock actual y productos Shopify..."):
            arti_df, arti_source = read_arti_for_app(brand_config)
            stock_df = read_current_stock_from_bigquery(get_bigquery_config())
            shopify_products = fetch_products(shopify_config)
            result = build_catalog_kpis(arti_df, stock_df, shopify_products, brand_config)
            result["meta"] = {
                "arti_source": arti_source,
                "stock_rows": len(stock_df),
                "shopify_products": len(shopify_products),
                "fecha_corte": clean_value(stock_df["fecha_corte"].max()) if not stock_df.empty and "fecha_corte" in stock_df.columns else "",
            }
            st.session_state[run_key] = result

    result = st.session_state.get(run_key)
    if not result:
        st.info("Ejecuta el diagnostico para generar KPIs, graficos y descargables.")
        return

    meta = result.get("meta", {})
    st.caption(
        f"Fuente ARTI: {meta.get('arti_source', '')}  |  Stock file: {format_kpi_number(meta.get('stock_rows', 0))}  |  "
        f"Productos Shopify: {format_kpi_number(meta.get('shopify_products', 0))}  |  Fecha corte: {meta.get('fecha_corte', '')}"
    )
    kpis = result["kpis"]
    render_kpi_cards(kpis)

    actions_df = result["actions"]
    problem_counts = (
        actions_df["Problema"].value_counts().rename_axis("Problema").reset_index(name="Casos")
        if actions_df is not None and not actions_df.empty
        else pd.DataFrame({"Problema": ["Sin observaciones"], "Casos": [0]})
    )
    funnel_rows = [
        {"label": "Modelos con stock", "short": "Con stock", "value": kpis["modelos_con_stock"], "icon": "&#9633;"},
        {"label": "Modelos creados en Shopify", "short": "Creados", "value": kpis["modelos_creados_shopify"], "icon": "&#9635;"},
        {"label": "Creados sin stock", "short": "Sin stock", "value": kpis["productos_creados_sin_stock"], "icon": "&#9636;"},
        {"label": "Productos visibles", "short": "Visibles", "value": kpis["productos_visibles"], "icon": "&#9711;"},
        {"label": "Pendientes de creacion", "short": "Pendientes", "value": kpis["modelos_pendientes"], "icon": "!"},
        {"label": "Sin precio Shopify", "short": "Sin precio", "value": kpis["modelos_sin_precio"], "icon": "$"},
        {"label": "Sin foto Shopify", "short": "Sin foto", "value": kpis["modelos_sin_foto"], "icon": "&#9673;"},
        {"label": "Visibles sin stock", "short": "Visib. sin stock", "value": kpis["sin_stock_visibles"], "icon": "&#9888;"},
    ]
    pareto_rows = [
        {
            "label": clean_value(row.get("Problema")),
            "short": short_problem_label(row.get("Problema")),
            "value": int(row.get("Casos") or 0),
            "icon": "&#9679;",
        }
        for _, row in problem_counts.head(6).iterrows()
    ]

    brand_summary = result.get("brand_summary", pd.DataFrame())
    if brand_summary is not None and not brand_summary.empty and len(brand_summary) > 1:
        render_brand_summary_table(brand_summary)

    render_kpi_chart_grid(funnel_rows, pareto_rows)
    filtered_actions_df = render_actions_table(actions_df, f"{brand_config['site_key']}_kpi")
    if filtered_actions_df is not None and not filtered_actions_df.empty:
        st.download_button(
            "Descargar pendientes filtrados",
            data=dataframe_to_excel_bytes({"Pendientes filtrados": filtered_actions_df}),
            file_name=f"pendientes_filtrados_{brand_config['site_key']}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    missing_variants_df = result["missing_stock_variants"]
    filtered_variants_df = missing_variants_df
    if missing_variants_df is not None and not missing_variants_df.empty:
        filtered_variants_df = render_missing_variants_table(missing_variants_df, f"{brand_config['site_key']}_kpi")
        if filtered_variants_df is not None and not filtered_variants_df.empty:
            st.download_button(
                "Descargar variantes filtradas",
                data=dataframe_to_excel_bytes({"Variantes filtradas": filtered_variants_df}),
                file_name=f"variantes_filtradas_{brand_config['site_key']}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    excel_bytes = dataframe_to_excel_bytes(
        {
            "Resumen modelos": result["model_stock"],
            "Resumen por marca": result.get("brand_summary", pd.DataFrame()),
            "Pendientes accionables": filtered_actions_df if filtered_actions_df is not None else pd.DataFrame(),
            "Detalle variantes stock": filtered_variants_df if filtered_variants_df is not None else pd.DataFrame(),
            "Con stock no visibles": result["stock_not_visible"],
            "Sin stock visibles": result["no_stock_visible"],
            "Sin precio": result["no_price_models"],
            "Sin foto": result["no_photo_models"],
        }
    )
    st.download_button(
        "Descargar diagnostico KPIs",
        data=excel_bytes,
        file_name=f"kpis_catalogo_{brand_config['site_key']}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="XL", layout="wide")
    bigquery_config = get_bigquery_config()
    bigquery_ready = is_bigquery_configured(bigquery_config)

    render_sidebar_brand()
    site_options = {config["site_label"]: key for key, config in SITE_CONFIGS.items()}
    with st.sidebar.container(key="site_picker_card"):
        selected_site_label = st.selectbox(
            "Sitio destino",
            list(site_options),
            index=0,
            key="site_picker",
            label_visibility="collapsed",
        )
    selected_site_key = site_options[selected_site_label]
    brand_config = get_brand_config(selected_site_key)
    shopify_config = get_shopify_config(selected_site_key)
    ui_config = get_site_config(brand_config, shopify_config)
    inject_styles(ui_config)
    render_allowed_brands_card(brand_config)
    operation_area = st.sidebar.radio(
        "Tipo de operacion",
        ["KPIs de catalogo", "Carga de catalogo"],
        index=0,
    )
    operation_mode = "Carga completa"
    if operation_area == "Carga de catalogo":
        operation_mode = st.sidebar.radio(
            "Tipo de carga",
            ["Carga completa", "Carga parcial"],
            index=0,
        )
    with st.sidebar.container(key="shopify_sidebar_card"):
        render_sidebar_shopify_card(ui_config, shopify_config)
        if is_shopify_configured(shopify_config):
            if st.button("Probar conexion Shopify"):
                try:
                    shop = test_connection(shopify_config)
                    st.success(f"Conectado a {shop.get('name', brand_config['site_label'])}")
                    st.caption(shop.get("myshopifyDomain") or shopify_config["shop_domain"])
                    st.caption(f"Origen token: {shop.get('token_source', '')}")
                except ShopifyApiError as exc:
                    st.error(str(exc))
        else:
            st.warning("API no configurada para este sitio.")
            st.code(
                f"""[shopify_sites.{selected_site_key}]
shop_domain = "tienda.myshopify.com"
client_id = "..."
client_secret = "..."
admin_access_token = "..."
api_version = "{DEFAULT_API_VERSION}"
""",
                language="toml",
            )

    render_top_header(ui_config)
    if operation_area == "KPIs de catalogo":
        render_catalog_kpi_dashboard(ui_config, brand_config, shopify_config, bigquery_ready)
        return

    render_stepper(ui_config, current_step=current_flow_step())

    if operation_mode == "Carga parcial":
        operation_labels = {
            "Tags": "tags",
            "Fotos 10 vistas": "photos",
            "Siblings": "siblings",
            "Titulo": "title",
            "Body HTML / Material / Cuidado": "body",
        }
        st.markdown('<div class="section-card"><h2>Carga parcial</h2>', unsafe_allow_html=True)
        update_label = st.selectbox("Que quieres actualizar", list(operation_labels), index=0)
        update_operation = operation_labels[update_label]
        update_source = st.radio(
            "Fuente de datos actuales",
            ["Shopify API", "Respaldo Excel"],
            index=0 if is_shopify_configured(shopify_config) else 1,
            help="Shopify API es la referencia operativa. El respaldo Excel solo se usa si la API no esta disponible.",
        )
        template_file = None
        if update_source == "Respaldo Excel":
            template_file = st.file_uploader(
                f"1. Subir respaldo operativo de {brand_config['site_label']}",
                type=["xlsx", "xls"],
                key="template_update",
                help="Se usa como respaldo para encontrar ID, Handle, tags actuales, fotos actuales y codigo modelo color.",
            )

        update_file = None
        tag_mode = "merge"
        image_mode = "replace"
        only_missing_images = True
        body_mode = "from_input"

        if update_operation == "tags":
            tag_mode = st.radio("Como aplicar tags", ["merge", "replace"], format_func=lambda v: "Agregar a los tags actuales" if v == "merge" else "Reemplazar todos los tags")
            update_file = st.file_uploader("2. Subir archivo con Mod-Col y Tags", type=["xlsx", "xls"], key="update_tags")
        elif update_operation == "photos":
            image_mode = st.radio("Comando de fotos", ["replace", "merge"], format_func=lambda v: "Reemplazar fotos del producto" if v == "replace" else "Agregar/mezclar fotos")
            if image_mode == "replace":
                only_missing_images = False
                st.caption("REPLACE procesa productos aunque ya tengan fotos: elimina las actuales y sube las 10 vistas nuevas por API.")
            else:
                only_missing_images = st.checkbox("Solo productos sin foto en el catalogo", value=False)
            update_file = st.file_uploader("2. Opcional: subir lista con Mod-Col a corregir", type=["xlsx", "xls"], key="update_photos")
            st.caption("Si no subes lista, revisa el catalogo completo. Siempre genera 10 URLs por producto.")
        elif update_operation == "siblings":
            st.caption("Recalcula siblings para todo el catalogo: todos los productos con el mismo codigo modelo quedan separados por comas.")
        elif update_operation == "title":
            update_file = st.file_uploader("2. Subir archivo con Mod-Col y Title", type=["xlsx", "xls"], key="update_title")
        elif update_operation == "body":
            body_source = st.radio(
                "Origen para corregir Body HTML",
                ["Desde input comercial", "Detectar desde respaldo Excel"],
                key="body_source",
            )
            body_mode = "from_input" if body_source == "Desde input comercial" else "fix_catalog"
            if body_mode == "from_input":
                update_file = st.file_uploader(
                    "2. Subir input con Mod-Col, Body HTML, Caracteristicas, Material y Cuidado",
                    type=["xlsx", "xls"],
                    key="update_body",
                )
            else:
                st.caption("Detecta Body HTML con Material/Cuidado mezclados y genera solo los productos afectados.")
        st.markdown("</div>", unsafe_allow_html=True)

        update_ready = update_file or update_operation in ("photos", "siblings") or body_mode == "fix_catalog"
        if update_source == "Shopify API" and not is_shopify_configured(shopify_config):
            st.error("Este sitio no tiene Shopify API configurada en Secrets.")
            update_ready = False

        if update_source == "Shopify API" and update_ready:
            try:
                update_df = read_excel(update_file) if update_file else None
                if update_df is not None:
                    _, detected_brands, blocked_brands = input_brand_report(update_df, brand_config)
                    if blocked_brands:
                        st.error(
                            f"El archivo tiene marcas no permitidas para {brand_config['site_label']}: "
                            f"{', '.join(blocked_brands)}."
                        )
                        st.stop()

                if st.button(f"Analizar carga parcial: {update_label}", type="primary"):
                    with st.spinner("Leyendo productos actuales desde Shopify..."):
                        shopify_products = fetch_products(shopify_config)
                    preview_df, issues_df, matrixify_df = build_shopify_update_preview(
                        shopify_products,
                        update_df,
                        update_operation,
                        brand_config,
                        tag_mode=tag_mode,
                        image_mode=image_mode,
                        only_missing_images=only_missing_images,
                        body_mode=body_mode,
                    )
                    st.session_state["shopify_preview_df"] = preview_df
                    st.session_state["shopify_preview_issues_df"] = issues_df
                    st.session_state["shopify_preview_matrixify_df"] = matrixify_df
                    st.session_state["shopify_preview_operation"] = update_operation

                preview_df = st.session_state.get("shopify_preview_df")
                issues_df = st.session_state.get("shopify_preview_issues_df", pd.DataFrame())
                matrixify_df = st.session_state.get("shopify_preview_matrixify_df", pd.DataFrame())
                if preview_df is not None:
                    if preview_df.empty:
                        st.warning("No se genero ninguna fila de vista previa.")
                    else:
                        st.success(f"Vista previa generada con {len(preview_df):,} cambios.")
                        st.dataframe(preview_df.head(100), use_container_width=True)
                    if issues_df is not None and not issues_df.empty:
                        st.warning(f"Hay {len(issues_df):,} observaciones.")
                        st.dataframe(issues_df, use_container_width=True)

                    excel_bytes = dataframe_to_excel_bytes(
                        {
                            "Vista previa": preview_df if preview_df is not None else pd.DataFrame(),
                            "Revision": issues_df if issues_df is not None else pd.DataFrame(),
                            "Matrixify fotos": matrixify_df if matrixify_df is not None else pd.DataFrame(),
                        }
                    )
                    st.download_button(
                        "Descargar estructura Matrixify",
                        data=excel_bytes,
                        file_name=f"vista_previa_{update_operation}_{brand_config['site_key']}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

                    can_apply = update_operation in ("tags", "title", "body", "siblings", "photos") and preview_df is not None and not preview_df.empty
                    if update_operation == "photos":
                        st.info("REPLACE elimina las fotos actuales del producto y sube las 10 URLs nuevas. MERGE agrega las URLs nuevas sin borrar las actuales.")
                    if can_apply:
                        confirm_apply = st.checkbox("Confirmo que revise la vista previa y quiero aplicar en Shopify")
                        if confirm_apply and st.button("Sincronizar Shopify", type="primary"):
                            with st.spinner("Sincronizando cambios en Shopify..."):
                                result_df = apply_shopify_preview(shopify_config, preview_df)
                            st.session_state["shopify_apply_result_df"] = result_df
                            st.dataframe(result_df, use_container_width=True)
                            st.download_button(
                                "Descargar reporte de sincronizacion",
                                data=dataframe_to_excel_bytes({"Resultado": result_df}),
                                file_name=f"resultado_shopify_{update_operation}_{brand_config['site_key']}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            )
            except Exception as exc:
                st.error("No pude generar o aplicar la carga parcial con Shopify API.")
                st.exception(exc)
        elif update_source == "Respaldo Excel" and template_file and update_ready:
            try:
                template_df = pd.read_excel(template_file, sheet_name="Products", dtype=object)
                if "Vendor" in template_df.columns:
                    catalog_vendors = {
                        clean_value(value).lower()
                        for value in template_df["Vendor"].dropna()
                        if clean_value(value)
                    }
                    expected_vendors = expected_catalog_vendors(brand_config)
                    if catalog_vendors and catalog_vendors.isdisjoint(expected_vendors):
                        st.error(
                            f"El respaldo Excel cargado no parece ser de {brand_config['site_label']}. "
                            f"Vendors esperados: {', '.join(sorted(expected_vendors))}. Vendors encontrados: {', '.join(sorted(catalog_vendors))}."
                        )
                        st.stop()

                update_df = read_excel(update_file) if update_file else None
                if update_df is not None:
                    _, detected_brands, blocked_brands = input_brand_report(update_df, brand_config)
                    if blocked_brands:
                        st.error(
                            f"El archivo tiene marcas no permitidas para {brand_config['site_label']}: "
                            f"{', '.join(blocked_brands)}."
                        )
                        st.stop()

                if st.button(f"Analizar carga parcial: {update_label}", type="primary"):
                    update_arti_df = None
                    if update_operation == "photos":
                        try:
                            update_arti_df, _ = read_arti_for_app(brand_config)
                        except Exception:
                            update_arti_df = None
                    matrixify_df, issues_df = build_matrixify_updates(
                        template_df,
                        update_input_df=update_df,
                        arti=update_arti_df,
                        operation=update_operation,
                        brand_config=brand_config,
                        tag_mode=tag_mode,
                        image_mode=image_mode,
                        only_missing_images=only_missing_images,
                        body_mode=body_mode,
                    )
                    if matrixify_df.empty:
                        st.warning("No se genero ninguna fila de carga parcial. Revisa la hoja Revision.")
                    else:
                        st.success(f"Carga parcial generada con {len(matrixify_df):,} productos.")
                        st.dataframe(matrixify_df.head(100), use_container_width=True)
                    if issues_df is not None and not issues_df.empty:
                        st.warning(f"Hay {len(issues_df):,} observaciones.")
                        st.dataframe(issues_df, use_container_width=True)
                    excel_bytes = update_to_excel_bytes(matrixify_df, issues_df)
                    st.download_button(
                        "Descargar estructura Matrixify",
                        data=excel_bytes,
                        file_name=f"carga_parcial_{update_operation}_{brand_config['site_key']}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            except Exception as exc:
                st.error("No pude generar la carga parcial.")
                st.exception(exc)
        else:
            st.info("Sube los archivos requeridos para generar la carga parcial.")
        return

    with st.container(key="sources_upload_panel"):
        render_sources_card(
            ui_config,
            bigquery_ready,
            input_count=int(st.session_state.get("input_row_count") or 0),
            shopify_count=int(st.session_state.get("shopify_product_count") or 0),
            arti_count=int(st.session_state.get("arti_row_count") or 0),
        )
        complete_source = st.radio(
            "Fuente de datos actuales",
            ["Shopify API", "Respaldo Excel"],
            index=0 if is_shopify_configured(shopify_config) else 1,
            help="Shopify API es la referencia operativa. El respaldo Excel solo se usa si la API no esta disponible.",
        )
        template_file = None
        upload_left, upload_right = st.columns([3.5, 1.5], gap="large")
        input_file = st.session_state.get("input")
        with upload_left:
            if complete_source == "Respaldo Excel" and input_file:
                st.caption("Input cargado. Ahora sube el Catalogo Matrixify para conservar IDs.")
            elif complete_source == "Respaldo Excel":
                st.caption("Primero carga el input comercial. Luego este mismo espacio pedira el Catalogo Matrixify.")
        with upload_right:
            if complete_source == "Respaldo Excel" and input_file:
                with st.container(key="catalog_upload_slot"):
                    template_file = st.file_uploader(
                        "Subir Catalogo Matrixify",
                        type=["xlsx", "xls"],
                        key="template",
                        label_visibility="collapsed",
                        help="Este archivo conserva Product ID y Variant ID cuando no usas Shopify API.",
                    )
            else:
                with st.container(key="input_upload_slot"):
                    input_file = st.file_uploader("Cargar input", type=["xlsx", "xls"], key="input", label_visibility="collapsed")
        st.session_state["input_loaded"] = bool(input_file)

    setup_rows = [
        {
            "Base": "Datos actuales Shopify",
            "Ruta": "Shopify API" if complete_source == "Shopify API" else f"Respaldo Excel de {brand_config['site_label']}",
            "Estado": "OK API" if complete_source == "Shopify API" and is_shopify_configured(shopify_config) else ("Obligatorio" if complete_source == "Respaldo Excel" else "Falta API"),
        },
        {
            "Base": "ARTI",
            "Ruta": "BigQuery" if bigquery_ready else f"{DEFAULT_ARTI_ZIP_PATH} / {DEFAULT_ARTI_CSV_PATH} / {DEFAULT_ARTI_PATH}",
            "Estado": "OK BigQuery"
            if bigquery_ready
            else (
                "OK ZIP"
                if Path(DEFAULT_ARTI_ZIP_PATH).exists()
                else ("OK CSV" if Path(DEFAULT_ARTI_CSV_PATH).exists() else ("OK XLSX" if Path(DEFAULT_ARTI_PATH).exists() else "Falta"))
            ),
        },
        {
            "Base": "Tipos Shopify",
            "Ruta": "data/tipos_shopify.xlsx",
            "Estado": "OK" if Path("data/tipos_shopify.xlsx").exists() else "Opcional",
        },
    ]
    render_base_status_card(setup_rows)

    can_process_complete = input_file and (complete_source == "Shopify API" or template_file)
    if can_process_complete:
        try:
            if complete_source == "Shopify API":
                if not is_shopify_configured(shopify_config):
                    st.error("Este sitio no tiene Shopify API configurada en Secrets.")
                    st.stop()
                with st.spinner("Leyendo productos y variantes actuales desde Shopify..."):
                    shopify_products = fetch_products(shopify_config)
                st.session_state["shopify_product_count"] = len(shopify_products)
                st.session_state["complete_shopify_products"] = shopify_products
                template_df = shopify_products_to_matrixify_df(shopify_products)
                template_source = f"Shopify API ({len(shopify_products):,} productos)"
            else:
                template_df = pd.read_excel(template_file, sheet_name="Products", dtype=object)
                template_source = f"respaldo operativo cargado para {brand_config['site_label']}"
                if "Vendor" in template_df.columns:
                    catalog_vendors = {
                        clean_value(value).lower()
                        for value in template_df["Vendor"].dropna()
                        if clean_value(value)
                    }
                    expected_vendors = expected_catalog_vendors(brand_config)
                    if catalog_vendors and catalog_vendors.isdisjoint(expected_vendors):
                        st.error(
                            f"El respaldo Excel cargado no parece ser de {brand_config['site_label']}. "
                            f"Vendors esperados: {', '.join(sorted(expected_vendors))}. Vendors encontrados: {', '.join(sorted(catalog_vendors))}."
                        )
                        st.stop()

            input_df = read_excel(input_file)
            st.session_state["input_row_count"] = len(input_df)
            brand_column, detected_brands, blocked_brands = input_brand_report(input_df, brand_config)
            if blocked_brands:
                st.error(
                    f"El input tiene marcas no permitidas para {brand_config['site_label']}: "
                    f"{', '.join(blocked_brands)}. Marcas permitidas: {', '.join(brand_config['allowed_arti_brands'])}."
                )
                st.stop()

            try:
                arti_df, arti_source = read_arti_for_app(brand_config)
            except FileNotFoundError:
                st.error(
                    "Falta configurar BigQuery o dejar un respaldo local de ARTI: "
                    f"{DEFAULT_ARTI_ZIP_PATH}, {DEFAULT_ARTI_CSV_PATH} o {DEFAULT_ARTI_PATH}"
                )
                st.stop()
            except Exception as exc:
                st.error("No se pudo leer el ARTI desde BigQuery.")
                st.exception(exc)
                st.stop()

            st.session_state["arti_row_count"] = len(arti_df)
            left_col, right_col = st.columns([2, 1], gap="large")
            analyze_clicked = False
            with left_col:
                render_preview_table(input_df)
                with st.container(key="action_panel"):
                    render_analyze_card(ui_config)
                    analyze_clicked = st.button("Analizar input", type="primary")
                render_validations_card()
            with right_col:
                render_summary_metrics(
                    [
                        ("Columnas base", len(template_df.columns)),
                        ("Filas ARTI BigQuery", len(arti_df)),
                        ("Productos input", len(input_df)),
                        ("Marcas detectadas", len(detected_brands)),
                    ]
                )
                render_operational_status(ui_config, shopify_config, bigquery_ready, input_loaded=True)

            if analyze_clicked:
                matrixify_df, summary_df, issues_df, type_warnings_df, skipped_df, sial_df = build_columbia_matrixify(
                    input_df, arti_df, template_df, brand_config=brand_config
                )
                matrixify_df = coalesce_duplicate_columns(matrixify_df)
                summary_df = coalesce_duplicate_columns(summary_df)
                issues_df = coalesce_duplicate_columns(issues_df)
                type_warnings_df = coalesce_duplicate_columns(type_warnings_df)
                skipped_df = coalesce_duplicate_columns(skipped_df)
                sial_df = coalesce_duplicate_columns(sial_df)
                if complete_source == "Shopify API":
                    matrixify_df = apply_shopify_siblings_to_matrixify(
                        matrixify_df,
                        st.session_state.get("complete_shopify_products", []),
                    )
                st.session_state["complete_matrixify_df"] = matrixify_df
                st.session_state["complete_summary_df"] = summary_df
                st.session_state["complete_issues_df"] = issues_df
                st.session_state["complete_type_warnings_df"] = type_warnings_df
                st.session_state["complete_skipped_df"] = skipped_df
                st.session_state["complete_sial_df"] = sial_df

            matrixify_df = st.session_state.get("complete_matrixify_df")
            if matrixify_df is not None:
                summary_df = st.session_state.get("complete_summary_df", pd.DataFrame())
                issues_df = st.session_state.get("complete_issues_df", pd.DataFrame())
                type_warnings_df = st.session_state.get("complete_type_warnings_df", pd.DataFrame())
                skipped_df = st.session_state.get("complete_skipped_df", pd.DataFrame())
                sial_df = st.session_state.get("complete_sial_df", pd.DataFrame())
                matrixify_df = coalesce_duplicate_columns(matrixify_df)
                summary_df = coalesce_duplicate_columns(summary_df)
                issues_df = coalesce_duplicate_columns(issues_df)
                type_warnings_df = coalesce_duplicate_columns(type_warnings_df)
                skipped_df = coalesce_duplicate_columns(skipped_df)
                sial_df = coalesce_duplicate_columns(sial_df)

                render_matrixify_result_card(ready=not matrixify_df.empty)
                if matrixify_df.empty:
                    st.error("No se pudo generar ninguna fila Matrixify. Revisa la hoja Revision.")
                else:
                    st.success(f"Vista previa generada con {len(matrixify_df):,} variantes.")
                    st.dataframe(summary_df, use_container_width=True)
                    st.dataframe(matrixify_df.head(100), use_container_width=True, height=360)

                if issues_df is not None and not issues_df.empty:
                    st.warning(f"Hay {len(issues_df):,} observaciones para revisar.")
                    st.dataframe(issues_df, use_container_width=True)

                if type_warnings_df is not None and not type_warnings_df.empty:
                    st.warning("Revisa la hoja Tipos nuevos antes de cargar en Shopify.")
                    st.dataframe(type_warnings_df, use_container_width=True)

                if skipped_df is not None and not skipped_df.empty:
                    st.info(f"{len(skipped_df):,} productos fueron omitidos porque no presentaban cambios.")
                    st.dataframe(skipped_df, use_container_width=True)

                if sial_df is not None and not sial_df.empty:
                    st.write("Vista previa Carga Sial")
                    st.dataframe(sial_df.head(100), use_container_width=True, height=320)

                excel_bytes = columbia_to_excel_bytes(
                    matrixify_df, summary_df, issues_df, type_warnings_df, skipped_df, sial_df
                )
                st.download_button(
                    "Descargar estructura Matrixify",
                    data=excel_bytes,
                    file_name=brand_config["output_filename"],
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )

                if complete_source == "Shopify API" and is_shopify_configured(shopify_config) and not matrixify_df.empty:
                    st.info(
                        "Sincronizacion directa habilitada para productos existentes: titulo, descripcion, vendor, tipo, tags, metafields y fotos."
                        " Productos nuevos, variantes, precios e inventario quedan para importacion Matrixify."
                    )
                    confirm_complete = st.checkbox("Confirmo que revise la vista previa y quiero sincronizar productos existentes en Shopify")
                    if confirm_complete and st.button("Sincronizar Shopify", type="primary"):
                        with st.spinner("Sincronizando productos existentes en Shopify..."):
                            result_df = apply_full_product_updates(shopify_config, matrixify_df)
                        st.session_state["complete_apply_result_df"] = result_df
                        st.dataframe(result_df, use_container_width=True)
                    result_df = st.session_state.get("complete_apply_result_df")
                    if result_df is not None:
                        st.download_button(
                            "Descargar reporte de sincronizacion",
                            data=dataframe_to_excel_bytes({"Resultado": result_df}),
                            file_name=f"resultado_carga_completa_{brand_config['site_key']}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )
            st.markdown("</div>", unsafe_allow_html=True)
        except Exception as exc:
            st.error("No pude procesar los archivos.")
            st.exception(exc)
    else:
        st.info("Carga el input comercial para comenzar. Si no usas Shopify API, tambien sube el respaldo Excel del sitio.")

    st.markdown(
        """
        <div class="benefits-wrap">
        <div class="benefits">
            <div class="benefit"><b>Actualiza con IDs</b><p>Usa Shopify API como referencia operativa para conservar IDs de producto y variante.</p></div>
            <div class="benefit"><b>Variantes por talla</b><p>Lee ARTI y genera SKUs, barcodes, precios y tallas ordenadas.</p></div>
            <div class="benefit"><b>Estructura controlada</b><p>Entrega siempre las hojas y columnas necesarias para carga Matrixify.</p></div>
        </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
