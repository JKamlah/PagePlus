"""PagePlus OCR pipeline.

Orchestrates the three layers we built:

    TaskMode + OCRModelProfile   (templates + schema)
            +
    OCRBackendSpec -> OCRBackend (provider call + error mapping)
            +
    postprocess(...)             (JSON -> PAGE-XML or Page mutation)

Given an :class:`OCRBackendSpec` and a :class:`TaskMode`, the pipeline turns a
list of :class:`PagePlusDocumentPage` s into either fresh PAGE-XML strings
(for ``layout_only`` / ``layout_and_text``) or mutated :class:`Page` objects
(for the three correction modes).

Sync and async entrypoints are both provided; the async one bounds concurrency
via ``asyncio.Semaphore`` -- this replaces the per-module
``ThreadPoolExecutor + Lock + timestamps`` pattern in
``pageplus/cli/gemini.py``.
"""
from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from pageplus.io.logger import logging
from pageplus.utils.llm.backends.base import (
    BackendCallContext,
    OCRBackend,
    RenderedPrompt,
)
from pageplus.utils.llm.core.builder import build_ocr_backend
from pageplus.utils.llm.core.errors import ConfigurationError, OCRError
from pageplus.utils.llm.core.retry import (
    DEFAULT_POLICY,
    RetryPolicy,
    awith_retry,
    with_retry,
)
from pageplus.utils.llm.core.specs import (
    ExecutionStrategy,
    OCRBackendSpec,
    OCRModelProfile,
    OCRResult,
    TaskMode,
)
from pageplus.utils.llm.templates import (
    get_postprocessor,
    render_page_xml_payload,
    render_prompt,
    resolve_profile,
)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class PagePlusDocumentPage:
    """Thin wrapper around an image + optional existing :class:`Page`.

    Carries the Page object itself (not a copy) for the correction modes so
    postprocessors can mutate in place. ``region_filter`` / ``line_filter``
    are reserved hooks for future tag/id-based narrowing; not wired into the
    default templates yet.
    """
    image_path: Path
    page: Optional[Any] = None                # pageplus.models.page.Page
    region_filter: Optional[Callable[[Any], bool]] = None
    line_filter: Optional[Callable[[Any], bool]] = None
    output_xml_path: Optional[Path] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineOutput:
    """One item returned from :meth:`PagePlusOCRPipeline.ocr_pages`.

    For ``layout_only`` / ``layout_and_text`` the result is a PAGE-XML string
    in :attr:`xml_content`; the caller persists it. For the correction modes
    the result is the mutated :class:`Page` in :attr:`page`, and
    :attr:`xml_content` is ``None``.
    """
    document: PagePlusDocumentPage
    ocr_result: Optional[OCRResult] = None
    xml_content: Optional[str] = None
    page: Optional[Any] = None
    error: Optional[BaseException] = None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

_CORRECTION_MODES = {
    TaskMode.LAYOUT_CORRECTION,
    TaskMode.TEXT_ONLY,
    TaskMode.TEXT_CORRECTION,
}

# Postprocessors whose raw model answer is plain text / markdown rather than a
# JSON object. Used to decide the raw-output folder name and file extension.
_TEXT_POSTPROCESSORS = {"markdown_to_page", "markdown2pagexml", "text"}


