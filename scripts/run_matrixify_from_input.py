import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app_matrixify import (
    apply_shopify_siblings_to_matrixify,
    build_centry_from_matrixify,
    coalesce_duplicate_columns,
    columbia_to_excel_bytes,
    shopify_products_to_matrixify_df,
)
from generate_columbia_matrixify import build_columbia_matrixify, get_brand_config, read_arti_source
from shopify_api import fetch_products, normalize_shop_domain


SITE_ENV_PREFIXES = {
    "columbia": ["COLUMBIA"],
    "rockford": ["ROCKFORD"],
    "hush_puppies": ["HUSHPUPPIES", "HUSH_PUPPIES"],
    "vans": ["VANS"],
}


def clean(value):
    if value is None:
        return ""
    return str(value).strip()


def normalize_site_key(value):
    text = clean(value).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "hushpuppies": "hush_puppies",
        "hush_puppies_pe": "hush_puppies",
        "columbia_pe": "columbia",
        "rockford_pe": "rockford",
        "vans_pe": "vans",
    }
    return aliases.get(text, text)


def read_excel_first_sheet(path, sheet_name=0):
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No existe el archivo input: {path}")
    df = pd.read_excel(path, sheet_name=sheet_name, dtype=object)
    if isinstance(df, dict):
        df = next(iter(df.values()), pd.DataFrame())
    return df.dropna(how="all")


def first_env(names):
    for name in names:
        value = clean(os.getenv(name))
        if value:
            return value
    return ""


def ensure_bigquery_credentials_env():
    if clean(os.getenv("BIGQUERY_SERVICE_ACCOUNT_JSON")):
        return
    google_json = clean(os.getenv("GOOGLE_CREDENTIALS_JSON") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON"))
    if google_json:
        os.environ["BIGQUERY_SERVICE_ACCOUNT_JSON"] = google_json
        return
    credentials_path = Path("credentials.json")
    if credentials_path.exists():
        os.environ["BIGQUERY_SERVICE_ACCOUNT_JSON"] = credentials_path.read_text(encoding="utf-8")


def shopify_config_from_env(site_key):
    prefixes = SITE_ENV_PREFIXES.get(site_key, [site_key.upper()])
    domain = first_env([f"{prefix}_SHOP_DOMAIN" for prefix in prefixes] + ["SHOPIFY_STORE", "SHOPIFY_SHOP_DOMAIN"])
    token = first_env(
        [
            f"{prefix}_ADMIN_API_ACCESS_TOKEN"
            for prefix in prefixes
        ]
        + [f"{prefix}_ADMIN_ACCESS_TOKEN" for prefix in prefixes]
        + [f"{prefix}_ACCESS_TOKEN" for prefix in prefixes]
        + ["SHOPIFY_TOKEN", "SHOPIFY_ADMIN_API_ACCESS_TOKEN", "SHOPIFY_ADMIN_ACCESS_TOKEN"]
    )
    location_ids = first_env(
        [f"{prefix}_INVENTORY_LOCATION_IDS" for prefix in prefixes]
        + [f"{prefix}_LOCATION_IDS" for prefix in prefixes]
        + ["INVENTORY_LOCATION_IDS", "LOCATION_IDS"]
    )
    return {
        "shop_domain": normalize_shop_domain(domain),
        "admin_access_token": token,
        "api_version": clean(os.getenv("API_VERSION")) or "2026-04",
        "inventory_location_ids": location_ids,
    }


def load_matrixify_context(args, site_key):
    if args.template_file:
        return read_excel_first_sheet(args.template_file, sheet_name="Products"), []

    shopify_config = shopify_config_from_env(site_key)
    if not shopify_config.get("shop_domain") or not shopify_config.get("admin_access_token"):
        raise RuntimeError(
            "Falta template_file o secrets de Shopify. "
            "Configura <SITIO>_SHOP_DOMAIN y <SITIO>_ADMIN_API_ACCESS_TOKEN en GitHub Actions."
        )
    products = fetch_products(shopify_config)
    return shopify_products_to_matrixify_df(products), products


def main():
    parser = argparse.ArgumentParser(
        description="Genera Matrixify/Centry/Sial desde un input comercial, sin SQLite ni FastAPI."
    )
    parser.add_argument("--site-key", required=True, help="columbia, rockford, hush_puppies o vans")
    parser.add_argument("--input-file", required=True, help="Ruta del Excel comercial dentro del repo")
    parser.add_argument("--template-file", default="", help="Opcional: respaldo Matrixify con hoja Products")
    parser.add_argument("--output-dir", default="job_outputs", help="Carpeta de salida")
    parser.add_argument("--output-name", default="", help="Nombre del Excel generado")
    args = parser.parse_args()

    site_key = normalize_site_key(args.site_key)
    brand_config = get_brand_config(site_key)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    input_df = read_excel_first_sheet(args.input_file)
    template_df, shopify_products = load_matrixify_context(args, site_key)
    ensure_bigquery_credentials_env()
    arti_df, arti_source = read_arti_source(
        allow_local_fallback=False,
        brand_config=brand_config,
    )

    matrixify_df, summary_df, issues_df, type_warnings_df, skipped_df, sial_df = build_columbia_matrixify(
        input_df,
        arti_df,
        template_df,
        brand_config=brand_config,
    )

    matrixify_df = coalesce_duplicate_columns(matrixify_df)
    summary_df = coalesce_duplicate_columns(summary_df)
    issues_df = coalesce_duplicate_columns(issues_df)
    type_warnings_df = coalesce_duplicate_columns(type_warnings_df)
    skipped_df = coalesce_duplicate_columns(skipped_df)
    sial_df = coalesce_duplicate_columns(sial_df)

    if shopify_products:
        matrixify_df = apply_shopify_siblings_to_matrixify(matrixify_df, shopify_products)

    centry_df, centry_issues_df = build_centry_from_matrixify(
        matrixify_df,
        brand_config,
        arti_df=arti_df,
    )

    output_name = clean(args.output_name) or brand_config.get("output_filename") or f"matrixify_{site_key}.xlsx"
    output_path = output_dir / output_name
    excel_buffer = columbia_to_excel_bytes(
        matrixify_df,
        summary_df,
        issues_df,
        type_warnings_df,
        skipped_df,
        sial_df,
        centry_df,
        centry_issues_df,
    )
    output_path.write_bytes(excel_buffer.getvalue())

    report = {
        "status": "ok",
        "site_key": site_key,
        "site_label": brand_config.get("site_label"),
        "input_file": str(Path(args.input_file)),
        "output_file": str(output_path),
        "arti_source": arti_source,
        "input_rows": int(len(input_df)),
        "matrixify_rows": int(len(matrixify_df)),
        "products": int(matrixify_df["Handle"].nunique()) if "Handle" in matrixify_df.columns else 0,
        "issues": int(len(issues_df)),
        "skipped": int(len(skipped_df)),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "run_summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
