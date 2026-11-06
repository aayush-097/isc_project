import json
import logging
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.ai.face_detector import FACE_MODEL_SETUP_MESSAGE, Detector
from backend.app.config import Settings
from backend.app.db.database import connect_database
from backend.app.services.video_processing import process_case_video
from backend.app.video.processor import ProcessingStats


logger = logging.getLogger(__name__)
DEVELOPMENT_OWNER_ID = "development-upload-identity"
DEVELOPMENT_OWNER_USERNAME = "__development_uploads__"
DEVELOPMENT_PASSWORD_SENTINEL = "!disabled-development-only!"


def create_video_record(
    database_path: Path,
    *,
    case_id: str,
    title: str,
    folder_path: Path,
) -> None:
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN")
        connection.execute(
            """
            INSERT OR IGNORE INTO users (id, username, password_hash)
            VALUES (?, ?, ?)
            """,
            (
                DEVELOPMENT_OWNER_ID,
                DEVELOPMENT_OWNER_USERNAME,
                DEVELOPMENT_PASSWORD_SENTINEL,
            ),
        )
        identity = connection.execute(
            "SELECT id FROM users WHERE id = ?",
            (DEVELOPMENT_OWNER_ID,),
        ).fetchone()
        if identity is None:
            raise RuntimeError("The reserved development upload identity is unavailable.")
        connection.execute(
            """
            INSERT INTO cases (id, title, owner_id, folder_path, status)
            VALUES (?, ?, ?, ?, 'pending')
            """,
            (case_id, title, DEVELOPMENT_OWNER_ID, str(folder_path)),
        )
        connection.execute(
            "INSERT INTO jobs (id, case_id, status, progress) VALUES (?, ?, 'pending', 0)",
            (case_id, case_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_video_record(database_path: Path, case_id: str) -> dict[str, Any] | None:
    with closing(connect_database(database_path)) as connection:
        row = connection.execute(
            """
            SELECT cases.id, cases.title, cases.status AS case_status,
                   cases.created_at, jobs.status AS job_status, jobs.progress,
                   jobs.error, jobs.metrics_json
            FROM cases
            JOIN jobs ON jobs.case_id = cases.id
            WHERE cases.id = ?
            """,
            (case_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "case_id": row[0],
        "title": row[1],
        "case_status": row[2],
        "created_at": row[3],
        "job_status": row[4],
        "progress": row[5],
        "error": row[6],
        "metrics": json.loads(row[7]) if row[7] else None,
    }


def list_video_records(database_path: Path) -> list[dict[str, Any]]:
    with closing(connect_database(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT cases.id, cases.title, cases.status AS case_status,
                   cases.created_at, jobs.status AS job_status, jobs.progress,
                   jobs.error, jobs.metrics_json
            FROM cases
            JOIN jobs ON jobs.case_id = cases.id
            WHERE cases.owner_id = ?
            ORDER BY cases.created_at DESC, cases.id DESC
            """,
            (DEVELOPMENT_OWNER_ID,),
        ).fetchall()
    return [
        {
            "case_id": row[0],
            "title": row[1],
            "case_status": row[2],
            "created_at": row[3],
            "job_status": row[4],
            "progress": row[5],
            "error": row[6],
            "metrics": json.loads(row[7]) if row[7] else None,
        }
        for row in rows
    ]


def _set_processing_status(
    database_path: Path,
    case_id: str,
    *,
    status: str,
    progress: int,
    error: str | None = None,
    metrics: ProcessingStats | None = None,
) -> None:
    metrics_json = json.dumps(metrics.to_dict()) if metrics is not None else None
    case_status = "ready" if status == "completed" else status
    with closing(connect_database(database_path)) as connection:
        try:
            connection.execute("BEGIN")
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, progress = ?, error = ?, metrics_json = ?,
                    updated_at = ?
                WHERE id = ? AND case_id = ?
                """,
                (
                    status,
                    progress,
                    error,
                    metrics_json,
                    datetime.now(timezone.utc).isoformat(),
                    case_id,
                    case_id,
                ),
            )
            connection.execute(
                "UPDATE cases SET status = ? WHERE id = ?",
                (case_status, case_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def process_video_job(
    settings: Settings,
    case_id: str,
    source_path: Path,
    detector_factory: Any = None,
) -> None:
    database_path = settings.database_path
    try:
        _set_processing_status(
            database_path, case_id, status="processing", progress=0
        )

        def update_progress(processed: int, total: int | None) -> None:
            progress = min(99, int(processed * 100 / total)) if total else 0
            _set_processing_status(
                database_path, case_id, status="processing", progress=progress
            )

        detector: Detector | None = detector_factory() if detector_factory else None
        stats = process_case_video(
            source_path,
            case_id,
            detector,
            settings=settings,
            progress_callback=update_progress,
        )
        _set_processing_status(
            database_path,
            case_id,
            status="completed",
            progress=100,
            metrics=stats,
        )
    except Exception as exc:
        if "checkpoint is missing or empty" in str(exc).lower():
            safe_error = FACE_MODEL_SETUP_MESSAGE
        elif "cuda" in str(exc).lower():
            safe_error = (
                "Configured CUDA inference is unavailable. Check FACE_DEVICE, "
                "the PyTorch build, NVIDIA driver, and GPU availability."
            )
        else:
            safe_error = "Video processing failed. Check the backend log for details."
        logger.exception("Video processing failed for case_id=%s", case_id)
        _set_processing_status(
            database_path,
            case_id,
            status="failed",
            progress=0,
            error=safe_error,
        )
