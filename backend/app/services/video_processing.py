import re
from pathlib import Path

from backend.app.ai.face_detector import Detector
from backend.app.config import Settings, get_settings
from backend.app.video.processor import ProcessingStats, ProgressCallback, process_video


CASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


def process_case_video(
    input_path: Path,
    case_id: str,
    detector: Detector | None = None,
    *,
    settings: Settings | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ProcessingStats:
    """Process an uploaded source to a fixed processed/public.mp4 under case storage."""
    if not CASE_ID_PATTERN.fullmatch(case_id):
        raise ValueError("case_id must contain only letters, digits, underscores, or hyphens")
    app_settings = settings or get_settings()
    storage_root = app_settings.storage_path.resolve()
    case_directory = (storage_root / case_id).resolve()
    try:
        case_directory.relative_to(storage_root)
    except ValueError as exc:
        raise ValueError("case output directory must remain inside configured storage") from exc

    processed_directory = case_directory / "processed"
    processed_directory.mkdir(parents=True, exist_ok=True)
    return process_video(
        input_path,
        processed_directory / "public.mp4",
        detector,
        settings=app_settings,
        progress_callback=progress_callback,
    )
