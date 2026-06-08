"""Streamlit-friendly bridge for the unified **LLM-OCR** pipeline.

This supersedes :class:`pageplus.gui.cli_bridges.litellm.LiteLLMBridge`. It keeps
that bridge's provider-preset discovery, credential writes, custom-endpoint CRUD
and SSH-tunnel controls, and adds:

- **Rich presets** (:class:`pageplus.utils.llm.ocr_presets.LLMOCRPresetManager`)
  that bundle provider + model + step + prompt + mapping + task mode/level +
  tag filters, and turning a preset into an :class:`OCRModelProfile` so the
  chosen prompt and output mapping are actually used.
- **Task level** (Region / Textline) via the pipeline's per-snippet execution.
- **"Process only Tags"** filters wired into ``region_filter`` / ``line_filter``.
- **Normalized token usage** so cost reporting works across Gemini-style and
  OpenAI-style usage keys.
- **Per-file error reporting** instead of all-or-nothing success.

Every public method returns a ``{"success", "output", ...}`` dict and never
raises into the GUI.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from pageplus.gui.utils.settings import Settings
from pageplus.gui.utils.undo import UndoManager
from pageplus.utils.llm.ocr_presets import (
    LLMOCRPresetManager,
    MAPPING_CHOICES,
    STEP_DEFINITIONS,
    STEP_NAMES,
    TASK_LEVELS,
    build_profile,
    provider_matches_task,
    step_family,
)
from pageplus.utils.llm.pipeline_store import EXECUTION_MODES, LLMOCRPipelineStore


def _litellm_available() -> bool:
    from importlib import util
    return util.find_spec("litellm") is not None


def _normalize_usage(usage: Dict[str, Any]) -> Dict[str, int]:
    """Map any backend's usage dict to ``{prompt, candidates, total}`` tokens.

    Handles Gemini-style (``prompt_token_count`` / ``candidates_token_count`` /
    ``total_token_count``) and OpenAI/LiteLLM-style (``prompt_tokens`` /
    ``completion_tokens`` / ``total_tokens``) keys.
    """
    if not isinstance(usage, dict):
        return {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}

    def _first(*keys: str) -> int:
        for k in keys:
            v = usage.get(k)
            if isinstance(v, (int, float)):
                return int(v)
        return 0

    prompt = _first("prompt_token_count", "prompt_tokens")
    candidates = _first("candidates_token_count", "completion_tokens", "candidate_tokens")
    total = _first("total_token_count", "total_tokens")
    if not total:
        total = prompt + candidates
    return {
        "prompt_tokens": prompt,
        "candidates_tokens": candidates,
        "total_tokens": total,
    }


class LLMOcrBridge:
    """GUI-facing wrapper around :class:`PagePlusOCRPipeline` for all providers."""

    def __init__(self) -> None:
        self._presets = LLMOCRPresetManager()
        self._pipelines = LLMOCRPipelineStore()

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> dict:
        if _litellm_available():
            return {"success": True, "output": "LiteLLM is installed."}
        return {
            "success": False,
            "output": (
                "LiteLLM is not installed. Run `pageplus llm-ocr install` "
                "or `pip install litellm json-repair`."
            ),
        }

    # ------------------------------------------------------------------
    # Step / mapping / level metadata (for the UI)
    # ------------------------------------------------------------------

    def step_metadata(self) -> dict:
        return {
            "success": True,
            "output": f"{len(STEP_NAMES)} step(s).",
            "steps": STEP_NAMES,
            "step_definitions": STEP_DEFINITIONS,
            "mappings": MAPPING_CHOICES,
            "task_levels": TASK_LEVELS,
        }

    # ------------------------------------------------------------------
    # Provider presets (LiteLLM-routable + custom + transformers)
    # ------------------------------------------------------------------

    def list_providers(self, only_configured: bool = False) -> dict:
        try:
            from pageplus.utils.llm.provider_registry import (
                available_providers,
                list_providers,
            )
            providers = available_providers() if only_configured else list_providers()
            rows: List[Dict[str, Any]] = []
            for p in providers:
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
            return {"success": True, "output": f"Found {len(rows)} provider(s).", "providers": rows}
        except Exception as exc:
            return {"success": False, "output": str(exc), "providers": []}

    def provider_info(self, provider_id: str) -> dict:
        try:
            from pageplus.utils.llm.provider_registry import get_preset
            preset = get_preset(provider_id)
            api_key, api_base = preset.resolve_credentials()
            return {
                "success": True,
                "output": preset.display_name,
                "provider": {
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
            return {"success": False, "output": str(exc), "provider": None}

    def save_api_key(self, provider_id: str, api_key: str) -> dict:
        try:
            from pageplus.utils.llm.provider_registry import get_preset
            preset = get_preset(provider_id)
            if not preset.env_api_key:
                return {"success": False, "output": f"Provider '{preset.display_name}' has no API-key env var."}
            Settings().set(preset.env_api_key, api_key)
            return {"success": True, "output": f"Saved {preset.env_api_key} to .env."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def save_api_base(self, provider_id: str, api_base_url: str) -> dict:
        try:
            from pageplus.utils.llm.provider_registry import get_preset
            preset = get_preset(provider_id)
            if not preset.env_api_base:
                return {"success": False, "output": f"Provider '{preset.display_name}' has no base-URL env var."}
            Settings().set(preset.env_api_base, api_base_url)
            return {"success": True, "output": f"Saved {preset.env_api_base} to .env."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    # ------------------------------------------------------------------
    # Rich LLM-OCR presets
    # ------------------------------------------------------------------

    def list_ocr_presets(self) -> dict:
        try:
            return {
                "success": True,
                "output": "ok",
                "presets": self._presets.list_presets(),
            }
        except Exception as exc:
            return {"success": False, "output": str(exc), "presets": []}

    def get_ocr_preset(self, preset_id: str) -> dict:
        preset = self._presets.get_preset(preset_id)
        if preset is None:
            return {"success": False, "output": f"Preset '{preset_id}' not found.", "preset": None}
        return {"success": True, "output": "ok", "preset": preset,
                "is_default": self._presets.is_default_preset(preset_id),
                "is_user": self._presets.is_user_preset(preset_id)}

    def save_ocr_preset(self, preset: Dict[str, Any]) -> dict:
        try:
            self._presets.upsert(preset)
            return {"success": True, "output": f"Saved preset '{preset.get('id')}'."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def delete_ocr_preset(self, preset_id: str) -> dict:
        try:
            if self._presets.delete(preset_id):
                return {"success": True, "output": f"Deleted preset '{preset_id}'."}
            return {"success": False, "output": f"Preset '{preset_id}' is a default and cannot be deleted."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    # ------------------------------------------------------------------
    # OCR / ReOCR via the unified pipeline
    # ------------------------------------------------------------------

    def run_ocr(
        self,
        *,
        provider_id: str,
        preset_id: Optional[str] = None,
        step: Optional[str] = None,
        task_mode: Optional[str] = None,
        task_level: Optional[str] = None,
        mapping: Optional[str] = None,
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        tag_filter: Optional[List[str]] = None,
        tag_regex: bool = False,
        model: Optional[str] = None,
        image_files: Optional[List[str]] = None,
        xml_files: Optional[List[str]] = None,
        outputdir: Optional[str] = None,
        image_folder: Optional[str] = None,
        same_names: bool = False,
        jobs: int = 4,
        calls_per_minute: int = 120,
        json_object: bool = False,
        overwrite: bool = True,
        dry_run: bool = False,
        max_image_size: Optional[int] = 1000,
    ) -> dict:
        """Run a single OCR step across files.

        The rich preset (``preset_id``) supplies defaults for step / task mode /
        level / mapping / prompts / filters; any explicit argument overrides it.
        ``provider_id`` selects the provider preset / custom endpoint to call.
        """
        if not _litellm_available():
            return self.is_available()

        try:
            from pageplus.models.page import Page
            from pageplus.utils.fs import find_image
            from pageplus.utils.llm.core import RetryPolicy, TaskMode, ExecutionStrategy
            from pageplus.utils.llm.filters import make_tag_filter
            from pageplus.utils.llm.pipeline import (
                PagePlusDocumentPage,
                PagePlusOCRPipeline,
            )
            from pageplus.utils.llm.provider_registry import spec_from_preset

            # --- Resolve the preset + overrides ------------------------------
            preset = self._presets.get_preset(preset_id) if preset_id else None
            preset = dict(preset) if preset else {
                "id": "adhoc", "name": "Ad-hoc", "step": step or "All-in-One",
                "filters": {},
            }
            step = step or preset.get("step") or "All-in-One"
            sd = STEP_DEFINITIONS.get(step, {})
            task_mode_str = task_mode or preset.get("task_mode") or sd.get("task_mode", "layout_and_text")
            task_level = task_level or preset.get("task_level") or sd.get("task_level", "Page")
            mapping = mapping or preset.get("mapping") or sd.get("mapping")
            if system_prompt is not None:
                preset["system_prompt"] = system_prompt
            if user_prompt is not None:
                preset["user_prompt"] = user_prompt
            preset["mapping"] = mapping
            if tag_filter is None:
                tag_filter = (preset.get("filters") or {}).get("tags") or []
            if not tag_regex:
                tag_regex = bool((preset.get("filters") or {}).get("tag_regex", False))

            try:
                mode = TaskMode(task_mode_str)
            except ValueError:
                return {"success": False, "output": f"Unknown task_mode '{task_mode_str}'.", "usage": []}

            family = step_family(step)
            use_snippets = task_level in ("TextRegion", "Textline") and family == "correction"

            region_filter = None
            line_filter = None
            if tag_filter:
                predicate = make_tag_filter(tag_filter, regex=tag_regex)
                if task_level == "TextRegion" or family == "fresh":
                    region_filter = predicate
                else:
                    line_filter = predicate

            # --- Build the document list -------------------------------------
            documents: List[PagePlusDocumentPage] = []
            backups: List[Path] = []

            if family == "fresh":
                if not image_files:
                    return {"success": False, "output": f"Step '{step}' needs image files.", "usage": []}
                for img in image_files:
                    img_path = Path(img)
                    out_xml = (Path(outputdir) / img_path.with_suffix(".xml").name) if outputdir \
                        else img_path.with_suffix(".xml")
                    if out_xml.exists() and overwrite and not dry_run:
                        backups.append(out_xml)
                    documents.append(PagePlusDocumentPage(
                        image_path=img_path, page=None, output_xml_path=out_xml,
                    ))
            else:  # correction
                if not xml_files:
                    return {"success": False, "output": f"Step '{step}' needs PAGE-XML files.", "usage": []}
                image_folder_path = Path(image_folder) if image_folder else None
                for xml in xml_files:
                    xml_path = Path(xml)
                    page = Page(xml_path)
                    if mode == TaskMode.TEXT_ONLY and not use_snippets:
                        page.delete_textlevel('TextRegion')
                    search_dir = image_folder_path or xml_path.parent
                    img_path = None
                    if same_names:
                        for ext in ('.png', '.jpg', '.jpeg', '.tif', '.tiff'):
                            img_path = find_image(xml_path.with_suffix(ext).name, search_dir)
                            if img_path:
                                break
                    else:
                        img_path = find_image(page.imageFilename(), search_dir)
                    if not img_path:
                        continue
                    out_xml = (Path(outputdir) / xml_path.name) if outputdir else xml_path
                    if out_xml.exists() and overwrite and not dry_run:
                        backups.append(out_xml)
                    documents.append(PagePlusDocumentPage(
                        image_path=img_path, page=page, output_xml_path=out_xml,
                        region_filter=region_filter, line_filter=line_filter,
                    ))

            if not documents:
                return {"success": False, "output": "No image/XML pairs could be resolved.", "usage": []}

            if backups:
                UndoManager.add_undo_state(
                    f"LLM-OCR {step} ({provider_id})", file_paths=backups,
                )

            # --- Auto-start SSH tunnel for custom endpoints ------------------
            tunnel_name: Optional[str] = None
            if provider_id.startswith("custom_"):
                from pageplus.utils.llm.endpoint_store import get_endpoint
                from pageplus.utils.ssh_tunnel import start_tunnel, stop_tunnel, tunnel_status
                import logging
                ep_name = provider_id.removeprefix("custom_")
                ep = get_endpoint(ep_name)
                if ep and ep.ssh_enabled and ep.ssh_command:
                    tunnel_name = ep_name
                    msg = start_tunnel(tunnel_name, ep.ssh_command)
                    logging.info("[ssh] %s", msg)
                    if tunnel_status(tunnel_name) != "running":
                        return {"success": False, "output": f"SSH Tunnel failed to start: {msg}", "usage": []}

            try:
                try:
                    spec = spec_from_preset(
                        provider_id,
                        model=model or (preset.get("model") or None),
                        task_mode=mode,
                        json_object_mode=json_object or None,
                        calls_per_minute=calls_per_minute,
                        max_image_size=max_image_size,
                    )
                except ValueError as exc:
                    return {"success": False, "output": str(exc), "usage": []}

                if use_snippets:
                    spec.execution = ExecutionStrategy.PER_SNIPPET

                try:
                    profile = build_profile(preset, spec, mode)
                except Exception as exc:
                    return {"success": False, "output": f"Could not build profile: {exc}", "usage": []}

                pipeline = PagePlusOCRPipeline.from_spec(
                    spec,
                    task_mode=mode,
                    profile=profile,
                    retry_policy=RetryPolicy(max_attempts=3),
                    max_concurrency=max(1, int(jobs)),
                    snippet_level=task_level if task_level in ("TextRegion", "Textline") else "Textline",
                )

                outputs = asyncio.run(pipeline.aocr_pages(documents, continue_on_error=True))

                usage_list: List[Dict[str, Any]] = []
                aggregated = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
                written: List[Path] = []
                errors: List[str] = []

                for out in outputs:
                    if out.error is not None:
                        errors.append(f"{out.document.image_path.name}: {out.error}")
                        continue
                    if out.ocr_result is not None:
                        norm = _normalize_usage(out.ocr_result.usage or {})
                        usage_list.append(out.ocr_result.usage or {})
                        for k in aggregated:
                            aggregated[k] += norm[k]
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

                summary = [
                    f"Provider: {provider_id}  Model: {spec.model}",
                    f"Step: {step}  Task mode: {mode.value}  Level: {task_level}",
                    f"Mapping: {mapping}",
                    f"Processed: {len(outputs)} (ok: {len(outputs) - len(errors)}, failed: {len(errors)})",
                ]
                if written:
                    summary.append(f"Wrote {len(written)} file(s).")
                if errors:
                    summary.append("Errors:")
                    summary.extend(f"  - {e}" for e in errors)

                return {
                    "success": not errors,
                    "output": "\n".join(summary),
                    "usage": usage_list,
                    "aggregated_usage": aggregated,
                    "written": [str(p) for p in written],
                    "errors": errors,
                }
            finally:
                if tunnel_name is not None:
                    from pageplus.utils.ssh_tunnel import stop_tunnel
                    import logging
                    logging.info("[ssh] %s", stop_tunnel(tunnel_name))

        except Exception as exc:
            return {"success": False, "output": str(exc), "usage": []}

    # ------------------------------------------------------------------
    # Provider / model matching for the pipeline cascade
    # ------------------------------------------------------------------

    def match_providers(
        self,
        *,
        step: str,
        task_mode: Optional[str] = None,
        only_configured: bool = True,
    ) -> dict:
        """Return providers (with candidate models) compatible with a task.

        Filters the provider presets to those that can run the given step/task
        mode: vision-capable and declaring the requested task mode (and, if
        ``only_configured``, with credentials/endpoint set up). The result feeds
        the Process-tab cascade so users only pick valid provider/model pairs.
        """
        sd = STEP_DEFINITIONS.get(step, {})
        mode = task_mode or sd.get("task_mode", "layout_and_text")
        providers = self.list_providers(only_configured=False).get("providers", [])
        rows: List[Dict[str, Any]] = []
        for p in providers:
            if not provider_matches_task(
                vision_capable=bool(p.get("vision_capable", True)),
                task_modes=list(p.get("task_modes", [])),
                configured=bool(p.get("configured", False)),
                task_mode=mode,
                require_configured=only_configured,
            ):
                continue
            models: List[str] = []
            if p.get("default_model"):
                models.append(p["default_model"])
            for m in p.get("alt_models", []):
                if m not in models:
                    models.append(m)
            rows.append({
                "id": p["id"],
                "display_name": p["display_name"],
                "configured": p["configured"],
                "default_model": p.get("default_model"),
                "models": models,
                "supports_json_schema": p.get("supports_json_schema", False),
            })
        return {
            "success": True,
            "output": f"{len(rows)} provider(s) match step '{step}' / mode '{mode}'.",
            "task_mode": mode,
            "providers": rows,
        }

    # ------------------------------------------------------------------
    # Pipelines (ordered multi-task) CRUD
    # ------------------------------------------------------------------

    def list_pipelines(self) -> dict:
        try:
            pipelines = self._pipelines.list_pipelines()
            return {"success": True, "output": f"{len(pipelines)} pipeline(s).",
                    "pipelines": pipelines}
        except Exception as exc:
            return {"success": False, "output": str(exc), "pipelines": []}

    def get_pipeline(self, pipeline_id: str) -> dict:
        try:
            p = self._pipelines.get_pipeline(pipeline_id)
            if p is None:
                return {"success": False, "output": f"Pipeline '{pipeline_id}' not found."}
            return {"success": True, "output": p["name"], "pipeline": p}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def save_pipeline(self, pipeline: Dict[str, Any]) -> dict:
        try:
            self._pipelines.upsert(pipeline)
            return {"success": True, "output": f"Saved pipeline '{pipeline.get('name', pipeline['id'])}'."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def delete_pipeline(self, pipeline_id: str) -> dict:
        try:
            ok = self._pipelines.delete(pipeline_id)
            return {"success": ok,
                    "output": "Deleted." if ok else f"Pipeline '{pipeline_id}' not found."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    # ------------------------------------------------------------------
    # Pipeline execution (stepwise / pagewise, async within a batch)
    # ------------------------------------------------------------------

    def run_pipeline(
        self,
        *,
        tasks: List[Dict[str, Any]],
        execution_mode: str = "stepwise",
        image_files: Optional[List[str]] = None,
        xml_files: Optional[List[str]] = None,
        outputdir: Optional[str] = None,
        image_folder: Optional[str] = None,
        same_names: bool = True,
        jobs: int = 4,
        calls_per_minute: int = 120,
        overwrite: bool = True,
        dry_run: bool = False,
        max_image_size: Optional[int] = 1000,
    ) -> dict:
        """Run an ordered list of tasks as a chained pipeline.

        * **stepwise** — run each task across *all* pages, then move to the next
          task (the produced/loaded XML becomes the working set for the next
          correction step).
        * **pagewise** — run the whole task chain for one page, then the next
          page (pages are processed concurrently up to ``jobs``).

        A *fresh* first step turns images into XML; subsequent *correction*
        steps mutate that XML. If the pipeline has no fresh step it operates on
        the provided ``xml_files`` (ReOCR).
        """
        if not _litellm_available():
            return self.is_available()
        if not tasks:
            return {"success": False, "output": "Pipeline has no tasks."}
        if execution_mode not in EXECUTION_MODES:
            return {"success": False, "output": f"Unknown execution_mode '{execution_mode}'."}

        base_image_dir: Optional[str] = None
        if image_files:
            try:
                base_image_dir = str(Path(image_files[0]).parent)
            except Exception:
                base_image_dir = None
        chain_image_folder = image_folder or base_image_dir

        agg = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
        all_written: List[str] = []
        all_errors: List[str] = []
        summary: List[str] = [f"Pipeline ({execution_mode}) · {len(tasks)} task(s)"]

        def _accumulate(res: dict) -> None:
            for k in agg:
                agg[k] += (res.get("aggregated_usage") or {}).get(k, 0)
            all_written.extend(res.get("written", []) or [])
            all_errors.extend(res.get("errors", []) or [])

        try:
            if execution_mode == "stepwise":
                working_xmls: Optional[List[str]] = list(xml_files) if xml_files else None
                for i, task in enumerate(tasks, start=1):
                    fam = step_family(task.get("step", "All-in-One"))
                    label = f"[{i}/{len(tasks)}] {task.get('step')} via {task.get('provider_id')}"
                    print(f"\n=== Step {label} ({fam}) ===", flush=True)
                    if fam == "fresh":
                        res = self._run_task(task, image_files=image_files, xml_files=None,
                                             outputdir=outputdir, image_folder=None,
                                             same_names=same_names, jobs=jobs,
                                             calls_per_minute=calls_per_minute,
                                             overwrite=overwrite, dry_run=dry_run,
                                             max_image_size=max_image_size)
                        if res.get("written"):
                            working_xmls = res["written"]
                    else:
                        xmls = working_xmls or (list(xml_files) if xml_files else None)
                        if not xmls:
                            res = {"success": False,
                                   "output": f"{label}: no XML available for correction step.",
                                   "errors": [f"{label}: no XML available."]}
                        else:
                            res = self._run_task(task, image_files=None, xml_files=xmls,
                                                 outputdir=None,
                                                 image_folder=chain_image_folder,
                                                 same_names=same_names if working_xmls is None else True,
                                                 jobs=jobs, calls_per_minute=calls_per_minute,
                                                 overwrite=overwrite, dry_run=dry_run,
                                                 max_image_size=max_image_size)
                            if res.get("written"):
                                working_xmls = res["written"]
                    print(res.get("output", ""), flush=True)
                    _accumulate(res)
            else:  # pagewise
                first_fresh = step_family(tasks[0].get("step", "All-in-One")) == "fresh"
                units = (image_files or []) if first_fresh else (xml_files or [])
                if not units:
                    return {"success": False,
                            "output": "No input pages (images for a fresh first step, "
                                      "or loaded XML otherwise)."}

                results = self._run_pages_concurrent(
                    units=units, first_fresh=first_fresh, tasks=tasks,
                    outputdir=outputdir, chain_image_folder=chain_image_folder,
                    same_names=same_names, calls_per_minute=calls_per_minute,
                    overwrite=overwrite, dry_run=dry_run,
                    max_image_size=max_image_size, jobs=jobs,
                )
                for res in results:
                    _accumulate(res)

            summary.append(f"Wrote {len(all_written)} file(s); {len(all_errors)} error(s).")
            if all_errors:
                summary.append("Errors:")
                summary.extend(f"  - {e}" for e in all_errors)
            return {
                "success": not all_errors,
                "output": "\n".join(summary),
                "aggregated_usage": agg,
                "written": all_written,
                "errors": all_errors,
            }
        except Exception as exc:
            return {"success": False, "output": str(exc),
                    "aggregated_usage": agg, "written": all_written,
                    "errors": all_errors + [str(exc)]}

    def _run_pages_concurrent(
        self, *, units: List[str], first_fresh: bool, tasks: List[Dict[str, Any]],
        outputdir: Optional[str], chain_image_folder: Optional[str], same_names: bool,
        calls_per_minute: int, overwrite: bool, dry_run: bool,
        max_image_size: Optional[int], jobs: int,
    ) -> List[dict]:
        """Pagewise: run the whole task chain per page, pages in a thread pool."""
        from concurrent.futures import ThreadPoolExecutor

        def process_page(unit: str) -> List[dict]:
            page_results: List[dict] = []
            working_xml: Optional[str] = None if first_fresh else unit
            for i, task in enumerate(tasks, start=1):
                fam = step_family(task.get("step", "All-in-One"))
                label = f"page {Path(unit).name} · [{i}/{len(tasks)}] {task.get('step')}"
                if fam == "fresh":
                    res = self._run_task(task, image_files=[unit], xml_files=None,
                                         outputdir=outputdir, image_folder=None,
                                         same_names=same_names, jobs=1,
                                         calls_per_minute=calls_per_minute,
                                         overwrite=overwrite, dry_run=dry_run,
                                         max_image_size=max_image_size)
                    if res.get("written"):
                        working_xml = res["written"][0]
                else:
                    if not working_xml:
                        res = {"success": False, "output": f"{label}: no XML to correct.",
                               "errors": [f"{label}: no XML to correct."]}
                    else:
                        res = self._run_task(task, image_files=None, xml_files=[working_xml],
                                             outputdir=None, image_folder=chain_image_folder,
                                             same_names=True, jobs=1,
                                             calls_per_minute=calls_per_minute,
                                             overwrite=overwrite, dry_run=dry_run,
                                             max_image_size=max_image_size)
                        if res.get("written"):
                            working_xml = res["written"][0]
                print(f"{label}: {'ok' if res.get('success') else 'failed'}", flush=True)
                page_results.append(res)
            return page_results

        results: List[dict] = []
        with ThreadPoolExecutor(max_workers=max(1, int(jobs))) as pool:
            for page_results in pool.map(process_page, units):
                results.extend(page_results)
        return results

    def _run_task(self, task: Dict[str, Any], **run_kwargs: Any) -> dict:
        """Map a pipeline task dict onto a single :meth:`run_ocr` call."""
        filters = task.get("filters") or {}
        return self.run_ocr(
            provider_id=task.get("provider_id", ""),
            preset_id=task.get("preset_id") or None,
            step=task.get("step"),
            task_mode=task.get("task_mode"),
            task_level=task.get("task_level"),
            model=task.get("model") or None,
            tag_filter=task.get("tags", filters.get("tags")) or None,
            tag_regex=bool(task.get("tag_regex", filters.get("tag_regex", False))),
            json_object=bool(task.get("json_object", False)),
            **run_kwargs,
        )

    # ------------------------------------------------------------------
    # Custom endpoint management (delegated to endpoint_store)
    # ------------------------------------------------------------------

    def list_custom_endpoints(self) -> dict:
        try:
            from pageplus.utils.llm.endpoint_store import load_endpoints
            endpoints = load_endpoints()
            return {
                "success": True,
                "output": f"Found {len(endpoints)} custom endpoint(s).",
                "endpoints": [
                    {
                        "name": ep.name, "base_url": ep.base_url, "api_key": ep.api_key,
                        "default_model": ep.default_model, "alt_models": ep.alt_models,
                        "ssh_enabled": ep.ssh_enabled, "ssh_command": ep.ssh_command,
                        "provider": getattr(ep, "provider", "openai"),
                    }
                    for ep in endpoints
                ],
            }
        except Exception as exc:
            return {"success": False, "output": str(exc), "endpoints": []}

    def save_custom_endpoint(
        self, name: str, base_url: str, api_key: str = "EMPTY",
        default_model: str = "", alt_models: list | None = None,
        ssh_enabled: bool = False, ssh_command: str = "", provider: str = "openai",
    ) -> dict:
        try:
            from pageplus.utils.llm.endpoint_store import SavedEndpoint, save_endpoint
            from pageplus.utils.llm.provider_registry import register_custom_endpoints
            save_endpoint(SavedEndpoint(
                name=name, base_url=base_url, api_key=api_key, default_model=default_model,
                alt_models=alt_models or [], ssh_enabled=ssh_enabled, ssh_command=ssh_command,
                provider=provider,
            ))
            register_custom_endpoints()
            return {"success": True, "output": f"Saved endpoint '{name}' (preset 'custom_{name}')."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def list_endpoint_models(self, name: str) -> dict:
        """Query a custom endpoint's server for the model names it actually has.

        Uses Ollama's ``/api/tags`` (provider ``ollama``/``ollama_chat``) or the
        OpenAI ``/v1/models`` route, so users can pick the exact installed name
        (with tag) instead of guessing — the usual cause of "model not found".
        """
        try:
            import json
            import urllib.request

            from pageplus.utils.llm.endpoint_store import get_endpoint, normalize_base_url
            ep = get_endpoint(name)
            if ep is None:
                return {"success": False, "output": f"Endpoint '{name}' not found.", "models": []}
            provider = getattr(ep, "provider", "openai")
            base = normalize_base_url(ep.base_url, provider)
            is_ollama = provider in ("ollama", "ollama_chat")
            url = f"{base}/api/tags" if is_ollama else f"{base}/models"
            headers = {}
            if ep.api_key and ep.api_key != "EMPTY":
                headers["Authorization"] = f"Bearer {ep.api_key}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if is_ollama:
                models = [
                    {"name": m.get("name"),
                     "vision": "vision" in (m.get("capabilities") or [])}
                    for m in data.get("models", []) if m.get("name")
                ]
            else:
                models = [{"name": m.get("id"), "vision": True}
                          for m in data.get("data", []) if m.get("id")]
            return {"success": True, "output": f"Found {len(models)} model(s) on '{name}'.",
                    "models": models, "url": url}
        except Exception as exc:
            return {"success": False, "output": f"Could not list models: {exc}", "models": []}

    def delete_custom_endpoint(self, name: str) -> dict:
        try:
            from pageplus.utils.llm.endpoint_store import delete_endpoint
            from pageplus.utils.llm.provider_registry import unregister_custom_endpoint
            deleted = delete_endpoint(name)
            unregister_custom_endpoint(name)
            if deleted:
                return {"success": True, "output": f"Deleted endpoint '{name}'."}
            return {"success": False, "output": f"Endpoint '{name}' not found."}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    # ------------------------------------------------------------------
    # SSH tunnel controls
    # ------------------------------------------------------------------

    def start_ssh_tunnel(self, endpoint_name: str) -> dict:
        try:
            from pageplus.utils.llm.endpoint_store import get_endpoint
            from pageplus.utils.ssh_tunnel import start_tunnel
            ep = get_endpoint(endpoint_name)
            if ep is None:
                return {"success": False, "output": f"Endpoint '{endpoint_name}' not found."}
            if not ep.ssh_enabled or not ep.ssh_command:
                return {"success": False, "output": f"Endpoint '{endpoint_name}' has no SSH tunnel configured."}
            msg = start_tunnel(endpoint_name, ep.ssh_command)
            success = "established" in msg.lower() or "pid" in msg.lower()
            return {"success": success, "output": msg}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def stop_ssh_tunnel(self, endpoint_name: str) -> dict:
        try:
            from pageplus.utils.ssh_tunnel import stop_tunnel
            return {"success": True, "output": stop_tunnel(endpoint_name)}
        except Exception as exc:
            return {"success": False, "output": str(exc)}

    def tunnel_status(self, endpoint_name: str) -> dict:
        try:
            from pageplus.utils.ssh_tunnel import tunnel_status
            status = tunnel_status(endpoint_name)
            return {"success": True, "output": status, "status": status}
        except Exception as exc:
            return {"success": False, "output": str(exc), "status": "error"}
