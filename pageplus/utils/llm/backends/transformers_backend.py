"""Direct HuggingFace ``transformers`` OCR backend (scaffold).

This is a deliberate scaffold: the provider, options
(:class:`~pageplus.utils.llm.core.specs.HuggingFaceOptions`), registration, and
profile resolution path all exist so the LLM-OCR tab can offer "direct
transformer integration" as a provider kind today. The actual in-process VLM
inference (à la the Churro ``hf`` backend: ``AutoProcessor`` +
``AutoModelForImageTextToText`` + ``apply_chat_template``) is intentionally left
as a follow-up; calling :meth:`ocr` raises a clear, actionable error rather than
silently doing nothing.

When implementing inference later, mirror Churro's pattern:
    1. Lazy-load processor/model once per backend instance.
    2. ``render_ocr_prompt`` via ``processor.apply_chat_template``.
    3. Build vision inputs (e.g. ``qwen_vl_utils.process_vision_info``).
    4. ``model.generate(...)`` and decode, trimming the prompt tokens.
    5. Map errors onto the :class:`OCRError` taxonomy.
"""
from __future__ import annotations

from pageplus.utils.llm.backends.base import (
    BackendCallContext,
    OCRBackend,
    RenderedPrompt,
)
from pageplus.utils.llm.core.builder import register_backend
from pageplus.utils.llm.core.errors import ConfigurationError
from pageplus.utils.llm.core.specs import (
    HuggingFaceOptions,
    OCRBackendSpec,
    OCRResult,
)


class TransformersBackend(OCRBackend):
    """Scaffold backend for local HuggingFace ``transformers`` VLMs.

    Construction succeeds (so the provider can be listed/selected and a spec
    built), but :meth:`ocr` raises until in-process inference is wired up.
    """

    def __init__(self, spec: OCRBackendSpec) -> None:
        super().__init__(spec)
        opts = spec.options
        if not isinstance(opts, HuggingFaceOptions):
            raise ConfigurationError(
                f"TransformersBackend requires HuggingFaceOptions, "
                f"got {type(opts).__name__}",
                provider=spec.provider, model=spec.model,
            )
        self._opts: HuggingFaceOptions = opts

    def ocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        raise ConfigurationError(
            "The direct 'transformers' backend is scaffolded but inference is "
            "not implemented yet. Use an OpenAI-compatible server (e.g. vLLM "
            "serving the same model) via a custom endpoint, or the Gemini / "
            "LiteLLM providers, until the in-process transformers path lands.",
            provider=self.provider_name, model=self.model_name,
        )


def _factory(spec: OCRBackendSpec) -> TransformersBackend:
    return TransformersBackend(spec)


# Registered unconditionally: the stub is lightweight and importing it must not
# require the (heavy, optional) ``transformers`` package to be installed.
register_backend("transformers", _factory)
