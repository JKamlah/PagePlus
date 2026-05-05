"""Jinja template registry and prompt rendering.

Templates live as ``.j2`` files next to this module (one per task mode). The
registry loads them lazily via Jinja2's ``FileSystemLoader``. Rendering
produces a :class:`RenderedPrompt` ready for any :class:`OCRBackend`.

A separate helper :func:`render_page_xml_payload` emits a compact JSON
serialization of a ``Page`` object that can be passed either inline in the
user prompt or as an extra part (Gemini) depending on the backend.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from pageplus.utils.llm.backends.base import RenderedPrompt
from pageplus.utils.llm.core.specs import OCRModelProfile, TaskMode


_TEMPLATES_DIR = Path(__file__).parent


@dataclass
class TemplateRegistry:
    """Lazily-loaded store of Jinja templates.

    Kept as a dataclass so tests / alternative template roots can instantiate
    a fresh registry without touching the module-level default."""
    root: Path = field(default=_TEMPLATES_DIR)
    _env: Any = None
    _templates: Dict[str, Any] = field(default_factory=dict)

    def _ensure_env(self):
        if self._env is None:
            from jinja2 import Environment, FileSystemLoader, StrictUndefined
            self._env = Environment(
                loader=FileSystemLoader(str(self.root)),
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
                keep_trailing_newline=False,
                undefined=StrictUndefined,
            )
        return self._env

    def get(self, name: str):
        if name in self._templates:
            return self._templates[name]
        env = self._ensure_env()
        tpl = env.get_template(f"{name}.j2")
        self._templates[name] = tpl
        return tpl

    def render(self, name: str, **context) -> str:
        return self.get(name).render(**context)


_DEFAULT_REGISTRY = TemplateRegistry()


def render_prompt(
    profile: OCRModelProfile,
    *,
    page_xml_dict: Optional[Dict[str, Any]] = None,
    page_xml_text: Optional[str] = None,
    snippet_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    registry: Optional[TemplateRegistry] = None,
) -> RenderedPrompt:
    """Render the system+user prompts for ``profile``.

    * For ``layout_only`` / ``layout_and_text`` only the image matters and the
      page-xml context is ignored.
    * For the three correction modes ``page_xml_dict`` is required; it's
      serialized into the user prompt via the template.
    """
    registry = registry or _DEFAULT_REGISTRY
    extra = dict(extra or {})
    context = {
        "task_mode": profile.task_mode.value,
        "page_xml": page_xml_dict,
        "page_xml_text": page_xml_text,
        "snippet_id": snippet_id,
        **extra,
    }
    if profile.system_prompt is not None:
        system_text = profile.system_prompt
    else:
        system_text = registry.render(f"{profile.template}.system", **context)
    if profile.user_prompt is not None:
        user_text = profile.user_prompt
    else:
        user_text = registry.render(f"{profile.template}.user", **context)

    expected_format = "json" if profile.schema else extra.get("expected_format", "json")
    if extra.get("json_object_mode") and expected_format == "json":
        expected_format = "json_object"
    return RenderedPrompt(
        system=system_text,
        user=user_text,
        task_mode=profile.task_mode.value,
        schema=profile.schema,
        expected_format=expected_format,
        extra=extra,
    )


def render_page_xml_payload(page, *, include_text: bool, mode: TaskMode) -> str:
    """Serialize a ``Page`` into a compact JSON blob for correction prompts.

    Format:

        {
          "regions": [
            {
              "id": str,
              "type": str,
              "coords": "x,y x,y ...",
              "textlines": [
                {"id": str, "type": str, "coords": "...", "baseline": "...",
                 "text": str?}   # text only when include_text=True
              ]
            }
          ]
        }

    For ``layout_correction`` the pipeline passes ``include_text=False`` to
    keep the prompt compact; for ``text_correction`` it passes ``True`` so
    the model has the existing transcription to fix.
    """
    regions_out: List[Dict[str, Any]] = []
    for region in _iter_regions(page):
        region_entry: Dict[str, Any] = {
            "id": _safe_get_id(region),
            "type": _safe_get_tag(region),
            "coords": _safe_get_coords(region),
            "textlines": [],
        }
        for line in getattr(region, "textlines", []) or []:
            line_entry: Dict[str, Any] = {
                "id": _safe_get_id(line),
                "type": _safe_get_tag(line),
                "coords": _safe_get_coords(line),
                "baseline": _safe_get_baseline(line),
            }
            if include_text:
                try:
                    line_entry["text"] = line.get_text() or ""
                except Exception:  # pragma: no cover
                    line_entry["text"] = ""
            region_entry["textlines"].append(line_entry)
        regions_out.append(region_entry)
    return json.dumps({"regions": regions_out}, ensure_ascii=False)


def _iter_regions(page):
    regions = getattr(page, "regions", None)
    if regions is None:
        return []
    out = []
    for attr in ("textregions", "tableregions"):
        out.extend(getattr(regions, attr, []) or [])
    return out


def _safe_get_id(obj) -> str:
    try:
        return obj.get_id()
    except Exception:  # pragma: no cover
        return ""


def _safe_get_tag(obj) -> str:
    try:
        return obj.get_tag() or ""
    except Exception:  # pragma: no cover
        return ""


def _safe_get_coords(obj) -> str:
    try:
        return obj.get_coordinates(returntype="string") or ""
    except Exception:  # pragma: no cover
        return ""


def _safe_get_baseline(obj) -> str:
    try:
        return obj.get_baseline_coordinates(returntype="string") or ""
    except Exception:  # pragma: no cover
        return ""
