from __future__ import annotations


class ProxyError(Exception):
    def __init__(self, message: str, *, status: int = 500, error_type: str = "api_error"):
        super().__init__(message)
        self.message = message
        self.status = status
        self.error_type = error_type


class TokenExpired(ProxyError):
    def __init__(self, message: str = "Antigravity access token expired"):
        super().__init__(message, status=401, error_type="invalid_request_error")
