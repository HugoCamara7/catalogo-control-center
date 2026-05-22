import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd


TEMPLATE_PATH = Path(r"C:\Users\hcamara\Downloads\Export_2026-05-21_113908.xlsx")
INPUT_PATH = Path(r"C:\Users\hcamara\Documents\Version Input prueba.xlsx")
ARTI_PATH = Path(r"C:\Users\hcamara\Documents\ARTI ACTUALIZADO 10-05-2026.xlsx")
DEFAULT_ARTI_CSV_PATH = Path("data/arti.csv")
DEFAULT_ARTI_ZIP_PATH = Path("data/arti.zip")
DEFAULT_ARTI_XLSX_PATH = Path("data/arti.xlsx")
OUTPUT_DIR = Path("outputs")
OUTPUT_PATH = OUTPUT_DIR / "matrixify_columbia_generado.xlsx"
KNOWN_TYPES_PATH = Path("data/tipos_shopify.xlsx")

INVENTORY_PREFIX = "Inventory Available:"
IMAGE_BASE_URL = "https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com/COLUMBIA%20SHOPIFY"
IMAGE_VALIDATION_BASE_URL = "https://s3.amazonaws.com/ecom-imagenes.forus-digital.xyz.peru/COLUMBIA%20SHOPIFY"
MAX_IMAGES_PER_PRODUCT = 10
VALIDATE_IMAGES = False


