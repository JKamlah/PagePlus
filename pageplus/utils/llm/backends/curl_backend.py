"""Direct Curl-style HTTP POST REST backend.

Sends a flat JSON POST request with base64-encoded image and prompt.
Registered under the provider name "curl".
"""
from __future__ import annotations

import base64
import json
import urllib.request
import urllib.error
from pathlib import Path
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
    CurlHTTPOptions,
)

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None  # type: ignore[assignment]


class CurlHTTPBackend(OCRBackend):
    """OCR backend calling a custom REST endpoint with a flat JSON body."""

    def __init__(self, spec: OCRBackendSpec) -> None:
        super().__init__(spec)
        opts = spec.options
        if not isinstance(opts, CurlHTTPOptions):
            raise ConfigurationError(
                f"CurlHTTPBackend requires CurlHTTPOptions, got {type(opts).__name__}",
                provider=spec.provider, model=spec.model,
            )
        self._opts: CurlHTTPOptions = opts

    def ocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        if not self._opts.url:
            raise ConfigurationError(
                "No target URL configured for curl provider.",
                provider=self.provider_name,
            )

        import logging
        logging.debug("[curl_backend] OCR call: url=%r image=%s", self._opts.url, ctx.image_path.name)

        # 1. Process image & convert to base64
        image, image_format = get_image(ctx.image_path)
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
        image_b64 = image_to_base64(image)

        # 2. Build combined prompt text (system + user)
        combined_parts = []
        if prompt.system:
            combined_parts.append(prompt.system)
        if prompt.user:
            combined_parts.append(prompt.user)
        if ctx.page_xml_payload:
            combined_parts.append(ctx.page_xml_payload)
        combined_prompt = "\n\n".join(combined_parts)

        # 3. Construct payload
        payload = {
            self._opts.image_key: image_b64,
            self._opts.prompt_key: combined_prompt,
        }

        # 4. Set headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PagePlus-CurlBackend",
        }
        if self._opts.api_key and self._opts.api_key != "EMPTY":
            headers["Authorization"] = f"Bearer {self._opts.api_key}"

        data_bytes = json.dumps(payload).encode("utf-8")

        # 5. Execute HTTP POST using urllib
        req = urllib.request.Request(
            self._opts.url,
            data=data_bytes,
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self._opts.timeout) as response:
                resp_bytes = response.read()
                content = resp_bytes.decode("utf-8")
        except urllib.error.HTTPError as exc:
            logging.exception(f"[curl_backend] HTTP error calling {self._opts.url!r}")
            raise self._translate_http_error(exc) from exc
        except Exception as exc:
            logging.exception(f"[curl_backend] Connection/Timeout error calling {self._opts.url!r}")
            raise TransientError(str(exc), provider=self.provider_name, model=self.model_name, cause=exc) from exc

        # 6. Parse response
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
                    structured = json_repair.repair_json(content, return_objects=True)
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
        else:
            # For non-json text mappings, or as fallback
            structured = content

        # Check if we got structured response but need to extract text from a JSON response
        text_content = content
        if isinstance(structured, dict):
            # Try some common text keys if the response was a JSON object but we wanted text
            for key in ("text", "content", "result", "output", "transcription", "response"):
                if key in structured and isinstance(structured[key], str):
                    text_content = structured[key]
                    break

        return OCRResult(
            text=text_content,
            structured=structured,
            provider_name=self.provider_name,
            model_name=self.model_name,
            usage={"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0},
            ocr_metadata={
                "task_mode": prompt.task_mode,
                "snippet_id": ctx.snippet_id,
                **dict(ctx.metadata),
            },
            raw_response=content,
        )

    def _translate_http_error(self, exc: urllib.error.HTTPError) -> BaseException:
        code = exc.code
        body = ""
        try:
            body = exc.read().decode("utf-8")
        except Exception:
            pass

        kwargs = dict(
            provider=self.provider_name,
            model=self.model_name,
            cause=exc,
            raw_response=body,
        )
        msg = f"HTTP {code}: {exc.reason}. Body: {body[:500]}"

        if code == 401 or code == 403:
            return AuthError(msg, **kwargs)
        if code == 429:
            return RateLimitError(msg, **kwargs)
        if code >= 500:
            return TransientError(msg, **kwargs)
        return ProviderError(msg, **kwargs)


def _factory(spec: OCRBackendSpec) -> CurlHTTPBackend:
    return CurlHTTPBackend(spec)


register_backend("curl", _factory)
