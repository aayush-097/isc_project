from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from backend.app.api import auth, cases, jobs, restore, videos
from backend.app.config import Settings, get_settings
from backend.app.db.database import initialize_database
from backend.app.schemas.api import ErrorDetail, ErrorResponse, HealthResponse


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        app_settings.storage_path.mkdir(parents=True, exist_ok=True)
        initialize_database(app_settings.database_path)
        yield

    app = FastAPI(
        title="Reversible Face Privacy API",
        description=(
            "Development API for face-blurred video processing. Health and "
            "development video upload/status/list/stream endpoints are functional. "
            "Authentication, case ownership, verification, and restoration are deferred."
        ),
        version="0.2.5",
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.video_detector_factory = None

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details = [
            {
                "loc": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        body = ErrorResponse(
            error=ErrorDetail(
                code="validation_error",
                message="The request did not match the API contract.",
                details=details,
            )
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    @app.exception_handler(HTTPException)
    async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", "http_error"))
            message = str(exc.detail.get("message", "The request could not be completed."))
        else:
            code = "http_error"
            message = str(exc.detail)
        body = ErrorResponse(error=ErrorDetail(code=code, message=message))
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(),
            headers=exc.headers,
        )

    @app.get("/health", response_model=HealthResponse, tags=["health"])
    def health() -> HealthResponse:
        """Report that the API process is responsive."""
        return HealthResponse()

    app.include_router(auth.router)
    app.include_router(cases.router)
    app.include_router(jobs.router)
    app.include_router(restore.router)
    app.include_router(videos.router)
    return app


app = create_app()
