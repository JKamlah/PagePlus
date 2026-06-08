"""LiteLLM OCR backend.

Wraps ``litellm.completion`` behind the unified :class:`OCRBackend` protocol.
Replaces the inline ``completion(...)`` calls in ``pageplus/cli/litellm.py``.
Translates the common failure modes (authentication, rate limiting, bad
request, schema validation) into our unified error taxonomy so the retry
decorator can be universal across backends.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict

from pageplus.utils.image import image_to_base64, get_image
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
    LiteLLMTransportConfig,
    OCRBackendSpec,
    OCRResult,
)

try:
    import litellm
    from litellm import completion as _completion
    _LITELLM_AVAILABLE = True
except ImportError:  # pragma: no cover
    litellm = None  # type: ignore[assignment]
    _completion = None
    _LITELLM_AVAILABLE = False

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None  # type: ignore[assignment]

_DEBUG_ENABLED = False

# Strip base64 image payloads so verbose logging does not flood the terminal.
_DATA_URI_RE = re.compile(r"(data:image/[A-Za-z0-9.+-]+;base64,)[A-Za-z0-9+/=\s]+")
_LONG_B64_RE = re.compile(r"[A-Za-z0-9+/]{200,}={0,2}")


def redact_base64(text: str) -> str:
    """Replace base64 image data (data URIs and long blobs) with a short marker."""
    if not text:
        return text
    text = _DATA_URI_RE.sub(lambda m: m.group(1) + "<base64 image omitted>", text)
    text = _LONG_B64_RE.sub("<base64 omitted>", text)
    return text


class _RedactBase64Filter(logging.Filter):
    """Logging filter that scrubs base64 image blobs from log records."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            if isinstance(record.msg, str):
                record.msg = redact_base64(record.msg)
            if record.args:
                if isinstance(record.args, dict):
                    record.args = {k: (redact_base64(v) if isinstance(v, str) else v)
                                   for k, v in record.args.items()}
                else:
                    record.args = tuple(redact_base64(a) if isinstance(a, str) else a
                                        for a in record.args)
        except Exception:  # pragma: no cover - never let logging break the run
            pass
        return True


_REDACT_FILTER = _RedactBase64Filter()


def _install_redaction() -> None:
    """Attach the base64 redaction filter to the loggers LiteLLM debug uses."""
    for logger_name in ("", "LiteLLM", "litellm"):
        logger = logging.getLogger(logger_name)
        if _REDACT_FILTER not in logger.filters:
            logger.addFilter(_REDACT_FILTER)
        for handler in logger.handlers:
            if _REDACT_FILTER not in handler.filters:
                handler.addFilter(_REDACT_FILTER)


def _maybe_enable_litellm_debug() -> None:
    """Turn on LiteLLM's verbose request logging when PAGEPLUS_LLM_DEBUG is set.

    With this on, LiteLLM logs the exact upstream request (URL + JSON), which is
    the quickest way to see what is actually being called. Base64 image payloads
    are redacted so the terminal is not flooded.
    """
    global _DEBUG_ENABLED
    if _DEBUG_ENABLED or litellm is None:
        return
    if os.environ.get("PAGEPLUS_LLM_DEBUG", "").strip().lower() not in ("1", "true", "yes", "on"):
        return
    try:
        litellm._turn_on_debug()
    except Exception:  # pragma: no cover - older litellm
        try:
            litellm.set_verbose = True  # type: ignore[attr-defined]
        except Exception:
            pass
    _install_redaction()
    _DEBUG_ENABLED = True


def _endpoint_for(provider_prefix: str, api_base: str | None) -> str:
    """Best-effort full URL LiteLLM will POST to, for logging only."""
    base = (api_base or "").rstrip("/")
    prefix = (provider_prefix or "").lower()
    if prefix == "ollama":
        return f"{base}/api/generate"
    if prefix == "ollama_chat":
        return f"{base}/api/chat"
    if base:
        return f"{base}/chat/completions"
    return f"(provider default for '{provider_prefix}')"


