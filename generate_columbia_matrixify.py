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
DEFAULT_IMAGE_HOST = "https://ecom-imagenes.forus-digital.xyz.peru.s3.amazonaws.com"
DEFAULT_IMAGE_VALIDATION_HOST = "https://s3.amazonaws.com/ecom-imagenes.forus-digital.xyz.peru"
IMAGE_BASE_URL = f"{DEFAULT_IMAGE_HOST}/COLUMBIA"
IMAGE_VALIDATION_BASE_URL = f"{DEFAULT_IMAGE_VALIDATION_HOST}/COLUMBIA"
MAX_IMAGES_PER_PRODUCT = 10
VALIDATE_IMAGES = False

BRAND_IMAGE_FOLDERS = {
    "ACCESORIOS HP": "HUSH PUPPIES",
    "COLUMBIA": "COLUMBIA",
    "HUSH PUPPIES": "HUSH PUPPIES",
    "HUSH PUPPIES KIDS": "HUSH PUPPIES",
    "KEDS": "KEDS",
    "MOUNTAIN HARDWEAR": "MOUNTAINHARDWEAR",
    "PATAGONIA": "PATAGONIA",
    "ROCKFORD": "ROCKFORD",
    "SOREL": "SOREL",
    "VANS": "VANS",
}

BRAND_DISPLAY_NAMES = {
    "ACCESORIOS HP": "Hush Puppies",
    "COLUMBIA": "Columbia",
    "HUSH PUPPIES": "Hush Puppies",
    "HUSH PUPPIES KIDS": "Hush Puppies",
    "KEDS": "Keds",
    "MOUNTAIN HARDWEAR": "Mountain Hardwear",
    "PATAGONIA": "Patagonia",
    "ROCKFORD": "Rockford",
    "SOREL": "Sorel",
    "VANS": "Vans",
}

SIAL_TAIL_COLUMBIA = [
    "Nuevo o Actualizar (Columbia.pe)",
    "Porduct Id - Columbia.pe",
    "Nuevo o Actualizar (Supermall.pe)",
    "Porduct Id - Supermall.pe",
    "Nuevo o Actualizar (Supermall.pe).1",
    "Porduct Id - Rockford.pe",
    "4",
    "13",
    "6",
]

SIAL_TAIL_HUSH = [
    "Nuevo o Actualizar (Columbia.pe)",
    "Sku - Supermall.pe",
    "Porduct Id - Columbia.pe",
    "Nuevo o Actualizar (Supermall.pe)",
    "Porduct Id - Supermall.pe",
    "2",
    "13",
]

SIAL_TAIL_ROCKFORD = [
    "Nuevo o Actualizar (Columbia.pe)",
    "Sku - Supermall.pe",
    "Porduct Id - Columbia.pe",
    "Nuevo o Actualizar (Supermall.pe)",
    "Porduct Id - Supermall.pe",
    "6",
    "13",
]

SIAL_TAIL_VANS = [
    "Nuevo o Actualizar (Columbia.pe)",
    "Sku - Supermall.pe",
    "Porduct Id - Columbia.pe",
    "Nuevo o Actualizar (Supermall.pe)",
    "Porduct Id - Supermall.pe",
    "103",
]


def _config_clean(value):
    if value is None:
        return ""
    return str(value).strip()


SITE_CONFIGS = {
    "columbia": {
        "label": "Columbia",
        "site_label": "Columbia.pe",
        "allowed_arti_brands": ["COLUMBIA"],
        "vendor": "columbiape",
        "legacy_vendors": ["columbiape"],
        "store_domain": "Columbia.pe",
        "image_folder": "COLUMBIA",
        "output_filename": "matrixify_columbia_generado.xlsx",
        "sial_tail_columns": SIAL_TAIL_COLUMBIA,
        "sial_active_columns": ["4", "13", "6"],
    },
    "rockford": {
        "label": "Rockford",
        "site_label": "Rockford.pe",
        "allowed_arti_brands": ["COLUMBIA", "ROCKFORD", "PATAGONIA", "SOREL", "MOUNTAIN HARDWEAR"],
        "vendor": "rockfordpe",
        "legacy_vendors": ["rockfordpe"],
        "store_domain": "Rockford.pe",
        "image_folder": "ROCKFORD",
        "output_filename": "matrixify_rockford_generado.xlsx",
        "sial_tail_columns": SIAL_TAIL_ROCKFORD,
        "sial_active_columns": ["6", "13"],
    },
    "hush_puppies": {
        "label": "Hush Puppies",
        "site_label": "HushPuppies.pe",
        "allowed_arti_brands": ["HUSH PUPPIES", "HUSH PUPPIES KIDS", "ACCESORIOS HP", "KEDS", "ROCKFORD"],
        "vendor": "hushpuppiespe",
        "legacy_vendors": ["hushpuppiespe"],
        "store_domain": "HushPuppies.pe",
        "image_folder": "HUSH PUPPIES",
        "output_filename": "matrixify_hush_puppies_generado.xlsx",
        "sial_tail_columns": SIAL_TAIL_HUSH,
        "sial_active_columns": ["2", "13"],
    },
    "vans": {
        "label": "Vans",
        "site_label": "Vans.pe",
        "allowed_arti_brands": ["VANS"],
        "vendor": "Vans",
        "legacy_vendors": ["vanspe", "Vans"],
        "store_domain": "Vans.pe",
        "image_folder": "VANS",
        "output_filename": "matrixify_vans_generado.xlsx",
        "sial_tail_columns": SIAL_TAIL_VANS,
        "sial_active_columns": ["103"],
    },
}

BRAND_CONFIGS = SITE_CONFIGS


