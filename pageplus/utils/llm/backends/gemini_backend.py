"""Gemini (google-genai) OCR backend.

Replaces the direct ``google.genai`` calls that lived inline in
``pageplus/cli/gemini.py``. Error mapping translates the SDK's ``ClientError``
into our unified taxonomy so the retry decorator can do its job. The backend
also takes over the manual ``request_timestamps`` rate-limit that was copy-
pasted across multiple functions.
"""
from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, Optional

from pageplus.io.logger import logging
from pageplus.utils.image import get_image
from pageplus.utils.llm.backends.base import (
    BackendCallContext,
    OCRBackend,
    RenderedPrompt,
)
from pageplus.utils.llm.core.builder import register_backend
from pageplus.utils.llm.core.errors import (
    AuthError,
    ConfigurationError,
    ProviderError,
    RateLimitError,
    SchemaError,
    TransientError,
)
from pageplus.utils.llm.core.specs import (
    GeminiOptions,
    OCRBackendSpec,
    OCRResult,
)

try:  # Guarded so this module can be imported in environments without google-genai.
    from google import genai
    from google.genai import types as genai_types
    from google.genai.errors import ClientError as GenAIClientError
    _GENAI_AVAILABLE = True
except ImportError:  # pragma: no cover
    genai = None
    genai_types = None
    GenAIClientError = Exception
    _GENAI_AVAILABLE = False

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None  # type: ignore[assignment]


class _GeminiRateLimiter:
    """Tiny, thread-safe sliding-window limiter. Replaces the copy-pasted
    ``request_timestamps`` lists from ``pageplus/cli/gemini.py``."""

    def __init__(self, calls_per_minute: int) -> None:
        self.limit = max(1, int(calls_per_minute))
        self._lock = threading.Lock()
        self._timestamps: list[float] = []

    def wait(self) -> None:
        with self._lock:
            now = time.time()
            self._timestamps = [t for t in self._timestamps if now - t < 60]
            if len(self._timestamps) >= self.limit:
                sleep_for = 60 - (now - self._timestamps[0])
                if sleep_for > 0:
                    logging.warning(
                        "Gemini rate limit reached; sleeping %.2fs", sleep_for)
                    time.sleep(sleep_for)
            self._timestamps.append(time.time())


