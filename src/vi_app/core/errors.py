from __future__ import annotations

from fastapi import HTTPException, status


class ViAppError(Exception):
    """Base application exception."""

    pass


class BadRequest(ViAppError):
    pass


class NotFound(ViAppError):
    pass


def to_http(exc: Exception) -> HTTPException:
    """
    Convert our exceptions to HTTPException with sensible defaults.
    """
    if isinstance(exc, BadRequest):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    if isinstance(exc, NotFound):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, ViAppError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        )
    # Fallback
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
    )
