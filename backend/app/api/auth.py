from fastapi import APIRouter, status

from backend.app.api.common import not_implemented
from backend.app.schemas.api import (
    CredentialsRequest,
    ErrorResponse,
    MessageResponse,
    UserResponse,
)


router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={501: {"description": "Registration is not implemented.", "model": ErrorResponse}},
)
def register(payload: CredentialsRequest) -> UserResponse:
    """Create an account. Authentication is intentionally deferred."""
    not_implemented("Registration")


@router.post(
    "/login",
    response_model=UserResponse,
    responses={501: {"description": "Login is not implemented.", "model": ErrorResponse}},
)
def login(payload: CredentialsRequest) -> UserResponse:
    """Start a session. Authentication is intentionally deferred."""
    not_implemented("Login")


@router.post(
    "/logout",
    response_model=MessageResponse,
    responses={501: {"description": "Logout is not implemented.", "model": ErrorResponse}},
)
def logout() -> MessageResponse:
    """End the current session. Authentication is intentionally deferred."""
    not_implemented("Logout")


@router.get(
    "/me",
    response_model=UserResponse,
    responses={501: {"description": "Session lookup is not implemented.", "model": ErrorResponse}},
)
def current_user() -> UserResponse:
    """Return the current user. Authentication is intentionally deferred."""
    not_implemented("Current-user lookup")
