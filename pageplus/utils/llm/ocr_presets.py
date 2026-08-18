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
    "table_correction_apply",# Crop table XML+image -> detect merged cells & proportions -> replace by ID
    "table_html_correction_apply", # HTML table -> correct structure & text -> replace by ID
    "table2html_apply",
    "table_html_to_page",    # HTML table -> fresh PAGE XML
    "pp_layout_json_to_page",# PP-Layout JSON (PaddleOCR) -> fresh PAGE XML
    "pp_layout_extend_json_to_page",# PP-Layout Extend JSON (regions + lines) -> fresh PAGE XML
    "pp_layout_extend_table_json_to_page",# PP-Layout Extend Table JSON -> fresh PAGE XML
    "mistral_ocr_to_page",   # Mistral OCR JSON (blocks + HTML tables) -> fresh PAGE XML
    "markdown_to_page",      # markdown text -> fresh PAGE XML
    "text_only_apply",       # JSON text -> mutate existing Page
    "text_correction_apply",
    "layout_correction_apply",
    "field_tagging_apply",
    "reading_order_apply",
    "reading_order_text_correction_apply",
]


TASK_LEVELS: List[str] = ["Page", "TableRegion", "TextRegion", "Textline"]

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

READING_ORDER_GEMINI_3_5_FLASH_PROMPT = (
    "You are a reading-order analysis and OCR correction AI for historical documents. "
    "You receive a document image and a PAGE-XML to JSON conversion containing regions with "
    "their IDs, polygon coordinates ('coords'), and OCR textlines with existing text.\n\n"
    "Your tasks are:\n"
    "1. Determine and correct the logical reading order ('ro') of the regions and textlines based on "
    "the visual layout, polygon coordinates, and text context. Use nested arrays to group logical "
    "macro-blocks (e.g. columns) when appropriate.\n"
    "2. Correct any OCR text mistakes or typos in the textlines while preserving original spelling "
    "and diacritics.\n\n"
    "Return JSON only: {\"regions\": [{\"id\": \"r0\", \"textlines\": [{\"id\": \"tl0\", \"text\": \"corrected text\"}]}], \"ro\": [\"r0\", \"r1\", ...]}."
)

TABLE_RECOGNITION_PROMPT = (
    "You are a table transcription AI. Transcribe every table in the image into JSON "
    "optimized for visual reconstruction. Use verbatim transcription (keep archaic "
    "spelling; use \\n for line breaks within a cell).\n\n"
    "Return JSON only: {\"tables\": [{\"id\": \"t0\", \"box_2d\": [ymin, xmin, ymax, xmax], "
    "\"rows\": 3, \"cols\": 3, \"cells\": [{\"row\": 0, \"col\": 0, \"rowspan\": 1, \"colspan\": 1, \"value\": \"text\"}]}]}."
)

TABLE_CORRECTION_PROMPT = (
    "You are an expert table structure analysis and OCR correction AI.\n"
    "You receive a cropped table image along with an initial table JSON structure containing:\n"
    "- table id and bounding box ('box_2d')\n"
    "- total rows ('rows') and total columns ('cols')\n"
    "- list of cells ('cells'), each with 'row', 'col', 'rowspan', 'colspan', and 'value'\n\n"
    "Your tasks are:\n"
    "1. Inspect the cropped table image and verify the table structure and text content.\n"
    "2. Detect merged cells (indicated by big brackets '[' / ']' or spanning lines) and set appropriate 'rowspan' and 'colspan' values.\n"
    "3. Correct any OCR mistakes or missing text in cell values.\n"
    "4. Refine the table bounding box 'box_2d' [ymin, xmin, ymax, xmax] on a 0-1000 scale relative to the cropped table snippet.\n\n"
    "Return JSON only: {\"tables\": [{\"id\": \"t0\", \"box_2d\": [ymin, xmin, ymax, xmax], \"rows\": R, \"cols\": C, \"cells\": [{\"row\": 0, \"col\": 0, \"rowspan\": 1, \"colspan\": 1, \"value\": \"...\"}]}]}."
)

