"""Provider-agnostic rich preset store for the LLM-OCR tab.

A *preset* here bundles everything needed to run one OCR task end-to-end:

    provider + model + processing step + task mode + task level
        + system/user prompt + output mapping + tag filters

This generalizes the Gemini ``PipelineManager`` (which was Gemini-specific) into
something any provider (local/SSH, OpenAI-compatible, Gemini-compatible, or the
scaffolded transformers backend) can use. Defaults are shipped in code; user
presets are persisted as JSON under the GUI storage dir and merged on top, so
users can add/override without touching the package.

The companion :func:`build_profile` turns a preset + resolved
:class:`OCRBackendSpec` into an :class:`OCRModelProfile` the pipeline consumes,
so the prompt and the output mapping the user picked are actually used at run
time (the gap that existed in the Gemini path).
"""
from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List, Optional

from pageplus.utils.constants import GUI_STORAGE_DIR
from pageplus.utils.llm.core.specs import OCRBackendSpec, OCRModelProfile, TaskMode


# ---------------------------------------------------------------------------
# Processing steps -> sensible task mode / mapping / level defaults.
# ---------------------------------------------------------------------------

# family: "fresh" emits a brand-new PAGE-XML from an image; "correction" mutates
# an existing PAGE-XML (requires loaded XML / ReOCR).
STEP_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "All-in-One": {
        "task_mode": "layout_and_text",
        "mapping": "gemini2d_to_page",
        "task_level": "Page",
        "family": "fresh",
        "uses_builtin_template": True,
    },
    "Textrecognition": {
        "task_mode": "text_only",
        "mapping": "text_only_apply",
        "task_level": "Textline",
        "family": "correction",
        "uses_builtin_template": True,
    },
    "Segmentation": {
        "task_mode": "layout_only",
        "mapping": "segmentation_to_page",
        "task_level": "Page",
        "family": "fresh",
        "uses_builtin_template": False,
    },
    "TableRecognition": {
        "task_mode": "layout_and_text",
        "mapping": "table_json_to_page",
        "task_level": "Page",
        "family": "fresh",
        "uses_builtin_template": False,
    },
    "Field-Tagging": {
        "task_mode": "layout_correction",
        "mapping": "field_tagging_apply",
        "task_level": "Page",
        "family": "correction",
        "uses_builtin_template": False,
    },
    "Reading-Order": {
        "task_mode": "layout_correction",
        "mapping": "reading_order_apply",
        "task_level": "Page",
        "family": "correction",
        "uses_builtin_template": False,
    },
}

STEP_NAMES: List[str] = list(STEP_DEFINITIONS.keys())

# Output mappings the UI exposes (postprocessor names registered in
# pageplus.utils.llm.templates.postprocess).
MAPPING_CHOICES: List[str] = [
    "gemini2d_to_page",      # JSON bbox+text -> fresh PAGE XML
    "segmentation_to_page",  # JSON regions -> fresh PAGE XML
    "table_json_to_page",    # JSON tables -> fresh PAGE XML
    "markdown_to_page",      # markdown text -> fresh PAGE XML
    "text_only_apply",       # JSON text -> mutate existing Page
    "text_correction_apply",
    "layout_correction_apply",
    "field_tagging_apply",
    "reading_order_apply",
]

TASK_LEVELS: List[str] = ["Page", "TextRegion", "Textline"]

# Mappings that consume plain text (markdown) instead of JSON.
_TEXT_MAPPINGS = {"markdown_to_page"}


# ---------------------------------------------------------------------------
# Embedded default prompts (kept in code so they ship with the package).
# ---------------------------------------------------------------------------

SEGMENTATION_PROMPT = (
    "You are an advanced Document Layout Analysis AI. Parse the document image "
    "into a structured JSON with 'regions' and a hierarchical reading order 'ro'.\n\n"
    "For every region provide: id (r0, r1, ...), box_2d [ymin, xmin, ymax, xmax] on a "
    "0-1000 scale, type (strictly one of TextRegion, TableRegion, ImageRegion, "
    "GraphicRegion, ChartRegion, LineDrawingRegion, SeparatorRegion, MathsRegion, "
    "ChemRegion, MusicRegion, AdvertRegion, MapRegion, NoiseRegion, UnknownRegion), a "
    "short 'content' summary (not a full transcription), a 'structure' subtype, and a "
    "'style' list.\n"
    "Build 'ro' as the reading order; use nested arrays to group logical macro-blocks.\n\n"
    "Return JSON only: {\"regions\": [{\"id\", \"box_2d\", \"type\", \"content\", "
    "\"structure\", \"style\"}], \"ro\": [\"r0\", [\"r1\", \"r2\"]]}."
)

