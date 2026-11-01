from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile, status
from fastapi.responses import Response

from backend.app.api.common import not_implemented
from backend.app.schemas.api import (
    CaseCreatedResponse,
    CaseListResponse,
    ErrorResponse,
    VerificationResponse,
)


router = APIRouter(prefix="/cases", tags=["cases"])


@router.get(
    "",
    response_model=CaseListResponse,
    responses={501: {"description": "Case listing is not implemented.", "model": ErrorResponse}},
)
def list_cases() -> CaseListResponse:
    """List cases visible to the authenticated user."""
    not_implemented("Case listing")


@router.post(
    "",
    response_model=CaseCreatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={501: {"description": "Case uploads are not implemented.", "model": ErrorResponse}},
)
def create_case(
    title: Annotated[str, Form(min_length=1, max_length=200)],
    video: Annotated[UploadFile, File(description="Video to process")],
) -> CaseCreatedResponse:
    """Upload a video and enqueue its protection job."""
    not_implemented("Video upload and processing")


@router.get(
    "/{case_id}/public",
    response_class=Response,
    responses={
        200: {"description": "The public blurred video.", "content": {"video/mp4": {}}},
        501: {"description": "Video streaming is not implemented.", "model": ErrorResponse},
    },
)
def get_public_video(case_id: str) -> Response:
    """Stream a case's public blurred video to an authenticated user."""
    not_implemented("Public video streaming")


@router.get(
    "/{case_id}/verify",
    response_model=VerificationResponse,
    responses={501: {"description": "Integrity verification is not implemented.", "model": ErrorResponse}},
)
def verify_case(case_id: str) -> VerificationResponse:
    """Verify a case's manifest and protected artifacts."""
    not_implemented("Integrity verification")