@dataclass
class PagePlusOCRPipeline:
    """Dispatches :class:`PagePlusDocumentPage` s to a backend based on
    :class:`TaskMode` and merges the result back into PAGE-XML."""
    backend: OCRBackend
    task_mode: TaskMode
    profile: Optional[OCRModelProfile] = None
    retry_policy: RetryPolicy = field(default_factory=lambda: DEFAULT_POLICY)
    max_concurrency: int = 4
    execution: ExecutionStrategy = ExecutionStrategy.WHOLE_PAGE
    # For PER_SNIPPET execution: which element granularity to crop and OCR.
    # One of "TextRegion" / "Textline". Ignored for WHOLE_PAGE.
    snippet_level: str = "Textline"
    # Persist the raw model answer (JSON / markdown) next to the output, into a
    # ``json/`` or ``markdown/`` subfolder, *before* converting to PAGE-XML.
    save_raw: bool = True

    # Constructors ---------------------------------------------------------

    @classmethod
    def from_spec(
        cls,
        spec: OCRBackendSpec,
        task_mode: TaskMode,
        *,
        profile: Optional[OCRModelProfile] = None,
        retry_policy: Optional[RetryPolicy] = None,
        max_concurrency: int = 4,
        snippet_level: str = "Textline",
        save_raw: bool = True,
    ) -> "PagePlusOCRPipeline":
        backend = build_ocr_backend(spec)
        resolved = profile or spec.profile or resolve_profile(
            spec.provider, spec.model, task_mode)
        if resolved.task_mode != task_mode:
            raise ConfigurationError(
                f"Profile '{resolved.name}' is for task_mode={resolved.task_mode.value}, "
                f"but pipeline was asked for task_mode={task_mode.value}.",
                provider=spec.provider, model=spec.model,
            )
        return cls(
            backend=backend,
            task_mode=task_mode,
            profile=resolved,
            retry_policy=retry_policy or DEFAULT_POLICY,
            max_concurrency=max_concurrency,
            execution=spec.execution,
            snippet_level=snippet_level,
            save_raw=save_raw,
        )

    # Sync entrypoints -----------------------------------------------------

    def ocr_page(self, document: PagePlusDocumentPage) -> PipelineOutput:
        """Process one page synchronously. Raises on unrecoverable failure."""
        if self.execution == ExecutionStrategy.PER_SNIPPET:
            return self._ocr_page_snippets(document)

        prompt, ctx = self._prepare_call(document)

        @with_retry(self.retry_policy)
        def _call() -> OCRResult:
            return self.backend.ocr(prompt, ctx)

        result = _call()
        return self._merge(document, result)

    def ocr_pages(
        self,
        documents: List[PagePlusDocumentPage],
        *,
        continue_on_error: bool = True,
    ) -> List[PipelineOutput]:
        outputs: List[PipelineOutput] = []
        for doc in documents:
            try:
                outputs.append(self.ocr_page(doc))
            except Exception as exc:
                if not continue_on_error:
                    raise
                logging.error("OCR failed for %s: %s", doc.image_path, exc)
                outputs.append(PipelineOutput(document=doc, error=exc))
        return outputs

    # Async entrypoints ----------------------------------------------------

    async def aocr_page(self, document: PagePlusDocumentPage) -> PipelineOutput:
        if self.execution == ExecutionStrategy.PER_SNIPPET:
            # Snippet OCR mutates a shared Page object and crops images; run the
            # whole page in a worker thread to keep it off the event loop.
            return await asyncio.to_thread(self._ocr_page_snippets, document)

        prompt, ctx = self._prepare_call(document)

        @awith_retry(self.retry_policy)
        async def _call() -> OCRResult:
            return await self.backend.aocr(prompt, ctx)

        result = await _call()
        return self._merge(document, result)

    async def aocr_pages(
        self,
        documents: List[PagePlusDocumentPage],
        *,
        continue_on_error: bool = True,
    ) -> List[PipelineOutput]:
        sem = asyncio.Semaphore(max(1, int(self.max_concurrency)))

        async def _run(doc: PagePlusDocumentPage) -> PipelineOutput:
            async with sem:
                try:
                    return await self.aocr_page(doc)
                except Exception as exc:
                    if not continue_on_error:
                        raise
                    logging.error("OCR failed for %s: %s", doc.image_path, exc)
                    return PipelineOutput(document=doc, error=exc)

        return await asyncio.gather(*(_run(d) for d in documents))

    # Helpers --------------------------------------------------------------

    def _prepare_call(
        self, document: PagePlusDocumentPage,
    ) -> tuple[RenderedPrompt, BackendCallContext]:
        if self.profile is None:
            raise ConfigurationError(
                "Pipeline has no profile configured; use `from_spec`.",
                provider=self.backend.provider_name,
                model=self.backend.model_name,
            )
        page_xml_text: Optional[str] = None
        page_xml_dict: Optional[Dict[str, Any]] = None
        # Calculate rescaling scale factors
        scale_x, scale_y = 1.0, 1.0
        max_image_size = getattr(self.backend.spec.options, "max_image_size", None)
        if max_image_size:
            try:
                from PIL import Image
                with Image.open(document.image_path) as img:
                    w, h = img.size
                if w > max_image_size or h > max_image_size:
                    if w >= h:
                        new_w = max_image_size
                        new_h = int(h * (max_image_size / w))
                    else:
                        new_h = max_image_size
                        new_w = int(w * (max_image_size / h))
                    new_w = max(1, new_w)
                    new_h = max(1, new_h)
                    scale_x = new_w / w
                    scale_y = new_h / h
            except Exception as exc:
                logging.warning("Could not pre-calculate rescaling scale factor: %s", exc)

        if self.task_mode in _CORRECTION_MODES:
            if document.page is None:
                raise ConfigurationError(
                    f"Task mode {self.task_mode.value} requires document.page to be provided.",
                    provider=self.backend.provider_name,
                    model=self.backend.model_name,
                )
            include_text = self.task_mode == TaskMode.TEXT_CORRECTION
            page_xml_text = render_page_xml_payload(
                document.page, include_text=include_text, mode=self.task_mode,
                region_filter=document.region_filter,
                line_filter=document.line_filter,
                scale_x=scale_x,
                scale_y=scale_y,
            )

        prompt = render_prompt(
            self.profile,
            page_xml_dict=page_xml_dict,
            page_xml_text=page_xml_text,
        )
        ctx = BackendCallContext(
            image_path=document.image_path,
            page_xml_payload=None,  # payload is already in the user prompt
            page_xml_dict=page_xml_dict,
            metadata=dict(document.metadata),
        )
        return prompt, ctx

    # Raw-answer persistence ----------------------------------------------

    def _raw_format(self) -> tuple[str, str]:
        """Return ``(subdir, extension)`` for the raw model answer."""
        expected = getattr(self.profile, "expected_format", None) if self.profile else None
        mapping = (getattr(self.profile, "postprocess", "") if self.profile else "") or ""
        is_text = expected == "text" or mapping in _TEXT_POSTPROCESSORS
        if is_text:
            return "markdown", ".md"
        return "json", ".json"

    def _raw_target(self, document: PagePlusDocumentPage, subdir: str, ext: str) -> Path:
        stem = (document.output_xml_path or document.image_path).stem
        if self.save_raw:
            # Permanent artifact: json/ or markdown/ next to the output XML.
            out_xml = document.output_xml_path
            base_dir = out_xml.parent if out_xml is not None else document.image_path.parent
            return base_dir / subdir / f"{stem}{ext}"
        # save_raw is False: keep the answer only as a temporary file.
        tmp_dir = Path(tempfile.gettempdir()) / "pageplus_raw" / subdir
        return tmp_dir / f"{stem}{ext}"

    def _save_raw(
        self,
        document: PagePlusDocumentPage,
        *,
        text: Optional[str],
        structured: Optional[Any],
    ) -> Optional[Path]:
        """Persist the raw model answer before it is converted to PAGE-XML.

        Always written: with ``save_raw=True`` it lands permanently in a
        ``json/`` / ``markdown/`` folder next to the output; with
        ``save_raw=False`` it goes to a temporary folder instead. Saved even
        when the later conversion fails, so it can be inspected or re-converted.
        Returns the path written (or ``None``).
        """
        subdir, ext = self._raw_format()
        if ext == ".json" and structured is not None:
            import json as _json
            try:
                content = _json.dumps(structured, indent=2, ensure_ascii=False)
            except Exception:
                content = text or ""
        else:
            content = text or ""
        if not content.strip():
            return None
        try:
            target = self._raw_target(document, subdir, ext)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            logging.info("[raw] saved model answer -> %s", target)
            return target
        except Exception as exc:  # pragma: no cover - best-effort persistence
            logging.warning("[raw] could not save model answer: %s", exc)
            return None

    def _merge(
        self, document: PagePlusDocumentPage, result: OCRResult,
    ) -> PipelineOutput:
        if self.profile is None:
            raise ConfigurationError("No profile on pipeline",
                                     provider=self.backend.provider_name,
                                     model=self.backend.model_name)
        # Persist the raw answer first, so it survives a conversion failure.
        self._save_raw(document, text=result.text, structured=result.structured)

        # Scale coordinates back to original size if rescaling occurred
        orig_w = result.ocr_metadata.get("original_width")
        orig_h = result.ocr_metadata.get("original_height")
        scaled_w = result.ocr_metadata.get("rescaled_width")
        scaled_h = result.ocr_metadata.get("rescaled_height")
        if orig_w and orig_h and scaled_w and scaled_h:
            if orig_w != scaled_w or orig_h != scaled_h:
                scale_x = orig_w / scaled_w
                scale_y = orig_h / scaled_h
                from pageplus.utils.llm.templates.postprocess import scale_structured_coordinates
                result.structured = scale_structured_coordinates(result.structured, scale_x, scale_y)

        if self.profile.postprocess_fn is not None:
            fn = self.profile.postprocess_fn
        else:
            fn = get_postprocessor(self.profile.postprocess)

        try:
            output_value = fn(
                result.structured,
                document.image_path,
                page=document.page,
                text=result.text,
                region_filter=document.region_filter,
                line_filter=document.line_filter,
            )
        except OCRError:
            raise
        except Exception as exc:
            raise OCRError(
                f"Postprocessor '{self.profile.postprocess}' failed: {exc}",
                provider=self.backend.provider_name,
                model=self.backend.model_name,
                cause=exc,
            ) from exc

        xml_content: Optional[str] = None
        merged_page: Optional[Any] = None
        if self.task_mode in _CORRECTION_MODES:
            # The postprocessor mutates the Page in place and returns None.
            merged_page = document.page
        else:
            xml_content = output_value if isinstance(output_value, str) else None

        return PipelineOutput(
            document=document,
            ocr_result=result,
            xml_content=xml_content,
            page=merged_page,
        )

    # Per-snippet execution ------------------------------------------------

    _SNIPPET_SYSTEM_DEFAULT = (
        "You are an expert OCR transcriber. You are given a cropped image of a "
        "single {unit} from a historical document. Transcribe its text exactly "
        "as written, preserving spelling, diacritics, and line breaks. Return "
        "only the transcription with no commentary."
    )

    def _ocr_page_snippets(self, document: PagePlusDocumentPage) -> PipelineOutput:
        """Crop each region/line, OCR it on its own, and write text back.

        This is the fallback path for backends/models that work best on small
        crops, and the way the LLM-OCR tab implements the *Region* / *Textline*
        task level. The existing :class:`Page` is mutated in place.
        """
        if document.page is None:
            raise ConfigurationError(
                "Per-snippet execution requires document.page to be provided.",
                provider=self.backend.provider_name,
                model=self.backend.model_name,
            )

        from PIL import Image
        from pageplus.utils.image import crop_image_by_polygon

        unit = "text region" if self.snippet_level == "TextRegion" else "text line"
        system_text = (self.profile.system_prompt if self.profile else None) or \
            self._SNIPPET_SYSTEM_DEFAULT.format(unit=unit)
        user_text = (self.profile.user_prompt if self.profile else None) or \
            "Transcribe the text in this image."

        elements = list(self._collect_snippet_elements(document))
        usage_total: Dict[str, int] = {}
        raw_map: Dict[str, str] = {}
        n_done = 0
        try:
            base_image = Image.open(document.image_path).convert("RGB")
        except Exception as exc:  # pragma: no cover - defensive
            raise OCRError(
                f"Could not open image {document.image_path}: {exc}",
                provider=self.backend.provider_name,
                model=self.backend.model_name,
                cause=exc,
            ) from exc

        with tempfile.TemporaryDirectory(prefix="pageplus_snippet_") as tmpdir:
            tmp_root = Path(tmpdir)
            for idx, element in enumerate(elements):
                polygon = self._element_polygon(element)
                if polygon is None:
                    continue
                try:
                    snippet, _bbox = crop_image_by_polygon(
                        base_image, polygon, transparent_background=False,
                        square_canvas=False,
                    )
                    snippet_path = tmp_root / f"snippet_{idx}.png"
                    snippet.convert("RGB").save(snippet_path)
                except Exception as exc:  # pragma: no cover - defensive
                    logging.warning("Snippet crop failed for element %s: %s",
                                    self._element_id(element), exc)
                    continue

                prompt = RenderedPrompt(
                    system=system_text,
                    user=user_text,
                    task_mode=self.task_mode.value,
                    schema=None,
                    expected_format="text",
                )
                ctx = BackendCallContext(
                    image_path=snippet_path,
                    snippet_id=self._element_id(element),
                    metadata=dict(document.metadata),
                )

                @with_retry(self.retry_policy)
                def _call() -> OCRResult:
                    return self.backend.ocr(prompt, ctx)

                try:
                    result = _call()
                except OCRError as exc:
                    logging.error("Snippet OCR failed for %s: %s",
                                  self._element_id(element), exc)
                    continue

                text = (result.text or "").strip()
                if text:
                    raw_map[self._element_id(element) or f"snippet_{idx}"] = text
                if text and hasattr(element, "update_text"):
                    try:
                        element.update_text(text)
                        n_done += 1
                    except Exception as exc:  # pragma: no cover - defensive
                        logging.warning("update_text failed for %s: %s",
                                        self._element_id(element), exc)
                for key, value in (result.usage or {}).items():
                    if isinstance(value, (int, float)):
                        usage_total[key] = usage_total.get(key, 0) + int(value)

        merged_result = OCRResult(
            text="",
            provider_name=self.backend.provider_name,
            model_name=self.backend.model_name,
            usage=usage_total,
            ocr_metadata={
                "task_mode": self.task_mode.value,
                "execution": "per_snippet",
                "snippet_level": self.snippet_level,
                "snippets_processed": n_done,
            },
        )
        # Persist the per-snippet answers (id -> text) as a raw JSON answer.
        if raw_map:
            import json as _json
            try:
                target = self._raw_target(document, "json", ".json")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    _json.dumps(raw_map, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                logging.info("[raw] saved %d snippet answers -> %s",
                             len(raw_map), target)
            except Exception as exc:  # pragma: no cover - best-effort persistence
                logging.warning("[raw] could not save snippet answers: %s", exc)
        return PipelineOutput(
            document=document,
            ocr_result=merged_result,
            xml_content=None,
            page=document.page,
        )

    def _collect_snippet_elements(self, document: PagePlusDocumentPage):
        """Yield the regions or textlines to OCR, honouring the filters."""
        page = document.page
        regions = []
        page_regions = getattr(page, "regions", None)
        if page_regions is not None:
            for attr in ("textregions", "tableregions"):
                regions.extend(getattr(page_regions, attr, []) or [])

        for region in regions:
            if document.region_filter is not None:
                try:
                    if not document.region_filter(region):
                        continue
                except Exception:  # pragma: no cover - defensive
                    pass
            if self.snippet_level == "TextRegion":
                yield region
                continue
            for line in getattr(region, "textlines", []) or []:
                if document.line_filter is not None:
                    try:
                        if not document.line_filter(line):
                            continue
                    except Exception:  # pragma: no cover - defensive
                        pass
                yield line

    @staticmethod
    def _element_polygon(element):
        try:
            poly = element.get_coordinates(returntype="polygon")
        except Exception:  # pragma: no cover - defensive
            return None
        if poly is None or getattr(poly, "is_empty", False):
            return None
        return poly

    @staticmethod
    def _element_id(element) -> str:
        try:
            return element.get_id()
        except Exception:  # pragma: no cover - defensive
            return ""
