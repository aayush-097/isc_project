import re
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import closing
import mimetypes
from pathlib import Path, PurePosixPath

import cv2
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.app.ai.face_detector import FACE_MODEL_SETUP_MESSAGE, checkpoint_is_available
from backend.app.api.auth import CurrentUser, require_csrf
from backend.app.config import Settings
from backend.app.schemas.api import (
    VideoListItem,
    VideoListResponse,
    VideoProcessingMetrics,
    VideoPublicStatusResponse,
    VideoStatusResponse,
    VideoUploadResponse,
)
from backend.app.services.video_jobs import (
    create_video_record,
    get_video_record,
    list_video_records,
    process_video_job,
    _set_processing_status,
)


router = APIRouter(prefix="/videos", tags=["development videos"])
CASE_ID_PATTERN = re.compile(r"^case_[0-9a-f]{32}$")
SUPPORTED_EXTENSIONS = {".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm"}
UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_FILENAME_LENGTH = 255


def _case_directory(settings: Settings, case_id: str) -> Path:
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise HTTPException(status_code=404, detail="Video case not found.")
    root = settings.storage_path.resolve()
    directory = (root / case_id).resolve()
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Video case not found.") from exc
    if directory.parent != root or directory.name != case_id:
        raise HTTPException(status_code=404, detail="Video case not found.")
    return directory


