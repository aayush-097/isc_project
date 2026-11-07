from datetime import datetime
from typing import Literal

import re

from pydantic import BaseModel, Field, field_validator


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, str]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class FaceModelStatusResponse(BaseModel):
    checkpoint_available: bool
    checkpoint_name: str
    detection_class: Literal["face", "person"]
    message: str


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=1024)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9_.-]{3,64}", normalized):
            raise ValueError(
                "Username must be 3-64 characters using letters, numbers, '.', '_' or '-'."
            )
        return normalized


class UserResponse(BaseModel):
    id: str
    username: str


class AuthResponse(UserResponse):
    csrf_token: str


class MessageResponse(BaseModel):
    message: str


class RestoreStartRequest(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class RestoreStartResponse(BaseModel):
    token: str
    expires_in_seconds: int


class CaseSummary(BaseModel):
    id: str
    title: str
    is_owner: bool
    status: Literal["pending", "processing", "ready", "failed"]
    created_at: datetime


class CaseListResponse(BaseModel):
    cases: list[CaseSummary]


class CaseCreatedResponse(BaseModel):
    id: str
    job_id: str
    status: Literal["pending", "processing"]


class VerificationResponse(BaseModel):
    valid: bool
    message: str


class JobResponse(BaseModel):
    id: str
    case_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    progress: int = Field(ge=0, le=100)
    error: str | None = None


VideoStatus = Literal["queued", "processing", "completed", "failed"]


class VideoUploadResponse(BaseModel):
    case_id: str
    title: str
    status: VideoStatus
    message: str


class VideoPasskeyRequest(BaseModel):
    passkey: str = Field(min_length=16, max_length=1024)
    confirm_passkey: str | None = Field(default=None, min_length=16, max_length=1024)


class VideoUnlockResponse(BaseModel):
    message: str
    expires_in_seconds: int


class VideoProcessingMetrics(BaseModel):
    input_width: int
    input_height: int
    input_fps: float | None
    input_frame_count: int | None = Field(
        description="Container-reported frame-count estimate, not the decoded frame count."
    )
    processed_frames: int
    detected_face_instances: int
    frames_with_detections: int
    elapsed_seconds: float
    processing_fps: float
    output_frame_count: int
    output_validation_status: str
    gpu_acceleration_used: bool
    output_fps: float


class VideoStatusResponse(BaseModel):
    case_id: str
    title: str
    status: VideoStatus
    progress: int | None = None
    error: str | None = None
    metrics: VideoProcessingMetrics | None = None
    original_filename: str | None = None
    processing_completed_at: datetime | None = None
    duration_seconds: float | None = None
    video_width: int | None = None
    video_height: int | None = None
    is_owner: bool = True
    original_protected: bool = False


class VideoListItem(BaseModel):
    case_id: str
    title: str
    status: VideoStatus
    created_at: datetime
    error: str | None = None
    metrics: VideoProcessingMetrics | None = None
    is_owner: bool


class VideoListResponse(BaseModel):
    videos: list[VideoListItem]


class VideoPublicStatusResponse(BaseModel):
    status: VideoStatus
