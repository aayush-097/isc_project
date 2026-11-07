import hashlib
import hmac
import logging
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from backend.app.config import Settings
from backend.app.db.database import connect_database
from backend.app.schemas.api import (
    AuthResponse,
    CredentialsRequest,
    ErrorResponse,
    MessageResponse,
)


router = APIRouter(prefix="/auth", tags=["authentication"])
logger = logging.getLogger(__name__)
PASSWORD_HASHER = PasswordHasher()
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION = timedelta(minutes=15)
GENERIC_LOGIN_ERROR = "Invalid username or password."
_DUMMY_PASSWORD_HASH = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_session(
    connection: sqlite3.Connection,
    user_id: str,
    settings: Settings,
) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).isoformat()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(seconds=settings.session_ttl_seconds)
    ).isoformat()
    connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    connection.execute(
        """
        INSERT INTO sessions (token_hash, user_id, csrf_token, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (_token_hash(token), user_id, csrf_token, expires_at),
    )
    return token, csrf_token


def _set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _check_origin(request: Request, settings: Settings) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") != settings.frontend_origin.rstrip("/"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "invalid_origin", "message": "Request origin is not allowed."},
        )


def get_session_record(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required", "message": "Please sign in."},
        )

    now = datetime.now(timezone.utc).isoformat()
    with closing(connect_database(settings.database_path)) as connection:
        row = connection.execute(
            """
            SELECT users.id, users.username, sessions.csrf_token, sessions.expires_at
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ?
            """,
            (_token_hash(token),),
        ).fetchone()
        if row is not None and row[3] <= now:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),)
            )
            connection.commit()

    if row is None or row[3] <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "authentication_required", "message": "Please sign in."},
        )
    return {
        "id": row[0],
        "username": row[1],
        "csrf_token": row[2],
        "session_token_hash": _token_hash(token),
    }


def require_current_user(request: Request) -> dict[str, Any]:
    return get_session_record(request)


def require_csrf(request: Request, session: dict[str, Any]) -> None:
    supplied = request.headers.get("x-csrf-token", "")
    if not supplied or not hmac.compare_digest(supplied, session["csrf_token"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "csrf_failed", "message": "The request could not be verified."},
        )


CurrentUser = Annotated[dict[str, Any], Depends(require_current_user)]


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: {"description": "Username is already registered.", "model": ErrorResponse},
    },
)
def register(
    payload: CredentialsRequest,
    request: Request,
    response: Response,
) -> AuthResponse:
    """Create an account and sign in the new user."""
    settings = _settings(request)
    _check_origin(request, settings)
    user_id = str(uuid4())
    password_hash = PASSWORD_HASHER.hash(payload.password)
    try:
        with closing(connect_database(settings.database_path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
                (user_id, payload.username, password_hash),
            )
            token, csrf_token = _create_session(connection, user_id, settings)
            connection.commit()
    except sqlite3.IntegrityError as exc:
        if "users.username" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "username_taken",
                    "message": "That username is already registered.",
                },
            ) from exc
        logger.exception("Could not register user due to a database integrity error.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "registration_failed", "message": "Could not create the account."},
        ) from exc
    except sqlite3.Error as exc:
        logger.exception("Could not register user.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "registration_failed", "message": "Could not create the account."},
        ) from exc

    _set_session_cookie(response, token, settings)
    return AuthResponse(id=user_id, username=payload.username, csrf_token=csrf_token)


@router.post(
    "/login",
    response_model=AuthResponse,
    responses={401: {"description": "Invalid username or password.", "model": ErrorResponse}},
)
def login(
    payload: CredentialsRequest,
    request: Request,
    response: Response,
) -> AuthResponse:
    """Verify credentials, enforce lockout, and start a database-backed session."""
    settings = _settings(request)
    _check_origin(request, settings)
    now = datetime.now(timezone.utc)
    try:
        with closing(connect_database(settings.database_path)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, username, password_hash, failed_attempts, locked_until
                FROM users WHERE username = ?
                """,
                (payload.username,),
            ).fetchone()

            if row is None:
                hash_to_verify = _DUMMY_PASSWORD_HASH
                user_locked = False
            else:
                hash_to_verify = row[2]
                user_locked = bool(row[4] and datetime.fromisoformat(row[4]) > now)

            try:
                password_valid = PASSWORD_HASHER.verify(hash_to_verify, payload.password)
            except (VerifyMismatchError, InvalidHashError):
                password_valid = False

            if row is None or user_locked or not password_valid:
                if row is not None and not user_locked:
                    failed_attempts = row[3] + 1
                    locked_until = (
                        (now + LOCKOUT_DURATION).isoformat()
                        if failed_attempts >= MAX_FAILED_ATTEMPTS
                        else None
                    )
                    connection.execute(
                        """
                        UPDATE users
                        SET failed_attempts = ?, locked_until = ?
                        WHERE id = ?
                        """,
                        (failed_attempts, locked_until, row[0]),
                    )
                connection.commit()
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail={"code": "invalid_credentials", "message": GENERIC_LOGIN_ERROR},
                )

            connection.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?",
                (row[0],),
            )
            token, csrf_token = _create_session(connection, row[0], settings)
            connection.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        logger.exception("Could not complete user login.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "login_failed", "message": "Could not complete sign in."},
        ) from exc

    _set_session_cookie(response, token, settings)
    return AuthResponse(id=row[0], username=row[1], csrf_token=csrf_token)


@router.post(
    "/logout",
    response_model=MessageResponse,
    responses={
        401: {"description": "Authentication is required.", "model": ErrorResponse},
        403: {"description": "CSRF token is invalid.", "model": ErrorResponse},
    },
)
def logout(
    request: Request,
    response: Response,
    current_user: CurrentUser,
) -> MessageResponse:
    """Revoke the current session and clear its browser cookie."""
    require_csrf(request, current_user)
    token = request.cookies.get(_settings(request).session_cookie_name)
    if token:
        token_hash = _token_hash(token)
        with closing(connect_database(_settings(request).database_path)) as connection:
            connection.execute(
                "DELETE FROM video_unlock_grants WHERE session_token_hash = ?",
                (token_hash,),
            )
            connection.execute(
                "DELETE FROM sessions WHERE token_hash = ?", (token_hash,)
            )
            connection.commit()
    response.delete_cookie(
        key=_settings(request).session_cookie_name,
        path="/",
        secure=_settings(request).session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.delete_cookie(
        key="video_unlock_grant",
        path="/api/videos",
        secure=_settings(request).session_cookie_secure,
        httponly=True,
        samesite="strict",
    )
    return MessageResponse(message="Signed out.")


@router.get(
    "/me",
    response_model=AuthResponse,
    responses={401: {"description": "Authentication is required.", "model": ErrorResponse}},
)
def current_user(current_user: CurrentUser) -> AuthResponse:
    """Return the signed-in user and the CSRF token for subsequent writes."""
    return AuthResponse(**current_user)
