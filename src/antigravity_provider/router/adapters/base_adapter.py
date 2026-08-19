"""Base provider adapter interface for multi-provider router."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from ..router_config import RouterProfileConfig


class ErrorCategory:
    QUOTA_EXHAUSTED = "quota-exhausted"
    RATE_LIMITED = "rate-limited"
    AUTH_REQUIRED = "auth-required"
    TRANSIENT = "transient"
    INVALID_REQUEST = "invalid-request"
    FATAL = "fatal"


@dataclass
class ErrorClassification:
    category: str
    message: str
    retry_delay_seconds: int = 60
    reset_duration_seconds: int = 1800
    model_family: Optional[str] = None


class BaseProviderAdapter(ABC):
    @abstractmethod
    def invoke(self, profile: RouterProfileConfig, request: Dict[str, Any]) -> Dict[str, Any]:
        """Execute chat completion request and return standard OpenAI-compatible dict."""
        ...

    @abstractmethod
    def health_check(self, profile: RouterProfileConfig) -> bool:
        """Probe provider profile to check reachability and auth."""
        ...

    @abstractmethod
    def discover_models(self, profile: RouterProfileConfig) -> List[str]:
        """Return list of supported models for this profile."""
        ...

    @abstractmethod
    def classify_error(self, exc: Exception, response_data: Optional[Dict[str, Any]] = None) -> ErrorClassification:
        """Classify execution failure into structured error category."""
        ...

    def release(self, profile: RouterProfileConfig) -> None:
        """Clean up any ephemeral resources for this profile."""
        pass
