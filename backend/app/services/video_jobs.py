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
from backend.app.services.video_crypto import decrypt_video_to_file
from backend.app.services.video_processing import process_case_video
from backend.app.video.processor import ProcessingStats


logger = logging.getLogger(__name__)


def create_video_record(
    database_path: Path,
    *,
    case_id: str,
    title: str,
    owner_id: str,
    folder_path: Path,
    original_filename: str,
    original_relative_path: str,
    crypto_metadata: dict[str, bytes | int | str],
) -> None:
    connection = connect_database(database_path)
    try:
        connection.execute("BEGIN")
        connection.execute(
            """
            INSERT INTO cases (
                id, title, owner_id, folder_path, original_filename,
                original_relative_path, blurred_relative_path, passkey_salt,
                wrapped_video_key, key_wrap_nonce, crypto_version,
                crypto_algorithm, key_wrap_algorithm, kdf_time_cost,
                kdf_memory_cost_kib, kdf_parallelism, encrypted_size, status
            )
            VALUES (?, ?, ?, ?, ?, ?, 'processed/public.mp4', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                case_id,
                title,
                owner_id,
                str(folder_path),
                original_filename,
                original_relative_path,
                crypto_metadata["salt"],
                crypto_metadata["wrapped_key"],
                crypto_metadata["wrap_nonce"],
                crypto_metadata["crypto_version"],
                crypto_metadata["crypto_algorithm"],
                crypto_metadata["key_wrap_algorithm"],
                crypto_metadata["kdf_time_cost"],
                crypto_metadata["kdf_memory_cost_kib"],
                crypto_metadata["kdf_parallelism"],
                crypto_metadata["encrypted_size"],
            ),
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
            SELECT cases.id, cases.title, cases.owner_id, cases.status,
                   cases.created_at, cases.original_filename,
                   cases.original_relative_path, cases.blurred_relative_path,
                   cases.processing_completed_at, cases.duration_seconds,
                   cases.video_width, cases.video_height, cases.passkey_salt,
                   cases.wrapped_video_key, cases.key_wrap_nonce,
                   cases.crypto_version, cases.crypto_algorithm,
                   cases.key_wrap_algorithm, cases.kdf_time_cost,
                   cases.kdf_memory_cost_kib, cases.kdf_parallelism,
                   cases.encrypted_size, jobs.status, jobs.progress,
                   jobs.error, jobs.metrics_json
            FROM cases
            JOIN jobs ON jobs.case_id = cases.id
            WHERE cases.id = ?
            """,
            (case_id,),
        ).fetchone()
    if row is None:
        return None
    return _video_record_dict(row)


def _video_record_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "case_id": row[0],
        "title": row[1],
        "owner_id": row[2],
        "case_status": row[3],
        "created_at": row[4],
        "original_filename": row[5],
        "original_relative_path": row[6],
        "blurred_relative_path": row[7],
        "processing_completed_at": row[8],
        "duration_seconds": row[9],
        "video_width": row[10],
        "video_height": row[11],
        "passkey_salt": row[12],
        "wrapped_video_key": row[13],
        "key_wrap_nonce": row[14],
        "crypto_version": row[15],
        "crypto_algorithm": row[16],
        "key_wrap_algorithm": row[17],
        "kdf_time_cost": row[18],
        "kdf_memory_cost_kib": row[19],
        "kdf_parallelism": row[20],
        "encrypted_size": row[21],
        "job_status": row[22],
        "progress": row[23],
        "error": row[24],
        "metrics": json.loads(row[25]) if row[25] else None,
    }


def list_video_records(database_path: Path) -> list[dict[str, Any]]:
    with closing(connect_database(database_path)) as connection:
        rows = connection.execute(
            """
            SELECT cases.id, cases.title, cases.owner_id, cases.status,
                   cases.created_at, cases.original_filename,
                   cases.original_relative_path, cases.blurred_relative_path,
                   cases.processing_completed_at, cases.duration_seconds,
                   cases.video_width, cases.video_height, cases.passkey_salt,
                   cases.wrapped_video_key, cases.key_wrap_nonce,
                   cases.crypto_version, cases.crypto_algorithm,
                   cases.key_wrap_algorithm, cases.kdf_time_cost,
                   cases.kdf_memory_cost_kib, cases.kdf_parallelism,
                   cases.encrypted_size, jobs.status, jobs.progress,
                   jobs.error, jobs.metrics_json
            FROM cases
            JOIN jobs ON jobs.case_id = cases.id
            ORDER BY cases.created_at DESC, cases.id DESC
            """
        ).fetchall()
    return [_video_record_dict(row) for row in rows]


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
    completed_at = (
        datetime.now(timezone.utc).isoformat() if status == "completed" else None
    )
    duration_seconds = None
    video_width = None
    video_height = None
    if metrics is not None:
        video_width = metrics.input_width
        video_height = metrics.input_height
        if metrics.input_fps and metrics.input_fps > 0 and metrics.processed_frames:
            duration_seconds = metrics.processed_frames / metrics.input_fps
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
                """
                UPDATE cases
                SET status = ?, processing_completed_at = ?,
                    duration_seconds = COALESCE(?, duration_seconds),
                    video_width = COALESCE(?, video_width),
                    video_height = COALESCE(?, video_height)
                WHERE id = ?
                """,
                (
                    case_status,
                    completed_at,
                    duration_seconds,
                    video_width,
                    video_height,
                    case_id,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def process_video_job(
    settings: Settings,
    case_id: str,
    encrypted_path: Path,
    data_key: bytes,
    encrypted_size: int,
    detector_factory: Any = None,
) -> None:
    database_path = settings.database_path
    source_path = settings.storage_path / case_id / ".processing-source.tmp"
    try:
        decrypt_video_to_file(
            encrypted_path,
            source_path,
            video_id=case_id,
            data_key=data_key,
            expected_size=encrypted_size,
        )
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
    finally:
        source_path.unlink(missing_ok=True)