class GeminiBackend(OCRBackend):
    """OCRBackend implementation for the ``google-genai`` SDK."""

    def __init__(self, spec: OCRBackendSpec) -> None:
        super().__init__(spec)
        if not _GENAI_AVAILABLE:
            raise ConfigurationError(
                "google-genai is not installed; install it or use a different provider.",
                provider=spec.provider, model=spec.model)
        opts = spec.options
        if not isinstance(opts, GeminiOptions):
            raise ConfigurationError(
                f"GeminiBackend requires GeminiOptions, got {type(opts).__name__}",
                provider=spec.provider, model=spec.model)
        if not opts.api_key:
            raise ConfigurationError(
                "GeminiOptions.api_key is not set.",
                provider=spec.provider, model=spec.model)
        self._options: GeminiOptions = opts
        self._limiter = _GeminiRateLimiter(opts.calls_per_minute)
        self._client: Optional["genai.Client"] = None

    def client(self) -> "genai.Client":
        if self._client is None:
            stier = (self._options.service_tier or "").lower()
            # For Flex inference, set client-side timeout to at least 600s (10 min) per Google docs.
            timeout_sec = max(600.0, self._options.timeout) if stier == "flex" else self._options.timeout
            try:
                self._client = genai.Client(
                    api_key=self._options.api_key,
                    http_options={"timeout": int(timeout_sec * 1000)}
                )
            except Exception:
                self._client = genai.Client(api_key=self._options.api_key)
        return self._client

    # ---- OCRBackend API -------------------------------------------------

    def ocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        if not self.model_name:
            raise ConfigurationError("No Gemini model configured.",
                                     provider=self.provider_name)
        self._limiter.wait()
        stier = (self._options.service_tier or "").lower()
        max_attempts = 3 if stier == "flex" else 1
        base_delay = 5.0

        for attempt in range(max_attempts):
            try:
                file_upload = self._upload_image(ctx)
                config = self._build_config(prompt)
                contents = self._build_contents(prompt, ctx, file_upload)
                response = self.client().models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
                return self._parse_response(response, prompt, ctx)
            except GenAIClientError as exc:  # pragma: no cover - depends on SDK shape
                raise self._translate_client_error(exc) from exc
            except (ConfigurationError, AuthError, SchemaError):
                raise
            except Exception as exc:
                msg = str(exc)
                low = msg.lower()
                is_transient_busy = "503" in msg or "429" in msg or "unavailable" in low or "capacity" in low or "rate" in low
                if stier == "flex" and is_transient_busy and attempt < max_attempts - 1:
                    delay = base_delay * (2 ** attempt)
                    logging.warning(
                        "[Flex Inference] Server busy/congested (%s). Retrying in %.1fs (attempt %d/%d)...",
                        msg, delay, attempt + 1, max_attempts
                    )
                    time.sleep(delay)
                    continue

                if "api key" in low or "unauthorized" in low or "permission" in low:
                    raise AuthError(msg, provider=self.provider_name,
                                    model=self.model_name, cause=exc) from exc
                if "rate" in low and "limit" in low:
                    raise RateLimitError(msg, provider=self.provider_name,
                                         model=self.model_name, cause=exc) from exc
                raise TransientError(msg, provider=self.provider_name,
                                     model=self.model_name, cause=exc) from exc


    # ---- Internals ------------------------------------------------------

    def _upload_image(self, ctx: BackendCallContext):
        # Mirror the existing, known-good upload pattern used by
        # ``pageplus/utils/llm/table_recognition.py`` and the legacy Gemini
        # CLI: ``client.files.upload(file=<path>)`` with no config. Older
        # google-genai SDK versions don't expose ``genai_types.UploadConfig``
        # at all, and there's no functional reason to pass a display name.
        return self.client().files.upload(file=ctx.image_path)

    def _build_config(self, prompt: RenderedPrompt) -> "genai_types.GenerateContentConfig":
        thinking_config = None
        if self._options.thinking_budget > 0 and "2.5" in self.model_name:
            thinking_config = genai_types.ThinkingConfig(
                include_thoughts=True,
                thinking_budget=self._options.thinking_budget,
            )
        response_mime = "application/json" if prompt.expected_format.startswith("json") else "text/plain"
        cfg_kwargs: Dict[str, Any] = dict(
            temperature=self._options.temperature,
            top_p=self._options.top_p,
            response_mime_type=response_mime,
            system_instruction=prompt.system,
            max_output_tokens=self._options.max_output_tokens,
        )
        if thinking_config is not None:
            cfg_kwargs["thinking_config"] = thinking_config
        stier = (self._options.service_tier or "").lower()
        if stier and stier not in ("auto", "unspecified"):
            cfg_kwargs["service_tier"] = stier
        try:
            return genai_types.GenerateContentConfig(**cfg_kwargs)
        except TypeError as exc:
            if "service_tier" in cfg_kwargs and "service_tier" in str(exc):
                cfg_kwargs.pop("service_tier", None)
                return genai_types.GenerateContentConfig(**cfg_kwargs)
            raise


    def _build_contents(self, prompt: RenderedPrompt, ctx: BackendCallContext, file_upload) -> list:
        contents: list = [
            genai_types.Part.from_uri(
                file_uri=file_upload.uri,
                mime_type=file_upload.mime_type,
            ),
            prompt.user,
        ]
        # For correction modes, the page-xml payload is passed as an additional text part.
        if ctx.page_xml_payload:
            contents.append(ctx.page_xml_payload)
        return contents

    def _parse_response(self, response, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        text = getattr(response, "text", "") or ""
        usage = getattr(response, "usage_metadata", None)
        structured: Any = None
        if prompt.expected_format.startswith("json"):
            if not text:
                raise SchemaError(
                    "Gemini returned empty body for JSON task.",
                    provider=self.provider_name, model=self.model_name,
                    raw_response=str(response))
            try:
                if json_repair is not None:
                    structured = json_repair.repair_json(text, return_objects=True)
                else:
                    structured = json.loads(text)
            except Exception as exc:  # pragma: no cover - defensive
                raise SchemaError(
                    f"Gemini JSON parse failed: {exc}",
                    provider=self.provider_name, model=self.model_name,
                    raw_response=text,
                    cause=exc,
                ) from exc
        return OCRResult(
            text=text,
            structured=structured,
            provider_name=self.provider_name,
            model_name=self.model_name,
            usage={
                "total_token_count": getattr(usage, "total_token_count", 0) if usage else 0,
                "prompt_token_count": getattr(usage, "prompt_token_count", 0) if usage else 0,
                "candidates_token_count": getattr(usage, "candidates_token_count", 0) if usage else 0,
            },
            ocr_metadata={
                "task_mode": prompt.task_mode,
                "snippet_id": ctx.snippet_id,
                **dict(ctx.metadata),
            },
            raw_response=response,
        )

    def _translate_client_error(self, exc: GenAIClientError) -> Exception:
        code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
        message = getattr(exc, "message", None) or str(exc)
        kwargs = dict(provider=self.provider_name, model=self.model_name, cause=exc)
        if code == 429:
            return RateLimitError(message, **kwargs)
        if code in (401, 403):
            return AuthError(message, **kwargs)
        if code in (400, 404, 422):
            return ProviderError(message, **kwargs)
        if code is not None and int(code) >= 500:
            return TransientError(message, **kwargs)
        return TransientError(message, **kwargs)


def _factory(spec: OCRBackendSpec) -> GeminiBackend:
    return GeminiBackend(spec)


if _GENAI_AVAILABLE:
    register_backend("gemini", _factory)
