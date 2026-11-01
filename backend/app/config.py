from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    face_model_path: Path = PROJECT_ROOT / "models" / "best.pt"
    face_confidence_threshold: float = Field(default=0.25, ge=0, le=1)
    face_image_size: int = Field(default=960, ge=32, le=4096)
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


def get_settings() -> Settings:
    return Settings()
