from fastapi import APIRouter
from fastapi.responses import Response

from backend.app.api.common import not_implemented
from backend.app.schemas.api import ErrorResponse, RestoreStartRequest, RestoreStartResponse


router = APIRouter(tags=["restoration"])


@router.post(
    "/cases/{case_id}/restore/start",
    response_model=RestoreStartResponse,
    responses={501: {"description": "Restoration is not implemented.", "model": ErrorResponse}},
)
def start_restore(case_id: str, payload: RestoreStartRequest) -> RestoreStartResponse:
    """Request owner-authorized restoration after password re-entry."""
    not_implemented("Restoration")


@router.get(
    "/restore/stream/{token}",
    response_class=Response,
    responses={
        200: {"description": "A restored MJPEG stream.", "content": {"multipart/x-mixed-replace": {}}},
        501: {"description": "Restore streaming is not implemented.", "model": ErrorResponse},
    },
)
def restore_stream(token: str) -> Response:
    """Stream restored frames using a short-lived, single-use token."""
    not_implemented("Restore streaming")
