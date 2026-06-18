import os
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from catalog_engine import run_shopify_sync_job
from job_store import OUTPUT_DIR, add_event, create_job, get_job, list_job_events, list_recent_jobs, update_job


app = FastAPI(title="Forus Catalog Control Center API", version="0.1.0")


def _run_job_safely(job_id):
    try:
        run_shopify_sync_job(job_id)
    except Exception as exc:
        update_job(job_id, status="error", error=str(exc), message=str(exc))
        add_event(job_id, stage="Error", detail=str(exc))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/jobs/sync-shopify")
async def create_sync_shopify_job(
    site_key: str = Form(...),
    file: UploadFile = File(...),
    start_immediately: bool = Form(True),
):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "matrixify.xlsx").name
    job_id = create_job("sync_shopify", site_key, params={"filename": safe_name})
    input_path = OUTPUT_DIR / f"{job_id}_{safe_name}"
    input_path.write_bytes(await file.read())
    update_job(job_id, input_path=str(input_path), message="Archivo recibido")

    if start_immediately:
        thread = threading.Thread(target=_run_job_safely, args=(job_id,), daemon=True)
        thread.start()

    return {"job_id": job_id, "status": get_job(job_id)["status"]}


@app.post("/jobs/{job_id}/run")
def run_job(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    if job["status"] in {"running"}:
        return {"job_id": job_id, "status": job["status"], "message": "Job ya esta corriendo"}
    thread = threading.Thread(target=_run_job_safely, args=(job_id,), daemon=True)
    thread.start()
    return {"job_id": job_id, "status": "running"}


@app.get("/jobs")
def jobs(limit: int = 25):
    return {"jobs": list_recent_jobs(limit)}


@app.get("/jobs/{job_id}")
def job_status(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    return {"job": job, "events": list_job_events(job_id, limit=25)}


@app.get("/jobs/{job_id}/result")
def job_result(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job no encontrado")
    result_path = job.get("result_path")
    if not result_path or not Path(result_path).exists():
        raise HTTPException(status_code=404, detail="Resultado aun no disponible")
    return FileResponse(
        result_path,
        filename=f"resultado_{job_id}.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
