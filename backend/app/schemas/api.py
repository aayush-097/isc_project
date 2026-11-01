from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict[str, str]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class CredentialsRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class UserResponse(BaseModel):
    id: str
    username: str


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
