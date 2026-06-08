"""Persistence for user-defined **LLM-OCR pipelines**.

A *pipeline* is an ordered list of tasks that are run one after another (the
output of a fresh step feeds the following correction steps). Each task pins one
provider/model plus the preset (prompt + output mapping) to apply, so a saved
pipeline reloads exactly. Unlike presets, pipelines ship no code defaults — they
are entirely user-created and stored as JSON under the GUI storage dir.

Task schema (one dict per task)::

    {
        "step":        "All-in-One",          # processing step name
        "task_mode":   "layout_and_text",     # TaskMode value
        "task_level":  "Page",                # Page / TextRegion / Textline
        "preset_id":   "allinone",            # preset supplying prompt + mapping
        "provider_id": "gemini",              # provider preset / custom endpoint id
        "model":       "gemini-2.0-flash",    # "" => provider default
        "tags":        ["heading"],           # optional "process only tags"
        "tag_regex":   false,
        "json_object": false                  # force json_object mode for this task
    }

Pipeline schema::

    {
        "id": "...", "name": "...", "description": "...",
        "execution_mode": "stepwise" | "pagewise",
        "tasks": [ <task>, ... ]
    }
"""
from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional

from pageplus.utils.constants import GUI_STORAGE_DIR

EXECUTION_MODES: List[str] = ["stepwise", "pagewise"]


class LLMOCRPipelineStore:
    """Load/save user pipelines (ordered task lists) as JSON."""

    def __init__(self) -> None:
        self.user_dir = GUI_STORAGE_DIR / "llm_ocr"
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.user_path = self.user_dir / "llm_ocr_pipelines.json"
        self._pipelines: Dict[str, Dict[str, Any]] = self._load()

    # ---- persistence ----------------------------------------------------

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.user_path.exists():
            return {}
        try:
            data = json.loads(self.user_path.read_text(encoding="utf-8"))
            pipelines = data.get("pipelines", data) if isinstance(data, dict) else {}
            if isinstance(pipelines, list):
                return {p["id"]: p for p in pipelines if p.get("id")}
            if isinstance(pipelines, dict):
                return pipelines
        except Exception:
            pass
        return {}

    def save(self) -> None:
        self.user_path.write_text(
            json.dumps({"version": 1, "pipelines": list(self._pipelines.values())},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---- queries --------------------------------------------------------

    def list_pipelines(self) -> List[Dict[str, Any]]:
        return [copy.deepcopy(p) for p in self._pipelines.values()]

    def get_pipeline(self, pipeline_id: str) -> Optional[Dict[str, Any]]:
        p = self._pipelines.get(pipeline_id)
        return copy.deepcopy(p) if p else None

    # ---- mutations ------------------------------------------------------

    def upsert(self, pipeline: Dict[str, Any]) -> None:
        if not pipeline.get("id"):
            raise ValueError("Pipeline needs an 'id'.")
        if not isinstance(pipeline.get("tasks"), list) or not pipeline["tasks"]:
            raise ValueError("Pipeline needs at least one task.")
        mode = pipeline.get("execution_mode", "stepwise")
        if mode not in EXECUTION_MODES:
            raise ValueError(f"Unknown execution_mode '{mode}'.")
        self._pipelines[pipeline["id"]] = copy.deepcopy(pipeline)
        self.save()

    def delete(self, pipeline_id: str) -> bool:
        if pipeline_id in self._pipelines:
            del self._pipelines[pipeline_id]
            self.save()
            return True
        return False
