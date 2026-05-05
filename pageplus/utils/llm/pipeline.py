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
        )

    # Sync entrypoints -----------------------------------------------------

    def ocr_page(self, document: PagePlusDocumentPage) -> PipelineOutput:
        """Process one page synchronously. Raises on unrecoverable failure."""
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

    def _merge(
        self, document: PagePlusDocumentPage, result: OCRResult,
    ) -> PipelineOutput:
        if self.profile is None:
            raise ConfigurationError("No profile on pipeline",
                                     provider=self.backend.provider_name,
                                     model=self.backend.model_name)
        if self.profile.postprocess_fn is not None:
            fn = self.profile.postprocess_fn
        else:
            fn = get_postprocessor(self.profile.postprocess)

        try:
            output_value = fn(
                result.structured,
                document.image_path,
                page=document.page,
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