def clean(value):
    if value is None or pd.isna(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def compare_clean(value):
    text = clean(value)
    if text.lower() in ("nan", "none", "nat"):
        return ""
    if text.upper() in ("TRUE", "FALSE"):
        return text.upper()
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    return re.sub(r"\s+", " ", text).strip()


def normalize_text(value):
    text = clean(value).lower()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "™": "",
        "®": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-")


def normalize_handle(handle, mod_col):
    base = normalize_text(handle)
    code = normalize_text(mod_col)
    if not base:
        return code
    if code and code not in base:
        return f"{base}-{code}"
    return base


def model_code(mod_col):
    text = clean(mod_col).upper()
    if "-" not in text:
        return text
    return text.rsplit("-", 1)[0]


def split_model_color(mod_col):
    text = clean(mod_col).upper()
    if "-" not in text:
        return text, ""
    return tuple(text.rsplit("-", 1))


def image_candidates(mod_col):
    model, color = split_model_color(mod_col)
    if not model or not color:
        return []
    image_key = f"{model}_{color}"
    return [f"{IMAGE_BASE_URL}/{image_key}_{position}.jpg" for position in range(1, MAX_IMAGES_PER_PRODUCT + 1)]


def validation_url(url):
    return url.replace(IMAGE_BASE_URL, IMAGE_VALIDATION_BASE_URL)


def url_is_image(url, timeout=4):
    request = Request(validation_url(url), method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.status < 400 and content_type.lower().startswith("image/")
    except HTTPError as exc:
        if exc.code in (403, 405):
            try:
                request = Request(
                    validation_url(url),
                    method="GET",
                    headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-32"},
                )
                with urlopen(request, timeout=timeout) as response:
                    content_type = response.headers.get("Content-Type", "")
                    return response.status < 400 and content_type.lower().startswith("image/")
            except (HTTPError, URLError, TimeoutError, OSError):
                return False
        return False
    except (URLError, TimeoutError, OSError):
        return False


def build_image_lookup(mod_cols, validate=VALIDATE_IMAGES):
    lookup = {}
    for mod_col in sorted({clean(value).upper() for value in mod_cols if clean(value)}):
        urls = image_candidates(mod_col)
        if not validate:
            lookup[mod_col] = list(dict.fromkeys(urls))
            continue

        valid_urls = []
        misses_after_found = 0
        for url in urls:
            if url_is_image(url, timeout=2):
                valid_urls.append(url)
                misses_after_found = 0
            elif valid_urls:
                misses_after_found += 1
                if misses_after_found >= 2:
                    break
        lookup[mod_col] = list(dict.fromkeys(valid_urls))
    return lookup


def normalize_size(value):
    if value is None or pd.isna(value):
        return ""

    if isinstance(value, (pd.Timestamp, datetime)):
        return f"{value.day}/{value.month}"

    text = clean(value).upper()
    if not text:
        return ""

    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]

    if re.fullmatch(r"\d+", text):
        number = int(text)
        if 50 <= number <= 130 and number % 5 == 0:
            converted = number / 10
            return str(int(converted)) if converted.is_integer() else str(converted)
        return text

    aliases = {
        "OS": "O/S",
        "UNICA": "O/S",
        "ÚNICA": "O/S",
        "TALLA UNICA": "O/S",
        "LXL": "L/XL",
        "SM": "S/M",
        "ML": "M/L",
    }
    return aliases.get(text, text)


def size_sort_key(value):
    size = normalize_size(value)
    alpha_order = {
        "XXXS": 1,
        "XXS": 2,
        "XS": 3,
        "S": 4,
        "S/M": 5,
        "M": 6,
        "M/L": 7,
        "L": 8,
        "L/XL": 9,
        "XL": 10,
        "XXL": 11,
        "XXXL": 12,
        "O/S": 99,
    }
    if size in alpha_order:
        return (0, alpha_order[size], size)
    if re.fullmatch(r"\d+(\.\d+)?", size):
        return (1, float(size), size)
    match = re.fullmatch(r"(\d+(\.\d+)?)/(\d+(\.\d+)?)", size)
    if match:
        return (2, float(match.group(1)), float(match.group(3)), size)
    return (9, 9999, size)


def format_technology(value):
    text = clean(value)
    if not text:
        return ""
    items = [item.strip() for item in text.split(",") if item.strip()]
    return json.dumps(items, ensure_ascii=False)


def technology_logo_slug(value):
    text = clean(value).lower()
    compound_replacements = {
        "techlite": "tech-lite",
        "outdry": "out-dry",
        "omnimax": "omni-max",
        "omni max": "omni-max",
        "adapttrax": "adapt-trax",
        "adapt trax": "adapt-trax",
        "navicfit": "navic-fit",
        "navic fit": "navic-fit",
    }
    for old, new in compound_replacements.items():
        text = text.replace(old, new)
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "™": "",
        "®": "",
        "&": "and",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return f"logo.{text}-clb" if text else ""


def format_technology_logos(value):
    text = clean(value)
    if not text:
        return ""
    logos = []
    seen = set()
    for item in [part.strip() for part in text.split(",") if part.strip()]:
        logo = technology_logo_slug(item)
        if logo and logo not in seen:
            logos.append(logo)
            seen.add(logo)
    return ", ".join(logos)


def html_list(value):
    text = clean(value)
    if not text:
        return ""
    items = [item.strip() for item in re.split(r"[\n\r]+", text) if item.strip()]
    if not items:
        items = [text]
    return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"


def build_body_html(row):
    description = clean(row.get("Body HTML.1")) or clean(row.get("Body HTML"))
    features = clean(row.get("Caracteristicas"))
    material = clean(row.get("Material"))
    care = clean(row.get("Cuidado"))

    parts = []
    if description:
        parts.append(
            '<section class="nweb" data-titulo="Nombre Web" id="nombre-web-section">'
            "<h3>Descripción</h3>"
            f"<p>{description}</p>"
        )
    if features:
        parts.append(
            '<div class="nweb__Caracteristicas" data-titulo="Características">'
            '<h3 class="nweb__Caracteristicas-titulo">Características</h3>'
            f'{html_list(features)}'
            "</div>"
        )
    if material:
        parts.append(
            '<div class="nweb__Materiales" data-titulo="Materiales">'
            '<h3 class="nweb__Materiales-titulo">Materiales</h3>'
            f'{html_list(material)}'
            "</div>"
        )
    if care:
        parts.append(
            '<div class="nweb__Cuidados" data-titulo="Cuidados">'
            '<h3 class="nweb__Cuidados-titulo">Cuidados</h3>'
            f'{html_list(care)}'
            "</div>"
        )
    if description:
        parts.append("</section>")
    return "".join(parts) if parts else ""


def first_existing(df, candidates):
    normalized = {str(col).strip().lower(): col for col in df.columns}
    for candidate in candidates:
        found = normalized.get(candidate.lower())
        if found is not None:
            return found
    return None


def normalize_compare(value):
    return re.sub(r"\s+", " ", clean(value)).strip().upper()


def load_known_types(path=KNOWN_TYPES_PATH):
    if not path.exists():
        return set(), ""

    values = set()
    if path.suffix.lower() in (".txt", ".csv"):
        if path.suffix.lower() == ".txt":
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if normalize_compare(line):
                    values.add(normalize_compare(line))
        else:
            df = pd.read_csv(path, dtype=object)
            for column in df.columns:
                if any(word in str(column).lower() for word in ["tipo", "type", "familia", "prenda"]):
                    values.update(normalize_compare(value) for value in df[column].dropna())
            if not values and len(df.columns):
                values.update(normalize_compare(value) for value in df.iloc[:, 0].dropna())
        return {value for value in values if value}, str(path)

    xl = pd.ExcelFile(path)
    for sheet_name in xl.sheet_names:
        df = pd.read_excel(path, sheet_name=sheet_name, dtype=object)
        if df.empty:
            continue
        candidate_columns = [
            column
            for column in df.columns
            if any(word in str(column).lower() for word in ["tipo", "type", "familia", "prenda"])
        ]
        if not candidate_columns and len(df.columns):
            candidate_columns = [df.columns[0]]
        for column in candidate_columns:
            values.update(normalize_compare(value) for value in df[column].dropna())

    return {value for value in values if value}, str(path)


def build_new_type_warnings(input_df):
    known_types, source = load_known_types()
    if not known_types:
        return pd.DataFrame(
            [
                {
                    "Campo": "Configuracion",
                    "Valor": "",
                    "Productos": "",
                    "Ejemplos Mod-Col": "",
                    "Nota": "No se encontro data/tipos_shopify.xlsx. Si quieres control de tipos nuevos, pega ahi la lista actual de Shopify.",
                }
            ]
        )

    checks = [
        ("Type", "Type"),
        ("Metafield custom.tipo", "Metafield: custom.tipo [single_line_text_field]"),
    ]
    rows = []
    for label, column in checks:
        if column not in input_df.columns:
            continue
        work = input_df[["Mod-Col", column]].copy()
        work["__VALUE"] = work[column].map(clean)
        work["__KEY"] = work[column].map(normalize_compare)
        work = work[(work["__KEY"] != "") & (~work["__KEY"].isin(known_types))]
        for value, group in work.groupby("__VALUE", dropna=True):
            rows.append(
                {
                    "Campo": label,
                    "Valor": value,
                    "Productos": len(group),
                    "Ejemplos Mod-Col": ", ".join(group["Mod-Col"].map(clean).head(10)),
                    "Nota": f"No existe en {source}",
                }
            )

    return pd.DataFrame(rows, columns=["Campo", "Valor", "Productos", "Ejemplos Mod-Col", "Nota"])


def available_output_path(path):
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for number in range(2, 1000):
        candidate = path.with_name(f"{stem}_{number}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError("No pude encontrar un nombre de salida disponible.")


ARTI_REQUIRED_COLUMNS = [
    "CODINT_MA",
    "COD MOD COL",
    "Mod-Col",
    "TALNUM_MA",
    "MARCA_MA",
    "Precio",
    "CodBarras",
]


def _truthy(value):
    if isinstance(value, bool):
        return value
    return clean(value).lower() in ("1", "true", "yes", "si", "sí", "y")


def _bigquery_configured(config):
    if not config:
        return False
    if "enabled" in config and not _truthy(config.get("enabled")):
        return False
    table = clean(config.get("table"))
    has_full_table = table.count(".") == 2
    has_split_table = clean(config.get("project_id")) and clean(config.get("dataset")) and table
    return bool(clean(config.get("query")) or has_full_table or has_split_table)


def _bigquery_config_from_env():
    config = {
        "enabled": os.getenv("BIGQUERY_ENABLED", ""),
        "project_id": os.getenv("BIGQUERY_PROJECT_ID", ""),
        "dataset": os.getenv("BIGQUERY_DATASET", ""),
        "table": os.getenv("BIGQUERY_TABLE", ""),
        "query": os.getenv("BIGQUERY_QUERY", ""),
        "location": os.getenv("BIGQUERY_LOCATION", ""),
    }
    service_account_json = os.getenv("BIGQUERY_SERVICE_ACCOUNT_JSON", "")
    if service_account_json:
        config["service_account_info"] = json.loads(service_account_json)
    return {key: value for key, value in config.items() if value}


def _bigquery_config_from_streamlit():
    try:
        import streamlit as st
    except Exception:
        return {}

    try:
        secrets = st.secrets
        config = dict(secrets.get("bigquery", {}))
        service_account = secrets.get("gcp_service_account", None)
        if service_account:
            config["service_account_info"] = dict(service_account)
        return {key: value for key, value in config.items() if value}
    except Exception:
        return {}


def _read_arti_from_bigquery(config):
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError as exc:
        raise RuntimeError(
            "BigQuery esta configurado, pero faltan dependencias. "
            "Instala google-cloud-bigquery y db-dtypes."
        ) from exc

    project_id = clean(config.get("project_id"))
    credentials_info = config.get("service_account_info")
    credentials = None
    if credentials_info:
        credentials = service_account.Credentials.from_service_account_info(dict(credentials_info))
        project_id = project_id or credentials.project_id

    client = bigquery.Client(project=project_id or None, credentials=credentials)
    project_id = project_id or client.project
    query = clean(config.get("query"))
    if not query:
        dataset = clean(config.get("dataset"))
        table = clean(config.get("table"))
        table_id = table if table.count(".") == 2 else f"{project_id}.{dataset}.{table}"
        query = f"""
        SELECT
          CAST(id_producto AS STRING) AS CODINT_MA,
          CAST(codmod_codcol AS STRING) AS `COD MOD COL`,
          CAST(codmod_codcol AS STRING) AS `Mod-Col`,
          CAST(talla_numero AS STRING) AS TALNUM_MA,
          CAST(marca AS STRING) AS MARCA_MA,
          CAST(NULL AS STRING) AS Precio,
          CAST(NULL AS STRING) AS CodBarras
        FROM `{table_id}`
        WHERE UPPER(CAST(marca AS STRING)) = 'COLUMBIA'
          AND codmod_codcol IS NOT NULL
          AND id_producto IS NOT NULL
        """

    job_config = bigquery.QueryJobConfig(use_legacy_sql=False)
    query_job = client.query(query, job_config=job_config, location=clean(config.get("location")) or None)
    df = query_job.to_dataframe()
    for column in ARTI_REQUIRED_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    source = clean(config.get("table")) or "query configurada"
    return df[ARTI_REQUIRED_COLUMNS].astype(object), f"BigQuery: {source}"


def read_arti_source(
    zip_path=DEFAULT_ARTI_ZIP_PATH,
    csv_path=DEFAULT_ARTI_CSV_PATH,
    xlsx_path=DEFAULT_ARTI_XLSX_PATH,
    bigquery_config=None,
    allow_local_fallback=True,
):
    if bigquery_config is None:
        bigquery_config = _bigquery_config_from_streamlit() or _bigquery_config_from_env()
    if _bigquery_configured(bigquery_config):
        try:
            return _read_arti_from_bigquery(bigquery_config)
        except Exception as exc:
            if not allow_local_fallback:
                raise RuntimeError(f"No se pudo leer ARTI desde BigQuery. Detalle: {exc}") from exc
            print(f"No se pudo leer BigQuery; usando respaldo local. Detalle: {exc}")
    if zip_path.exists():
        return pd.read_csv(zip_path, dtype=object, usecols=lambda col: col in ARTI_REQUIRED_COLUMNS), str(zip_path)
    if csv_path.exists():
        return pd.read_csv(csv_path, dtype=object, usecols=lambda col: col in ARTI_REQUIRED_COLUMNS), str(csv_path)
    if xlsx_path.exists():
        return (
            pd.read_excel(
                xlsx_path,
                sheet_name=0,
                dtype=object,
                usecols=lambda col: col in ARTI_REQUIRED_COLUMNS,
            ),
            str(xlsx_path),
        )
    return (
        pd.read_excel(
            ARTI_PATH,
            sheet_name="Hoja1",
            dtype=object,
            usecols=lambda col: col in ARTI_REQUIRED_COLUMNS,
        ),
        str(ARTI_PATH),
    )


def prepare_matrixify_context(matrixify_source):
    if isinstance(matrixify_source, pd.DataFrame):
        matrixify_df = matrixify_source.copy()
        matrixify_columns = list(matrixify_df.columns)
    else:
        matrixify_df = pd.DataFrame()
        matrixify_columns = list(matrixify_source)

    end_column = "Metafield: custom.guia_de_tallas [page_reference]"
    if end_column in matrixify_columns:
        matrixify_columns = matrixify_columns[: matrixify_columns.index(end_column) + 1]
    return matrixify_columns, matrixify_df


def build_existing_lookup(matrixify_df):
    product_by_key = {}
    product_by_handle = {}
    variant_by_sku = {}

    if matrixify_df.empty:
        return product_by_key, product_by_handle, variant_by_sku

    for _, row in matrixify_df.iterrows():
        handle = clean(row.get("Handle"))
        mod_col = clean(row.get("Metafield: custom.codigo_modelo_color [id]")).upper()
        sku = clean(row.get("Variant SKU"))

        product_payload = {
            "ID": clean(row.get("ID")),
            "Handle": handle,
            "Created At": row.get("Created At", ""),
            "Updated At": row.get("Updated At", ""),
            "Published At": row.get("Published At", ""),
            "URL": row.get("URL", ""),
        }

        if handle and handle not in product_by_handle:
            product_by_handle[handle] = product_payload
        if mod_col and mod_col not in product_by_key:
            product_by_key[mod_col] = product_payload

        if sku and sku not in variant_by_sku:
            variant_by_sku[sku] = {
                "Variant Inventory Item ID": clean(row.get("Variant Inventory Item ID")),
                "Variant ID": clean(row.get("Variant ID")),
                "Variant Image": row.get("Variant Image", ""),
            }

    return product_by_key, product_by_handle, variant_by_sku


SKIP_COMPARE_EXCLUDED_COLUMNS = {
    "ID",
    "Command",
    "Created At",
    "Updated At",
    "Published At",
    "URL",
    "Total Inventory Qty",
    "Row #",
    "Top Row",
    "Image Type",
    "Image Src",
    "Image Command",
    "Image Position",
    "Image Width",
    "Image Height",
    "Image Alt Text",
    "Variant Inventory Item ID",
    "Variant ID",
    "Variant Command",
    "Variant Position",
    "Variant Image",
}


def comparable_columns(columns):
    return [
        column
        for column in columns
        if column not in SKIP_COMPARE_EXCLUDED_COLUMNS
        and not column.startswith(INVENTORY_PREFIX)
        and not column.startswith("Metafield: shopify--")
        and not column.startswith("Metafield: mm-google-shopping")
        and not column.startswith("Metafield: mc-facebook")
    ]


def product_is_unchanged(product_rows, existing_rows, columns):
    if existing_rows.empty:
        return False

    generated_skus = [clean(row.get("Variant SKU")) for row in product_rows]
    existing_by_sku = {
        clean(row.get("Variant SKU")): row
        for _, row in existing_rows.iterrows()
        if clean(row.get("Variant SKU"))
    }

    if set(generated_skus) != set(existing_by_sku):
        return False

    compare_cols = comparable_columns(columns)
    for generated in product_rows:
        sku = clean(generated.get("Variant SKU"))
        existing = existing_by_sku.get(sku)
        if existing is None:
            return False
        for column in compare_cols:
            if column not in existing.index:
                continue
            if compare_clean(generated.get(column, "")) != compare_clean(existing.get(column, "")):
                return False
    return True


def build_columbia_matrixify(input_df, arti, matrixify_source):
    matrixify_columns, matrixify_df = prepare_matrixify_context(matrixify_source)
    product_by_key, product_by_handle, variant_by_sku = build_existing_lookup(matrixify_df)

    input_df = input_df.dropna(how="all").copy()
    input_df["__KEY"] = input_df["Mod-Col"].map(lambda value: clean(value).upper())
    input_df["__MODEL"] = input_df["Mod-Col"].map(model_code)
    input_df["__HANDLE"] = input_df.apply(
        lambda row: normalize_handle(row.get("Handle Input") or row.get("Handle"), row.get("Mod-Col")),
        axis=1,
    )
    siblings_by_model = (
        input_df.groupby("__MODEL")["__HANDLE"]
        .apply(lambda values: ", ".join(dict.fromkeys(clean(value) for value in values if clean(value))))
        .to_dict()
    )
    image_lookup = build_image_lookup(input_df["Mod-Col"])
    wanted_keys = set(input_df["__KEY"])
    arti = arti.copy()
    if "Mod-Col" not in arti.columns:
        arti["Mod-Col"] = ""
    if "COD MOD COL" not in arti.columns:
        arti["COD MOD COL"] = ""
    arti["__KEY"] = arti["Mod-Col"].where(
        arti["Mod-Col"].map(clean) != "",
        arti["COD MOD COL"],
    ).map(lambda value: clean(value).upper())
    for optional_column in ("Precio", "CodBarras"):
        if optional_column not in arti.columns:
            arti[optional_column] = ""
    arti = arti[arti["__KEY"].isin(wanted_keys)].copy()
    arti = arti[arti["CODINT_MA"].map(clean) != ""].copy()
    arti["__SIZE"] = arti["TALNUM_MA"].map(normalize_size)
    arti = arti[arti["__SIZE"] != ""].copy()
    arti = arti.sort_values(by=["__KEY", "__SIZE"], key=lambda series: series.map(size_sort_key))

    tech_col = first_existing(input_df, ["METAFIELD TECNOLOGÍAS"])
    rows = []
    issues = []
    skipped_rows = []

    for input_index, product in input_df.iterrows():
        key = product["__KEY"]
        variants = arti[arti["__KEY"] == key].copy()
        if variants.empty:
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Sin variantes validas en ARTI/BigQuery",
                    "Fila input": input_index + 2,
                }
            )
            continue

        variants = variants.drop_duplicates(subset=["CODINT_MA", "__SIZE", "CodBarras"])
        variants = variants.sort_values("__SIZE", key=lambda series: series.map(size_sort_key))

        handle = product["__HANDLE"]
        product_images = image_lookup.get(key, [])
        if not product_images:
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Sin fotos validas en la ruta COLUMBIA SHOPIFY",
                    "Fila input": input_index + 2,
                }
            )
        title = clean(product.get("Title"))
        body_html = build_body_html(product)
        tags = clean(product.get("Tags"))
        product_type = clean(product.get("Type"))
        technology_value = product.get(tech_col) if tech_col else ""
        color_web = clean(product.get("Color Web"))
        image_alt = f"{title} {color_web}".strip()
        existing_product = product_by_key.get(key) or product_by_handle.get(handle) or {}
        existing_handle = existing_product.get("Handle") or handle
        existing_rows = (
            matrixify_df[matrixify_df["Handle"].map(clean) == existing_handle].copy()
            if not matrixify_df.empty and "Handle" in matrixify_df.columns
            else pd.DataFrame()
        )
        product_rows = []

        for position, (_, variant) in enumerate(variants.iterrows(), start=1):
            is_first = position == 1
            output = {column: "" for column in matrixify_columns}
            variant_sku = clean(variant.get("CODINT_MA"))
            existing_variant = variant_by_sku.get(variant_sku, {})

            output.update(
                {
                    "ID": existing_product.get("ID", ""),
                    "Handle": handle,
                    "Command": "MERGE",
                    "Title": title,
                    "Body HTML": body_html if is_first else "",
                    "Vendor": "columbiape",
                    "Type": product_type,
                    "Tags": tags,
                    "Tags Command": "REPLACE",
                    "Status": "Active",
                    "Published": "TRUE" if clean(variant.get("Precio")) else "FALSE",
                    "Created At": existing_product.get("Created At", ""),
                    "Updated At": existing_product.get("Updated At", ""),
                    "Published At": existing_product.get("Published At", ""),
                    "Published Scope": "web",
                    "Gift Card": "FALSE",
                    "URL": existing_product.get("URL", ""),
                    "Total Inventory Qty": 0,
                    "Row #": position,
                    "Top Row": "TRUE" if is_first else "",
                    "Image Type": "IMAGE",
                    "Image Src": "; ".join(product_images),
                    "Image Command": "MERGE",
                    "Image Position": "",
                    "Image Width": "",
                    "Image Height": "",
                    "Image Alt Text": image_alt,
                    "Variant Inventory Item ID": existing_variant.get("Variant Inventory Item ID", ""),
                    "Variant ID": existing_variant.get("Variant ID", ""),
                    "Variant Command": "MERGE",
                    "Option1 Name": "Talla",
                    "Option1 Value": variant["__SIZE"],
                    "Variant Position": position,
                    "Variant SKU": variant_sku,
                    "Variant Barcode": clean(variant.get("CodBarras")),
                    "Variant Image": existing_variant.get("Variant Image", ""),
                    "Variant Price": clean(variant.get("Precio")),
                    "Variant Compare At Price": "",
                }
            )

            for column in matrixify_columns:
                if column.startswith(INVENTORY_PREFIX):
                    output[column] = 0

            if is_first:
                output.update(
                    {
                        "Metafield: custom.pais_de_fabricacion [single_line_text_field]": clean(
                            product.get("Metafield: custom.pais_de_fabricacion [single_line_text_field]")
                        ),
                        "Metafield: custom.logo [list.metaobject_reference]": format_technology_logos(
                            technology_value
                        ),
                        "Metafield: custom.color_forus [single_line_text_field]": clean(
                            product.get("Metafield: custom.color_forus [single_line_text_field]")
                        ),
                        "Metafield: theme.siblings_color [single_line_text_field]": color_web,
                        "Metafield: theme.siblings [single_line_text_field]": siblings_by_model.get(
                            product["__MODEL"], handle
                        ),
                        "Metafield: custom.grupo_color [single_line_text_field]": clean(
                            product.get("Metafield: custom.grupo_color [single_line_text_field]")
                        ),
                        "Metafield: custom.genero [single_line_text_field]": clean(
                            product.get("Metafield: custom.genero [single_line_text_field]")
                        ),
                        "Metafield: custom.tipo [single_line_text_field]": clean(
                            product.get("Metafield: custom.tipo [single_line_text_field]")
                        ),
                        "Metafield: custom.descripcion_corta [single_line_text_field]": clean(
                            product.get("Metafield: custom.descripcion_corta [single_line_text_field]")
                        ),
                        "Metafield: custom.nombre_corto [single_line_text_field]": clean(
                            product.get("Metafield: custom.nombre_corto [single_line_text_field]")
                        ),
                        "Metafield: custom.codigo_modelo_color [id]": clean(
                            product.get("Metafield: custom.codigo_modelo_color [id]")
                        )
                        or key,
                        "Metafield: custom.sub_categoria [single_line_text_field]": product_type,
                        "Metafield: custom.categoria [single_line_text_field]": clean(
                            product.get("Metafield: custom.categoria [single_line_text_field]")
                        ),
                        "Metafield: custom.guia_de_tallas [page_reference]": "",
                        "Metafield: custom.tecnologia [list.single_line_text_field]": format_technology(
                            technology_value
                        ),
                        "Metafield: custom.deporte [list.single_line_text_field]": format_technology(
                            product.get("Metafield: custom.deporte [list.single_line_text_field]")
                        ),
                        "Metafield: mm-google-shopping.custom_product [boolean]": "FALSE",
                    }
                )

            product_rows.append(output)

        if existing_product.get("ID") and product_is_unchanged(product_rows, existing_rows, matrixify_columns):
            skipped_rows.append(
                {
                    "Mod-Col": key,
                    "Handle": handle,
                    "Filas omitidas": len(product_rows),
                    "Motivo": "Ya existe en Matrixify modelo y no presenta cambios en campos comparados",
                }
            )
            continue

        rows.extend(product_rows)

    output_df = pd.DataFrame(rows, columns=matrixify_columns)
    issues_df = pd.DataFrame(issues)
    skipped_df = pd.DataFrame(
        skipped_rows,
        columns=["Mod-Col", "Handle", "Filas omitidas", "Motivo"],
    )
    type_warnings_df = build_new_type_warnings(input_df)
    summary_df = pd.DataFrame(
        [
            {"Metrica": "Productos input", "Valor": len(input_df)},
            {"Metrica": "Productos con match ARTI", "Valor": output_df["Handle"].nunique() if len(output_df) else 0},
            {"Metrica": "Filas variantes Matrixify", "Valor": len(output_df)},
            {"Metrica": "Productos omitidos sin cambios", "Valor": len(skipped_df)},
            {
                "Metrica": "Filas omitidas sin cambios",
                "Valor": int(skipped_df["Filas omitidas"].sum()) if len(skipped_df) else 0,
            },
            {
                "Metrica": "Productos existentes con ID",
                "Valor": output_df.loc[output_df["ID"].map(clean) != "", "Handle"].nunique()
                if "ID" in output_df.columns and len(output_df)
                else 0,
            },
            {
                "Metrica": "Variantes existentes con Variant ID",
                "Valor": int((output_df["Variant ID"].map(clean) != "").sum())
                if "Variant ID" in output_df.columns and len(output_df)
                else 0,
            },
            {"Metrica": "Observaciones", "Valor": len(issues_df)},
            {
                "Metrica": "Tipos/Familias nuevas",
                "Valor": 0
                if type_warnings_df.empty or type_warnings_df.iloc[0]["Campo"] == "Configuracion"
                else len(type_warnings_df),
            },
        ]
    )
    return output_df, summary_df, issues_df, type_warnings_df, skipped_df


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    template = pd.read_excel(TEMPLATE_PATH, sheet_name="Products", dtype=object)

    input_df = pd.read_excel(INPUT_PATH, sheet_name=0, dtype=object)

    arti, arti_source = read_arti_source()

    output_df, summary_df, issues_df, type_warnings_df, skipped_df = build_columbia_matrixify(
        input_df, arti, template
    )

    output_path = available_output_path(OUTPUT_PATH)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        output_df.to_excel(writer, sheet_name="Products", index=False)
        summary_df.to_excel(writer, sheet_name="Resumen", index=False)
        issues_df.to_excel(writer, sheet_name="Revision", index=False)
        type_warnings_df.to_excel(writer, sheet_name="Tipos nuevos", index=False)
        skipped_df.to_excel(writer, sheet_name="Omitidos sin cambios", index=False)

        for sheet in writer.book.worksheets:
            sheet.freeze_panes = "A2"
            for cell in sheet[1]:
                cell.style = "Headline 4"
            max_col = min(sheet.max_column, 98)
            for col_idx in range(1, max_col + 1):
                sheet.column_dimensions[sheet.cell(1, col_idx).column_letter].width = 18

    print(output_path.resolve())
    print(f"ARTI usado: {arti_source}")
    print(summary_df.to_string(index=False))


if __name__ == "__main__":
    main()
