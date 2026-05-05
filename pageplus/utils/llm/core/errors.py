"""Provider-agnostic OCR error taxonomy.

All backends translate their native exceptions into this hierarchy, so the
pipeline can implement a single retry / surfacing policy without having to know
about LiteLLM, google.genai, or any other provider SDK.

Hierarchy and classification are inspired by Churro's error taxonomy, adapted
to PagePlus's style; there is no runtime dependency on ``churro-ocr``.
"""
from __future__ import annotations

from typing import Optional


class OCRError(Exception):
    """Base class for OCR-related errors raised by any backend."""

    def __init__(self, message: str, *, provider: Optional[str] = None,
                 model: Optional[str] = None, cause: Optional[BaseException] = None) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.cause = cause

    def __str__(self) -> str:  # pragma: no cover - trivial formatting
        base = super().__str__()
        suffix = []
        if self.provider:
            suffix.append(f"provider={self.provider}")
        if self.model:
            suffix.append(f"model={self.model}")
        return f"{base} ({', '.join(suffix)})" if suffix else base


class TransientError(OCRError):
    """A transient backend error that should be retried (network blip, 5xx)."""

    def __init__(self, message: str, *, retry_after: Optional[float] = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class RateLimitError(TransientError):
    """The provider throttled the request. ``retry_after`` is in seconds if known."""


class AuthError(OCRError):
    """Credentials are missing, invalid, or lack permission for the requested operation."""


class ConfigurationError(OCRError):
    """The backend spec is incomplete or inconsistent (e.g. no model, unknown provider)."""


class ProviderError(OCRError):
    """The provider returned an error that is not retryable (bad request, safety filter, etc.)."""


class SchemaError(OCRError):
    """The provider returned a response that does not satisfy the template's declared schema."""

    def __init__(self, message: str, *, raw_response: Optional[str] = None, **kwargs) -> None:
        super().__init__(message, **kwargs)
        self.raw_response = raw_response
