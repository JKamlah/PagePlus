"""Streamlit-friendly bridge to the LiteLLM-backed OCR pipeline.

This mirrors :class:`pageplus.gui.cli_bridges.gemini.GeminiBridge` but targets
the provider-agnostic LiteLLM path built on top of
:class:`pageplus.utils.llm.pipeline.PagePlusOCRPipeline` and the provider
preset registry.

The bridge is intentionally thin:

- **Preset discovery** (:meth:`list_presets`, :meth:`preset_info`) wraps
  :mod:`pageplus.utils.llm.provider_registry` so the GUI can render a
  preset picker without importing LiteLLM modules directly.
- **Credential writes** (:meth:`save_api_key`, :meth:`save_api_base`) route
  through :class:`pageplus.gui.utils.settings.Settings` so changes land in
  the shared ``.env`` file and survive reloads.
- **OCR** (:meth:`run_ocr`) builds a spec from a preset, resolves file lists
  into :class:`PagePlusDocumentPage` inputs (correctly for both image-only
  modes and XML-correction modes), runs the pipeline, and writes the
  resulting PAGE-XML / mutated Page back to disk.

The bridge never crashes the GUI: every public entrypoint returns a
``{"success", "output", ...}`` dict.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from pageplus.gui.utils.settings import Settings
from pageplus.gui.utils.undo import UndoManager


# We only depend on LiteLLM through the pipeline + provider_registry. Those
# modules require LiteLLM to be installed; we import lazily inside methods so
# that importing this bridge never crashes when LiteLLM is absent.


def _litellm_available() -> bool:
    from importlib import util
    return util.find_spec("litellm") is not None


class LiteLLMBridge:
    """GUI-facing wrapper around :class:`PagePlusOCRPipeline` with LiteLLM."""

    # ------------------------------------------------------------------
    # Availability / capability introspection
    # ------------------------------------------------------------------

    def is_available(self) -> dict:
        """Return ``{"success", "output"}`` indicating LiteLLM availability."""
        if _litellm_available():
            return {"success": True, "output": "LiteLLM is installed."}
        return {
            "success": False,
            "output": (
                "LiteLLM is not installed. Run `pageplus litellm install` "
                "or `pip install litellm json-repair`."
            ),
        }

    # ------------------------------------------------------------------
    # Preset discovery
    # ------------------------------------------------------------------

    def list_presets(self, only_configured: bool = False) -> dict:
        """Return preset metadata as plain dicts for Streamlit consumption."""
        try:
            from pageplus.utils.llm.provider_registry import (
                available_providers,
                list_providers,
            )

            presets = available_providers() if only_configured else list_providers()
            rows: List[Dict[str, Any]] = []
            for p in presets:
                rows.append({
                    "id": p.id,
                    "display_name": p.display_name,
                    "litellm_prefix": p.litellm_prefix,
                    "default_model": p.default_model,
                    "alt_models": list(p.alt_models),
                    "env_api_key": p.env_api_key,
                    "env_api_base": p.env_api_base,
                    "api_base_hint": p.api_base_hint,
                    "requires_base_url": p.requires_base_url,
                    "vision_capable": p.vision_capable,
                    "supports_json_schema": p.supports_json_schema,
                    "task_modes": [tm.value for tm in p.task_modes],
                    "configured": p.is_configured(),
                })
            return {
                "success": True,
                "output": f"Found {len(rows)} preset(s).",
                "presets": rows,
            }
        except Exception as exc:
            return {"success": False, "output": str(exc), "presets": []}

    def preset_info(self, preset_id: str) -> dict:
        """Detailed info for a single preset (resolved credentials masked)."""
        try:
            from pageplus.utils.llm.provider_registry import get_preset

            preset = get_preset(preset_id)
            api_key, api_base = preset.resolve_credentials()
            return {
                "success": True,
                "output": preset.display_name,
                "preset": {
                    "id": preset.id,
                    "display_name": preset.display_name,
                    "litellm_prefix": preset.litellm_prefix,
                    "default_model": preset.default_model,
                    "alt_models": list(preset.alt_models),
                    "env_api_key": preset.env_api_key,
                    "env_api_base": preset.env_api_base,
                    "api_base_hint": preset.api_base_hint,
                    "requires_base_url": preset.requires_base_url,
                    "vision_capable": preset.vision_capable,
                    "supports_json_schema": preset.supports_json_schema,
                    "task_modes": [tm.value for tm in preset.task_modes],
                    "api_key_set": bool(api_key),
                    "api_base_url": api_base,
                    "configured": preset.is_configured(),
                },
            }
        except Exception as exc:
            return {"success": False, "output": str(exc), "preset": None}

    # ------------------------------------------------------------------
    # Credential management (writes to .env)
    # ------------------------------------------------------------------

    def save_api_key(self, preset_id: str, api_key: str) -> dict:
        try:
            from pageplus.utils.llm.provider_registry import get_preset

            preset = get_preset(preset_id)
            if not preset.env_api_key:
                return {
                    "success": False,
                    "output": f"Preset '{preset.display_name}' does not use an API-key env var.",
                }
            Settings().set(preset.env_api_key, api_key)
            return {
                "success": True,
                "output": f"Saved {preset.env_api_key} to .env.",
            }
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def save_api_base(self, preset_id: str, api_base_url: str) -> dict:
        try:
            from pageplus.utils.llm.provider_registry import get_preset

            preset = get_preset(preset_id)
            if not preset.env_api_base:
                return {
                    "success": False,
                    "output": f"Preset '{preset.display_name}' does not use a base-URL env var.",
                }
            Settings().set(preset.env_api_base, api_base_url)
            return {
                "success": True,
                "output": f"Saved {preset.env_api_base} to .env.",
            }
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    # ------------------------------------------------------------------
    # OCR via the unified pipeline
    # ------------------------------------------------------------------

    def run_ocr(
        self,
        preset_id: str,
        task_mode: str,
        image_files: Optional[List[str]] = None,
        xml_files: Optional[List[str]] = None,
        *,
        model: Optional[str] = None,
        outputdir: Optional[str] = None,
        image_folder: Optional[str] = None,
        same_names: bool = False,
        jobs: int = 4,
        calls_per_minute: int = 120,
        json_object: bool = False,
        overwrite: bool = True,
        dry_run: bool = False,
    ) -> dict:
        """Run OCR/correction on one or more files via LiteLLM.

        Mode-specific expectations:

        - ``layout_only`` / ``layout_and_text``: ``image_files`` is required;
          the pipeline emits fresh PAGE-XML per image.
        - ``layout_correction`` / ``text_only`` / ``text_correction``:
          ``xml_files`` is required. Matching images are resolved via
          ``page.imageFilename()`` (or by ``same_names`` lookup in
          ``image_folder``).

        The resulting PAGE-XML is written next to the input (``overwrite``) or
        under ``<outputdir>/<xml_file.name>``. When ``dry_run`` is true no
        files are written, but the pipeline still runs for cost estimation.
        """
        if not _litellm_available():
            return self.is_available()

        try:
            from pageplus.models.page import Page
            from pageplus.utils.fs import find_image
            from pageplus.utils.llm.core import RetryPolicy, TaskMode
            from pageplus.utils.llm.pipeline import (
                PagePlusDocumentPage,
                PagePlusOCRPipeline,
            )
            from pageplus.utils.llm.provider_registry import spec_from_preset

            try:
                mode = TaskMode(task_mode)
            except ValueError:
                return {
                    "success": False,
                    "output": f"Unknown task_mode '{task_mode}'.",
                    "usage": [],
                }

            image_only_modes = {TaskMode.LAYOUT_ONLY, TaskMode.LAYOUT_AND_TEXT}
            # Every other :class:`TaskMode` is a correction mode that requires
            # an existing PAGE-XML document.

            documents: List[PagePlusDocumentPage] = []
            backups: List[Path] = []

            if mode in image_only_modes:
                if not image_files:
                    return {
                        "success": False,
                        "output": f"Task mode '{task_mode}' needs image files.",
                        "usage": [],
                    }
                for img in image_files:
                    img_path = Path(img)
                    if outputdir:
                        out_xml = Path(outputdir) / img_path.with_suffix(".xml").name
                    else:
                        out_xml = img_path.with_suffix(".xml")
                    if out_xml.exists() and overwrite and not dry_run:
                        backups.append(out_xml)
                    documents.append(PagePlusDocumentPage(
                        image_path=img_path,
                        page=None,
                        output_xml_path=out_xml,
                    ))
            else:  # correction_modes
                if not xml_files:
                    return {
                        "success": False,
                        "output": f"Task mode '{task_mode}' needs PAGE-XML files.",
                        "usage": [],
                    }
                image_folder_path = Path(image_folder) if image_folder else None
                for xml in xml_files:
                    xml_path = Path(xml)
                    page = Page(xml_path)
                    if mode == TaskMode.TEXT_ONLY:
                        page.delete_textlevel('TextRegion')
                    search_dir = image_folder_path or xml_path.parent
                    if same_names:
                        img_path: Optional[Path] = None
                        for ext in ('.png', '.jpg', '.jpeg', '.tif', '.tiff'):
                            candidate = xml_path.with_suffix(ext).name
                            img_path = find_image(candidate, search_dir)
                            if img_path:
                                break
                    else:
                        img_path = find_image(page.imageFilename(), search_dir)
                    if not img_path:
                        continue
                    if outputdir:
                        out_xml = Path(outputdir) / xml_path.name
                    else:
                        out_xml = xml_path
                    if out_xml.exists() and overwrite and not dry_run:
                        backups.append(out_xml)
                    documents.append(PagePlusDocumentPage(
                        image_path=img_path,
                        page=page,
                        output_xml_path=out_xml,
                    ))

            if not documents:
                return {
                    "success": False,
                    "output": "No image/XML pairs could be resolved.",
                    "usage": [],
                }

            if backups:
                UndoManager.add_undo_state(
                    f"LiteLLM OCR ({preset_id}, {task_mode})",
                    file_paths=backups,
                )

            try:
                spec = spec_from_preset(
                    preset_id,
                    model=model,
                    task_mode=mode,
                    json_object_mode=json_object or None,
                    calls_per_minute=calls_per_minute,
                )
            except ValueError as exc:
                return {"success": False, "output": str(exc), "usage": []}

            pipeline = PagePlusOCRPipeline.from_spec(
                spec,
                task_mode=mode,
                retry_policy=RetryPolicy(max_attempts=3),
                max_concurrency=max(1, int(jobs)),
            )

            outputs = asyncio.run(
                pipeline.aocr_pages(documents, continue_on_error=True)
            )

            usage_list: List[Dict[str, Any]] = []
            written: List[Path] = []
            errors: List[str] = []

            for out in outputs:
                if out.error is not None:
                    errors.append(f"{out.document.image_path.name}: {out.error}")
                    continue
                if out.ocr_result is not None:
                    usage_list.append(out.ocr_result.usage or {})
                if dry_run or out.document.output_xml_path is None:
                    continue
                target = out.document.output_xml_path
                target.parent.mkdir(parents=True, exist_ok=True)
                if out.page is not None:
                    out.page.save_xml(target)
                    written.append(target)
                elif out.xml_content:
                    target.write_text(out.xml_content, encoding="utf-8")
                    written.append(target)

            summary_lines = [
                f"Model: {spec.model}",
                f"Task mode: {task_mode}",
                f"Processed: {len(outputs)} (successful: {len(outputs) - len(errors)}, "
                f"failed: {len(errors)})",
            ]
            if written:
                summary_lines.append(f"Wrote {len(written)} file(s).")
            if errors:
                summary_lines.append("Errors:")
                summary_lines.extend(f"  - {e}" for e in errors)

            return {
                "success": not errors,
                "output": "\n".join(summary_lines),
                "usage": usage_list,
                "written": [str(p) for p in written],
            }

        except Exception as exc:
            return {"success": False, "output": str(exc), "usage": []}
