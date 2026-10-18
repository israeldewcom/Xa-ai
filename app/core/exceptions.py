from typing import Any


class XAError(Exception):
    """Base application error. Maps to a JSON response via the handler."""
    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "An internal error occurred."

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 status_code: int | None = None, details: Any = None):
        self.message = message or self.message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        self.details = details
        super().__init__(self.message)


class AuthenticationError(XAError):
    status_code = 401
    code = "UNAUTHENTICATED"
    message = "Authentication required."


class PermissionDenied(XAError):
    status_code = 403
    code = "PERMISSION_DENIED"
    message = "You do not have permission to do that."


class NotFound(XAError):
    status_code = 404
    code = "NOT_FOUND"
    message = "Resource not found."


class ConflictError(XAError):
    status_code = 409
    code = "CONFLICT"
    message = "The request conflicts with the current state."


class ValidationFailure(XAError):
    status_code = 422
    code = "VALIDATION_FAILED"
    message = "The request was invalid."


class RateLimited(XAError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests."
    retry_after: int | None = None

    def __init__(self, message: str | None = None, retry_after: int | None = None, **kw):
        super().__init__(message, **kw)
        self.retry_after = retry_after


class CapabilityUnavailable(XAError):
    status_code = 503
    code = "CAPABILITY_UNAVAILABLE"
    message = "This capability is not available."

    def __init__(self, capability: str, **kw):
        super().__init__(f"Capability '{capability}' is not configured.", **kw)
        self.capability = capability


class BackendError(XAError):
    status_code = 502
    code = "BACKEND_ERROR"
    message = "The upstream model backend failed."
