"""Typed API errors. Every rejection carries a stable machine-readable code."""
from __future__ import annotations

from typing import Any


class ApiError(Exception):
    status = 400

    def __init__(self, code: str, detail: str, **extra: Any):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"error": self.code, "detail": self.detail, **self.extra}


class BadRequest(ApiError):
    status = 400


class Forbidden(ApiError):
    status = 403


class NotFound(ApiError):
    status = 404


class Conflict(ApiError):
    status = 409


class Gone(ApiError):
    status = 410


class TooLarge(ApiError):
    status = 413


class Unprocessable(ApiError):
    status = 422


class TooManyRequests(ApiError):
    status = 429
