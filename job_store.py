import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs" / "jobs"
DB_PATH = DATA_DIR / "jobs.sqlite"


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_job_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                site_key TEXT NOT NULL,
                status TEXT NOT NULL,
                input_path TEXT,
                result_path TEXT,
                params_json TEXT,
                total INTEGER DEFAULT 0,
                processed INTEGER DEFAULT 0,
                ok INTEGER DEFAULT 0,
                partial INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0,
                skipped INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS job_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                product TEXT DEFAULT '',
                stage TEXT DEFAULT '',
                detail TEXT DEFAULT ''
            )
            """
        )


def _row_to_dict(cursor, row):
    if row is None:
        return None
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


def create_job(kind, site_key, input_path="", params=None):
    ensure_job_storage()
    job_id = uuid.uuid4().hex
    now = utc_now()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO jobs (
                id, kind, site_key, status, input_path, params_json, created_at, updated_at, message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                kind,
                site_key,
                "queued",
                str(input_path or ""),
                json.dumps(params or {}, ensure_ascii=False),
                now,
                now,
                "Job creado",
            ),
        )
    return job_id


def update_job(job_id, **fields):
    ensure_job_storage()
    if not fields:
        return
    fields["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = list(fields.values()) + [job_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", values)


def add_event(job_id, product="", stage="", detail=""):
    ensure_job_storage()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO job_events (job_id, created_at, product, stage, detail)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, utc_now(), str(product or ""), str(stage or ""), str(detail or "")[:1000]),
        )


def get_job(job_id):
    ensure_job_storage()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,))
        return _row_to_dict(cursor, cursor.fetchone())


def list_recent_jobs(limit=25):
    ensure_job_storage()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
            (int(limit),),
        )
        return [_row_to_dict(cursor, row) for row in cursor.fetchall()]


def list_job_events(job_id, limit=50):
    ensure_job_storage()
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            """
            SELECT created_at, product, stage, detail
            FROM job_events
            WHERE job_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (job_id, int(limit)),
        )
        return [_row_to_dict(cursor, row) for row in cursor.fetchall()][::-1]