def _public_video_path(settings: Settings, case_id: str) -> Path:
    directory = _case_directory(settings, case_id)
    record = get_video_record(settings.database_path, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Video case not found.")
    relative_path = record.get("blurred_relative_path") or "public.mp4"
    output = _stored_video_path(directory, relative_path)
    if output is None and relative_path == "public.mp4":
        output = _safe_case_child(directory, "public.mp4")
    if output is None:
        raise HTTPException(status_code=404, detail="Video output not found.")
    return output


def _safe_case_child(directory: Path, relative_path: str) -> Path | None:
    parts = PurePosixPath(relative_path).parts
    if (
        not parts
        or PurePosixPath(relative_path).is_absolute()
        or any(part in {"", ".", ".."} for part in parts)
        or "\\" in relative_path
    ):
        return None
    output = directory.joinpath(*parts).resolve()
    try:
        output.relative_to(directory)
    except ValueError:
        return None
    return output


def _stored_video_path(directory: Path, relative_path: str | None) -> Path | None:
    return _safe_case_child(directory, relative_path) if relative_path else None


def _original_video_path(settings: Settings, record: dict) -> Path | None:
    directory = _case_directory(settings, record["case_id"])
    stored_path = _stored_video_path(directory, record.get("original_relative_path"))
    if stored_path is not None:
        return stored_path
    if record.get("original_relative_path"):
        return None
    legacy_sources = [
        path
        for path in directory.glob("original.*")
        if path.suffix.lower() in SUPPORTED_EXTENSIONS and path.is_file()
    ]
    return (
        _safe_case_child(directory, legacy_sources[0].name)
        if len(legacy_sources) == 1
        else None
    )


def _owned_record(settings: Settings, case_id: str, user_id: str) -> dict:
    record = get_video_record(settings.database_path, case_id)
    if record is None or record["owner_id"] != user_id:
        raise HTTPException(status_code=404, detail="Video case not found.")
    return record


def _status(record: dict, settings: Settings) -> VideoStatusResponse:
    status = record["job_status"]
    public_video = _public_video_path(settings, record["case_id"])
    validated = (
        record.get("metrics") is not None
        and record["metrics"].get("output_validation_status") == "passed"
    )
    if status == "completed" and (not public_video.is_file() or not validated):
        _set_processing_status(
            settings.database_path,
            record["case_id"],
            status="failed",
            progress=0,
            error="Processed video output is unavailable; processing must be repeated.",
        )
        status = "failed"
        record["error"] = "Processed video output is unavailable; processing must be repeated."
        record["metrics"] = None

    return VideoStatusResponse(
        case_id=record["case_id"],
        title=record["title"],
        status={"pending": "queued", "completed": "completed"}.get(status, status),
        progress=record["progress"],
        error=record.get("error"),
        metrics=VideoProcessingMetrics(**record["metrics"]) if record.get("metrics") else None,
        original_filename=record.get("original_filename"),
        processing_completed_at=record.get("processing_completed_at"),
        duration_seconds=record.get("duration_seconds"),
        video_width=record.get("video_width"),
        video_height=record.get("video_height"),
        is_owner=True,
    )


def _validate_video_file(path: Path) -> None:
    capture = cv2.VideoCapture(str(path))
    try:
        if not capture.isOpened():
            raise HTTPException(
                status_code=400,
                detail="The uploaded file could not be opened as a video.",
            )
        success, frame = capture.read()
        if not success or frame is None or frame.size == 0:
            raise HTTPException(
                status_code=400,
                detail="The uploaded video contains no readable frames.",
            )
    finally:
        capture.release()


@router.post(
    "/upload",
    response_model=VideoUploadResponse,
    status_code=202,
    responses={
        400: {"description": "The uploaded file is not a readable video."},
        413: {"description": "The upload exceeds the configured size limit."},
        415: {"description": "The filename extension is unsupported."},
    },
)
async def upload_video(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
    title: str = Form(..., min_length=1, max_length=200),
    video: UploadFile = File(...),
) -> VideoUploadResponse:
    require_csrf(request, current_user)
    settings: Settings = request.app.state.settings
    cleaned_title = title.strip()
    if not cleaned_title:
        raise HTTPException(status_code=422, detail="Case title cannot be empty.")

    filename = video.filename
    if (
        not filename
        or len(filename) > MAX_FILENAME_LENGTH
        or "\x00" in filename
        or not filename.strip()
    ):
        raise HTTPException(status_code=400, detail="A valid video filename is required.")
    extension = PurePosixPath(filename.replace("\\", "/")).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported video extension. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}.",
        )

    case_id = f"case_{uuid.uuid4().hex}"
    case_directory = _case_directory(settings, case_id)
    original_directory = case_directory / "original"
    original_path = original_directory / f"original{extension}"
    temporary_path = case_directory / f".upload{extension}.tmp"
    case_directory.mkdir(parents=True, exist_ok=False)

    total_bytes = 0
    try:
        original_directory.mkdir()
        with temporary_path.open("xb") as destination:
            while chunk := await video.read(UPLOAD_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > settings.max_video_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Video upload exceeds the configured limit of "
                            f"{settings.max_video_upload_bytes} bytes."
                        ),
                    )
                destination.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=400, detail="The uploaded video is empty.")

        _validate_video_file(temporary_path)
        if (
            getattr(request.app.state, "video_detector_factory", None) is None
            and not checkpoint_is_available(settings.face_model_path)
        ):
            raise HTTPException(status_code=503, detail=FACE_MODEL_SETUP_MESSAGE)

        temporary_path.replace(original_path)
        try:
            create_video_record(
                settings.database_path,
                case_id=case_id,
                title=cleaned_title,
                owner_id=current_user["id"],
                folder_path=case_directory,
                original_filename=PurePosixPath(filename.replace("\\", "/")).name,
                original_relative_path=f"original/original{extension}",
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=401, detail="Please sign in again.") from exc
        except sqlite3.Error as exc:
            raise HTTPException(
                status_code=500,
                detail="Could not create the video processing record.",
            ) from exc

        background_tasks.add_task(
            process_video_job,
            settings,
            case_id,
            original_path,
            getattr(request.app.state, "video_detector_factory", None),
        )
        return VideoUploadResponse(
            case_id=case_id,
            title=cleaned_title,
            status="queued",
            message="Upload accepted. Video processing has been queued.",
        )
    except Exception:
        shutil.rmtree(case_directory, ignore_errors=True)
        raise
    finally:
        await video.close()


