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

def _is_pp_layout_json(structured: Any) -> bool:
    if isinstance(structured, list) and len(structured) > 0 and isinstance(structured[0], dict):
        if "cls_id" in structured[0] or "polygon_points" in structured[0]:
            return True
    elif isinstance(structured, dict):
        for key in ("regions", "items", "results", "elements", "layout"):
            if key in structured and isinstance(structured[key], list) and len(structured[key]) > 0:
                first = structured[key][0]
                if isinstance(first, dict) and ("cls_id" in first or "polygon_points" in first):
                    return True
    return False


def _layout_and_text_to_xml(structured: Any, image_path: Path,
                             page=None, **opts) -> str:
    """Gemini 2D JSON with bboxes + text -> fresh PAGE XML string."""
    if _is_pp_layout_json(structured):
        from pageplus.utils.mappings import pp_layout_json_to_page
        return pp_layout_json_to_page(structured, image_path, settings=opts)

    from pageplus.utils.mappings import gemini2d_to_page  # local import
    use_fallback = opts.get("use_bbox_fallback")
    return gemini2d_to_page(structured, image_path,
                            settings=opts, use_bbox_fallback=use_fallback)


def _layout_only_to_xml(structured: Any, image_path: Path,
                        page=None, **opts) -> str:
    """JSON with regions+coords only (no text) -> PAGE XML string.

    If the backend returns a 'regions' key we use the segmentation helper;
    otherwise we reuse ``gemini2d_to_page`` with empty text fields.
    """
    if _is_pp_layout_json(structured):
        from pageplus.utils.mappings import pp_layout_json_to_page
        return pp_layout_json_to_page(structured, image_path, settings=opts)

    from pageplus.utils.mappings import gemini2d_to_page, segmentation_to_page
    if isinstance(structured, dict) and "regions" in structured:
        return segmentation_to_page(structured, image_path)
    return gemini2d_to_page(structured, image_path,
                            settings=opts, use_bbox_fallback=False)


def _table_json_to_xml(structured: Any, image_path: Path,
                       page=None, **opts) -> str:
    from pageplus.utils.mappings import table_json_to_page
    return table_json_to_page(structured, image_path)


def _markdown_to_xml(structured: Any, image_path: Path,
                     page=None, **opts) -> str:
    """Markdown (plain text) output -> fresh PAGE XML string.

    For markdown profiles the backend returns text (``expected_format=text``),
    so the markdown lives in ``opts['text']``; we fall back to ``structured``
    when it is itself a string.
    """
    from pageplus.utils.mappings import markdown2pagexml
    markdown_text = opts.get("text")
    if not markdown_text and isinstance(structured, str):
        markdown_text = structured
    return markdown2pagexml(markdown_text or "", image_path)


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


def _field_tagging_apply(structured: Any, image_path: Path,
                         page=None, **opts) -> Optional[str]:
    """Apply Field-Tagging output to an existing Page in place.

    Expects ``{regions: [{id, type?, structure?, box_2d?}], ro?: [...]}``
    (the schema produced by ``Prompt/Field-Tagging-Prompt.txt``). For each
    region matched by id we update its tag (``structure`` preferred, else
    ``type``) and, when a ``box_2d`` is given, refine its coordinates. Finally
    the reading order is rebuilt from ``ro`` when present.

    New regions invented by the model (ids like ``new_r0``) are ignored here;
    creating fresh XML elements from a tag-only pass is out of scope.
    """
    if page is None:
        logging.warning("field_tagging postprocessor received no page; skipping merge")
        return None
    regions = _extract_region_list(structured)
    img_dims = _image_dims(image_path)
    for updated in regions:
        region_id = updated.get("id")
        if not region_id or str(region_id).startswith("new_"):
            continue
        region = page.get_region_by_id(region_id) if hasattr(page, "get_region_by_id") else None
        if region is None:
            continue
        tag = updated.get("structure") or updated.get("type")
        if tag and hasattr(region, "set_tag"):
            try:
                region.set_tag(tag=tag)
            except Exception:  # pragma: no cover - defensive
                pass
        coords = _coords_from_box_2d(updated.get("box_2d"), img_dims)
        if coords and hasattr(region, "update_coordinates"):
            try:
                region.update_coordinates(coords)
            except Exception:  # pragma: no cover - defensive
                pass
    ro = structured.get("ro") if isinstance(structured, dict) else None
    if ro:
        _apply_reading_order(page, ro)
    return None


