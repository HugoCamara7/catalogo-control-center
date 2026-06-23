import argparse

from catalog_engine import run_shopify_sync_job
from job_store import add_event, update_job


def main():
    parser = argparse.ArgumentParser(description="Ejecuta un job de sincronizacion Shopify.")
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    try:
        run_shopify_sync_job(args.job_id)
    except Exception as exc:
        update_job(args.job_id, status="error", error=str(exc), message=str(exc))
        add_event(args.job_id, stage="Error", detail=str(exc))
        raise


if __name__ == "__main__":
    main()
