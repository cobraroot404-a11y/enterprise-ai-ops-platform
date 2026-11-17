"""Standardized API errors."""


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None,
                 retry_after: int | None = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class DependencyUnavailable(AppError):
    """A required local dependency (embedding model, language model) failed: 503 with Retry-After, never a raw 500."""
    status_code = 503
    code = "dependency_unavailable"

    def __init__(self, message: str, *, code: str | None = None, retry_after: int = 10):
        super().__init__(message, code=code, retry_after=retry_after)


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class Invalid(AppError):
    status_code = 422
    code = "invalid"
