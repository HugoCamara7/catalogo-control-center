import io
import base64
import json
import re
from collections import defaultdict
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


APP_TITLE = "Conversor Matrixify por Tallas"
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


def _product_lookup_from_shopify(records):
    by_key = {}
    by_handle = {}
    for record in records:
        key = clean_value(record.get("Mod-Col")).upper()
        handle = clean_value(record.get("Handle"))
        if key and key not in by_key:
            by_key[key] = record
        if handle and handle not in by_handle:
            by_handle[handle] = record
    return by_key, by_handle


def _source_key_for_update(row):
    for column in ("Mod-Col", "COD MOD COL", "Metafield: custom.codigo_modelo_color [id]"):
        value = clean_value(row.get(column))
        if value:
            return value.upper()
    return ""


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
        for _, product in products_df.iterrows():
            new_value = siblings_by_model.get(product["__MODEL"], "")
            current = clean_value(product.get("Siblings"))
            if not new_value or current == new_value:
                continue
            rows.append(
                {
                    "Accion": "Actualizar",
                    "Sitio": brand_config["site_label"],
                    "Operacion": "siblings",
                    "Mod-Col": product.get("Mod-Col"),
                    "Product ID": product.get("Product ID"),
                    "Handle": product.get("Handle"),
                    "Campo": "Metafield: theme.siblings",
                    "Valor actual": current,
                    "Valor nuevo": new_value,
                    "Estado": "OK",
                    "Observacion": f"{len(_split_tags(new_value))} handles del mismo modelo",
                }
            )
        return pd.DataFrame(rows), pd.DataFrame(issues), pd.DataFrame()

    source_df = update_input_df.dropna(how="all").copy() if update_input_df is not None else pd.DataFrame()
    if operation == "photos" and source_df.empty:
        source_df = pd.DataFrame(shopify_products)

    matrixify_rows = []
    for input_index, row in source_df.iterrows():
        key = _source_key_for_update(row)
        handle = clean_value(row.get("Handle"))
        product = by_key.get(key) or by_handle.get(handle)
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
                    "Accion": "Generar Matrixify",
                    "Sitio": brand_config["site_label"],
                    "Operacion": "photos",
                    "Mod-Col": product_key,
                    "Product ID": product_id,
                    "Handle": product.get("Handle"),
                    "Campo": "Fotos",
                    "Valor actual": current_images,
                    "Valor nuevo": urls_text,
                    "Estado": "OK",
                    "Observacion": "Vista previa API. Aplicacion directa de media queda desactivada por seguridad.",
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
            elif operation == "siblings":
                metafields_set(
                    shopify_config,
                    [
                        {
                            "ownerId": product_id,
                            "namespace": "theme",
                            "key": "siblings",
                            "type": "single_line_text_field",
                            "value": clean_value(row.get("Valor nuevo")),
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
    ]
    try:
        if Path(DEFAULT_MATRIXIFY_PATH).exists():
            default_columns = list(pd.read_excel(DEFAULT_MATRIXIFY_PATH, sheet_name="Products", nrows=0).columns)
    except Exception:
        pass

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
                }
            )
            rows.append(row)
    return pd.DataFrame(rows, columns=default_columns)


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
    if key_column not in df.columns or siblings_column not in df.columns:
        return df

    def sibling_value(row):
        key = clean_value(row.get(key_column)).upper()
        if not key:
            return row.get(siblings_column)
        model = key.rsplit("-", 1)[0]
        return siblings_map.get(model, row.get(siblings_column))

    top_rows = df["Handle"].map(clean_value) != ""
    df.loc[top_rows, siblings_column] = df.loc[top_rows].apply(sibling_value, axis=1)
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
    url = clean_value(value)
    prefix = "https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/"
    if url.startswith(prefix):
        return "https://s3.amazonaws.com/ecom-imagenes.forus-digital.xyz.peru/" + url[len(prefix):]
    return url


def _image_url_candidates(value):
    original = clean_value(value)
    converted = _shopify_image_url(original)
    return list(dict.fromkeys([url for url in (converted, original) if url]))


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


def _variant_bulk_input_from_row(row):
    size = clean_value(row.get("Option1 Value"))
    if not size:
        return None

    option_name = clean_value(row.get("Option1 Name")) or "Talla"
    variant = {
        "optionValues": [
            {
                "optionName": option_name,
                "name": size,
            }
        ]
    }
    price = clean_value(row.get("Variant Price"))
    compare_at_price = clean_value(row.get("Variant Compare At Price"))
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