def normalize_brand_name(value):
    text = _config_clean(value).upper()
    replacements = {
        "á": "a",
        "é": "e",
        "í": "i",
        "ó": "o",
        "ú": "u",
        "ñ": "n",
        "™": "",
        "®": "",
        "Ã": "A",
        "Ã‰": "E",
        "Ã": "I",
        "Ã“": "O",
        "Ãš": "U",
        "Ã‘": "N",
        "Á": "A",
        "É": "E",
        "Í": "I",
        "Ó": "O",
        "Ú": "U",
        "Ñ": "N",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def brand_display_name(value, fallback=""):
    normalized = normalize_brand_name(value)
    if normalized in BRAND_DISPLAY_NAMES:
        return BRAND_DISPLAY_NAMES[normalized]
    return _config_clean(value) or fallback


def brand_from_variants(variants):
    if variants is None or variants.empty or "MARCA_MA" not in variants.columns:
        return "", []
    brands_by_normalized = {}
    for value in variants["MARCA_MA"].dropna():
        raw = clean(value)
        normalized = normalize_brand_name(raw)
        if normalized and normalized not in brands_by_normalized:
            brands_by_normalized[normalized] = raw
    return next(iter(brands_by_normalized.values()), ""), sorted(brands_by_normalized)


def variants_are_mountain_hardwear(variants):
    if variants is None or variants.empty or "MARCA_MA" not in variants.columns:
        return False
    return variants["MARCA_MA"].map(normalize_brand_name).eq("MOUNTAIN HARDWEAR").any()


def get_brand_config(site="columbia", overrides=None):
    key = _config_clean(site).lower().replace(" ", "_") or "columbia"
    base = SITE_CONFIGS.get(key, SITE_CONFIGS["columbia"]).copy()
    base["site_key"] = key
    base["allowed_arti_brands"] = [normalize_brand_name(value) for value in base.get("allowed_arti_brands", [])]
    base["arti_brand"] = ", ".join(base["allowed_arti_brands"])
    base["legacy_vendors"] = [_config_clean(value).lower() for value in base.get("legacy_vendors", [])]
    if overrides:
        for field, value in overrides.items():
            if _config_clean(value):
                base[field] = _config_clean(value)
    folder = _config_clean(base.get("image_folder")) or base["label"].upper()
    encoded_folder = folder.replace(" ", "%20")
    base["image_base_url"] = f"{DEFAULT_IMAGE_HOST}/{encoded_folder}"
    base["image_validation_base_url"] = f"{DEFAULT_IMAGE_VALIDATION_HOST}/{encoded_folder}"
    return base


def brand_image_config(brand_name, fallback_config):
    config = fallback_config.copy()
    folder = BRAND_IMAGE_FOLDERS.get(normalize_brand_name(brand_name), fallback_config.get("image_folder", ""))
    if not folder:
        return config
    encoded_folder = folder.replace(" ", "%20")
    config["image_folder"] = folder
    config["image_base_url"] = f"{DEFAULT_IMAGE_HOST}/{encoded_folder}"
    config["image_validation_base_url"] = f"{DEFAULT_IMAGE_VALIDATION_HOST}/{encoded_folder}"
    return config


def clean(value):
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        parts = [clean(item) for item in value]
        return " | ".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = [clean(item) for item in value.values()]
        return " | ".join(part for part in parts if part)
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def safe_int(value, default=0):
    try:
        text = clean(value)
        if not text:
            return default
        return int(float(text.replace(",", ".")))
    except (TypeError, ValueError):
        return default


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


def image_candidates(mod_col, brand_config=None):
    brand_config = brand_config or get_brand_config()
    model, color = split_model_color(mod_col)
    if not model or not color:
        return []
    image_key = f"{model}_{color}"
    return [f"{brand_config['image_base_url']}/{image_key}_{position}.jpg" for position in range(1, MAX_IMAGES_PER_PRODUCT + 1)]


def validation_url(url, brand_config=None):
    brand_config = brand_config or get_brand_config()
    return url.replace(brand_config["image_base_url"], brand_config["image_validation_base_url"])


def url_is_image(url, timeout=4, brand_config=None):
    request = Request(validation_url(url, brand_config), method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            return response.status < 400 and content_type.lower().startswith("image/")
    except HTTPError as exc:
        if exc.code in (403, 405):
            try:
                request = Request(
                    validation_url(url, brand_config),
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


def build_image_lookup(mod_cols, validate=VALIDATE_IMAGES, brand_config=None):
    brand_config = brand_config or get_brand_config()
    lookup = {}
    for mod_col in sorted({clean(value).upper() for value in mod_cols if clean(value)}):
        urls = image_candidates(mod_col, brand_config)
        if not validate:
            lookup[mod_col] = list(dict.fromkeys(urls))
            continue

        valid_urls = []
        misses_after_found = 0
        for url in urls:
            if url_is_image(url, timeout=2, brand_config=brand_config):
                valid_urls.append(url)
                misses_after_found = 0
            elif valid_urls:
                misses_after_found += 1
                if misses_after_found >= 2:
                    break
        lookup[mod_col] = list(dict.fromkeys(valid_urls))
    return lookup


def build_image_lookup_by_brand(input_df, brand_column, brand_config):
    lookup = {}
    for _, row in input_df.iterrows():
        mod_col = clean(row.get("Mod-Col")).upper()
        if not mod_col:
            continue
        row_brand_config = brand_image_config(row.get(brand_column) if brand_column else "", brand_config)
        cache_key = (mod_col, row_brand_config["image_folder"])
        if cache_key not in lookup:
            lookup[cache_key] = build_image_lookup([mod_col], brand_config=row_brand_config).get(mod_col, [])
    return lookup


def normalize_size(value):
    if value is None or pd.isna(value):
        return ""

    if isinstance(value, (pd.Timestamp, datetime)):
        return f"{value.day}/{value.month}"

    text = clean(value).upper()
    if not text:
        return ""
    if text in {"NAN", "NONE", "NULL", "NA", "N/A", "#N/A", "#N/D", "#ND", "SIN TALLA"}:
        return ""

    text = re.sub(r"\b(TALLA|SIZE|TAL)\b", "", text).strip()
    text = re.sub(r"\s+", " ", text)

    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]

    if re.fullmatch(r"\d+", text):
        number = int(text)
        if 50 <= number <= 130 and number % 5 == 0:
            converted = number / 10
            return str(int(converted)) if converted.is_integer() else str(converted)
        if 140 <= number <= 490 and number % 5 == 0:
            converted = number / 10
            return str(int(converted)) if converted.is_integer() else str(converted)
        return text

    aliases = {
        "OS": "O/S",
        "UNICA": "O/S",
        "ÚNICA": "O/S",
        "ÚNICA": "O/S",
        "TALLA UNICA": "O/S",
        "TALLA ÚNICA": "O/S",
        "SX": "XS",
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
    if text.startswith("[") and text.endswith("]"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = [clean(item) for item in parsed if clean(item)]
                return json.dumps(items, ensure_ascii=False)
        except Exception:
            pass
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


def valid_price(value):
    text = clean(value).replace(",", ".")
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return clean(value)
    if number <= 0:
        return ""
    if number.is_integer():
        return str(int(number))
    return text


def strip_html(value):
    text = re.sub(r"<[^>]+>", " ", clean(value))
    return re.sub(r"\s+", " ", text).strip()


def first_non_empty(*values):
    for value in values:
        text = clean(value)
        if text:
            return text
    return ""


def limit_words(value, max_words=45):
    text = re.sub(r"\s+", " ", clean(strip_html(value))).strip(" -:;,.")
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).strip(" -:;,.")


def product_category(product):
    return first_non_empty(
        product.get("Metafield: custom.categoria [single_line_text_field]"),
        product.get("Categoria "),
        product.get("Categoria"),
        product.get("Category"),
    )


def product_gender(product):
    return first_non_empty(
        product.get("Metafield: custom.genero [single_line_text_field]"),
        product.get("Genero"),
        product.get("Género"),
        product.get("Gender"),
    )


def product_technology(product, tech_col):
    return clean(product.get(tech_col)) if tech_col else ""


def sial_dimension_defaults(product):
    text = normalize_text(
        " ".join(
            clean(value)
            for value in (
                product.get("Type"),
                product_category(product),
                product.get("Categoria "),
                product.get("Tags"),
                product.get("Title"),
            )
            if clean(value)
        )
    )
    is_footwear = any(term in text for term in ("calzado", "zapatilla", "zapato", "botin", "bota", "sandalia"))
    if is_footwear:
        return {"weight": 900, "length": 35, "width": 21, "height": 12}
    return {"weight": 200, "length": 29, "width": 27, "height": 1}


def sial_dimension_value(product, key, fallback):
    aliases = {
        "weight": ("Product Weight", "Package Weight", "Peso del paquete", "Peso (gr)", "Product Weight (gr)"),
        "length": ("Product Length", "Package Length", "Largo del paquete", "Largo (cm)"),
        "width": ("Product Width", "Package Width", "Ancho del paquete", "Ancho (cm)"),
        "height": ("Product Height", "Package Height", "Alto del paquete", "Alto (cm)"),
    }
    return first_non_empty(*(product.get(column) for column in aliases.get(key, ())), fallback)


def category_blocks_zero_size(product):
    values = [
        product_category(product),
        product.get("Categoria "),
        product.get("Categoria"),
        product.get("Type"),
        product.get("Metafield: custom.tipo [single_line_text_field]"),
        product.get("Metafield: custom.categoria [single_line_text_field]"),
        product.get("Tags"),
    ]
    text = normalize_text(" ".join(clean(value) for value in values if clean(value)))
    blocked_terms = (
        "vestuario",
        "calzado",
        "ropa",
        "zapatilla",
        "zapato",
        "bota",
        "botin",
        "sandalia",
        "camisa",
        "camiseta",
        "polera",
        "pantalon",
        "short",
        "casaca",
        "chaqueta",
        "parka",
        "polar",
        "poleron",
        "vestido",
        "falda",
        "media",
        "medias",
        "calcetin",
        "calcetines",
    )
    return any(term in text for term in blocked_terms)


def is_zero_size(value):
    raw_text = clean(value).upper()
    normalized_text = clean(normalize_size(value)).upper()
    candidates = {raw_text, normalized_text}
    for text in candidates:
        text = re.sub(r"\b(TALLA|SIZE|TAL)\b", "", text)
        text = re.sub(r"\s+", "", text).replace(",", ".")
        if re.fullmatch(r"0+(\.0+)?", text):
            return True
        if re.fullmatch(r"0+\.?0*[A-Z]*", text) and re.sub(r"[^A-Z]", "", text) in ("",):
            return True
    if re.search(r"(^|[^A-Z0-9])0+([,.]0+)?([^A-Z0-9]|$)", raw_text):
        return True
    return False


def is_one_size(value):
    size = clean(normalize_size(value)).upper().replace(" ", "")
    return size in ("O/S", "OS", "ONESIZE", "UNICA", "ÚNICA", "TALLAUNICA")


def display_size_for_site(value, brand_config=None):
    brand_config = brand_config or get_brand_config()
    site_label = clean(brand_config.get("site_label"))
    if site_label == "Rockford.pe" and (is_one_size(value) or is_zero_size(value)):
        return "Talla Única"
    return normalize_size(value)


def dedupe_variants_for_shopify(variants, brand_config=None, issues=None, key="", input_index=None):
    if variants is None or variants.empty:
        return variants
    kept_indexes = []
    seen_skus = set()
    duplicate_skus = []
    for index, row in variants.iterrows():
        sku = clean(row.get("CODINT_MA")).upper()
        size = clean(display_size_for_site(row.get("__SIZE"), brand_config)).upper()
        if sku and sku in seen_skus:
            duplicate_skus.append(f"{sku} ({size or 'sin talla'})")
            continue
        if sku:
            seen_skus.add(sku)
        kept_indexes.append(index)
    if issues is not None:
        if duplicate_skus:
            issue = {
                "Mod-Col": key,
                "Problema": "Se omitieron variantes duplicadas por SKU antes de enviar a Shopify",
                "Cantidad": safe_int(len(duplicate_skus)),
                "Detalle": ", ".join(duplicate_skus[:12]),
            }
            if input_index is not None:
                issue["Fila input"] = input_index + 2
            issues.append(issue)
    return variants.loc[kept_indexes].copy()


def sial_size_value(value):
    return clean(value)


def is_internal_k_size(value):
    size = clean(normalize_size(value)).upper().replace(" ", "")
    return bool(re.fullmatch(r"K\d+", size))


def boolean_mask(series, predicate):
    if series is None:
        return pd.Series(dtype=bool)
    def apply_predicate(value):
        try:
            return bool(predicate(value))
        except (TypeError, ValueError, AttributeError):
            return False

    return series.map(apply_predicate).fillna(False).astype(bool)


def _row_blocks_zero_size(row):
    return category_blocks_zero_size(row)


def row_is_mountain_hardwear(row):
    values = [
        row.get("Vendor"),
        row.get("Metafield: custom.marca [single_line_text_field]"),
        row.get("Marca"),
        row.get("Brand"),
    ]
    return any(normalize_brand_name(value) == "MOUNTAIN HARDWEAR" for value in values if clean(value))


def final_variant_filter(output_df, sial_df, issues_df):
    issues = [] if issues_df is None or issues_df.empty else issues_df.to_dict("records")

    if output_df is not None and not output_df.empty and "Option1 Value" in output_df.columns:
        k_mask = output_df["Option1 Value"].map(is_internal_k_size)
        if k_mask.any():
            issues.append(
                {
                    "Mod-Col": "Salida final",
                    "Problema": "Se eliminaron filas finales con talla interna K",
                    "Fila input": "",
                    "Cantidad": safe_int(k_mask.sum()),
                }
            )
            output_df = output_df[~k_mask].copy()

        zero_mask = output_df.apply(
            lambda row: is_zero_size(row.get("Option1 Value")) and _row_blocks_zero_size(row),
            axis=1,
        )
        if zero_mask.any():
            issues.append(
                {
                    "Mod-Col": "Salida final",
                    "Problema": "Se eliminaron filas finales con talla 0/000 en vestuario/calzado",
                    "Fila input": "",
                    "Cantidad": safe_int(zero_mask.sum()),
                }
            )
            output_df = output_df[~zero_mask].copy()

        if "Variant SKU" in output_df.columns:
            missing_sku_mask = output_df["Variant SKU"].map(clean).eq("")
            if missing_sku_mask.any():
                issues.append(
                    {
                        "Mod-Col": "Salida final",
                        "Problema": "Se eliminaron filas finales sin Variant SKU",
                        "Fila input": "",
                        "Cantidad": safe_int(missing_sku_mask.sum()),
                    }
                )
                output_df = output_df[~missing_sku_mask].copy()

        if {"Handle", "Option1 Value"}.issubset(output_df.columns):
            drop_accessory_zero = pd.Series(False, index=output_df.index)
            handle_key = output_df["Handle"].map(clean).replace("", pd.NA).ffill().fillna("").str.upper()
            for _, group in output_df.groupby(handle_key, sort=False):
                zero_group_mask = group["Option1 Value"].map(is_zero_size)
                if not zero_group_mask.any():
                    continue
                real_size_mask = group["Option1 Value"].map(clean).ne("") & ~group["Option1 Value"].map(is_zero_size)
                if real_size_mask.any():
                    drop_accessory_zero.loc[group.index[zero_group_mask]] = True
            if drop_accessory_zero.any():
                issues.append(
                    {
                        "Mod-Col": "Salida final",
                        "Problema": "Se eliminaron filas finales talla 0/000 porque el producto tiene una talla real",
                        "Fila input": "",
                        "Cantidad": safe_int(drop_accessory_zero.sum()),
                    }
                )
                output_df = output_df[~drop_accessory_zero].copy()

        if {"Handle", "Variant SKU"}.issubset(output_df.columns):
            sku_key = output_df["Variant SKU"].map(clean).str.upper()
            handle_key = output_df["Handle"].map(clean).replace("", pd.NA).ffill().fillna("").str.upper()
            duplicate_sku_mask = sku_key.ne("") & pd.DataFrame({"Handle": handle_key, "SKU": sku_key}).duplicated(keep="first")
            if duplicate_sku_mask.any():
                issues.append(
                    {
                        "Mod-Col": "Salida final",
                        "Problema": "Se eliminaron filas finales con SKU duplicado dentro del mismo producto",
                        "Fila input": "",
                        "Cantidad": safe_int(duplicate_sku_mask.sum()),
                    }
                )
                output_df = output_df[~duplicate_sku_mask].copy()

    if sial_df is not None and not sial_df.empty and "Talla" in sial_df.columns:
        k_mask = sial_df["Talla"].map(is_internal_k_size)
        if k_mask.any():
            sial_df = sial_df[~k_mask].copy()
        def sial_zero_blocked(row):
            if not is_zero_size(row.get("Talla")):
                return False
            text = normalize_text(
                " ".join(
                    clean(row.get(column))
                    for column in ("Categoria ", "Sub Categoria", "Tipo de Producto")
                    if column in row.index
                )
            )
            return "calzado" in text or "vestuario" in text

        zero_mask = sial_df.apply(sial_zero_blocked, axis=1)
        if zero_mask.any():
            sial_df = sial_df[~zero_mask].copy()

    return output_df, sial_df, pd.DataFrame(issues)


def sial_product_bullets(product, product_type, color_web, tech_col, brand_config=None, brand_label=""):
    brand_config = brand_config or get_brand_config()
    brand_label = clean(brand_label) or brand_config["label"]
    pieces = [
        ("Tipo De Producto", product_type),
        ("Género", product_gender(product)),
        ("Color", color_web),
        ("Marca", brand_label),
    ]
    technology = product_technology(product, tech_col)
    if technology:
        pieces.append(("Tecnologías", technology))
    return ", ".join(f"{label} | {value}" for label, value in pieces if clean(value))


def sial_short_features(value, max_words=45):
    return limit_words(value, max_words)


def build_sial_row(product, variant, key, product_images, existing_product, tech_col, brand_config=None, brand_label=""):
    brand_config = brand_config or get_brand_config()
    brand_label = clean(brand_label) or brand_config["label"]
    display_size = sial_size_value(variant.get("__SIAL_SIZE") or variant["__SIZE"])
    model, color = split_model_color(key)
    product_type = clean(product.get("Type"))
    color_web = clean(product.get("Color Web"))
    title = clean(product.get("Title"))
    body_html = build_body_html(product)
    existing_id = clean(existing_product.get("ID"))
    dimension_defaults = sial_dimension_defaults(product)
    technology = limit_words(product_technology(product, tech_col), 45)
    row = {
        "Cod. Modelo": model,
        "Cod. Color": color,
        "Talla": display_size,
        "Product Name ": title,
        "Product Bullets": first_non_empty(
            product.get("Product Bullets"),
            sial_product_bullets(product, product_type, color_web, tech_col, brand_config, brand_label),
        ),
        "Product Description": first_non_empty(product.get("Product Description"), strip_html(body_html)),
        "Image URL": "",
        "Product Weight": sial_dimension_value(product, "weight", dimension_defaults["weight"]),
        "Product Length": sial_dimension_value(product, "length", dimension_defaults["length"]),
        "Product Width": sial_dimension_value(product, "width", dimension_defaults["width"]),
        "Product Height": sial_dimension_value(product, "height", dimension_defaults["height"]),
        "Package Weight": sial_dimension_value(product, "weight", dimension_defaults["weight"]),
        "Package Length": sial_dimension_value(product, "length", dimension_defaults["length"]),
        "Package Width": sial_dimension_value(product, "width", dimension_defaults["width"]),
        "Package Height": sial_dimension_value(product, "height", dimension_defaults["height"]),
        "Boost ": clean(product.get("Boost ")),
        "Talla Web ": display_size,
        "Color Web": color_web,
        "Categoria ": product_category(product),
        "Sub Categoria": product_type,
        "Genero": product_gender(product),
        "Estilo ": clean(product.get("Estilo ")) or clean(product.get("Metafield: custom.tipo [single_line_text_field]")),
        "Colecciones ": clean(product.get("Colecciones ")),
        "Temporada ": clean(product.get("Temporada ")) or clean(product.get("Temporada")),
        "Modelo": clean(product.get("Modelo")),
        "Marca": brand_label,
        "Tecnologias ": technology,
        "Caracteristicas": sial_short_features(product.get("Caracteristicas")),
        "Tipo de Boardshort": clean(product.get("Tipo de Boardshort")),
        "Tipo de Bikini": clean(product.get("Tipo de Bikini")),
        "Iniciativas": clean(product.get("Iniciativas")),
        "Tipo de Material": clean(product.get("Tipo de Material")),
        "1": clean(product.get("1")),
        "Tipo de Prenda": clean(product.get("Tipo de Prenda")),
        "Adicional 2 ": clean(product.get("Adicional 2 ")),
        "Adicional 3 ": clean(product.get("Adicional 3 ")),
        "Adicional 4 ": clean(product.get("Adicional 4 ")),
        "Adicional 5 ": clean(product.get("Adicional 5 ")),
        "Adicional 6 ": clean(product.get("Adicional 6 ")),
        "Adicional 7 ": clean(product.get("Adicional 7 ")),
        "Adicional 8 ": clean(product.get("Adicional 8 ")),
        "Adicional 9 ": clean(product.get("Adicional 9 ")),
        "Adicional 10": clean(product.get("Adicional 10")),
        "Mod-Col": key,
        "Sku - Sial": clean(variant.get("CODINT_MA")),
    }
    for column in brand_config.get("sial_tail_columns", []):
        if column.startswith("Nuevo o Actualizar"):
            row[column] = "Actualizar" if existing_id else "Crear"
        elif column.startswith("Porduct Id"):
            row[column] = existing_id if brand_config["store_domain"] in column else ""
        elif column.startswith("Sku -"):
            row[column] = clean(variant.get("CODINT_MA"))
        elif column in brand_config.get("sial_active_columns", []):
            row[column] = 1
        else:
            row[column] = ""
    return row


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
    normalized_compact = {normalize_header_key(col): col for col in df.columns}
    for candidate in candidates:
        found = normalized.get(candidate.lower())
        if found is not None:
            return found
        found = normalized_compact.get(normalize_header_key(candidate))
        if found is not None:
            return found
    return None


def normalize_header_key(value):
    text = normalize_brand_name(value).lower()
    text = text.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    text = text.replace("ñ", "n")
    return re.sub(r"[^a-z0-9]+", "", text)


def ensure_mod_col_column(df):
    if "Mod-Col" in df.columns:
        return df
    mod_col = first_existing(
        df,
        [
            "Mod-Col",
            "Mod Col",
            "ModCol",
            "MODCOL",
            "COD MOD COL",
            "COD_MOD_COL",
            "COD-MOD-COL",
            "Cod Mod Col",
            "Codigo Modelo Color",
            "Código Modelo Color",
            "Codigo Modelo-Color",
            "Código Modelo-Color",
            "codigo_modelo_color",
            "codigo modelo color",
            "Metafield: custom.codigo_modelo_color [id]",
        ],
    )
    if not mod_col:
        available = ", ".join(str(column) for column in df.columns)
        raise ValueError(
            "No encontre la columna de codigo modelo-color. "
            "El input debe tener una columna llamada Mod-Col, COD MOD COL o codigo_modelo_color. "
            f"Columnas recibidas: {available}"
        )
    df = df.copy()
    df["Mod-Col"] = df[mod_col]
    return df


def detect_brand_column(df):
    return first_existing(
        df,
        [
            "Marca",
            "MARCA",
            "Brand",
            "Vendor",
            "Proveedor",
            "Metafield: custom.marca [single_line_text_field]",
        ],
    )


def input_brand_report(input_df, brand_config):
    brand_column = detect_brand_column(input_df)
    allowed = set(brand_config.get("allowed_arti_brands", []))
    if not brand_column:
        return brand_column, [], []

    detected = sorted(
        {
            normalize_brand_name(value)
            for value in input_df[brand_column].dropna()
            if normalize_brand_name(value)
        }
    )
    blocked = [brand for brand in detected if brand not in allowed]
    return brand_column, detected, blocked


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

SIAL_COLUMNS = [
    "Cod. Modelo",
    "Cod. Color",
    "Talla",
    "Product Name ",
    "Product Bullets",
    "Product Description",
    "Image URL",
    "Product Weight",
    "Product Length",
    "Product Width",
    "Product Height",
    "Package Weight",
    "Package Length",
    "Package Width",
    "Package Height",
    "Boost ",
    "Talla Web ",
    "Color Web",
    "Categoria ",
    "Sub Categoria",
    "Genero",
    "Estilo ",
    "Colecciones ",
    "Temporada ",
    "Modelo",
    "Marca",
    "Tecnologias ",
    "Caracteristicas",
    "Tipo de Boardshort",
    "Tipo de Bikini",
    "Iniciativas",
    "Tipo de Material",
    "1",
    "Tipo de Prenda",
    "Adicional 2 ",
    "Adicional 3 ",
    "Adicional 4 ",
    "Adicional 5 ",
    "Adicional 6 ",
    "Adicional 7 ",
    "Adicional 8 ",
    "Adicional 9 ",
    "Adicional 10",
    "Mod-Col",
    "Sku - Sial",
    "Nuevo o Actualizar (Columbia.pe)",
    "Porduct Id - Columbia.pe",
    "Nuevo o Actualizar (Supermall.pe)",
    "Porduct Id - Supermall.pe",
    "Nuevo o Actualizar (Supermall.pe).1",
    "Porduct Id - Rockford.pe",
    "4",
    "13",
    "6",
]


def get_sial_columns(brand_config=None):
    brand_config = brand_config or get_brand_config()
    tail_start = SIAL_COLUMNS.index("Nuevo o Actualizar (Columbia.pe)")
    columns = SIAL_COLUMNS[:tail_start] + list(brand_config.get("sial_tail_columns") or SIAL_COLUMNS[tail_start:])
    deduped = []
    seen = set()
    for column in columns:
        if column in seen:
            continue
        deduped.append(column)
        seen.add(column)
    return deduped


def coalesce_duplicate_columns(df):
    if df is None or df.empty or not df.columns.duplicated().any():
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
            empty_mask = merged.map(clean) == ""
            merged.loc[empty_mask] = candidate.loc[empty_mask]
        result[column] = merged
    return result


BIGQUERY_ARTI_COLUMN_CANDIDATES = {
    "CODINT_MA": [
        "CODINT_MA",
        "codint_ma",
        "codint",
        "id_producto",
        "idproducto",
        "sku",
        "sku_producto",
    ],
    "COD MOD COL": [
        "COD MOD COL",
        "COD_MOD_COL",
        "cod_mod_col",
        "codmod_codcol",
        "codmod_ma_codcol_ma",
        "mod_col",
        "modelo_color",
        "codigo_modelo_color",
    ],
    "Mod-Col": [
        "Mod-Col",
        "MOD_COL",
        "mod_col",
        "codmod_codcol",
        "codmod_ma_codcol_ma",
        "modelo_color",
        "codigo_modelo_color",
    ],
    "TALNUM_MA": [
        "TALNUM_MA",
        "talnum_ma",
        "talla_numero",
        "talla",
        "size",
    ],
    "MARCA_MA": [
        "MARCA_MA",
        "marca_ma",
        "marca",
        "brand",
    ],
    "Precio": [
        "Precio",
        "precio_ma",
        "precio",
        "price",
        "precio_venta",
        "pvp",
    ],
    "CodBarras": [
        "CodBarras",
        "codbarras",
        "CODBARRAS",
        "cod_barras",
        "codigo_barras",
        "codigo_barra",
        "codigo de barras",
        "codigo de barra",
        "barcode",
        "bar_code",
        "ean",
        "EAN",
        "cod_ean",
        "codigo_ean",
        "upc",
        "UPC",
        "gtin",
        "ean13",
        "ean_13",
        "barra",
        "barras",
        "codbarra",
        "cod_barra",
        "codbar",
        "cod_bar",
        "codbar_ma",
        "cod_bar_ma",
        "CODBAR_MA",
        "COD_BAR_MA",
        "cod_barr",
        "codbarr",
        "cod_barras_ma",
        "codbarra_ma",
        "codbarras_ma",
        "barra_ma",
        "ean_ma",
        "ean_producto",
        "ean_prod",
        "ean_sku",
        "ean13_ma",
        "codigo_barra_producto",
        "codigo_barras_producto",
        "gtin_ma",
        "upc_ma",
        "upc_producto",
        "codigo_barras_ma",
        "codigo_de_barras",
        "codigo_de_barra",
        "codigo_ean13",
        "cod_ean13",
    ],
}

BIGQUERY_MODEL_COLUMN_CANDIDATES = [
    "codmod_ma",
    "cod_modelo",
    "codmodelo",
    "modelo_codigo",
]

BIGQUERY_COLOR_COLUMN_CANDIDATES = [
    "codcol_ma",
    "cod_color",
    "codcolor",
    "color_codigo",
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
        "job_project_id": os.getenv("BIGQUERY_JOB_PROJECT_ID", ""),
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


def _normalize_bigquery_name(value):
    return re.sub(r"[^a-z0-9]+", "", clean(value).lower())


def _find_bigquery_column(available_columns, candidates):
    by_normalized = {_normalize_bigquery_name(column): column for column in available_columns}
    for candidate in candidates:
        found = by_normalized.get(_normalize_bigquery_name(candidate))
        if found:
            return found
    return ""


def _find_bigquery_barcode_columns(available_columns):
    exact = _find_bigquery_column(available_columns, BIGQUERY_ARTI_COLUMN_CANDIDATES["CodBarras"])
    candidates = [exact] if exact else []
    tokens = ("ean", "barra", "barras", "barcode", "barcod", "upc", "gtin")
    for column in available_columns:
        normalized = _normalize_bigquery_name(column)
        if any(token in normalized for token in tokens):
            candidates.append(column)
    return list(dict.fromkeys([column for column in candidates if column]))


def normalize_arti_required_columns(df):
    if df is None or df.empty:
        return df
    result = coalesce_duplicate_columns(df).copy()
    for output_column, candidates in BIGQUERY_ARTI_COLUMN_CANDIDATES.items():
        if output_column not in result.columns:
            result[output_column] = ""
        for candidate in candidates:
            found = _find_bigquery_column(result.columns, [candidate])
            if not found or found == output_column:
                continue
            fill_mask = result[output_column].map(clean).eq("") & result[found].map(clean).ne("")
            if fill_mask.any():
                result.loc[fill_mask, output_column] = result.loc[fill_mask, found]
    barcode_candidates = _find_bigquery_barcode_columns(result.columns)
    for found in barcode_candidates:
        if found == "CodBarras":
            continue
        fill_mask = result["CodBarras"].map(clean).eq("") & result[found].map(clean).ne("")
        if fill_mask.any():
            result.loc[fill_mask, "CodBarras"] = result.loc[fill_mask, found]
    if ("Mod-Col" not in result.columns or not (result["Mod-Col"].map(clean) != "").any()) and "COD MOD COL" in result.columns:
        result["Mod-Col"] = result["COD MOD COL"]
    for column in ARTI_REQUIRED_COLUMNS:
        if column not in result.columns:
            result[column] = ""
    return result


def _bigquery_select_expression(output_column, source_column, composite_expression=""):
    if composite_expression:
        return f"{composite_expression} AS `{output_column}`"
    if source_column:
        return f"CAST(`{source_column}` AS STRING) AS `{output_column}`"
    return f"CAST(NULL AS STRING) AS `{output_column}`"


def _bigquery_model_color_expression(column_map, model_column, color_column):
    if column_map.get("COD MOD COL"):
        return ""
    if not model_column or not color_column:
        return ""
    return f"CONCAT(CAST(`{model_column}` AS STRING), '-', CAST(`{color_column}` AS STRING))"


def _read_arti_from_bigquery(config, brand_config=None):
    brand_config = brand_config or get_brand_config()
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

    job_project_id = clean(config.get("job_project_id")) or project_id
    client = bigquery.Client(project=job_project_id or None, credentials=credentials)
    job_project_id = job_project_id or client.project
    project_id = project_id or job_project_id
    query = clean(config.get("query"))
    if not query:
        dataset = clean(config.get("dataset"))
        table = clean(config.get("table"))
        table_id = table if table.count(".") == 2 else f"{project_id}.{dataset}.{table}"
        table_schema = client.get_table(table_id).schema
        available_columns = [field.name for field in table_schema]
        column_map = {
            output_column: _find_bigquery_column(available_columns, candidates)
            for output_column, candidates in BIGQUERY_ARTI_COLUMN_CANDIDATES.items()
        }
        barcode_columns = _find_bigquery_barcode_columns(available_columns)
        if barcode_columns:
            column_map["CodBarras"] = barcode_columns[0]
        model_column = _find_bigquery_column(available_columns, BIGQUERY_MODEL_COLUMN_CANDIDATES)
        color_column = _find_bigquery_column(available_columns, BIGQUERY_COLOR_COLUMN_CANDIDATES)
        model_color_expression = _bigquery_model_color_expression(column_map, model_column, color_column)
        if model_color_expression:
            column_map["COD MOD COL"] = "__MODEL_COLOR__"
            column_map["Mod-Col"] = "__MODEL_COLOR__"

        missing_required = [
            output_column
            for output_column in ("CODINT_MA", "COD MOD COL", "TALNUM_MA")
            if not column_map.get(output_column)
        ]
        if missing_required:
            raise RuntimeError(
                "No pude encontrar columnas necesarias en BigQuery: "
                f"{', '.join(missing_required)}. "
                f"Columnas disponibles: {', '.join(available_columns[:80])}"
            )

        if not column_map.get("Mod-Col"):
            column_map["Mod-Col"] = column_map["COD MOD COL"]

        select_lines = [
            _bigquery_select_expression(
                output_column,
                "" if column_map.get(output_column) == "__MODEL_COLOR__" else column_map.get(output_column),
                model_color_expression if column_map.get(output_column) == "__MODEL_COLOR__" else "",
            )
            for output_column in ARTI_REQUIRED_COLUMNS
        ]
        for index, barcode_column in enumerate(barcode_columns[1:20], start=2):
            select_lines.append(f"CAST(`{barcode_column}` AS STRING) AS `CodBarras_alt_{index}`")
        where_lines = [f"`{column_map['CODINT_MA']}` IS NOT NULL"]
        if model_color_expression:
            where_lines.extend([f"`{model_column}` IS NOT NULL", f"`{color_column}` IS NOT NULL"])
        else:
            where_lines.append(f"`{column_map['COD MOD COL']}` IS NOT NULL")
        if column_map.get("MARCA_MA") and brand_config.get("allowed_arti_brands"):
            allowed_brands = ", ".join(f"'{brand}'" for brand in brand_config["allowed_arti_brands"])
            where_lines.append(f"UPPER(CAST(`{column_map['MARCA_MA']}` AS STRING)) IN ({allowed_brands})")

        query = f"""
        SELECT
          {", ".join(select_lines)}
        FROM `{table_id}`
        WHERE {" AND ".join(where_lines)}
        """

    job_config = bigquery.QueryJobConfig(use_legacy_sql=False)
    query_job = client.query(query, job_config=job_config, location=clean(config.get("location")) or None)
    df = query_job.to_dataframe()
    df = normalize_arti_required_columns(df)
    source = clean(config.get("table")) or "query configurada"
    return df[ARTI_REQUIRED_COLUMNS].astype(object), f"BigQuery: {source}"


def read_arti_source(
    zip_path=DEFAULT_ARTI_ZIP_PATH,
    csv_path=DEFAULT_ARTI_CSV_PATH,
    xlsx_path=DEFAULT_ARTI_XLSX_PATH,
    bigquery_config=None,
    allow_local_fallback=True,
    brand_config=None,
):
    brand_config = brand_config or get_brand_config()
    if bigquery_config is None:
        bigquery_config = _bigquery_config_from_streamlit() or _bigquery_config_from_env()
    if _bigquery_configured(bigquery_config):
        try:
            return _read_arti_from_bigquery(bigquery_config, brand_config=brand_config)
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
    required_columns = [
        SIBLINGS_COLUMN,
        SIBLINGS_COLOR_COLUMN,
        CUSTOM_SIBLINGS_COLUMN,
        CUSTOM_SIBLINGS_COLOR_COLUMN,
        PUBLICATION_DATE_COLUMN,
    ]
    for column in required_columns:
        if column not in matrixify_columns:
            matrixify_columns.append(column)
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
                "Variant Price": valid_price(row.get("Variant Price")),
                "Variant Compare At Price": valid_price(row.get("Variant Compare At Price")),
            }

    return product_by_key, product_by_handle, variant_by_sku


def matrixify_rows_for_handle(matrixify_df, handle):
    if matrixify_df is None or matrixify_df.empty or "Handle" not in matrixify_df.columns:
        return pd.DataFrame()
    target_handle = clean(handle)
    if not target_handle:
        return pd.DataFrame()

    current_handle = ""
    matching_indexes = []
    for index, row in matrixify_df.iterrows():
        row_handle = clean(row.get("Handle"))
        if row_handle:
            current_handle = row_handle
        if current_handle == target_handle:
            matching_indexes.append(index)
    return matrixify_df.loc[matching_indexes].copy() if matching_indexes else pd.DataFrame()


def variant_payload_from_existing_row(row):
    return {
        "Variant Inventory Item ID": clean(row.get("Variant Inventory Item ID")),
        "Variant ID": clean(row.get("Variant ID")),
        "Variant SKU": clean(row.get("Variant SKU")),
        "Variant Image": row.get("Variant Image", ""),
        "Variant Price": valid_price(row.get("Variant Price")),
        "Variant Compare At Price": valid_price(row.get("Variant Compare At Price")),
    }


def variant_size_lookup_keys(value):
    keys = []
    raw = clean(value).upper()
    normalized = clean(normalize_size(value)).upper()
    aliases = {
        "SX": "XS",
        "XS": "SX",
        "OS": "O/S",
        "O/S": "OS",
        "UNICA": "O/S",
        "ÚNICA": "O/S",
        "ÃšNICA": "O/S",
        "TALLA UNICA": "O/S",
        "TALLA ÚNICA": "O/S",
        "TALLA ÃšNICA": "O/S",
        "0": "O/S",
        "000": "O/S",
    }
    for key in (raw, normalized, aliases.get(raw, ""), aliases.get(normalized, "")):
        if key and key not in keys:
            keys.append(key)
    return keys


def build_product_variant_lookup(existing_rows):
    variant_by_product_sku = {}
    variant_by_product_size = {}
    if existing_rows is None or existing_rows.empty:
        return variant_by_product_sku, variant_by_product_size

    for _, existing_row in existing_rows.iterrows():
        payload = variant_payload_from_existing_row(existing_row)
        sku = clean(existing_row.get("Variant SKU"))
        if sku and sku not in variant_by_product_sku:
            variant_by_product_sku[sku] = payload
        for size_key in variant_size_lookup_keys(existing_row.get("Option1 Value")):
            if size_key not in variant_by_product_size:
                variant_by_product_size[size_key] = payload
    return variant_by_product_sku, variant_by_product_size


def variant_without_sku_by_size(variant_by_product_size, value):
    for size_key in variant_size_lookup_keys(value):
        variant = variant_by_product_size.get(size_key)
        if variant and not clean(variant.get("Variant SKU")):
            return variant
    return {}


def first_valid_product_price(existing_rows):
    if existing_rows is None or existing_rows.empty or "Variant Price" not in existing_rows.columns:
        return ""
    for value in existing_rows["Variant Price"]:
        price = valid_price(value)
        if price:
            return price
    return ""


def product_publication_date(product):
    for column in PUBLICATION_DATE_CANDIDATES:
        value = clean(product.get(column))
        if value:
            return value
    by_normalized = {normalize_header_key(column): column for column in getattr(product, "index", [])}
    for column in PUBLICATION_DATE_CANDIDATES:
        found = by_normalized.get(normalize_header_key(column))
        if found is not None:
            value = clean(product.get(found))
            if value:
                return value
    return ""


def row_first_existing(product, candidates):
    for column in candidates:
        value = clean(product.get(column))
        if value:
            return value
    by_normalized = {normalize_header_key(column): column for column in getattr(product, "index", [])}
    for column in candidates:
        found = by_normalized.get(normalize_header_key(column))
        if found is not None:
            value = clean(product.get(found))
            if value:
                return value
    return ""


def find_technology_column(df):
    direct = first_existing(df, ["METAFIELD TECNOLOGÍAS", "METAFIELD TECNOLOGIAS", "Tecnologias ", "Tecnologías"])
    if direct:
        return direct
    for column in df.columns:
        key = normalize_header_key(column)
        if key in ("metafieldtecnologias", "metafieldtecnologas", "tecnologias", "tecnologas", "tecnologia"):
            return column
        if key.startswith("metafieldtecnolog") or key in ("tecnolog", "tecnologas"):
            return column
    return ""


def fill_top_row_product_fields(output_df, input_df, tech_col=None):
    if output_df is None or output_df.empty or input_df is None or input_df.empty:
        return output_df
    if PRODUCT_KEY_COLUMN not in output_df.columns:
        return output_df

    tech_by_key = {}
    publication_by_key = {}
    for _, product in input_df.iterrows():
        key = clean(product.get("__KEY")) or clean(product.get("Mod-Col")).upper()
        if not key:
            continue
        tech_by_key[key] = row_first_existing(product, [tech_col, find_technology_column(input_df)])
        publication_by_key[key] = product_publication_date(product)

    if "Handle" in output_df.columns:
        top_mask = output_df["Handle"].map(clean) != ""
    else:
        top_mask = pd.Series([True] * len(output_df), index=output_df.index)

    for idx, row in output_df[top_mask].iterrows():
        key = clean(row.get(PRODUCT_KEY_COLUMN)).upper()
        technology_value = tech_by_key.get(key, "")
        if technology_value:
            logo_col = "Metafield: custom.logo [list.metaobject_reference]"
            tech_field_col = "Metafield: custom.tecnologia [list.single_line_text_field]"
            if logo_col in output_df.columns and not clean(row.get(logo_col)):
                output_df.at[idx, logo_col] = format_technology_logos(technology_value)
            if tech_field_col in output_df.columns and not clean(row.get(tech_field_col)):
                output_df.at[idx, tech_field_col] = format_technology(technology_value)
        publication_date = publication_by_key.get(key, "")
        if publication_date and PUBLICATION_DATE_COLUMN in output_df.columns and not clean(row.get(PUBLICATION_DATE_COLUMN)):
            output_df.at[idx, PUBLICATION_DATE_COLUMN] = publication_date
    return output_df


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


PRODUCT_KEY_COLUMN = "Metafield: custom.codigo_modelo_color [id]"
SIBLINGS_COLUMN = "Metafield: theme.siblings [single_line_text_field]"
SIBLINGS_COLOR_COLUMN = "Metafield: theme.siblings_color [single_line_text_field]"
CUSTOM_SIBLINGS_COLUMN = "Metafield: custom.siblings [single_line_text_field]"
CUSTOM_SIBLINGS_COLOR_COLUMN = "Metafield: custom.siblings_color [single_line_text_field]"
PUBLICATION_DATE_COLUMN = "Publication Publish Date"
PUBLICATION_DATE_CANDIDATES = [
    "Publication Publish Date",
    "Fecha publicación",
    "Fecha publicacion",
    "Fecha de publicación",
    "Fecha de publicacion",
    "Publish Date",
    "Publication Date",
    "Published At",
]


def _catalog_product_rows(matrixify_df):
    if matrixify_df is None or matrixify_df.empty:
        return pd.DataFrame()
    df = matrixify_df.copy()
    if "Handle" not in df.columns:
        return pd.DataFrame()
    df["__HANDLE_CLEAN"] = df["Handle"].map(clean)
    df = df[df["__HANDLE_CLEAN"] != ""].copy()
    return df.drop_duplicates(subset=["__HANDLE_CLEAN"], keep="first").copy()


def _catalog_lookup(matrixify_df):
    product_rows = _catalog_product_rows(matrixify_df)
    by_key = {}
    by_handle = {}
    for _, row in product_rows.iterrows():
        handle = clean(row.get("Handle"))
        key = clean(row.get(PRODUCT_KEY_COLUMN)).upper()
        payload = row.to_dict()
        if handle:
            by_handle[handle] = payload
        if key:
            by_key[key] = payload
    return by_key, by_handle, product_rows


def _source_key(row):
    return first_non_empty(row.get("Mod-Col"), row.get("COD MOD COL"), row.get(PRODUCT_KEY_COLUMN)).upper()


def _minimal_product_update(row, extra):
    payload = {
        "ID": clean(row.get("ID")),
        "Handle": clean(row.get("Handle")),
        "Command": "MERGE",
    }
    payload.update(extra)
    return payload


def _new_tags(current_tags, incoming_tags, mode):
    current = [tag.strip() for tag in clean(current_tags).split(",") if tag.strip()]
    incoming = [tag.strip() for tag in clean(incoming_tags).split(",") if tag.strip()]
    if mode == "replace":
        return ", ".join(dict.fromkeys(incoming))
    return ", ".join(dict.fromkeys(current + incoming))


def _split_labeled_body_text(text):
    text = strip_html(text)
    if not text:
        return "", "", ""
    pattern = re.compile(
        r"(?:^|\s)(Caracter[iÃ]sticas|Características|Material(?:es)?|Cuidado(?:s)?):?\s*",
        flags=re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return text, "", ""

    sections = {"features": "", "material": "", "care": ""}
    for index, match in enumerate(matches):
        label = normalize_text(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        value = text[start:end].strip(" :-")
        if "material" in label:
            sections["material"] = value
        elif "cuidado" in label:
            sections["care"] = value
        else:
            sections["features"] = value
    if not sections["features"] and matches[0].start() > 0:
        sections["features"] = text[: matches[0].start()].strip(" :-")
    return sections["features"], sections["material"], sections["care"]


def _body_needs_material_care_fix(value):
    text = normalize_text(strip_html(value))
    if not text:
        return False
    has_material = "material" in text or "materiales" in text
    has_care = "cuidado" in text or "cuidados" in text
    has_sections = "nweb__materiales" in clean(value).lower() and "nweb__cuidados" in clean(value).lower()
    return (has_material or has_care) and not has_sections


def _build_update_source(input_df, matrixify_df):
    if input_df is not None and not input_df.empty:
        return input_df.dropna(how="all").copy(), "input"
    return _catalog_product_rows(matrixify_df), "catalog"


def _arti_brand_by_key(arti):
    if arti is None or arti.empty or "MARCA_MA" not in arti.columns:
        return {}
    df = arti.copy()
    if "Mod-Col" not in df.columns:
        df["Mod-Col"] = ""
    if "COD MOD COL" not in df.columns:
        df["COD MOD COL"] = ""
    df["__KEY"] = df["Mod-Col"].where(df["Mod-Col"].map(clean) != "", df["COD MOD COL"]).map(lambda value: clean(value).upper())
    df = df[(df["__KEY"] != "") & (df["MARCA_MA"].map(clean) != "")].copy()
    return df.drop_duplicates(subset=["__KEY"]).set_index("__KEY")["MARCA_MA"].to_dict()


def build_matrixify_updates(
    matrixify_source,
    update_input_df=None,
    arti=None,
    operation="tags",
    brand_config=None,
    tag_mode="merge",
    image_mode="replace",
    only_missing_images=True,
    body_mode="from_input",
):
    brand_config = brand_config or get_brand_config()
    matrixify_df = matrixify_source.copy() if isinstance(matrixify_source, pd.DataFrame) else pd.DataFrame()
    by_key, by_handle, catalog_products = _catalog_lookup(matrixify_df)
    source_df, source_type = _build_update_source(update_input_df, matrixify_df)
    operation = clean(operation).lower()
    brand_by_key = _arti_brand_by_key(arti)

    rows = []
    issues = []
    seen_handles = set()

    if operation == "siblings":
        products = catalog_products.copy()
        if products.empty:
            return pd.DataFrame(), pd.DataFrame([{"Problema": "Catalogo Matrixify sin productos validos"}])
        products["__KEY"] = products[PRODUCT_KEY_COLUMN].map(lambda value: clean(value).upper()) if PRODUCT_KEY_COLUMN in products.columns else ""
        products["__MODEL"] = products["__KEY"].map(model_code)
        siblings_by_model = (
            products[products["__MODEL"] != ""]
            .groupby("__MODEL")["Handle"]
            .apply(lambda values: ", ".join(dict.fromkeys(clean(value) for value in values if clean(value))))
            .to_dict()
        )
        for _, product in products.iterrows():
            model = product.get("__MODEL", "")
            if not model or model not in siblings_by_model:
                continue
            handle = clean(product.get("Handle"))
            if handle in seen_handles:
                continue
            seen_handles.add(handle)
            rows.append(
                _minimal_product_update(
                    product,
                    {
                        SIBLINGS_COLUMN: siblings_by_model[model],
                        SIBLINGS_COLOR_COLUMN: clean(product.get(SIBLINGS_COLOR_COLUMN)),
                        CUSTOM_SIBLINGS_COLUMN: siblings_by_model[model],
                        CUSTOM_SIBLINGS_COLOR_COLUMN: clean(product.get(CUSTOM_SIBLINGS_COLOR_COLUMN))
                        or clean(product.get(SIBLINGS_COLOR_COLUMN)),
                    },
                )
            )
        return pd.DataFrame(rows), pd.DataFrame(issues)

    for input_index, source_row in source_df.iterrows():
        key = _source_key(source_row)
        handle = clean(source_row.get("Handle"))
        catalog_row = by_key.get(key) or by_handle.get(handle)
        if not catalog_row:
            issues.append(
                {
                    "Mod-Col": key,
                    "Handle": handle,
                    "Problema": "No se encontro el producto en el catalogo Matrixify",
                    "Fila": input_index + 2,
                }
            )
            continue

        catalog_handle = clean(catalog_row.get("Handle"))
        if catalog_handle in seen_handles:
            continue
        seen_handles.add(catalog_handle)

        if operation == "tags":
            tags_col = first_existing(source_df, ["Tags", "tags", "Etiquetas"])
            if not tags_col:
                issues.append({"Mod-Col": key, "Handle": catalog_handle, "Problema": "No se encontro columna Tags"})
                continue
            tags = _new_tags(catalog_row.get("Tags"), source_row.get(tags_col), tag_mode)
            rows.append(
                _minimal_product_update(
                    catalog_row,
                    {
                        "Tags": tags,
                        "Tags Command": "REPLACE",
                    },
                )
            )
        elif operation == "photos":
            product_key = key or clean(catalog_row.get(PRODUCT_KEY_COLUMN)).upper()
            source_brand = first_non_empty(
                source_row.get("Marca"),
                source_row.get("Brand"),
                catalog_row.get("Metafield: custom.marca [single_line_text_field]"),
                brand_by_key.get(product_key),
            )
            row_brand_config = brand_image_config(source_brand, brand_config)
            urls = image_candidates(product_key, row_brand_config)
            current_image = clean(catalog_row.get("Image Src"))
            if only_missing_images and current_image:
                continue
            rows.append(
                _minimal_product_update(
                    catalog_row,
                    {
                        "Image Src": "; ".join(urls),
                        "Image Command": "REPLACE" if image_mode == "replace" else "MERGE",
                        "Image Position": "",
                        "Image Alt Text": first_non_empty(
                            source_row.get("Image Alt Text"),
                            catalog_row.get("Image Alt Text"),
                            catalog_row.get("Title"),
                        ),
                    },
                )
            )
        elif operation == "title":
            title_col = first_existing(source_df, ["Title", "Titulo", "Título", "Nombre"])
            if not title_col:
                issues.append({"Mod-Col": key, "Handle": catalog_handle, "Problema": "No se encontro columna Title"})
                continue
            rows.append(_minimal_product_update(catalog_row, {"Title": clean(source_row.get(title_col))}))
        elif operation == "body":
            if body_mode == "from_input":
                body_html = build_body_html(source_row)
                if not body_html:
                    issues.append(
                        {"Mod-Col": key, "Handle": catalog_handle, "Problema": "No hay Body HTML/Caracteristicas/Material/Cuidado para construir"}
                    )
                    continue
            else:
                current_body = clean(catalog_row.get("Body HTML"))
                if not _body_needs_material_care_fix(current_body):
                    continue
                features, material, care = _split_labeled_body_text(current_body)
                body_html = build_body_html(
                    {
                        "Body HTML": "",
                        "Caracteristicas": features,
                        "Material": material,
                        "Cuidado": care,
                    }
                )
                if not body_html:
                    continue
            rows.append(_minimal_product_update(catalog_row, {"Body HTML": body_html}))
        else:
            issues.append({"Problema": f"Operacion no soportada: {operation}"})
            break

    output_df = pd.DataFrame(rows)
    issues_df = pd.DataFrame(issues)
    return output_df, issues_df


def build_columbia_matrixify(input_df, arti, matrixify_source, brand_config=None):
    brand_config = brand_config or get_brand_config()
    matrixify_columns, matrixify_df = prepare_matrixify_context(matrixify_source)
    product_by_key, product_by_handle, variant_by_sku = build_existing_lookup(matrixify_df)

    input_df = ensure_mod_col_column(input_df.dropna(how="all").copy())
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
    brand_column = detect_brand_column(input_df)
    image_lookup = build_image_lookup_by_brand(input_df, brand_column, brand_config)
    wanted_keys = set(input_df["__KEY"])
    arti = arti.copy()
    if "MARCA_MA" in arti.columns and brand_config.get("allowed_arti_brands"):
        allowed_brands = set(brand_config["allowed_arti_brands"])
        brand_mask = arti["MARCA_MA"].map(normalize_brand_name).isin(allowed_brands)
        if brand_mask.any():
            arti = arti[brand_mask].copy()
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
    arti["__SIAL_SIZE"] = arti["TALNUM_MA"].map(clean)
    arti["__SIZE"] = arti["TALNUM_MA"].map(normalize_size)
    invalid_size_rows = arti[arti["__SIZE"].map(clean) == ""].copy()
    arti = arti[arti["__SIZE"] != ""].copy()
    arti = arti.sort_values(by=["__KEY", "__SIZE"], key=lambda series: series.map(size_sort_key))

    tech_col = find_technology_column(input_df)
    rows = []
    sial_rows = []
    issues = []
    skipped_rows = []

    for input_index, product in input_df.iterrows():
        key = product["__KEY"]
        invalid_sizes_for_key = invalid_size_rows[invalid_size_rows["__KEY"] == key] if not invalid_size_rows.empty else pd.DataFrame()
        if not invalid_sizes_for_key.empty:
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Se omitieron filas de BigQuery/ARTI con talla vacia o no reconocida",
                    "Fila input": input_index + 2,
                    "Cantidad": safe_int(len(invalid_sizes_for_key)),
                }
            )
        variants = arti[arti["__KEY"] == key].copy()
        if "__SIZE" in variants.columns:
            one_size_mask = boolean_mask(variants["__SIZE"], is_one_size)
            zero_size_mask = boolean_mask(variants["__SIZE"], is_zero_size)
            internal_k_size_mask = boolean_mask(variants["__SIZE"], is_internal_k_size)
        else:
            one_size_mask = pd.Series(False, index=variants.index)
            zero_size_mask = pd.Series(False, index=variants.index)
            internal_k_size_mask = pd.Series(False, index=variants.index)
        has_one_size = bool(one_size_mask.any())
        one_size_zero_count = safe_int(zero_size_mask.sum()) if has_one_size else 0
        if one_size_zero_count:
            variants = variants[~zero_size_mask].copy()
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Se omitio talla 0/000 porque el producto tambien tiene O/S",
                    "Fila input": input_index + 2,
                    "Cantidad": one_size_zero_count,
                }
            )
            zero_size_mask = boolean_mask(variants["__SIZE"], is_zero_size) if "__SIZE" in variants.columns else pd.Series(False, index=variants.index)
            internal_k_size_mask = boolean_mask(variants["__SIZE"], is_internal_k_size) if "__SIZE" in variants.columns else pd.Series(False, index=variants.index)
        should_block_zero_size = category_blocks_zero_size(product) and clean(brand_config.get("site_label")) != "Rockford.pe"
        zero_size_count = safe_int(zero_size_mask.sum()) if should_block_zero_size else 0
        internal_k_size_count = safe_int(internal_k_size_mask.sum())
        if zero_size_count:
            variants = variants[~zero_size_mask].copy()
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Se omitieron variantes con talla 0 en vestuario/calzado",
                    "Fila input": input_index + 2,
                    "Cantidad": zero_size_count,
                }
            )
            internal_k_size_mask = boolean_mask(variants["__SIZE"], is_internal_k_size) if "__SIZE" in variants.columns else pd.Series(False, index=variants.index)
        if internal_k_size_count:
            variants = variants[~internal_k_size_mask].copy()
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Se omitieron variantes con talla interna K",
                    "Fila input": input_index + 2,
                    "Cantidad": internal_k_size_count,
                }
            )
        if variants.empty:
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Sin variantes validas en ARTI/BigQuery",
                    "Fila input": input_index + 2,
                }
            )
            continue

        variants = dedupe_variants_for_shopify(
            variants,
            brand_config=brand_config,
            issues=issues,
            key=key,
            input_index=input_index,
        )
        if variants.empty:
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": "Todas las variantes fueron omitidas por duplicidad de SKU",
                    "Fila input": input_index + 2,
                }
            )
            continue
        variants = variants.sort_values("__SIZE", key=lambda series: series.map(size_sort_key))

        variant_brand_raw, variant_brand_names = brand_from_variants(variants)
        if len(variant_brand_names) > 1:
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": f"BigQuery/ARTI tiene mas de una marca para el mismo modelo-color: {', '.join(variant_brand_names)}",
                    "Fila input": input_index + 2,
                }
            )
        product_brand_raw = variant_brand_raw or (product.get(brand_column) if brand_column else "")
        handle = product["__HANDLE"]
        product_image_config = brand_image_config(product_brand_raw, brand_config)
        image_cache_key = (key, product_image_config["image_folder"])
        if image_cache_key not in image_lookup:
            image_lookup[image_cache_key] = build_image_lookup([key], brand_config=product_image_config).get(key, [])
        product_images = image_lookup.get(image_cache_key, [])
        if not product_images:
            issues.append(
                {
                    "Mod-Col": key,
                    "Problema": f"Sin fotos validas en la ruta {product_image_config['image_folder']}",
                    "Fila input": input_index + 2,
                }
            )
        title = clean(product.get("Title"))
        body_html = build_body_html(product)
        tags = clean(product.get("Tags"))
        product_type = clean(product.get("Type"))
        technology_value = row_first_existing(
            product,
            [tech_col, "METAFIELD TECNOLOGÍAS", "METAFIELD TECNOLOGIAS", "Tecnologias ", "Tecnologías"],
        )
        color_web = clean(product.get("Color Web"))
        product_brand_label = brand_display_name(product_brand_raw, brand_config["label"])
        publication_date = product_publication_date(product)
        siblings_value = siblings_by_model.get(product["__MODEL"], handle)
        image_alt = f"{title} {color_web}".strip()
        existing_product = product_by_key.get(key) or product_by_handle.get(handle) or {}
        existing_handle = existing_product.get("Handle") or handle
        existing_rows = matrixify_rows_for_handle(matrixify_df, existing_handle)
        existing_variant_by_sku, existing_variant_by_size = build_product_variant_lookup(existing_rows)
        product_price_fallback = first_valid_product_price(existing_rows)
        product_rows = []
        product_sial_rows = []

        for position, (_, variant) in enumerate(variants.iterrows(), start=1):
            if is_internal_k_size(variant.get("__SIZE")) or is_internal_k_size(variant.get("TALNUM_MA")):
                continue
            if should_block_zero_size and (
                is_zero_size(variant.get("__SIZE")) or is_zero_size(variant.get("TALNUM_MA"))
            ):
                continue

            is_first = position == 1
            display_size = display_size_for_site(variant["__SIZE"], brand_config)
            output = {column: "" for column in matrixify_columns}
            variant_sku = clean(variant.get("CODINT_MA"))
            existing_variant = (
                existing_variant_by_sku.get(variant_sku, {})
                or variant_without_sku_by_size(existing_variant_by_size, display_size)
                or variant_by_sku.get(variant_sku, {})
            )
            variant_price = (
                valid_price(variant.get("Precio"))
                or valid_price(existing_variant.get("Variant Price"))
                or product_price_fallback
            )
            variant_compare_at_price = valid_price(existing_variant.get("Variant Compare At Price"))

            output.update(
                {
                    "ID": existing_product.get("ID", ""),
                    "Handle": handle,
                    "Command": "MERGE",
                    "Title": title,
                    "Body HTML": body_html if is_first else "",
                    "Vendor": product_brand_label,
                    "Type": product_type,
                    "Tags": tags,
                    "Tags Command": "REPLACE",
                    "Status": "Active",
                    "Published": "TRUE" if variant_price else "FALSE",
                    "Created At": existing_product.get("Created At", ""),
                    "Updated At": existing_product.get("Updated At", ""),
                    "Published At": existing_product.get("Published At", ""),
                    PUBLICATION_DATE_COLUMN: publication_date,
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
                    "Option1 Value": display_size,
                    "Variant Position": position,
                    "Variant SKU": variant_sku,
                    "Variant Barcode": clean(variant.get("CodBarras")),
                    "Variant Image": existing_variant.get("Variant Image", ""),
                    "Variant Price": variant_price,
                    "Variant Compare At Price": variant_compare_at_price,
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
                        "Metafield: theme.siblings [single_line_text_field]": siblings_value,
                        "Metafield: custom.siblings_color [single_line_text_field]": color_web,
                        "Metafield: custom.siblings [single_line_text_field]": siblings_value,
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
                        "Metafield: custom.materialidad [single_line_text_field]": clean(
                            product.get("Metafield: custom.materialidad [single_line_text_field]")
                        ),
                        "Metafield: custom.marca [single_line_text_field]": product_brand_label,
                        "Metafield: custom.sub_categoria [single_line_text_field]": clean(
                            product.get("Metafield: custom.sub_categoria [single_line_text_field]")
                        )
                        or product_type,
                        "Metafield: custom.categoria [single_line_text_field]": clean(
                            product.get("Metafield: custom.categoria [single_line_text_field]")
                        ),
                        "Metafield: custom.guia_de_tallas [page_reference]": clean(
                            product.get("Metafield: custom.guia_de_tallas [page_reference]")
                        ),
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
            product_sial_rows.append(
                build_sial_row(product, variant, key, product_images, existing_product, tech_col, brand_config, product_brand_label)
            )

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
        sial_rows.extend(product_sial_rows)

    output_df = pd.DataFrame(rows, columns=matrixify_columns)
    output_df = fill_top_row_product_fields(output_df, input_df, tech_col)
    sial_df = pd.DataFrame(sial_rows, columns=get_sial_columns(brand_config))
    sial_df = coalesce_duplicate_columns(sial_df)
    issues_df = pd.DataFrame(issues)
    output_df, sial_df, issues_df = final_variant_filter(output_df, sial_df, issues_df)
    output_df = fill_top_row_product_fields(output_df, input_df, tech_col)
    sial_df = coalesce_duplicate_columns(sial_df)
    skipped_df = pd.DataFrame(
        skipped_rows,
        columns=["Mod-Col", "Handle", "Filas omitidas", "Motivo"],
    )
    type_warnings_df = build_new_type_warnings(input_df)
    summary_df = pd.DataFrame(
        [
            {"Metrica": "Productos input", "Valor": len(input_df)},
            {"Metrica": "Sitio destino", "Valor": brand_config["site_label"]},
            {"Metrica": "Productos con match ARTI", "Valor": output_df["Handle"].nunique() if len(output_df) else 0},
            {"Metrica": "Filas variantes Matrixify", "Valor": len(output_df)},
            {"Metrica": "Filas Carga Sial", "Valor": len(sial_df)},
            {"Metrica": "Productos omitidos sin cambios", "Valor": len(skipped_df)},
            {
                "Metrica": "Filas omitidas sin cambios",
                "Valor": safe_int(skipped_df["Filas omitidas"].sum()) if len(skipped_df) else 0,
            },
            {
                "Metrica": "Productos existentes con ID",
                "Valor": output_df.loc[output_df["ID"].map(clean) != "", "Handle"].nunique()
                if "ID" in output_df.columns and len(output_df)
                else 0,
            },
            {
                "Metrica": "Variantes existentes con Variant ID",
                "Valor": safe_int((output_df["Variant ID"].map(clean) != "").sum())
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
    return output_df, summary_df, issues_df, type_warnings_df, skipped_df, sial_df


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    template = pd.read_excel(TEMPLATE_PATH, sheet_name="Products", dtype=object)

    input_df = pd.read_excel(INPUT_PATH, sheet_name=0, dtype=object)

    arti, arti_source = read_arti_source()

    output_df, summary_df, issues_df, type_warnings_df, skipped_df, sial_df = build_columbia_matrixify(
        input_df, arti, template
    )

    output_path = available_output_path(OUTPUT_PATH)
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        output_df.to_excel(writer, sheet_name="Products", index=False)
        summary_df.to_excel(writer, sheet_name="Resumen", index=False)
        issues_df.to_excel(writer, sheet_name="Revision", index=False)
        sial_df.to_excel(writer, sheet_name="Carga Sial", index=False)
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