@router.post(
    "/{case_id}/retry",
    response_model=VideoUploadResponse,
    status_code=202,
    responses={
        404: {"description": "The video case does not exist."},
        409: {"description": "The case is not retryable or its source is unavailable."},
        503: {"description": "The configured face model checkpoint is unavailable."},
    },
)
def retry_video(
    case_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
) -> VideoUploadResponse:
    settings: Settings = request.app.state.settings
    require_csrf(request, current_user)
    record = _owned_record(settings, case_id, current_user["id"])
    if record["job_status"] != "failed":
        raise HTTPException(
            status_code=409,
            detail="Only failed video cases can be retried.",
        )
    if (
        getattr(request.app.state, "video_detector_factory", None) is None
        and not checkpoint_is_available(settings.face_model_path)
    ):
        raise HTTPException(status_code=503, detail=FACE_MODEL_SETUP_MESSAGE)

    source_path = _original_video_path(settings, record)
    if source_path is None or not source_path.is_file():
        raise HTTPException(
            status_code=409,
            detail="The original video is unavailable; upload the video again.",
        )

    _set_processing_status(
        settings.database_path,
        case_id,
        status="pending",
        progress=0,
    )
    background_tasks.add_task(
        process_video_job,
        settings,
        case_id,
        source_path,
        getattr(request.app.state, "video_detector_factory", None),
    )
    return VideoUploadResponse(
        case_id=case_id,
        title=record["title"],
        status="queued",
        message="Retry accepted. Video processing has been queued.",
    )


@router.get("", response_model=VideoListResponse)
def list_videos(request: Request, current_user: CurrentUser) -> VideoListResponse:
    settings: Settings = request.app.state.settings
    records = list_video_records(settings.database_path, current_user["id"])
    items = []
    for record in records:
        state = _status(record, settings)
        items.append(
            VideoListItem(
                case_id=record["case_id"],
                title=record["title"],
                status=state.status,
                created_at=record["created_at"],
                error=state.error,
                metrics=state.metrics,
                is_owner=True,
            )
        )
    return VideoListResponse(videos=items)


@router.get("/{case_id}/status", response_model=VideoStatusResponse)
def get_video_status(
    case_id: str,
    request: Request,
    current_user: CurrentUser,
) -> VideoStatusResponse:
    settings: Settings = request.app.state.settings
    record = _owned_record(settings, case_id, current_user["id"])
    return _status(record, settings)


