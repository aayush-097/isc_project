from fastapi import APIRouter

from backend.app.api.common import not_implemented
from backend.app.schemas.api import ErrorResponse, JobResponse


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    responses={501: {"description": "Job lookup is not implemented.", "model": ErrorResponse}},
)
def get_job(job_id: str) -> JobResponse:
    """Return progress for a job owned by the authenticated user."""
    not_implemented("Job lookup")
