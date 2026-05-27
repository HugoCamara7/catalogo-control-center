import io
import base64
import json
import re
from collections import defaultdict
from pathlib import Path

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
    st.sidebar.markdown("**Marcas permitidas**")
    st.sidebar.write(", ".join(brand_config["allowed_arti_brands"]))
    st.sidebar.caption(f"Vendor: {brand_config['vendor']} | Salida: {brand_config['output_filename']}")
    operation_mode = st.sidebar.radio(
        "Tipo de operacion",
        ["Carga completa", "Actualizacion puntual"],
        index=0,
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
        template_file = st.file_uploader(
            f"1. Subir ultimo catalogo Matrixify de {brand_config['site_label']}",
            type=["xlsx", "xls"],
            key="template_update",
            help="Se usa para encontrar ID, Handle, tags actuales, fotos actuales y codigo modelo color.",
        )

        needs_input = update_operation in ("tags", "title") or (
            update_operation == "body" and st.session_state.get("body_source", "Desde input comercial") == "Desde input comercial"
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

        if template_file and (update_file or update_operation in ("photos", "siblings") or body_mode == "fix_catalog"):
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

                if st.button(f"Generar actualizacion {update_label}", type="primary"):
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
                        "Descargar actualizacion Matrixify",
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
    input_file = st.file_uploader("1. Subir input comercial", type=["xlsx", "xls"], key="input")
    template_file = st.file_uploader(
        f"2. Subir ultimo catalogo Matrixify de {brand_config['site_label']}",
        type=["xlsx", "xls"],
        key="template",
        help="Este archivo es obligatorio para conservar Product ID y Variant ID, y evitar duplicados.",
    )
    st.markdown("</div>", unsafe_allow_html=True)

    setup_rows = [
        {
            "Base": "Catalogo Matrixify del sitio",
            "Ruta": f"Subir ultimo catalogo de {brand_config['site_label']}",
            "Estado": "Obligatorio",
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

    if input_file and template_file:
        try:
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
            st.caption(f"Matrixify modelo usado: {template_source}")
            st.caption(f"Arti usado: {arti_source}")
            st.caption(
                f"Marcas detectadas: {', '.join(detected_brands) if detected_brands else 'No se encontro columna de marca en el input'}"
            )
            col1, col2 = st.columns([2, 1])
            col1.write("Input productos")
            col1.dataframe(input_df.head(20), use_container_width=True)
            col2.write("Resumen bases")
            col2.metric("Columnas Matrixify", len(template_df.columns))
            col2.metric("Filas ARTI", len(arti_df))
            col2.metric("Productos input", len(input_df))
            col2.metric("Marcas detectadas", len(detected_brands))
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown('<div class="section-card"><h2>Procesar y generar Excel</h2>', unsafe_allow_html=True)
            st.write(f"Convierte el input en una salida Matrixify para {brand_config['site_label']} y agrega una hoja Carga Sial.")
            if st.button(f"Generar Matrixify {brand_config['site_label']}", type="primary"):
                matrixify_df, summary_df, issues_df, type_warnings_df, skipped_df, sial_df = build_columbia_matrixify(
                    input_df, arti_df, template_df, brand_config=brand_config
                )

                if matrixify_df.empty:
                    st.error("No se pudo generar ninguna fila Matrixify. Revisa la hoja Revision.")
                else:
                    st.success(f"Archivo generado con {len(matrixify_df):,} variantes.")
                    st.dataframe(summary_df, use_container_width=True)
                    st.dataframe(matrixify_df.head(100), use_container_width=True)

                    if not issues_df.empty:
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
                        "Descargar Excel Matrixify",
                        data=excel_bytes,
                        file_name=brand_config["output_filename"],
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            st.markdown("</div>", unsafe_allow_html=True)
        except Exception as exc:
            st.error("No pude procesar los archivos.")
            st.exception(exc)
    else:
        st.info("Carga el input comercial y el ultimo catalogo Matrixify del sitio seleccionado para comenzar.")

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