@router.get("/{case_id}/public-status", response_model=VideoPublicStatusResponse)
def get_public_video_status(case_id: str, request: Request) -> VideoPublicStatusResponse:
    settings: Settings = request.app.state.settings
    record = get_video_record(settings.database_path, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Video case not found.")
    status = {"pending": "queued", "completed": "completed"}.get(
        record["job_status"], record["job_status"]
    )
    if status == "completed":
        metrics = record.get("metrics")
        path = _public_video_path(settings, case_id)
        if (
            not metrics
            or metrics.get("output_validation_status") != "passed"
            or not path.is_file()
            or path.stat().st_size == 0
        ):
            status = "failed"
    return VideoPublicStatusResponse(status=status)


def _parse_range(value: str, file_size: int) -> tuple[int, int]:
    if not value.startswith("bytes=") or "," in value:
        raise ValueError("Only one byte range is supported.")
    range_value = value[6:].strip()
    start_text, separator, end_text = range_value.partition("-")
    if not separator:
        raise ValueError("Invalid byte range.")
    if not start_text:
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise ValueError("Invalid byte range.")
        start = max(file_size - suffix_length, 0)
        end = file_size - 1
    else:
        start = int(start_text)
        end = min(int(end_text), file_size - 1) if end_text else file_size - 1
    if start < 0 or start >= file_size or end < start:
        raise ValueError("Byte range is not satisfiable.")
    return start, end


def _stream_file(path: Path, start: int, length: int) -> Iterator[bytes]:
    with path.open("rb") as source:
        source.seek(start)
        remaining = length
        while remaining:
            chunk = source.read(min(UPLOAD_CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/{case_id}/public")
@router.get("/{case_id}/blurred", include_in_schema=False)
def get_public_video(case_id: str, request: Request) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    record = get_video_record(settings.database_path, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Video case not found.")
    if record["job_status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail="Blurred video is available only after processing is complete.",
        )

    path = _public_video_path(settings, case_id)
    metrics = record.get("metrics")
    if (
        not metrics
        or metrics.get("output_validation_status") != "passed"
        or not path.is_file()
        or path.stat().st_size == 0
    ):
        _set_processing_status(
            settings.database_path,
            case_id,
            status="failed",
            progress=0,
            error="Processed video output is unavailable; processing must be repeated.",
        )
        raise HTTPException(status_code=404, detail="Processed video output is unavailable.")
    return _stream_video(path, request, "blurred.mp4", "video/mp4", private=False)

@router.get("/{case_id}/original")
def get_original_video(
    case_id: str,
    request: Request,
    current_user: CurrentUser,
) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    record = _owned_record(settings, case_id, current_user["id"])
    if record["job_status"] in {"pending", "processing"}:
        raise HTTPException(
            status_code=409,
            detail="Original video is unavailable while processing.",
        )
    path = _original_video_path(settings, record)
    if path is None or not path.is_file() or path.stat().st_size == 0:
        raise HTTPException(status_code=404, detail="Original video is unavailable.")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return _stream_video(
        path,
        request,
        f"original{path.suffix.lower()}",
        media_type,
        private=True,
    )


def _stream_video(
    path: Path,
    request: Request,
    filename: str,
    media_type: str,
    *,
    private: bool,
) -> StreamingResponse:
    file_size = path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(file_size),
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "private, no-store" if private else "no-store",
        "X-Content-Type-Options": "nosniff",
    }
    range_header = request.headers.get("range")
    if range_header:
        try:
            start, end = _parse_range(range_header, file_size)
        except (ValueError, OverflowError):
            raise HTTPException(
                status_code=416,
                detail="Requested video byte range is not satisfiable.",
                headers={"Content-Range": f"bytes */{file_size}"},
            ) from None
        length = end - start + 1
        headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
        headers["Content-Length"] = str(length)
        return StreamingResponse(
            _stream_file(path, start, length),
            status_code=206,
            media_type=media_type,
            headers=headers,
        )
    return StreamingResponse(
        _stream_file(path, 0, file_size),
        media_type=media_type,
        headers=headers,
    )


@router.delete("/{case_id}", status_code=204)
def delete_video(
    case_id: str,
    request: Request,
    current_user: CurrentUser,
) -> None:
    settings: Settings = request.app.state.settings
    require_csrf(request, current_user)
    record = _owned_record(settings, case_id, current_user["id"])
    if record["job_status"] in {"pending", "processing"}:
        raise HTTPException(status_code=409, detail="A video cannot be deleted while processing.")
    case_directory = _case_directory(settings, case_id)
    if not case_directory.exists():
        raise HTTPException(status_code=404, detail="Video case files not found.")
    trash_directory = case_directory.with_name(f".deleting-{case_id}-{uuid.uuid4().hex}")
    try:
        case_directory.rename(trash_directory)
        with closing(sqlite3.connect(settings.database_path, timeout=30)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM jobs WHERE case_id = ?", (case_id,))
            deleted = connection.execute(
                "DELETE FROM cases WHERE id = ? AND owner_id = ?",
                (case_id, current_user["id"]),
            ).rowcount
            if deleted != 1:
                raise HTTPException(status_code=404, detail="Video case not found.")
            connection.commit()
        shutil.rmtree(trash_directory)
    except HTTPException:
        if trash_directory.exists() and not case_directory.exists():
            trash_directory.rename(case_directory)
        raise
    except (OSError, sqlite3.Error) as exc:
        if trash_directory.exists() and not case_directory.exists():
            trash_directory.rename(case_directory)
        raise HTTPException(status_code=500, detail="Could not remove video case.") from exc