FIELD_TAGGING_PROMPT = (
    "You are a Document Layout Refinement AI. You receive a document image and a "
    "pre-detected JSON input of regions with bounding boxes and raw text.\n\n"
    "For each region output: id (preserve input ids; new regions get ids like new_r0), "
    "box_2d [ymin, xmin, ymax, xmax] on 0-1000 scale (refine if inaccurate), type "
    "(strictly one of TextRegion, TableRegion, ImageRegion, GraphicRegion, ChartRegion, "
    "LineDrawingRegion, SeparatorRegion, MathsRegion, ChemRegion, MusicRegion, "
    "AdvertRegion, MapRegion, NoiseRegion, UnknownRegion), a concise 'content' summary, "
    "a 'structure' subtype (e.g. heading, paragraph, header, footer, page-number, "
    "marginal, signature, drop-capital; table/list for tables), and a 'style' list.\n"
    "Visually scan for elements missing from the input and add them.\n"
    "Also output 'ro', the hierarchical reading order. Do not include the raw text in "
    "the output.\n\n"
    "Return JSON only: {\"regions\": [{\"id\", \"box_2d\", \"type\", \"content\", "
    "\"structure\", \"style\"}], \"ro\": [...]}."
)

READING_ORDER_PROMPT = (
    "You are a reading-order analysis AI. You receive a document image and a JSON list "
    "of existing regions with their ids and bounding boxes. Determine the correct "
    "logical reading order of the regions.\n\n"
    "Return JSON only: {\"ro\": [\"r0\", \"r1\", ...]} where ids are the input region "
    "ids in reading order. Use nested arrays to group logical macro-blocks (e.g. "
    "columns) when appropriate. Do not invent ids that are not in the input."
)

TABLE_RECOGNITION_PROMPT = (
    "You are a table transcription AI. Transcribe every table in the image into JSON "
    "optimized for visual reconstruction. Use verbatim transcription (keep archaic "
    "spelling; use \\n for line breaks within a cell).\n\n"
    "Return JSON only: {\"meta\": {\"page\": 1, \"dim\": [height, width]}, \"tables\": "
    "[{\"id\": \"t1\", \"box_2d\": [ymin, xmin, ymax, xmax], \"columns\": {\"width\": "
    "[...], \"align\": [\"L\",\"R\",\"C\"]}, \"sections\": {\"note\": [...], \"header\": "
    "[...], \"data\": [...], \"summary\": [...]}}]}. Each row is [col1, col2, ..., "
    "row-height-ratio]; horizontal merges use -1; vertical grouping uses nested arrays."
)

MARKDOWN_OCR_PROMPT = (
    "You are an expert OCR transcriber for historical documents. Transcribe the entire "
    "page to GitHub-flavoured Markdown: use '#'/'##' for headings, blank lines between "
    "paragraphs, and Markdown tables for tabular content. Preserve the original spelling "
    "and diacritics. Output only the Markdown, with no commentary or code fences."
)


# ---------------------------------------------------------------------------
# Default presets (provider/model left blank: chosen at run time in the UI).
# ---------------------------------------------------------------------------

def _preset(
    id: str, name: str, step: str, *,
    system_prompt: str = "",
    mapping: Optional[str] = None,
    task_mode: Optional[str] = None,
    task_level: Optional[str] = None,
    description: str = "",
) -> Dict[str, Any]:
    sd = STEP_DEFINITIONS[step]
    return {
        "id": id,
        "name": name,
        "description": description,
        "provider_preset": "",      # "" => use the provider selected in the tab
        "model": "",                # "" => provider default / UI override
        "step": step,
        "task_mode": task_mode or sd["task_mode"],
        "task_level": task_level or sd["task_level"],
        "mapping": mapping or sd["mapping"],
        "system_prompt": system_prompt,
        "user_prompt": "",
        "filters": {"tags": [], "tag_regex": False},
    }


