"""OCR backend protocol + abstract base class.

All backends implement :meth:`ocr` (sync) and :meth:`aocr` (async). They
accept a :class:`RenderedPrompt` already rendered by the template layer, plus
the runtime context (image path, optional Page XML serialization). Returning
an :class:`OCRResult` keeps the pipeline's merge step backend-agnostic.
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from pageplus.utils.llm.core.specs import OCRBackendSpec, OCRResult


@dataclass
class RenderedPrompt:
    """A prompt rendered by the template layer, ready to hand to a backend.

    The ``task_mode`` is forwarded so backends can pick the right call shape
    (for example, Gemini uses different ``GenerateContentConfig`` for tasks
    that require JSON vs. free-form text).
    """
    system: str
    user: str
    task_mode: str
    schema: Optional[Dict[str, Any]] = None
    expected_format: str = "json"  # json | json_object | text
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BackendCallContext:
    """All non-prompt inputs a backend needs for a single invocation."""
    image_path: Path
    page_xml_payload: Optional[str] = None   # serialized PAGE-XML for correction modes
    page_xml_dict: Optional[Dict[str, Any]] = None   # JSON-friendly layout dump
    # For per-snippet execution strategy: the region/line id currently being OCR'd.
    snippet_id: Optional[str] = None
    # Free-form extras forwarded into OCRResult.ocr_metadata.
    metadata: Dict[str, Any] = field(default_factory=dict)


class OCRBackend(ABC):
    """Abstract base for all OCR backends.

    Subclasses should be cheap to construct (no network I/O in ``__init__``)
    so the builder can instantiate them at pipeline setup time. Expensive
    client creation is done lazily on the first call.
    """

    def __init__(self, spec: OCRBackendSpec) -> None:
        self.spec = spec

    @property
    def provider_name(self) -> str:
        return self.spec.provider

    @property
    def model_name(self) -> str:
        return self.spec.model

    @abstractmethod
    def ocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        """Synchronous OCR entrypoint. Must raise :class:`OCRError` subclasses
        on failure so the retry decorator can do the right thing."""

    async def aocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        """Default async entrypoint runs :meth:`ocr` in a thread. Backends
        that have a native async API should override this."""
        return await asyncio.to_thread(self.ocr, prompt, ctx)
