"""Core abstractions for PagePlus's OCR backend layer.

The declarative spec / profile / retry / error taxonomy is inspired by the
Churro OCR project, but PagePlus does not depend on the ``churro-ocr`` package
at runtime. We only adopt the concepts and re-implement them natively in the
PAGE-XML world. See ``pageplus/utils/llm/CHURRO_UPSTREAM.md``.
"""

from pageplus.utils.llm.core.specs import (
    ExecutionStrategy,
    LiteLLMTransportConfig,
    GeminiOptions,
    HuggingFaceOptions,
    OpenAICompatibleOptions,
    AzureDocumentIntelligenceOptions,
    MistralOptions,
    OCRBackendSpec,
    OCRModelProfile,
    OCRResult,
    TaskMode,
)
from pageplus.utils.llm.core.errors import (
    OCRError,
    TransientError,
    RateLimitError,
    AuthError,
    ConfigurationError,
    ProviderError,
    SchemaError,
)
from pageplus.utils.llm.core.retry import RetryPolicy, with_retry, awith_retry
from pageplus.utils.llm.core.builder import build_ocr_backend, register_backend

__all__ = [
    "ExecutionStrategy",
    "LiteLLMTransportConfig",
    "GeminiOptions",
    "HuggingFaceOptions",
    "OpenAICompatibleOptions",
    "AzureDocumentIntelligenceOptions",
    "MistralOptions",
    "OCRBackendSpec",
    "OCRModelProfile",
    "OCRResult",
    "TaskMode",
    "OCRError",
    "TransientError",
    "RateLimitError",
    "AuthError",
    "ConfigurationError",
    "ProviderError",
    "SchemaError",
    "RetryPolicy",
    "with_retry",
    "awith_retry",
    "build_ocr_backend",
    "register_backend",
]