DEFAULT_PRESETS: List[Dict[str, Any]] = [
    _preset("allinone", "All-in-One OCR", "All-in-One",
            description="Layout + text in one pass (built-in template)."),
    _preset("markdown_ocr", "Markdown OCR (All-in-One)", "All-in-One",
            system_prompt=MARKDOWN_OCR_PROMPT, mapping="markdown_to_page",
            description="Whole-page transcription to Markdown, mapped to PAGE XML."),
    _preset("textrec_line", "Text Recognition (Textline)", "Textrecognition",
            task_level="Textline",
            description="(Re)OCR text per textline on an existing layout."),
    _preset("textrec_region", "Text Recognition (Region)", "Textrecognition",
            task_level="TextRegion",
            description="(Re)OCR text per region on an existing layout."),
    _preset("segmentation", "Segmentation", "Segmentation",
            system_prompt=SEGMENTATION_PROMPT,
            description="Detect regions + reading order from the image."),
    _preset("table", "Table Recognition", "TableRecognition",
            system_prompt=TABLE_RECOGNITION_PROMPT,
            description="Transcribe tables to TableRegions/TableCells."),
    _preset("field_tagging", "Field-Tagging", "Field-Tagging",
            system_prompt=FIELD_TAGGING_PROMPT,
            description="Classify/refine region types + reading order on existing XML."),
    _preset("reading_order", "Reading-Order", "Reading-Order",
            system_prompt=READING_ORDER_PROMPT,
            description="Recompute the reading order of existing regions."),
]


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class LLMOCRPresetManager:
    """Load/merge/save LLM-OCR presets (code defaults + user JSON overrides)."""

    def __init__(self) -> None:
        self.user_dir = GUI_STORAGE_DIR / "llm_ocr"
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.user_path = self.user_dir / "llm_ocr_presets.json"
        self._user: Dict[str, Dict[str, Any]] = self._load_user()

    # ---- persistence ----------------------------------------------------

    def _load_user(self) -> Dict[str, Dict[str, Any]]:
        if not self.user_path.exists():
            return {}
        try:
            data = json.loads(self.user_path.read_text(encoding="utf-8"))
            presets = data.get("presets", data) if isinstance(data, dict) else {}
            if isinstance(presets, list):
                return {p["id"]: p for p in presets if p.get("id")}
            if isinstance(presets, dict):
                return presets
        except Exception:
            pass
        return {}

    def save(self) -> None:
        self.user_path.write_text(
            json.dumps({"version": 1, "presets": list(self._user.values())},
                       indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # ---- queries --------------------------------------------------------

    def _merged(self) -> Dict[str, Dict[str, Any]]:
        merged: Dict[str, Dict[str, Any]] = {p["id"]: copy.deepcopy(p) for p in DEFAULT_PRESETS}
        for pid, preset in self._user.items():
            merged[pid] = copy.deepcopy(preset)
        return merged

    def list_presets(self) -> List[Dict[str, Any]]:
        return list(self._merged().values())

    def get_preset(self, preset_id: str) -> Optional[Dict[str, Any]]:
        return self._merged().get(preset_id)

    def is_user_preset(self, preset_id: str) -> bool:
        return preset_id in self._user

    def is_default_preset(self, preset_id: str) -> bool:
        return any(p["id"] == preset_id for p in DEFAULT_PRESETS)

    # ---- mutations ------------------------------------------------------

    def upsert(self, preset: Dict[str, Any]) -> None:
        if not preset.get("id"):
            raise ValueError("Preset needs an 'id'.")
        self._user[preset["id"]] = copy.deepcopy(preset)
        self.save()

    def delete(self, preset_id: str) -> bool:
        if preset_id in self._user:
            del self._user[preset_id]
            self.save()
            return True
        return False


# ---------------------------------------------------------------------------
# Preset -> pipeline profile
# ---------------------------------------------------------------------------

def build_profile(preset: Dict[str, Any], spec: OCRBackendSpec,
                  task_mode: TaskMode) -> OCRModelProfile:
    """Turn a rich preset into an :class:`OCRModelProfile` for the pipeline.

    Inherits the template/schema from the registered default profile for the
    resolved ``(provider, model, task_mode)`` and overrides the prompt and the
    output mapping (postprocessor) with the preset's choices, so the user's
    prompt and mapping are actually used at run time.
    """
    from pageplus.utils.llm.templates import resolve_profile

    base = resolve_profile(spec.provider, spec.model, task_mode)
    mapping = preset.get("mapping") or base.postprocess
    system_prompt = (preset.get("system_prompt") or "").strip() or None
    user_prompt = (preset.get("user_prompt") or "").strip() or None

    schema = base.schema
    expected_format = base.expected_format
    # When the user supplies a step-specific prompt, the output shape is defined
    # by that prompt rather than the built-in template's strict schema; relax to
    # json_object (or text for markdown) so the model is not over-constrained.
    if mapping in _TEXT_MAPPINGS:
        schema = None
        expected_format = "text"
    elif system_prompt is not None and mapping != base.postprocess:
        schema = None

    return replace(
        base,
        name=f"llm_ocr_{preset.get('id', 'preset')}_{task_mode.value}",
        postprocess=mapping,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        schema=schema,
        expected_format=expected_format,
    )


def step_family(step: str) -> str:
    """'fresh' (image -> new XML) or 'correction' (mutate existing XML)."""
    return STEP_DEFINITIONS.get(step, {}).get("family", "fresh")


def mapping_is_text(mapping: Optional[str]) -> bool:
    """True if the mapping consumes plain text/markdown (not structured JSON)."""
    return mapping in _TEXT_MAPPINGS


def provider_matches_task(
    *,
    vision_capable: bool,
    task_modes: List[str],
    configured: bool,
    task_mode: str,
    require_configured: bool = True,
) -> bool:
    """Whether a provider is compatible with a task's step/mode criteria.

    Every LLM-OCR step sends the page image to the model, so vision capability
    is always required. The provider must also declare the requested task mode.
    JSON-schema support is *not* a hard filter because providers without strict
    schema support can still return structured JSON via ``json_object`` mode.
    """
    if require_configured and not configured:
        return False
    if not vision_capable:
        return False
    if task_modes and task_mode not in task_modes:
        return False
    return True
