import io
import base64
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
import streamlit as st

from generate_columbia_matrixify import build_columbia_matrixify, read_arti_source


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


def read_arti_for_app():
    arti_df, source = read_arti_source()
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


def columbia_to_excel_bytes(matrixify_df, summary_df, issues_df, type_warnings_df=None, skipped_df=None):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        matrixify_df.to_excel(writer, index=False, sheet_name="Products")
        summary_df.to_excel(writer, index=False, sheet_name="Resumen")
        issues_df.to_excel(writer, index=False, sheet_name="Revision")
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


def inject_styles():
    st.markdown(
        """
        <style>
        .block-container {
            max-width: 1120px;
            padding-top: 26px;
            padding-bottom: 36px;
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
            margin: 26px 0 22px;
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
            min-height: 150px;
            border: 1px solid #d7e6fb;
            border-radius: 8px;
            background: linear-gradient(135deg, #f7fbff 0%, #eef6ff 100%);
            display: flex;
            align-items: center;
            justify-content: center;
            margin-top: 20px;
            padding: 18px;
            box-shadow: 0 18px 45px rgba(20, 80, 160, 0.12);
        }
        .matrix-card img {
            max-height: 108px;
            max-width: 190px;
            object-fit: contain;
        }
        .brand-img {
            max-width: 190px;
            max-height: 72px;
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
            .benefits {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header():
    def image_data_uri(path):
        if not path.exists():
            return ""
        suffix = path.suffix.lower().replace(".", "")
        mime = "jpeg" if suffix in ("jpg", "jpeg") else "png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:image/{mime};base64,{encoded}"

    forus_src = image_data_uri(FORUS_LOGO_PATH)
    shopify_src = image_data_uri(SHOPIFY_LOGO_PATH)

    if FORUS_LOGO_PATH.exists():
        st.markdown(f'<img class="brand-img" src="{forus_src}" alt="Forus">', unsafe_allow_html=True)
    else:
        st.markdown(
            """
            <div class="forus-logo">FORUS</div>
            <div class="forus-tagline">CONSUMER FANATIC</div>
            """,
            unsafe_allow_html=True,
        )

    shopify_html = (
        f'<div class="matrix-card"><img src="{shopify_src}" alt="Shopify"></div>'
        if shopify_src
        else '<div class="matrix-card"><div class="matrix-icon"></div></div>'
    )
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-copy">
                <h1>Matrixify Columbia - Shopify</h1>
                <p>Sube el input comercial y descarga el Excel listo para crear o actualizar productos en Shopify.</p>
            </div>
            {shopify_html}
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div class="info-box">
            <b>Input esperado:</b><br>
            Archivo Excel con hoja Input, una fila por producto-color y columnas oficiales de Comercial.
        </div>
        """,
        unsafe_allow_html=True,
    )


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="XL", layout="wide")
    inject_styles()
    render_header()

    st.markdown('<div class="section-card"><h2>Cargar input</h2>', unsafe_allow_html=True)
    input_file = st.file_uploader("Subir Excel de Comercial", type=["xlsx", "xls"], key="input")
    st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("Configuracion avanzada", expanded=False):
        st.write("Solo usa esto si quieres probar con otra plantilla o con otro ARTI.")
        template_file = st.file_uploader(
            "Matrixify modelo opcional",
            type=["xlsx", "xls"],
            key="template",
            help=f"Si no subes nada, se usa {DEFAULT_MATRIXIFY_PATH}.",
        )
        arti_file = st.file_uploader(
            "ARTI opcional",
            type=["xlsx", "xls"],
            key="arti",
            help=f"Si no subes nada, se usa {DEFAULT_ARTI_PATH}.",
        )

    setup_rows = [
        {
            "Base": "Matrixify modelo",
            "Ruta": DEFAULT_MATRIXIFY_PATH,
            "Estado": "OK" if Path(DEFAULT_MATRIXIFY_PATH).exists() else "Falta",
        },
        {
            "Base": "ARTI",
            "Ruta": f"{DEFAULT_ARTI_ZIP_PATH} / {DEFAULT_ARTI_CSV_PATH} / {DEFAULT_ARTI_PATH}",
            "Estado": "OK ZIP"
            if Path(DEFAULT_ARTI_ZIP_PATH).exists()
            else ("OK CSV" if Path(DEFAULT_ARTI_CSV_PATH).exists() else ("OK XLSX" if Path(DEFAULT_ARTI_PATH).exists() else "Falta")),
        },
        {
            "Base": "Tipos Shopify",
            "Ruta": "data/tipos_shopify.xlsx",
            "Estado": "OK" if Path("data/tipos_shopify.xlsx").exists() else "Opcional",
        },
    ]
    with st.expander("Estado de bases", expanded=False):
        st.dataframe(pd.DataFrame(setup_rows), use_container_width=True, hide_index=True)

    if input_file:
        try:
            if template_file:
                template_df = pd.read_excel(template_file, sheet_name="Products", dtype=object)
                template_source = "archivo cargado en pantalla"
            else:
                if not Path(DEFAULT_MATRIXIFY_PATH).exists():
                    st.error(f"Falta la plantilla fija: {DEFAULT_MATRIXIFY_PATH}")
                    st.stop()
                template_df = pd.read_excel(DEFAULT_MATRIXIFY_PATH, sheet_name="Products", dtype=object)
                template_source = DEFAULT_MATRIXIFY_PATH

            input_df = read_excel(input_file)
            if arti_file:
                arti_df = read_excel(arti_file)
                arti_source = "archivo cargado en pantalla"
            else:
                try:
                    arti_df, arti_source = read_arti_for_app()
                except FileNotFoundError:
                    st.error(f"Falta el ARTI fijo: {DEFAULT_ARTI_ZIP_PATH}, {DEFAULT_ARTI_CSV_PATH} o {DEFAULT_ARTI_PATH}")
                    st.stop()

            st.markdown('<div class="section-card"><h2>Archivos cargados</h2>', unsafe_allow_html=True)
            st.caption(f"Matrixify modelo usado: {template_source}")
            st.caption(f"Arti usado: {arti_source}")
            col1, col2 = st.columns([2, 1])
            col1.write("Input productos")
            col1.dataframe(input_df.head(20), use_container_width=True)
            col2.write("Resumen bases")
            col2.metric("Columnas Matrixify", len(template_df.columns))
            col2.metric("Filas ARTI", len(arti_df))
            col2.metric("Productos input", len(input_df))
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown('<div class="section-card"><h2>Procesar y generar Excel</h2>', unsafe_allow_html=True)
            st.write("Convierte el input en una salida Matrixify con Products, Resumen, Revision, Tipos nuevos y Omitidos sin cambios.")
            if st.button("Generar Matrixify Columbia", type="primary"):
                matrixify_df, summary_df, issues_df, type_warnings_df, skipped_df = build_columbia_matrixify(
                    input_df, arti_df, template_df
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

                    excel_bytes = columbia_to_excel_bytes(
                        matrixify_df, summary_df, issues_df, type_warnings_df, skipped_df
                    )
                    st.download_button(
                        "Descargar Excel Matrixify",
                        data=excel_bytes,
                        file_name="matrixify_columbia_generado.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
            st.markdown("</div>", unsafe_allow_html=True)
        except Exception as exc:
            st.error("No pude procesar los archivos.")
            st.exception(exc)
    else:
        st.info("Carga el input de Comercial para comenzar el proceso.")

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
