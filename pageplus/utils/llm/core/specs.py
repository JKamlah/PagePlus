"""Declarative specs for OCR backends, model profiles, and task modes.

These dataclasses are the single source of truth that the pipeline, CLI, and
GUI all pass around. The shape is inspired by the Churro OCR project's
``providers.specs`` module; PagePlus re-implements the concept natively, with
no runtime dependency on ``churro-ocr``. See
``pageplus/utils/llm/CHURRO_UPSTREAM.md`` for the mapping of adopted concepts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union


# ---------------------------------------------------------------------------
# Task modes -- the five orthogonal PAGE-XML-aware workflows a backend can serve.
# ---------------------------------------------------------------------------

class TaskMode(str, Enum):
    """Orthogonal OCR task shapes. Each pairs with exactly one Jinja template
    and one schema in the template layer. Any backend may serve any task mode
    provided that a matching :class:`OCRModelProfile` is registered."""

    LAYOUT_ONLY = "layout_only"          # image -> regions/lines with coords, no text
    LAYOUT_AND_TEXT = "layout_and_text"  # image -> regions/lines with coords + text
    LAYOUT_CORRECTION = "layout_correction"  # image + PAGE-XML -> refined coords
    TEXT_ONLY = "text_only"              # image + PAGE-XML -> text per id (coords preserved)
    TEXT_CORRECTION = "text_correction"  # image + PAGE-XML+text -> refined text per id


class ExecutionStrategy(str, Enum):
    """How the pipeline feeds a page to the backend."""

    WHOLE_PAGE = "whole_page"    # one backend call per page (preferred for VLMs with layout context)
    PER_SNIPPET = "per_snippet"  # one backend call per line/region crop (fallback for minimal backends)


# ---------------------------------------------------------------------------
# Per-provider option dataclasses. Add a new one per supported provider family.
# ---------------------------------------------------------------------------

@dataclass
class LiteLLMTransportConfig:
    """Transport options for any provider routed through LiteLLM."""
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    timeout: float = 60.0
    provider_prefix: Optional[str] = None  # e.g. "openai", "azure", "mistral"
    extra_headers: Dict[str, str] = field(default_factory=dict)
    json_object_mode: bool = False  # use response_format={"type":"json_object"} instead of json_schema
    calls_per_minute: int = 120       # soft throttle applied by the LiteLLM backend
    max_image_size: Optional[int] = 1000


@dataclass
class GeminiOptions:
    """Options specific to standard/interactive ``google-genai`` SDK backend requests."""
    api_key: Optional[str] = None
    thinking_budget: int = 0
    temperature: float = 1e-7
    top_p: float = 1e-8
    max_output_tokens: int = 65536
    timeout: float = 300.0           # 5 minutes for interactive requests
    max_attempts: int = 3            # 3 retries for standard requests
    calls_per_minute: int = 120      # Default rate limit for interactive requests
    detail: str = "high"
    service_tier: str = "auto"       # "auto", "flex", "priority"
    is_batch: bool = False


@dataclass
class GeminiBatchOptions(GeminiOptions):
    """Options tailored specifically for long-running Gemini batch processing jobs."""
    timeout: float = 86400.0         # 24 hours processing limit for batch workloads
    max_attempts: int = 50           # 50 retries across 24h for resilient batch processing
    calls_per_minute: int = 60       # Throttled rate limit tailored for high-volume background batches
    is_batch: bool = True



@dataclass
class HuggingFaceOptions:
    """Options for running a local/remote HF pipeline (stub; fill in when needed)."""
    model_id: Optional[str] = None
    device: str = "cuda"
    dtype: str = "bfloat16"
    max_new_tokens: int = 2048
    trust_remote_code: bool = True


@dataclass
class OpenAICompatibleOptions:
    """Options for raw OpenAI-compatible endpoints (vLLM, Ollama's OpenAI shim, LM Studio)."""
    api_base_url: str = "http://localhost:8000/v1"
    api_key: Optional[str] = None
    timeout: float = 60.0
    calls_per_minute: int = 120
    max_image_size: Optional[int] = 1000


@dataclass
class AzureDocumentIntelligenceOptions:
    """Stub for Azure Document Intelligence; wire up when the backend is implemented."""
    endpoint: Optional[str] = None
    api_key: Optional[str] = None
    model_id: str = "prebuilt-read"


@dataclass
class MistralOptions:
    """Options for Mistral Document OCR API."""
    api_key: Optional[str] = None
    api_base_url: str = "https://api.mistral.ai/v1/ocr"
    model: str = "mistral-ocr-latest"
    table_format: Optional[str] = "html"
    include_blocks: bool = True
    extract_header: bool = False
    extract_footer: bool = False
    timeout: float = 60.0
    calls_per_minute: int = 120
    max_image_size: Optional[int] = 1000


@dataclass
class CurlHTTPOptions:
    """Options for a direct HTTP POST REST endpoint (curl-style)."""
    url: str
    api_key: Optional[str] = None
    timeout: float = 60.0
    image_key: str = "image"
    prompt_key: str = "prompt"
    calls_per_minute: int = 120
    max_image_size: Optional[int] = 1000


ProviderOptions = Union[
    LiteLLMTransportConfig,
    GeminiOptions,
    HuggingFaceOptions,
    OpenAICompatibleOptions,
    AzureDocumentIntelligenceOptions,
    MistralOptions,
    CurlHTTPOptions,
]


# ---------------------------------------------------------------------------
# Model profiles -- pair a task mode with a template, schema, and postprocessor.
# ---------------------------------------------------------------------------

@dataclass
class OCRModelProfile:
    """Declarative profile: 'for task X on provider Y, render template T and postprocess with P'.

    Profiles are registered via ``pageplus.utils.llm.templates.profiles`` and
    selected automatically by ``(provider, model, task_mode)`` at pipeline
    construction time.
    """
    name: str
    task_mode: TaskMode
    template: str                 # template name, e.g. "layout_and_text"
    postprocess: str              # registered postprocessor name, e.g. "gemini2d_to_page"
    schema: Optional[Dict[str, Any]] = None   # JSON schema (when backend supports json_schema)
    system_prompt: Optional[str] = None       # override for the system prompt
    user_prompt: Optional[str] = None         # override for the user prompt template
    # Force the response shape ("json" | "json_object" | "text"). When None the
    # format is inferred from ``schema`` (json when set, else json_object/text).
    expected_format: Optional[str] = None
    # Callable overrides -- if set, take precedence over the registered name lookups.
    postprocess_fn: Optional[Callable[..., Any]] = None


# ---------------------------------------------------------------------------
# Backend spec -- the single thing CLI/GUI code constructs.
# ---------------------------------------------------------------------------

@dataclass
class OCRBackendSpec:
    """Declarative backend description. Passed to :func:`build_ocr_backend`."""
    provider: str                                   # "litellm" | "gemini" | ...
    model: str
    options: ProviderOptions
    profile: Optional[OCRModelProfile] = None       # explicit profile, else resolved by task mode
    execution: ExecutionStrategy = ExecutionStrategy.WHOLE_PAGE
    # Free-form metadata forwarded into OCRResult.ocr_metadata for traceability.
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Unified result container.
# ---------------------------------------------------------------------------

@dataclass
class OCRResult:
    """What every backend returns.

    - ``text`` is the flat plaintext (handy for logging / CLI output).
    - ``structured`` is the parsed provider JSON, ready to be handed to the
      template's postprocessor, which turns it into PAGE-XML.
    - ``provider_name`` / ``model_name`` / ``usage`` are for telemetry.
    - ``ocr_metadata`` carries template/task/profile context plus any backend
      specific extras; the pipeline merges ``OCRBackendSpec.metadata`` in.
    """
    text: str = ""
    structured: Any = None
    provider_name: str = ""
    model_name: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    ocr_metadata: Dict[str, Any] = field(default_factory=dict)
    raw_response: Any = None

    def has_structured(self) -> bool:
        return self.structured is not None
