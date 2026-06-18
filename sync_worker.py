import argparse
import os

from catalog_engine import run_shopify_sync_job
from job_store import add_event, create_job, update_job


def main():
    parser = argparse.ArgumentParser(description="Ejecuta un job de sincronizacion Shopify.")
    parser.add_argument("--job-id", required=False)
    parser.add_argument("--site-key", default=os.getenv("SHOPIFY_STORE", "default"))
    args = parser.parse_args()

    job_id = args.job_id

    if not job_id:
        job_id = create_job(
            kind="shopify_sync",
            site_key=args.site_key,
            input_path="",
            params={
                "source": "github_actions",
                "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
                "github_repository": os.getenv("GITHUB_REPOSITORY", ""),
            },
        )
        add_event(job_id, stage="Inicio", detail="Job creado automáticamente desde GitHub Actions")

    try:
        update_job(job_id, status="running", message="Ejecutando sincronización desde GitHub Actions")
        add_event(job_id, stage="Inicio", detail="Ejecutando run_shopify_sync_job")
        run_shopify_sync_job(job_id)

    except Exception as exc:
        update_job(job_id, status="error", error=str(exc), message=str(exc))
        add_event(job_id, stage="Error", detail=str(exc))
        raise


if __name__ == "__main__":
    main()
