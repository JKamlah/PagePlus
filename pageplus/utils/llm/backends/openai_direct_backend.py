"""Direct OpenAI-compatible OCR backend.

Uses the ``openai`` Python library directly (no LiteLLM), matching the exact
call pattern that works with vLLM, TGI, LM Studio, and any other server that
implements the OpenAI ``/v1/chat/completions`` API.

This backend is registered under the provider name ``"openai_direct"`` and is
used automatically for custom endpoints saved through the GUI.
"""
from __future__ import annotations

import json
from typing import Any, Dict

from pageplus.utils.image import get_image, image_to_base64
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
    OCRBackendSpec,
    OCRResult,
    OpenAICompatibleOptions,
)

try:
    from openai import OpenAI
    _OPENAI_AVAILABLE = True
except ImportError:  # pragma: no cover
    OpenAI = None  # type: ignore[assignment,misc]
    _OPENAI_AVAILABLE = False

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None  # type: ignore[assignment]


class OpenAIDirectBackend(OCRBackend):
    """OCR backend using the ``openai`` library directly.

    Works with any server that speaks the OpenAI ``/v1/chat/completions``
    protocol (vLLM, TGI, LM Studio, Ollama's OpenAI shim, etc.).
    """

    def __init__(self, spec: OCRBackendSpec) -> None:
        super().__init__(spec)
        if not _OPENAI_AVAILABLE:
            raise ConfigurationError(
                "The 'openai' package is not installed; "
                "run `pip install openai`.",
                provider=spec.provider, model=spec.model,
            )
        opts = spec.options
        if not isinstance(opts, OpenAICompatibleOptions):
            raise ConfigurationError(
                f"OpenAIDirectBackend requires OpenAICompatibleOptions, "
                f"got {type(opts).__name__}",
                provider=spec.provider, model=spec.model,
            )
        self._opts: OpenAICompatibleOptions = opts
        # Lazy client creation – built on first call.
        self._client: OpenAI | None = None

    def _get_client(self) -> OpenAI:
        if self._client is None:
            api_key = self._opts.api_key
            if api_key:
                api_key = api_key.strip()
            if not api_key:
                api_key = "EMPTY"

            import logging
            logging.debug("[openai_direct] Creating client: base_url=%r (api_key set=%s)",
                          self._opts.api_base_url, api_key != "EMPTY")
            self._client = OpenAI(
                base_url=self._opts.api_base_url,
                api_key=api_key,
                timeout=self._opts.timeout,
            )
        return self._client

    # ---- OCRBackend API -------------------------------------------------

    def ocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        if not self.model_name:
            raise ConfigurationError(
                "No model configured.",
                provider=self.provider_name,
            )

        import logging
        logging.debug("[openai_direct] OCR call: model=%r image=%s", self.model_name, ctx.image_path.name)
        messages = self._build_messages(prompt, ctx)
        response_format = self._build_response_format(prompt)

        kwargs: Dict[str, Any] = dict(
            model=self.model_name,
            messages=messages,
            max_tokens=prompt.extra.get("max_tokens", 4096),
            temperature=1e-7,
            top_p=1e-8,
            n=1,
            stream=False,
        )
        if response_format is not None:
            kwargs["response_format"] = response_format

        try:
            client = self._get_client()
            response = client.chat.completions.create(**kwargs)
        except Exception as exc:
            logging.exception(f"[openai_direct] Exception in API call to {self._opts.api_base_url!r}")
            raise self._translate_exception(exc) from exc

        return self._parse_response(response, prompt, ctx)

    # ---- Internals ------------------------------------------------------

    def _build_messages(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> list:
        image, image_format = get_image(ctx.image_path)
        w, h = image.size
        ctx.metadata["original_width"] = w
        ctx.metadata["original_height"] = h
        ctx.metadata["rescaled_width"] = w
        ctx.metadata["rescaled_height"] = h
        if self._opts.max_image_size:
            from PIL import Image
            w, h = image.size
            max_size = self._opts.max_image_size
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
                ctx.metadata["rescaled_width"] = new_w
                ctx.metadata["rescaled_height"] = new_h
        image_b64 = image_to_base64(image)

        user_content: list = [
            {"type": "text", "text": prompt.user},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{image_format.lower()};base64,{image_b64}",
                },
            },
        ]
        if ctx.page_xml_payload:
            user_content.insert(1, {"type": "text", "text": ctx.page_xml_payload})

        messages: list = []
        system_role = (
            "user" if prompt.extra.get("only_user_prompt", False) else "system"
        )
        messages.append({
            "role": system_role,
            "content": [{"type": "text", "text": prompt.system}],
        })
        messages.append({"role": "user", "content": user_content})
        return messages

    def _build_response_format(self, prompt: RenderedPrompt) -> Dict[str, Any] | None:
        if prompt.expected_format == "text":
            return None
        use_json_object = (
            prompt.expected_format == "json_object"
        )
        if use_json_object or prompt.schema is None:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": prompt.extra.get(
                    "schema_name", f"{prompt.task_mode}_response"
                ),
                "strict": True,
                "schema": prompt.schema,
            },
        }

    def _parse_response(
        self, response, prompt: RenderedPrompt, ctx: BackendCallContext
    ) -> OCRResult:
        try:
            message = response.choices[0].message
            content = message.content or ""
        except Exception as exc:
            raise SchemaError(
                f"Unexpected response shape: {exc}",
                provider=self.provider_name,
                model=self.model_name,
                cause=exc,
            ) from exc

        structured: Any = None
        if prompt.expected_format.startswith("json"):
            if not content:
                raise SchemaError(
                    "Server returned empty body for JSON task.",
                    provider=self.provider_name,
                    model=self.model_name,
                    raw_response=content,
                )
            try:
                if json_repair is not None:
                    structured = json_repair.repair_json(
                        content, return_objects=True
                    )
                else:
                    structured = json.loads(content)
            except Exception as exc:
                raise SchemaError(
                    f"JSON parse failed: {exc}",
                    provider=self.provider_name,
                    model=self.model_name,
                    raw_response=content,
                    cause=exc,
                ) from exc

        usage_obj = getattr(response, "usage", None)
        usage: Dict[str, Any] = {}
        if usage_obj is not None:
            usage = {
                "total_tokens": getattr(usage_obj, "total_tokens", 0) or 0,
                "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0) or 0,
                "completion_tokens": getattr(
                    usage_obj, "completion_tokens", 0
                )
                or 0,
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
        name = type(exc).__name__
        kwargs = dict(
            provider=self.provider_name, model=self.model_name, cause=exc
        )
        low = str(exc).lower()
        if "rate limit" in low or "429" in low:
            return RateLimitError(str(exc), **kwargs)
        if "auth" in low or "api key" in low or "401" in low:
            return AuthError(str(exc), **kwargs)
        if "timeout" in low or "connection" in low:
            return TransientError(str(exc), **kwargs)
        if name in {
            "APIConnectionError",
            "APITimeoutError",
            "InternalServerError",
        }:
            return TransientError(str(exc), **kwargs)
        if name in {"AuthenticationError", "PermissionDeniedError"}:
            return AuthError(str(exc), **kwargs)
        if name == "BadRequestError":
            return ProviderError(str(exc), **kwargs)
        return TransientError(str(exc), **kwargs)


def _factory(spec: OCRBackendSpec) -> OpenAIDirectBackend:
    return OpenAIDirectBackend(spec)


if _OPENAI_AVAILABLE:
    register_backend("openai_direct", _factory)
