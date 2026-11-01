import re
import shutil
import sqlite3
import uuid
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import cv2
from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.app.config import Settings
from backend.app.schemas.api import (
    VideoListItem,
    VideoListResponse,
    VideoProcessingMetrics,
    VideoStatusResponse,
    VideoUploadResponse,
)
from backend.app.services.video_jobs import (
    get_video_record,
    list_video_records,
    process_video_job,
    create_video_record,
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
    return directory


def _public_video_path(settings: Settings, case_id: str) -> Path:
    directory = _case_directory(settings, case_id)
    output = (directory / "public.mp4").resolve()
    try:
        output.relative_to(directory)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Video output not found.") from exc
    return output


def _status(record: dict, settings: Settings) -> VideoStatusResponse:
    status = record["job_status"]
    public_video = _public_video_path(settings, record["case_id"])
    if status == "completed" and not public_video.is_file():
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
    title: str = Form(..., min_length=1, max_length=200),
    video: UploadFile = File(...),
) -> VideoUploadResponse:
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
    original_path = case_directory / f"original{extension}"
    temporary_path = case_directory / f".upload{extension}.tmp"
    case_directory.mkdir(parents=True, exist_ok=False)

    total_bytes = 0
    try:
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
        temporary_path.replace(original_path)
        try:
            create_video_record(
                settings.database_path,
                case_id=case_id,
                title=cleaned_title,
                folder_path=case_directory,
            )
        except sqlite3.Error as exc:
            raise HTTPException(
                status_code=500,
                detail="Could not create the video processing record.",
            ) from exc
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail="Could not initialize the development upload identity.",
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


@router.get("", response_model=VideoListResponse)
def list_videos(request: Request) -> VideoListResponse:
    settings: Settings = request.app.state.settings
    records = list_video_records(settings.database_path)
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
            )
        )
    return VideoListResponse(videos=items)


@router.get("/{case_id}/status", response_model=VideoStatusResponse)
def get_video_status(case_id: str, request: Request) -> VideoStatusResponse:
    settings: Settings = request.app.state.settings
    record = get_video_record(settings.database_path, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Video case not found.")
    return _status(record, settings)


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
def get_public_video(case_id: str, request: Request) -> StreamingResponse:
    settings: Settings = request.app.state.settings
    record = get_video_record(settings.database_path, case_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Video case not found.")
    if record["job_status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Video is not available while processing status is '{record['job_status']}'.",
        )

    path = _public_video_path(settings, case_id)
    if not path.is_file():
        _set_processing_status(
            settings.database_path,
            case_id,
            status="failed",
            progress=0,
            error="Processed video output is unavailable; processing must be repeated.",
        )
        raise HTTPException(status_code=404, detail="Processed video output is unavailable.")

    file_size = path.stat().st_size
    if file_size == 0:
        raise HTTPException(status_code=404, detail="Processed video output is unavailable.")
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
        return StreamingResponse(
            _stream_file(path, start, length),
            status_code=206,
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(length),
                "Content-Disposition": 'inline; filename="public.mp4"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return StreamingResponse(
        _stream_file(path, 0, file_size),
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(file_size),
            "Content-Disposition": 'inline; filename="public.mp4"',
            "X-Content-Type-Options": "nosniff",
        },
    )