def _reading_order_apply(structured: Any, image_path: Path,
                         page=None, **opts) -> Optional[str]:
    """Rebuild the Page ``<ReadingOrder>`` from the model output.

    Accepts either ``{ro: [...]}`` (possibly nested) or ``{regions: [{id}, ...]}``
    interpreted as a flat top-to-bottom order. Nothing else on the page is
    touched.
    """
    if page is None:
        logging.warning("reading_order postprocessor received no page; skipping merge")
        return None
    ro = None
    if isinstance(structured, dict):
        ro = structured.get("ro")
        if not ro:
            regions = _extract_region_list(structured)
            ro = [r.get("id") for r in regions if r.get("id")]
    if ro:
        _apply_reading_order(page, ro)
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


def _image_dims(image_path: Path) -> Optional[tuple]:
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return img.size  # (width, height)
    except Exception:  # pragma: no cover - defensive
        return None


def _coords_from_box_2d(box, img_dims: Optional[tuple]) -> Optional[list]:
    """Convert a ``[ymin, xmin, ymax, xmax]`` 0-1000 box to a pixel polygon."""
    if not box or not img_dims or len(box) != 4:
        return None
    try:
        ymin, xmin, ymax, xmax = (float(v) for v in box)
    except (TypeError, ValueError):
        return None
    w, h = img_dims
    ax1 = int(max(0, min(1000, xmin)) / 1000 * w)
    ay1 = int(max(0, min(1000, ymin)) / 1000 * h)
    ax2 = int(max(0, min(1000, xmax)) / 1000 * w)
    ay2 = int(max(0, min(1000, ymax)) / 1000 * h)
    if ax2 <= ax1 or ay2 <= ay1:
        return None
    return [(ax1, ay1), (ax2, ay1), (ax2, ay2), (ax1, ay2)]


def _apply_reading_order(page, ro: list) -> None:
    """Rebuild ``<ReadingOrder>`` on the Page element from ``ro``.

    ``ro`` may contain bare region-ref ids and nested lists (logical groups),
    mirroring the structure used by ``segmentation_to_page``. Any existing
    ``<ReadingOrder>`` is replaced. Inserted before the first region element so
    the result stays schema-valid.
    """
    from lxml import etree as ET

    ns = getattr(page, "ns", None)
    root = getattr(page, "root", None)
    if not ns or root is None:
        logging.warning("Cannot apply reading order: page has no root/ns")
        return
    page_el = root.find(f"{{{ns}}}Page")
    if page_el is None:
        return

    for existing in page_el.findall(f"{{{ns}}}ReadingOrder"):
        page_el.remove(existing)

    ro_el = ET.Element(f"{{{ns}}}ReadingOrder")
    root_group = ET.SubElement(ro_el, f"{{{ns}}}OrderedGroup")
    root_group.set("id", "ro_root")
    root_group.set("caption", "Regions reading order")

    counter = {"n": 0}

    def _add(parent, item, index):
        if isinstance(item, (list, tuple)):
            counter["n"] += 1
            group = ET.SubElement(parent, f"{{{ns}}}OrderedGroup")
            group.set("id", f"ro_group_{counter['n']}")
            group.set("index", str(index))
            for sub_idx, sub in enumerate(item):
                _add(group, sub, sub_idx)
        elif item:
            ref = ET.SubElement(parent, f"{{{ns}}}RegionRefIndexed")
            ref.set("index", str(index))
            ref.set("regionRef", str(item))

    for idx, item in enumerate(ro):
        _add(root_group, item, idx)

    region_tags = {
        f"{{{ns}}}TextRegion", f"{{{ns}}}TableRegion", f"{{{ns}}}ImageRegion",
        f"{{{ns}}}GraphicRegion", f"{{{ns}}}SeparatorRegion", f"{{{ns}}}ChartRegion",
        f"{{{ns}}}MathsRegion", f"{{{ns}}}LineDrawingRegion", f"{{{ns}}}NoiseRegion",
        f"{{{ns}}}AdvertRegion", f"{{{ns}}}MusicRegion", f"{{{ns}}}ChemRegion",
        f"{{{ns}}}MapRegion", f"{{{ns}}}UnknownRegion", f"{{{ns}}}CustomRegion",
    }
    insert_at = len(page_el)
    for i, child in enumerate(page_el):
        if child.tag in region_tags:
            insert_at = i
            break
    page_el.insert(insert_at, ro_el)


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
register_postprocessor("markdown_to_page", _markdown_to_xml)
register_postprocessor("text_only_apply", _text_only_apply)
register_postprocessor("text_correction_apply", _text_correction_apply)
register_postprocessor("layout_correction_apply", _layout_correction_apply)
register_postprocessor("field_tagging_apply", _field_tagging_apply)
register_postprocessor("reading_order_apply", _reading_order_apply)


