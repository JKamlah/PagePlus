"""Registry of postprocessors that turn backend JSON into PAGE-XML updates.

The existing helpers ``gemini2d_to_page``, ``segmentation_to_page``, and
``table_json_to_page`` (in :mod:`pageplus.utils.io`) are re-registered here
under stable names so templates can reference them without importing the
long-form module every time. New task modes add their own handlers via
:func:`register_postprocessor`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from pageplus.io.logger import logging


Postprocessor = Callable[..., Any]

_REGISTRY: Dict[str, Postprocessor] = {}


def register_postprocessor(name: str, fn: Postprocessor) -> None:
    _REGISTRY[name] = fn


def get_postprocessor(name: str) -> Postprocessor:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(sorted(_REGISTRY)) or "<none>"
        raise KeyError(
            f"No postprocessor registered under name '{name}'. Known: {available}"
        ) from exc


def list_postprocessors() -> list[str]:
    return sorted(_REGISTRY)


# ---------------------------------------------------------------------------
# Built-in postprocessors. Each signature is normalised to
# ``(structured, image_path, page=None, **opts) -> str | None``
# so the pipeline can dispatch uniformly.
# ---------------------------------------------------------------------------

def _layout_and_text_to_xml(structured: Any, image_path: Path,
                             page=None, **opts) -> str:
    """Gemini 2D JSON with bboxes + text -> fresh PAGE XML string."""
    from pageplus.utils.io import gemini2d_to_page  # local import: heavy deps
    use_fallback = opts.get("use_bbox_fallback")
    return gemini2d_to_page(structured, image_path,
                            settings=opts, use_bbox_fallback=use_fallback)


def _layout_only_to_xml(structured: Any, image_path: Path,
                        page=None, **opts) -> str:
    """JSON with regions+coords only (no text) -> PAGE XML string.

    If the backend returns a 'regions' key we use the segmentation helper;
    otherwise we reuse ``gemini2d_to_page`` with empty text fields.
    """
    from pageplus.utils.io import gemini2d_to_page, segmentation_to_page
    if isinstance(structured, dict) and "regions" in structured:
        return segmentation_to_page(structured, image_path)
    return gemini2d_to_page(structured, image_path,
                            settings=opts, use_bbox_fallback=False)


def _table_json_to_xml(structured: Any, image_path: Path,
                       page=None, **opts) -> str:
    from pageplus.utils.io import table_json_to_page
    return table_json_to_page(structured, image_path)


def _text_only_apply(structured: Any, image_path: Path,
                      page=None, **opts) -> Optional[str]:
    """Apply ``{region: {textline_id: text}}`` updates to an existing Page.

    Returns ``None`` because we mutate ``page`` in place; the pipeline will
    persist the Page object afterwards. Mirrors the reocr_multithread merge
    behaviour that used to live inline in ``pageplus/cli/gemini.py``.
    """
    if page is None:
        logging.warning("text_only postprocessor received no page; skipping merge")
        return None
    _apply_text_updates(structured, page, overwrite_tags=False)
    return None


def _text_correction_apply(structured: Any, image_path: Path,
                            page=None, **opts) -> Optional[str]:
    """Same as text_only but also updates region/line tags when present."""
    if page is None:
        logging.warning("text_correction postprocessor received no page; skipping merge")
        return None
    _apply_text_updates(structured, page, overwrite_tags=True)
    return None


def _layout_correction_apply(structured: Any, image_path: Path,
                              page=None, **opts) -> Optional[str]:
    """Merge refined coords from ``{regions: [{id, coords, textlines:[{id, coords, baseline}]}]}``
    into an existing Page. Text fields are left untouched."""
    if page is None:
        logging.warning("layout_correction postprocessor received no page; skipping merge")
        return None
    _apply_layout_updates(structured, page)
    return None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_text_updates(structured: Any, page, *, overwrite_tags: bool) -> None:
    """Merge ``{regions: [{id, type?, textlines: [{id, text_content, type?}]}]}``
    into an existing Page. Tolerant of the various key names Gemini produces."""
    regions = _extract_region_list(structured)
    for updated_region in regions:
        region_id = updated_region.get("id")
        if not region_id:
            continue
        region = page.get_region_by_id(region_id) if hasattr(page, "get_region_by_id") else None
        if region is None:
            continue
        if overwrite_tags and updated_region.get("type"):
            if hasattr(region, "set_tag"):
                try:
                    region.set_tag(tag=updated_region["type"])
                except Exception:  # pragma: no cover - defensive
                    pass
        for updated_line in updated_region.get("textlines", []) or []:
            line_id = updated_line.get("id")
            if not line_id:
                continue
            textline = region.get_textline_by_id(line_id) if hasattr(region, "get_textline_by_id") else None
            if textline is None:
                continue
            text = _extract_text_field(updated_line)
            if text is not None and len(text) <= 500:
                textline.update_text(text)
            if overwrite_tags and updated_line.get("type"):
                if hasattr(textline, "set_tag"):
                    try:
                        textline.set_tag(tag=updated_line["type"])
                    except Exception:  # pragma: no cover
                        pass


def _apply_layout_updates(structured: Any, page) -> None:
    """Merge refined coords back into existing lines/regions. Tolerant of
    both ``points`` (``"x,y x,y ..."``) and ``coords`` (list of tuples)."""
    regions = _extract_region_list(structured)
    for updated_region in regions:
        region_id = updated_region.get("id")
        if not region_id:
            continue
        region = page.get_region_by_id(region_id) if hasattr(page, "get_region_by_id") else None
        if region is None:
            continue
        coords = _extract_coord_points(updated_region)
        if coords and hasattr(region, "update_coordinates"):
            try:
                region.update_coordinates(coords)
            except Exception:  # pragma: no cover
                pass
        for updated_line in updated_region.get("textlines", []) or []:
            line_id = updated_line.get("id")
            if not line_id or not hasattr(region, "get_textline_by_id"):
                continue
            textline = region.get_textline_by_id(line_id)
            if textline is None:
                continue
            line_coords = _extract_coord_points(updated_line)
            if line_coords and hasattr(textline, "update_coordinates"):
                try:
                    textline.update_coordinates(line_coords)
                except Exception:  # pragma: no cover
                    pass
            baseline = _extract_coord_points(updated_line, key="baseline")
            if baseline and hasattr(textline, "update_baseline_coordinates"):
                try:
                    textline.update_baseline_coordinates(baseline)
                except Exception:  # pragma: no cover
                    pass


def _extract_region_list(structured: Any) -> list[dict]:
    if structured is None:
        return []
    if isinstance(structured, list):
        return [r for r in structured if isinstance(r, dict)]
    if isinstance(structured, dict):
        for key in ("regions", "textregions", "items", "results"):
            if key in structured and isinstance(structured[key], list):
                return [r for r in structured[key] if isinstance(r, dict)]
    return []


def _extract_text_field(entry: dict) -> Optional[str]:
    for key in ("text_content", "corrected", "text", "unicode", "content"):
        if key in entry:
            value = entry[key]
            if isinstance(value, str):
                return value.strip()
            if isinstance(value, list):
                return " ".join(str(v) for v in value).strip()
    return None


def _extract_coord_points(entry: dict, *, key: str = "coords") -> Optional[list]:
    value = entry.get(key) or entry.get(key + "_points") or entry.get("points")
    if value is None and key == "coords":
        value = entry.get("coordinates")
    if value is None:
        return None
    if isinstance(value, str):
        pts = []
        for tok in value.split():
            try:
                x, y = tok.split(",")
                pts.append((int(float(x)), int(float(y))))
            except ValueError:
                continue
        return pts or None
    if isinstance(value, list):
        pts = []
        for item in value:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                try:
                    pts.append((int(float(item[0])), int(float(item[1]))))
                except (TypeError, ValueError):
                    continue
        return pts or None
    return None


# ---------------------------------------------------------------------------
# Registrations
# ---------------------------------------------------------------------------

register_postprocessor("layout_and_text_to_xml", _layout_and_text_to_xml)
register_postprocessor("gemini2d_to_page", _layout_and_text_to_xml)  # legacy alias
register_postprocessor("layout_only_to_xml", _layout_only_to_xml)
register_postprocessor("segmentation_to_page", _layout_only_to_xml)  # legacy alias
register_postprocessor("table_json_to_page", _table_json_to_xml)
register_postprocessor("text_only_apply", _text_only_apply)
register_postprocessor("text_correction_apply", _text_correction_apply)
register_postprocessor("layout_correction_apply", _layout_correction_apply)
