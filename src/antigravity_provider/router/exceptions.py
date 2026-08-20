"""Typed Exception Hierarchy for Hermes Multi-Provider Router.

Ensures strict distinction between successful responses and provider errors,
enabling deterministic failover, health tracking, and error taxonomy.
"""
from __future__ import annotations

from typing import Optional


class RouterError(Exception):
    """Base exception for all router errors."""
    def __init__(self, message: str, provider: Optional[str] = None, profile_id: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.provider = provider
        self.profile_id = profile_id


class QuotaExceededError(RouterError):
    """Raised when provider returns HTTP 429 Resource Exhausted / Quota Limit."""
    def __init__(self, message: str = "Quota limit exhausted", reset_in_sec: Optional[int] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.reset_in_sec = reset_in_sec


class RateLimitedError(RouterError):
    """Raised when provider returns HTTP 429 Requests Per Minute (RPM) limit."""
    def __init__(self, message: str = "Rate limit reached", **kwargs):
        super().__init__(message, **kwargs)


class AuthRequiredError(RouterError):
    """Raised when profile credentials are missing or unconfigured."""
    def __init__(self, message: str = "Profile credentials required", **kwargs):
        super().__init__(message, **kwargs)


class AuthExpiredError(RouterError):
    """Raised when OAuth token or API key is invalid / expired (HTTP 401 / 403)."""
    def __init__(self, message: str = "Authentication token expired or invalid", **kwargs):
        super().__init__(message, **kwargs)


class ProviderUnavailableError(RouterError):
    """Raised when provider returns 5xx, network connection error, or timeout."""
    def __init__(self, message: str = "Provider service unavailable", status_code: Optional[int] = None, **kwargs):
        super().__init__(message, **kwargs)
        self.status_code = status_code


class TimeoutError(ProviderUnavailableError):
    """Raised when inference request times out."""
    def __init__(self, message: str = "Inference request timed out", **kwargs):
        super().__init__(message, **kwargs)


class InvalidRequestError(RouterError):
    """Raised when request payload is malformed (HTTP 400)."""
    def __init__(self, message: str = "Invalid request payload", **kwargs):
        super().__init__(message, **kwargs)
