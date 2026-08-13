"""Mistral Document AI / OCR backend.

Calls Mistral's dedicated OCR API endpoint (https://api.mistral.ai/v1/ocr)
with base64 document images, returning structured block coordinates and HTML tables.
Registered under the provider name "mistral_ocr".
"""
from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request
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
    MistralOptions,
    OCRBackendSpec,
    OCRResult,
)

try:
    import json_repair
except ImportError:  # pragma: no cover
    json_repair = None  # type: ignore[assignment]


class MistralOCRBackend(OCRBackend):
    """OCR backend calling Mistral's Document OCR API (/v1/ocr)."""

    def __init__(self, spec: OCRBackendSpec) -> None:
        super().__init__(spec)
        opts = spec.options
        if not isinstance(opts, MistralOptions):
            # Fall back to creating MistralOptions if dictionary/default options passed
            opts = MistralOptions()
        self._opts: MistralOptions = opts

    def ocr(self, prompt: RenderedPrompt, ctx: BackendCallContext) -> OCRResult:
        api_key = self._opts.api_key
        if not api_key:
            from pageplus.gui.utils.settings import Settings
            api_key = Settings().get("MISTRAL_API_KEY")
        
        if not api_key:
            raise ConfigurationError(
                "MISTRAL_API_KEY is not set. Please configure your API key for Mistral OCR.",
                provider=self.provider_name,
                model=self.model_name,
            )

        url = self._opts.api_base_url or "https://api.mistral.ai/v1/ocr"
        logging.debug("[mistral_ocr_backend] OCR call: url=%r image=%s", url, ctx.image_path.name)

        # 1. Process image
        image, image_format = get_image(ctx.image_path)
        w, h = image.size
        ctx.metadata["original_width"] = w
        ctx.metadata["original_height"] = h
        ctx.metadata["rescaled_width"] = w
        ctx.metadata["rescaled_height"] = h

        # Determine MIME type
        fmt_lower = (image_format or "jpeg").lower()
        if fmt_lower in ("png", "jpg", "jpeg", "webp", "gif"):
            mime_type = f"image/{fmt_lower if fmt_lower != 'jpg' else 'jpeg'}"
        else:
            mime_type = "image/jpeg"

        image_b64 = image_to_base64(image)
        data_url = f"data:{mime_type};base64,{image_b64}"

        # 2. Build payload according to Mistral OCR API spec
        payload: Dict[str, Any] = {
            "model": self.spec.model or self._opts.model or "mistral-ocr-latest",
            "document": {
                "type": "image_url",
                "image_url": data_url,
            },
            "table_format": self._opts.table_format or "html",
            "include_blocks": self._opts.include_blocks,
            "extract_header": self._opts.extract_header,
            "extract_footer": self._opts.extract_footer,
        }

        # 3. Set headers
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "PagePlus-MistralOCRBackend",
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data_bytes,
            headers=headers,
            method="POST",
        )

        # 4. Execute request
        try:
            with urllib.request.urlopen(req, timeout=self._opts.timeout) as response:
                resp_bytes = response.read()
                content = resp_bytes.decode("utf-8")
        except urllib.error.HTTPError as exc:
            logging.exception(f"[mistral_ocr_backend] HTTP error calling {url!r}")
            raise self._translate_http_error(exc) from exc
        except Exception as exc:
            logging.exception(f"[mistral_ocr_backend] Connection error calling {url!r}")
            raise TransientError(str(exc), provider=self.provider_name, model=self.model_name, cause=exc) from exc

        # 5. Parse response
        try:
            if json_repair is not None:
                structured = json_repair.repair_json(content, return_objects=True)
            else:
                structured = json.loads(content)
        except Exception as exc:
            raise SchemaError(
                f"Mistral OCR response JSON parse failed: {exc}",
                provider=self.provider_name,
                model=self.model_name,
                raw_response=content,
                cause=exc,
            ) from exc

        # Extract primary markdown text from first page if present
        text_content = ""
        if isinstance(structured, dict) and "pages" in structured and len(structured["pages"]) > 0:
            first_page = structured["pages"][0]
            if isinstance(first_page, dict):
                text_content = first_page.get("markdown", "")

        return OCRResult(
            text=text_content,
            structured=structured,
            provider_name=self.provider_name,
            model_name=self.model_name,
            usage=structured.get("usage_info", {}) if isinstance(structured, dict) else {},
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
        msg = f"Mistral OCR HTTP {code}: {exc.reason}. Body: {body[:500]}"

        if code in (401, 403):
            return AuthError(msg, **kwargs)
        if code == 429:
            return RateLimitError(msg, **kwargs)
        if code >= 500:
            return TransientError(msg, **kwargs)
        return ProviderError(msg, **kwargs)


def _factory(spec: OCRBackendSpec) -> MistralOCRBackend:
    return MistralOCRBackend(spec)


register_backend("mistral_ocr", _factory)