class LiteLLMBackend(OCRBackend):
    """OCRBackend over LiteLLM. Works for any OpenAI-compatible endpoint."""

    def __init__(self, spec: OCRBackendSpec) -> None:
        super().__init__(spec)
        if not _LITELLM_AVAILABLE:
            raise ConfigurationError(
                "litellm is not installed; install it or use a different provider.",
                provider=spec.provider, model=spec.model)
        opts = spec.options
        if not isinstance(opts, LiteLLMTransportConfig):
            raise ConfigurationError(
                f"LiteLLMBackend requires LiteLLMTransportConfig, got {type(opts).__name__}",
                provider=spec.provider, model=spec.model)
        self._transport: LiteLLMTransportConfig = opts
        _maybe_enable_litellm_debug()
        logging.info(
            "[litellm] call target: model=%s provider=%s api_base=%s -> %s "
            "(response_format=%s)",
            spec.model, self._transport.provider_prefix or "litellm",
            self._transport.api_base_url,
            _endpoint_for(self._transport.provider_prefix, self._transport.api_base_url),
            "json_object" if self._transport.json_object_mode else "json_schema/auto",
        )

    @property
    def provider_name(self) -> str:
        return self._transport.provider_prefix or "litellm"

    # ---- OCRBackend API -------------------------------------------------

    def ocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        if not self.model_name:
            raise ConfigurationError("No model configured.",
                                     provider=self.provider_name)
        messages = self._build_messages(prompt, ctx)
        response_format = self._build_response_format(prompt)
        try:
            response = _completion(
                model=self.model_name,
                api_key=self._transport.api_key,
                api_base=self._transport.api_base_url,
                timeout=self._transport.timeout,
                stream=False,
                temperature=1e-7,
                top_p=1e-8,
                n=1,
                messages=messages,
                response_format=response_format,
                max_tokens=prompt.extra.get("max_tokens", 2048),
                extra_headers=self._transport.extra_headers or None,
            )
        except Exception as exc:
            raise self._translate_exception(exc) from exc
        return self._parse_response(response, prompt, ctx)

    # ---- Internals ------------------------------------------------------

    def _build_messages(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> list:
        image, image_format = get_image(ctx.image_path)
        if self._transport.max_image_size:
            from PIL import Image
            w, h = image.size
            max_size = self._transport.max_image_size
            if w > max_size or h > max_size:
                if w >= h:
                    new_w = max_size
                    new_h = int(h * (max_size / w))
                else:
                    new_h = max_size
                    new_w = int(w * (max_size / h))
                new_w = max(1, new_w)
                new_h = max(1, new_h)
                image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        image_b64 = image_to_base64(image)
        user_content: list = [
            {"type": "text", "text": prompt.user},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{image_format.lower()};base64,{image_b64}",
                    "detail": prompt.extra.get("detail", "high"),
                },
            },
        ]
        if ctx.page_xml_payload:
            user_content.insert(1, {"type": "text", "text": ctx.page_xml_payload})

        messages: list = []
        system_role = "user" if prompt.extra.get("only_user_prompt", False) else "system"
        messages.append({
            "role": system_role,
            "content": [{"type": "text", "text": prompt.system}],
        })
        messages.append({"role": "user", "content": user_content})
        return messages

    def _build_response_format(self, prompt: RenderedPrompt) -> Dict[str, Any]:
        if prompt.expected_format == "text":
            return None  # type: ignore[return-value]
        use_json_object = (
            self._transport.json_object_mode or prompt.expected_format == "json_object"
        )
        if use_json_object or prompt.schema is None:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": prompt.extra.get("schema_name", f"{prompt.task_mode}_response"),
                "strict": True,
                "schema": prompt.schema,
            },
        }

    def _parse_response(self, response, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        try:
            message = response.choices[0].message
            content = message.content or ""
        except Exception as exc:
            raise SchemaError(
                f"Unexpected LiteLLM response shape: {exc}",
                provider=self.provider_name, model=self.model_name, cause=exc,
            ) from exc
        structured: Any = None
        if prompt.expected_format.startswith("json"):
            if not content:
                raise SchemaError(
                    "LiteLLM returned empty body for JSON task.",
                    provider=self.provider_name, model=self.model_name,
                    raw_response=content)
            try:
                if json_repair is not None:
                    structured = json_repair.repair_json(content, return_objects=True)
                else:
                    structured = json.loads(content)
            except Exception as exc:
                raise SchemaError(
                    f"LiteLLM JSON parse failed: {exc}",
                    provider=self.provider_name, model=self.model_name,
                    raw_response=content, cause=exc,
                ) from exc
        usage = getattr(response, "usage", None) or {}
        if not isinstance(usage, dict):
            usage = {
                "total_tokens": getattr(usage, "total_tokens", 0),
                "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                "completion_tokens": getattr(usage, "completion_tokens", 0),
            }
        return OCRResult(
            text=content,
            structured=structured,
            provider_name=self.provider_name,
            model_name=self.model_name,
            usage=usage,
            ocr_metadata={
                "task_mode": prompt.task_mode,
                "snippet_id": ctx.snippet_id,
                **dict(ctx.metadata),
            },
            raw_response=response,
        )

    def _translate_exception(self, exc: BaseException) -> BaseException:
        # LiteLLM normalizes provider errors into classes on ``litellm.exceptions``.
        # Try the class-based match first; otherwise fall back to message sniffing.
        name = type(exc).__name__
        kwargs = dict(provider=self.provider_name, model=self.model_name, cause=exc)
        if name in {"RateLimitError", "Timeout", "APITimeoutError"}:
            return RateLimitError(str(exc), **kwargs) if "rate" in name.lower() else TransientError(str(exc), **kwargs)
        if name in {"AuthenticationError", "PermissionDeniedError", "PermissionError"}:
            return AuthError(str(exc), **kwargs)
        if name in {"BadRequestError", "ContextWindowExceededError", "UnprocessableEntityError"}:
            return ProviderError(str(exc), **kwargs)
        if name in {"ServiceUnavailableError", "InternalServerError", "APIConnectionError"}:
            return TransientError(str(exc), **kwargs)
        low = str(exc).lower()
        if "rate limit" in low or "429" in low:
            return RateLimitError(str(exc), **kwargs)
        if "auth" in low or "api key" in low or "401" in low:
            return AuthError(str(exc), **kwargs)
        if "timeout" in low or "connection" in low or "5" in low[:2]:
            return TransientError(str(exc), **kwargs)
        # Default: treat as transient so retry can kick in; the decorator will
        # stop retrying after max_attempts.
        return TransientError(str(exc), **kwargs)


def _factory(spec: OCRBackendSpec) -> LiteLLMBackend:
    return LiteLLMBackend(spec)


if _LITELLM_AVAILABLE:
    register_backend("litellm", _factory)
