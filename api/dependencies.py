from __future__ import annotations

"""Shared FastAPI dependencies for all API routes.

Purpose:
- Provides a per-request database session generator (get_db).
- Exposes the application settings object as a FastAPI dependency (get_settings_dep).
- Enforces API key authentication via the X-API-Key header (verify_api_key),
  with an automatic bypass when DEPLOY_ENV is 'local'.

Dependencies:
- `database.connection.SessionLocal` for SQLAlchemy session lifecycle.
- `config.settings.get_settings` for API_KEY and DEPLOY_ENV values.
- `fastapi` for Request and HTTPException.

Usage:
- Inject `Depends(get_db)` in route handlers to receive an active session.
- Inject `Depends(get_settings_dep)` to access the Settings object.
- Inject `Depends(verify_api_key)` (or add to router dependencies) to protect
  any route with API key authentication.
"""

from collections.abc import Generator
import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from config.settings import Settings, get_settings
from database.connection import SessionLocal

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy session and ensure it is closed after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def get_settings_dep() -> Settings:
    """Return the cached application settings object."""
    return get_settings()


# ---------------------------------------------------------------------------
# API key authentication
# ---------------------------------------------------------------------------


def verify_api_key(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> bool:
    """Validate the X-API-Key header against the configured API_KEY.

    Returns True when the key matches.
    Raises HTTP 401 when the key is missing or incorrect.
    Skips the check entirely when DEPLOY_ENV is 'local'.
    """
    if settings.DEPLOY_ENV == "local":
        return True

    provided_key = request.headers.get("X-API-Key", "")
    expected_key = settings.API_KEY

    if not provided_key or provided_key != expected_key:
        logger.warning("API key validation failed for request path %s", request.url.path)
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key.",
        )

    return True
