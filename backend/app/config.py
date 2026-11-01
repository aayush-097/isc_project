from pathlib import Path

from pydantic import field_validator
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

    @field_validator("database_path", "storage_path")
    @classmethod
    def resolve_relative_paths(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value


def get_settings() -> Settings:
    return Settings()