def _missing_variant_inputs(product_variant_rows):
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
        payload = _variant_bulk_input_from_row(variant_row)
        if payload:
            variants.append(payload)
            seen_keys.add(dedupe_key)
    return variants


def _all_variant_inputs(product_variant_rows):
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
        payload = _variant_bulk_input_from_row(variant_row)
        if payload:
            variants.append(payload)
            seen_keys.add(dedupe_key)
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

    messages = []
    if values_in_order:
        option_payloads = []
        for option in options:
            payload = {"id": option.get("id"), "name": option.get("name")}
            if clean_value(option.get("id")) == clean_value(size_option.get("id")):
                payload["values"] = [{"name": value} for value in values_in_order]
            option_payloads.append(payload)
        product_options_reorder(shopify_config, product_gid, option_payloads)
        messages.append("orden de tallas actualizado")

    variant_by_size = {}
    for variant in variants:
        size = _selected_option_value(variant, option_name)
        if size and size not in variant_by_size:
            variant_by_size[size] = variant.get("id")
    variant_order = [size for size in ordered_sizes if size in variant_by_size]
    variant_order.extend(size for size in variant_by_size if size not in variant_order)
    positions = [
        {"id": variant_by_size[size], "position": position}
        for position, size in enumerate(variant_order, start=1)
        if clean_value(variant_by_size.get(size))
    ]
    if positions:
        product_variants_bulk_reorder(shopify_config, product_gid, positions)
        messages.append("orden de variantes actualizado")
    return ", ".join(messages)


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

            missing_variants = (
                _missing_variant_inputs(product_variant_rows)
                if clean_value(row.get("ID"))
                else _all_variant_inputs(product_variant_rows)
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


def inject_styles():
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1120px;
            padding-top: 42px;
            padding-bottom: 36px;
        }
        .brand-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 24px;
            margin-bottom: 42px;
        }
        .brand-row .brand-img {
            max-width: 205px;
            max-height: 82px;
            object-fit: contain;
            object-position: left center;
            display: block;
        }
        .brand-row .shopify-img {
            max-width: 96px;
            max-height: 96px;
            object-fit: contain;
            object-position: right center;
            display: block;
        }
        .forus-logo {
            font-size: 46px;
            line-height: 0.92;
            font-weight: 900;
            color: #123a8c;
            letter-spacing: 0;
        }
        .forus-tagline {
            color: #123a8c;
            font-size: 13px;
            letter-spacing: 5px;
            font-weight: 800;
            margin-top: 4px;
        }
        .hero-copy {
            margin: 0 0 22px;
        }
        .hero-copy h1 {
            color: #001f4f;
            font-size: 32px;
            margin: 0 0 18px;
            letter-spacing: 0;
        }
        .hero-copy p {
            color: #4d6383;
            margin: 0;
            font-size: 15px;
        }
        .matrix-card {
            min-height: 0;
            border: 0;
            border-radius: 0;
            background: transparent;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            margin-top: 0;
            padding: 0;
            box-shadow: none;
        }
        .matrix-card img {
            max-height: 108px;
            max-width: 190px;
            object-fit: contain;
        }
        .brand-img {
            max-width: 205px;
            max-height: 82px;
            object-fit: contain;
            object-position: left center;
            display: block;
        }
        .matrix-icon {
            position: relative;
            width: 120px;
            height: 84px;
            border-radius: 8px;
            background: white;
            box-shadow: 0 12px 26px rgba(0, 60, 140, 0.14);
        }
        .matrix-icon:before {
            content: "SHOPIFY";
            position: absolute;
            left: -24px;
            top: 34px;
            background: #00a047;
            color: white;
            font-weight: 800;
            border-radius: 5px;
            padding: 7px 10px;
            font-size: 13px;
            box-shadow: 0 8px 16px rgba(0, 100, 50, 0.25);
        }
        .matrix-icon:after {
            content: "M";
            position: absolute;
            right: -20px;
            top: 18px;
            width: 70px;
            height: 54px;
            border-radius: 18px;
            background: #1465f4;
            color: white;
            font-weight: 900;
            font-size: 34px;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .info-box {
            border: 1px solid #cfe2ff;
            background: #f2f8ff;
            border-radius: 8px;
            padding: 18px 22px;
            color: #002b66;
            margin: 14px 0 22px;
        }
        .section-card {
            border: 1px solid #d9e6f7;
            border-radius: 8px;
            padding: 22px;
            margin: 18px 0;
            background: white;
            box-shadow: 0 14px 34px rgba(20, 60, 120, 0.06);
        }
        .section-card h2 {
            color: #001f4f;
            font-size: 23px;
            margin: 0 0 14px;
            letter-spacing: 0;
        }
        .benefits {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 18px;
            margin-top: 26px;
        }
        .benefit {
            border: 1px solid #d9e6f7;
            border-radius: 8px;
            padding: 18px;
            background: white;
        }
        .benefit b {
            color: #001f4f;
        }
        .benefit p {
            color: #4d6383;
            margin: 10px 0 0;
            font-size: 14px;
        }
        div[data-testid="stFileUploader"] {
            border: 1px dashed #9cc3ff;
            border-radius: 8px;
            padding: 18px;
            background: #fbfdff;
        }
        .stButton button, .stDownloadButton button {
            border-radius: 8px;
            font-weight: 700;
        }
        @media (max-width: 760px) {
            .brand-row {
                align-items: flex-start;
                margin-bottom: 28px;
            }
            .brand-row .brand-img {
                max-width: 165px;
            }
            .brand-row .shopify-img {
                max-width: 72px;
            }
            .benefits {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(brand_config=None):
    brand_config = brand_config or get_brand_config()
    def image_data_uri(path):
        if not path.exists():
            return ""
        suffix = path.suffix.lower().replace(".", "")
        mime = "jpeg" if suffix in ("jpg", "jpeg") else "png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/{mime};base64,{encoded}"

    forus_src = image_data_uri(FORUS_LOGO_PATH)
    shopify_src = image_data_uri(SHOPIFY_LOGO_PATH)

    forus_html = (
        f'<img class="brand-img" src="{forus_src}" alt="Forus">'
        if forus_src
        else '<div><div class="forus-logo">FORUS</div><div class="forus-tagline">CONSUMER FANATIC</div></div>'
    )
    shopify_html = (
        f'<img class="shopify-img" src="{shopify_src}" alt="Shopify">'
        if shopify_src
        else '<div class="matrix-icon"></div>'
    )
    st.markdown(
        f"""
        <div class="brand-row">
            {forus_html}
            {shopify_html}
        </div>
        <div class="hero">
            <div class="hero-copy">
                <h1>Matrixify {brand_config['site_label']} - Shopify</h1>
                <p>Sube el input comercial y el ultimo catalogo Matrixify del sitio para conservar IDs y evitar duplicados.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="info-box">
            <b>Flujo obligatorio:</b><br>
            Elige el sitio destino, sube el input comercial y sube el ultimo catalogo Matrixify del mismo sitio.
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="XL", layout="wide")
    inject_styles()
    bigquery_config = get_bigquery_config()
    bigquery_ready = is_bigquery_configured(bigquery_config)

    site_options = {config["site_label"]: key for key, config in SITE_CONFIGS.items()}
    selected_site_label = st.sidebar.selectbox("Sitio destino", list(site_options), index=0)
    selected_site_key = site_options[selected_site_label]
    brand_config = get_brand_config(selected_site_key)
    shopify_config = get_shopify_config(selected_site_key)
    st.sidebar.markdown("**Marcas permitidas**")
    st.sidebar.write(", ".join(brand_config["allowed_arti_brands"]))
    st.sidebar.caption(f"Vendor: {brand_config['vendor']} | Salida: {brand_config['output_filename']}")
    operation_mode = st.sidebar.radio(
        "Tipo de operacion",
        ["Carga completa", "Actualizacion puntual"],
        index=0,
    )

    with st.sidebar.expander("Shopify API", expanded=False):
        if is_shopify_configured(shopify_config):
            st.success(f"Configurado: {shopify_config['shop_domain']}")
            st.caption(f"Version Admin API: {shopify_config['api_version']}")
            if shopify_config.get("admin_access_token"):
                st.caption("Token: configurado en Secrets")
            else:
                st.caption("Token: se obtendra con client_id/client_secret")
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

    render_header(brand_config)

    if operation_mode == "Actualizacion puntual":
        operation_labels = {
            "Tags": "tags",
            "Fotos 10 vistas": "photos",
            "Siblings": "siblings",
            "Titulo": "title",
            "Body HTML / Material / Cuidado": "body",
        }
        st.markdown('<div class="section-card"><h2>Actualizacion puntual</h2>', unsafe_allow_html=True)
        update_label = st.selectbox("Que quieres actualizar", list(operation_labels), index=0)
        update_operation = operation_labels[update_label]
        update_source = st.radio(
            "Fuente de datos actuales",
            ["Shopify API", "Catalogo Matrixify"],
            index=0 if is_shopify_configured(shopify_config) else 1,
            help="Shopify API evita subir el ultimo catalogo. Catalogo Matrixify queda como respaldo.",
        )
        template_file = None
        if update_source == "Catalogo Matrixify":
            template_file = st.file_uploader(
                f"1. Subir ultimo catalogo Matrixify de {brand_config['site_label']}",
                type=["xlsx", "xls"],
                key="template_update",
                help="Se usa para encontrar ID, Handle, tags actuales, fotos actuales y codigo modelo color.",
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
            only_missing_images = st.checkbox("Solo productos sin foto en el catalogo", value=True)
            update_file = st.file_uploader("2. Opcional: subir lista con Mod-Col a corregir", type=["xlsx", "xls"], key="update_photos")
            st.caption("Si no subes lista, revisa el catalogo completo. Siempre genera 10 URLs por producto.")
        elif update_operation == "siblings":
            st.caption("Recalcula siblings para todo el catalogo: todos los productos con el mismo codigo modelo quedan separados por comas.")
        elif update_operation == "title":
            update_file = st.file_uploader("2. Subir archivo con Mod-Col y Title", type=["xlsx", "xls"], key="update_title")
        elif update_operation == "body":
            body_source = st.radio(
                "Origen para corregir Body HTML",
                ["Desde input comercial", "Detectar desde catalogo Matrixify"],
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

                if st.button(f"Analizar actualizacion: {update_label}", type="primary"):
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

                    can_apply = update_operation in ("tags", "title", "body", "siblings") and preview_df is not None and not preview_df.empty
                    if update_operation == "photos":
                        st.info("Para actualizacion puntual de fotos, descarga la estructura Matrixify y revisa las URLs antes de importar.")
                    elif can_apply:
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
                st.error("No pude generar o aplicar la actualizacion con Shopify API.")
                st.exception(exc)
        elif update_source == "Catalogo Matrixify" and template_file and update_ready:
            try:
                template_df = pd.read_excel(template_file, sheet_name="Products", dtype=object)
                if "Vendor" in template_df.columns:
                    catalog_vendors = {
                        clean_value(value).lower()
                        for value in template_df["Vendor"].dropna()
                        if clean_value(value)
                    }
                    if catalog_vendors and brand_config["vendor"].lower() not in catalog_vendors:
                        st.error(
                            f"El catalogo Matrixify cargado no parece ser de {brand_config['site_label']}. "
                            f"Vendor esperado: {brand_config['vendor']}. Vendors encontrados: {', '.join(sorted(catalog_vendors))}."
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

                if st.button(f"Analizar actualizacion: {update_label}", type="primary"):
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
                        st.warning("No se genero ninguna fila de actualizacion. Revisa la hoja Revision.")
                    else:
                        st.success(f"Actualizacion generada con {len(matrixify_df):,} productos.")
                        st.dataframe(matrixify_df.head(100), use_container_width=True)
                    if issues_df is not None and not issues_df.empty:
                        st.warning(f"Hay {len(issues_df):,} observaciones.")
                        st.dataframe(issues_df, use_container_width=True)
                    excel_bytes = update_to_excel_bytes(matrixify_df, issues_df)
                    st.download_button(
                        "Descargar estructura Matrixify",
                        data=excel_bytes,
                        file_name=f"actualizacion_{update_operation}_{brand_config['site_key']}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            except Exception as exc:
                st.error("No pude generar la actualizacion puntual.")
                st.exception(exc)
        else:
            st.info("Sube los archivos requeridos para generar la actualizacion puntual.")
        return

    st.markdown('<div class="section-card"><h2>Cargar archivos obligatorios</h2>', unsafe_allow_html=True)
    complete_source = st.radio(
        "Fuente de datos actuales",
        ["Shopify API", "Catalogo Matrixify"],
        index=0 if is_shopify_configured(shopify_config) else 1,
        help="Shopify API evita subir el ultimo catalogo Matrixify.",
    )
    input_file = st.file_uploader("1. Subir input comercial", type=["xlsx", "xls"], key="input")
    template_file = None
    if complete_source == "Catalogo Matrixify":
        template_file = st.file_uploader(
            f"2. Subir ultimo catalogo Matrixify de {brand_config['site_label']}",
            type=["xlsx", "xls"],
            key="template",
            help="Este archivo conserva Product ID y Variant ID cuando no usas Shopify API.",
        )
    st.markdown("</div>", unsafe_allow_html=True)

    setup_rows = [
        {
            "Base": "Datos actuales Shopify",
            "Ruta": "Shopify API" if complete_source == "Shopify API" else f"Subir ultimo catalogo de {brand_config['site_label']}",
            "Estado": "OK API" if complete_source == "Shopify API" and is_shopify_configured(shopify_config) else ("Obligatorio" if complete_source == "Catalogo Matrixify" else "Falta API"),
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
    with st.expander("Estado de bases", expanded=False):
        st.dataframe(pd.DataFrame(setup_rows), use_container_width=True, hide_index=True)

    can_process_complete = input_file and (complete_source == "Shopify API" or template_file)
    if can_process_complete:
        try:
            if complete_source == "Shopify API":
                if not is_shopify_configured(shopify_config):
                    st.error("Este sitio no tiene Shopify API configurada en Secrets.")
                    st.stop()
                with st.spinner("Leyendo productos y variantes actuales desde Shopify..."):
                    shopify_products = fetch_products(shopify_config)
                st.session_state["complete_shopify_products"] = shopify_products
                template_df = shopify_products_to_matrixify_df(shopify_products)
                template_source = f"Shopify API ({len(shopify_products):,} productos)"
            else:
                template_df = pd.read_excel(template_file, sheet_name="Products", dtype=object)
                template_source = f"catalogo Matrixify cargado para {brand_config['site_label']}"
                if "Vendor" in template_df.columns:
                    catalog_vendors = {
                        clean_value(value).lower()
                        for value in template_df["Vendor"].dropna()
                        if clean_value(value)
                    }
                    if catalog_vendors and brand_config["vendor"].lower() not in catalog_vendors:
                        st.error(
                            f"El catalogo Matrixify cargado no parece ser de {brand_config['site_label']}. "
                            f"Vendor esperado: {brand_config['vendor']}. Vendors encontrados: {', '.join(sorted(catalog_vendors))}."
                        )
                        st.stop()

            input_df = read_excel(input_file)
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

            st.markdown('<div class="section-card"><h2>Archivos cargados</h2>', unsafe_allow_html=True)
            st.caption(f"Datos actuales usados: {template_source}")
            st.caption(f"Arti usado: {arti_source}")
            st.caption(
                f"Marcas detectadas: {', '.join(detected_brands) if detected_brands else 'No se encontro columna de marca en el input'}"
            )
            col1, col2 = st.columns([2, 1])
            col1.write("Input productos")
            col1.dataframe(input_df.head(20), use_container_width=True)
            col2.write("Resumen bases")
            col2.metric("Columnas base", len(template_df.columns))
            col2.metric("Filas ARTI", len(arti_df))
            col2.metric("Productos input", len(input_df))
            col2.metric("Marcas detectadas", len(detected_brands))
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown('<div class="section-card"><h2>Analizar y preparar carga</h2>', unsafe_allow_html=True)
            st.write(f"Analiza el input para {brand_config['site_label']}, arma la estructura Matrixify y agrega la hoja Carga Sial.")
            if st.button("Analizar input", type="primary"):
                matrixify_df, summary_df, issues_df, type_warnings_df, skipped_df, sial_df = build_columbia_matrixify(
                    input_df, arti_df, template_df, brand_config=brand_config
                )
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

                if matrixify_df.empty:
                    st.error("No se pudo generar ninguna fila Matrixify. Revisa la hoja Revision.")
                else:
                    st.success(f"Vista previa generada con {len(matrixify_df):,} variantes.")
                    st.dataframe(summary_df, use_container_width=True)
                    st.dataframe(matrixify_df.head(100), use_container_width=True)

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
                    st.dataframe(sial_df.head(100), use_container_width=True)

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
        st.info("Carga el input comercial para comenzar. Si usas Catalogo Matrixify, tambien sube el ultimo catalogo del sitio.")

    st.markdown(
        """
        <div class="benefits">
            <div class="benefit"><b>Actualiza con IDs</b><p>Usa la ultima descarga Matrixify para conservar IDs de producto y variante.</p></div>
            <div class="benefit"><b>Variantes por talla</b><p>Lee ARTI y genera SKUs, barcodes, precios y tallas ordenadas.</p></div>
            <div class="benefit"><b>Estructura controlada</b><p>Entrega siempre las hojas y columnas necesarias para carga Matrixify.</p></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
