import os
import re
from pathlib import Path

import pandas as pd

from app_matrixify import apply_full_product_updates, dataframe_to_excel_bytes
from job_store import OUTPUT_DIR, add_event, get_job, update_job


def _env_name(site_key, suffix):
    site = re.sub(r"[^A-Za-z0-9]+", "_", str(site_key or "")).strip("_").upper()
    return f"{site}_{suffix}" if site else suffix


def shopify_config_from_env(site_key):
    """Read Shopify credentials from environment variables.

    Site-specific variables win over generic variables. For example:
    COLUMBIA_SHOP_DOMAIN, COLUMBIA_ADMIN_API_ACCESS_TOKEN,
    COLUMBIA_INVENTORY_LOCATION_IDS.
    """
    def pick(name, default=""):
        return os.getenv(_env_name(site_key, name)) or os.getenv(name) or default

    return {
        "shop_domain": pick("SHOP_DOMAIN") or pick("SHOPIFY_SHOP_DOMAIN"),
        "admin_api_access_token": pick("ADMIN_API_ACCESS_TOKEN") or pick("SHOPIFY_ADMIN_API_ACCESS_TOKEN"),
        "api_version": pick("API_VERSION", "2026-04") or "2026-04",
        "inventory_location_ids": pick("INVENTORY_LOCATION_IDS") or pick("SHOPIFY_INVENTORY_LOCATION_IDS"),
    }


def read_matrixify_excel(path, sheet_name="Products"):
    path = Path(path)
    try:
        return pd.read_excel(path, sheet_name=sheet_name, dtype=object).dropna(how="all")
    except ValueError:
        return pd.read_excel(path, sheet_name=0, dtype=object).dropna(how="all")


def summarize_result(result_df):
    if result_df is None or result_df.empty or "Resultado" not in result_df.columns:
        return {"total": 0, "ok": 0, "partial": 0, "errors": 0, "skipped": 0}
    result = result_df["Resultado"].fillna("").astype(str).str.upper().str.strip()
    return {
        "total": int(len(result_df)),
        "ok": int((result == "OK").sum()),
        "partial": int((result == "PARCIAL").sum()),
        "errors": int((result == "ERROR").sum()),
        "skipped": int((result == "OMITIDO").sum()),
    }


def run_shopify_sync_job(job_id):
    job = get_job(job_id)
    if not job:
        raise RuntimeError(f"Job no encontrado: {job_id}")

    site_key = job["site_key"]
    input_path = job["input_path"]
    update_job(job_id, status="running", message="Leyendo Excel Matrixify")
    add_event(job_id, stage="Inicio", detail=f"Leyendo {input_path}")

    matrixify_df = read_matrixify_excel(input_path)
    if matrixify_df.empty:
        raise RuntimeError("El Excel Matrixify no tiene filas para sincronizar.")

    config = shopify_config_from_env(site_key)
    if not config.get("shop_domain") or not config.get("admin_api_access_token"):
        raise RuntimeError(
            "Faltan credenciales Shopify en variables de entorno: SHOP_DOMAIN/ADMIN_API_ACCESS_TOKEN "
            "o sus variantes por sitio."
        )

    total_products = int(matrixify_df["Handle"].dropna().astype(str).str.strip().nunique()) if "Handle" in matrixify_df.columns else 0
    update_job(job_id, total=total_products, message="Sincronizando Shopify")

    def progress(current, total, handle, stage, message=""):
        add_event(job_id, product=handle, stage=stage, detail=message)
        update_job(
            job_id,
            processed=int(current or 0),
            total=int(total or total_products or 0),
            message=f"{stage}: {handle}"[:500],
        )

    result_df = apply_full_product_updates(config, matrixify_df, progress_callback=progress)
    summary = summarize_result(result_df)

    result_path = OUTPUT_DIR / f"{job_id}_resultado.xlsx"
    result_path.write_bytes(dataframe_to_excel_bytes({"Resultado": result_df}))

    update_job(
        job_id,
        status="done" if summary["errors"] == 0 else "done_with_errors",
        result_path=str(result_path),
        processed=summary["total"],
        total=summary["total"],
        ok=summary["ok"],
        partial=summary["partial"],
        errors=summary["errors"],
        skipped=summary["skipped"],
        message="Job finalizado",
    )
    add_event(job_id, stage="Fin", detail=f"Resultado guardado en {result_path}")
    return result_path