TABLE_HTML_CORRECTION_PROMPT = (
    "You are an expert table structure analysis and OCR correction AI.\n"
    "You receive a cropped table image along with an HTML table representation of the existing table structure.\n\n"
    "Your tasks are:\n"
    "1. Inspect the table image and verify the HTML table structure and cell content.\n"
    "2. Correct any cell text, OCR errors, or missing contents.\n"
    "3. Correct the table grid structure using HTML <table>, <tr>, and <td> tags with 'rowspan' and 'colspan' attributes for merged cells.\n"
    "4. Output only valid HTML <table> elements with no commentary or markdown code fences outside the table."
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
    provider_preset: str = "",
    model: str = "",
    system_prompt: str = "",
    mapping: Optional[str] = None,
    task_mode: Optional[str] = None,
    task_level: Optional[str] = None,
    description: str = "",
    bindings: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    sd = STEP_DEFINITIONS[step]
    b_list = bindings
    if b_list is None and provider_preset:
        b_list = [{"provider": provider_preset, "model": model}]
    return {
        "id": id,
        "name": name,
        "description": description,
        "provider_preset": provider_preset,
        "model": model,
        "bindings": b_list or [],
        "step": step,
        "task_mode": task_mode or sd["task_mode"],
        "task_level": task_level or sd["task_level"],
        "mapping": mapping or sd["mapping"],
        "system_prompt": system_prompt,
        "user_prompt": "",
        "filters": {
            "tags": [],
            "tag_regex": False,
            "min_table_rows": None,
            "max_table_rows": None,
        },
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
    _preset("table_correction", "Table Recognition & Structure Correction", "TableRecognition",
            system_prompt=TABLE_CORRECTION_PROMPT,
            task_mode="layout_correction",
            mapping="table_correction_apply",
            description="Crop table regions, parse table XML + image into LLM, detect merged cells (brackets), adjust row/col proportions, and replace by ID."),
    _preset("table_html_correction", "Table Recognition & Structure Correction (HTML Table)", "TableRecognition",
            system_prompt=TABLE_HTML_CORRECTION_PROMPT,
            task_mode="layout_correction",
            mapping="table_html_correction_apply",
            description="Crop table regions, parse table XML to HTML <table>, correct HTML structure and text via LLM, and update PAGE-XML table structure."),
    _preset("table2html", "Table Recognition (HTML Table Output)", "TableRecognition",
            system_prompt=TABLE_HTML_CORRECTION_PROMPT,
            mapping="table_html_to_page",
            description="Transcribe tables to HTML <table> structure and map back to PAGE-XML."),
    _preset("field_tagging", "Field-Tagging", "Field-Tagging",
            system_prompt=FIELD_TAGGING_PROMPT,
            description="Classify/refine region types + reading order on existing XML."),
    _preset("reading_order", "Reading-Order", "Reading-Order",
            system_prompt=READING_ORDER_PROMPT,
            description="Recompute the reading order of existing regions."),
    _preset("reading_order_gemini_3_5_flash", "Reading-Order & Text Correction (Gemini 3.5 Flash)", "Reading-Order",
            provider_preset="gemini", model="gemini-3.5-flash",
            system_prompt=READING_ORDER_GEMINI_3_5_FLASH_PROMPT,
            task_mode="text_correction",
            mapping="reading_order_apply",
            description="Correct reading order and OCR text mistakes using Gemini 3.5 Flash based on PAGE-XML to JSON conversion."),
    _preset("mistral_ocr_allinone", "Mistral Document OCR (Layout + HTML Tables)", "All-in-One",
            provider_preset="mistral_ocr", model="mistral-ocr-latest",
            mapping="mistral_ocr_to_page",
            description="Extract document layout, text blocks, and HTML tables into PAGE-XML using Mistral OCR API."),
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


def step_family(step: str, task_mode: Optional[str] = None) -> str:
    """'fresh' (image -> new XML) or 'correction' (mutate existing XML)."""
    if task_mode in ("layout_correction", "text_correction", "text_only"):
        return "correction"
    if task_mode in ("layout_and_text", "layout_only", "markdown"):
        return "fresh"
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