def _pp_layout_json_to_xml(structured: Any, image_path: Path,
                           page=None, **opts) -> str:
    """PP-Layout JSON (PaddleOCR layout detection) -> fresh PAGE XML string."""
    from pageplus.utils.mappings import pp_layout_json_to_page  # local import
    return pp_layout_json_to_page(structured, image_path,
                                  settings=opts)


register_postprocessor("pp_layout_json_to_page", _pp_layout_json_to_xml)


def _pp_layout_extend_json_to_xml(structured: Any, image_path: Path,
                                  page=None, **opts) -> str:
    """PP-Layout Extend JSON -> fresh PAGE XML string."""
    from pageplus.utils.mappings import pp_layout_extend_json_to_page  # local import
    return pp_layout_extend_json_to_page(structured, image_path, settings=opts)


register_postprocessor("pp_layout_extend_json_to_page", _pp_layout_extend_json_to_xml)


def _pp_layout_extend_table_json_to_xml(structured: Any, image_path: Path,
                                        page=None, **opts) -> str:
    """PP-Layout Extend Table JSON -> fresh PAGE XML string."""
    from pageplus.utils.mappings import pp_layout_extend_table_json_to_page  # local import
    return pp_layout_extend_table_json_to_page(structured, image_path, settings=opts)


register_postprocessor("pp_layout_extend_table_json_to_page", _pp_layout_extend_table_json_to_xml)


def scale_structured_coordinates(data: Any, scale_x: float, scale_y: float) -> Any:
    """Recursively traverses a JSON-like data structure and scales coordinates.
    
    Only applies to keys that represent absolute pixel coordinates.
    """
    if scale_x == 1.0 and scale_y == 1.0:
        return data

    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            if k in ("polygon_points", "polygon", "polygon_pts") and isinstance(v, list):
                # Format: [[x, y], [x, y], ...]
                new_dict[k] = [
                    [int(float(pt[0]) * scale_x), int(float(pt[1]) * scale_y)]
                    if isinstance(pt, (list, tuple)) and len(pt) == 2 else pt
                    for pt in v
                ]
            elif k in ("coordinate", "bbox") and isinstance(v, list) and len(v) >= 4:
                # Format: [x1, y1, x2, y2]
                try:
                    scaled = [
                        int(float(v[0]) * scale_x),
                        int(float(v[1]) * scale_y),
                        int(float(v[2]) * scale_x),
                        int(float(v[3]) * scale_y),
                    ]
                    # Preserve any additional elements (e.g. score, class_id)
                    if len(v) > 4:
                        scaled.extend(v[4:])
                    new_dict[k] = scaled
                except (ValueError, TypeError):
                    new_dict[k] = v
            elif k in ("coords", "baseline", "coords_points", "points", "coordinates", "baseline_points") and isinstance(v, str):
                # Format: "x,y x,y ..."
                pts = []
                for tok in v.split():
                    try:
                        x, y = tok.split(",")
                        scaled_x = int(float(x) * scale_x)
                        scaled_y = int(float(y) * scale_y)
                        pts.append(f"{scaled_x},{scaled_y}")
                    except ValueError:
                        pts.append(tok)
                new_dict[k] = " ".join(pts)
            elif k in ("coords", "baseline", "coords_points", "points", "coordinates", "baseline_points") and isinstance(v, list):
                # Format: [[x, y], [x, y], ...] or list of floats/ints
                new_list = []
                for item in v:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        try:
                            new_list.append([int(float(item[0]) * scale_x), int(float(item[1]) * scale_y)])
                        except (ValueError, TypeError):
                            new_list.append(item)
                    else:
                        new_list.append(item)
                new_dict[k] = new_list
            else:
                new_dict[k] = scale_structured_coordinates(v, scale_x, scale_y)
        return new_dict

    elif isinstance(data, list):
        return [scale_structured_coordinates(item, scale_x, scale_y) for item in data]

    return data



