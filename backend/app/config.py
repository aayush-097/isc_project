import os
import shutil
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _add_ffmpeg_to_path() -> None:
    """Ensure ffmpeg/ffprobe resolve even when a Windows install does not update PATH."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return

    candidate_roots = [
        Path.home() / "AppData" / "Local" / "Microsoft" / "WinGet" / "Packages",
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path("C:/"),
        Path("/usr/bin"),
        Path("/usr/local/bin"),
    ]
    resolved = None
    for root in candidate_roots:
        if not root.exists():
            continue
        for executable_name in ("ffmpeg", "ffprobe"):
            if shutil.which(executable_name):
                resolved = shutil.which(executable_name)
                break
            for match in root.glob(f"**/{executable_name}.exe"):
                resolved = str(match)
                break
            if resolved:
                break
            for match in root.glob(f"**/{executable_name}"):
                resolved = str(match)
                break
            if resolved:
                break
        if resolved:
            break

    if resolved:
        ffmpeg_dir = str(Path(resolved).parent)
        path_entries = [value for value in os.environ.get("PATH", "").split(os.pathsep) if value]
        if ffmpeg_dir not in path_entries:
            os.environ["PATH"] = os.pathsep.join([ffmpeg_dir, *path_entries])


_add_ffmpeg_to_path()


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_path: Path = PROJECT_ROOT / "storage" / "app.db"
    storage_path: Path = PROJECT_ROOT / "storage" / "cases"
    frontend_origin: str = "http://localhost:5173"
    session_cookie_name: str = "faceprivacy_session"
    session_cookie_secure: bool = False
    face_model_path: Path = PROJECT_ROOT / "models" / "yolo26n.pt"
    face_detection_class: Literal["face", "person"] = "person"
    face_confidence_threshold: float = Field(default=0.05, ge=0, le=1)
    face_image_size: int = Field(default=640, ge=32, le=4096)
    face_device: str = "auto"
    face_blur_strength: int = Field(default=99, ge=3, le=99)
    face_box_padding: float = Field(default=0.18, ge=0, le=1)
    max_video_upload_bytes: int = Field(default=500 * 1024 * 1024, ge=1)

    @field_validator("database_path", "storage_path")
    @classmethod
    def resolve_relative_paths(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value

    @field_validator("face_model_path")
    @classmethod
    def resolve_model_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value

    @field_validator("face_blur_strength")
    @classmethod
    def require_odd_blur_strength(cls, value: int) -> int:
        if value % 2 == 0:
            raise ValueError("face_blur_strength must be an odd integer")
        return value

    @field_validator("face_device")
    @classmethod
    def validate_face_device(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "cpu", "cuda"} and not normalized.isdigit():
            raise ValueError("face_device must be auto, cpu, cuda, or a CUDA device index")
        return normalized

    @field_validator("face_detection_class", mode="before")
    @classmethod
    def normalize_face_detection_class(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized not in {"face", "person"}:
            raise ValueError("face_detection_class must be face or person")
        return normalized


def get_settings() -> Settings:
    return Settings()
