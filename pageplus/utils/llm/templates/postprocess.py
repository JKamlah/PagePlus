"""Registry of postprocessors that turn backend JSON into PAGE-XML updates.

The existing helpers ``gemini2d_to_page``, ``segmentation_to_page``, and
``table_json_to_page`` (in :mod:`pageplus.utils.io`) are re-registered here
under stable names so templates can reference them without importing the
long-form module every time. New task modes add their own handlers via
:func:`register_postprocessor`.
"""
from __future__ import annotations

import re
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
    """Rebuild the Page ``<ReadingOrder>`` from the model output and update line text if present.

    Accepts either ``{ro: [...]}`` (possibly nested) or ``{regions: [{id}, ...]}``
    interpreted as a flat top-to-bottom order. Also merges text corrections
    present in regions/textlines.
    """
    if page is None:
        logging.warning("reading_order postprocessor received no page; skipping merge")
        return None
    _apply_text_updates(structured, page, overwrite_tags=False)
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
    for key in ("text_content", "corrected", "text", "unicode", "content", "markdown"):
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

def _table_correction_apply(structured: Any, image_path: Path,
                            page=None, **opts) -> Optional[str]:
    """Applies refined table structures and replaces old <TableRegion> elements in an existing Page in-place by ID.
    If page is None, returns fresh PAGE-XML string.
    """
    if page is None:
        from pageplus.utils.mappings.table_json import table_json_to_page
        return table_json_to_page(structured, image_path)

    from pageplus.utils.mappings.table_json import replace_table_region_by_id

    tables = []
    if isinstance(structured, list):
        tables = structured
    elif isinstance(structured, dict):
        tables = structured.get("tables", [structured]) if ("tables" in structured or "id" in structured or "box_2d" in structured) else []

    offset = opts.get("offset", (0, 0))
    snippet_dim = opts.get("snippet_dim")

    for table_data in tables:
        t_id = table_data.get("id")
        if t_id:
            replace_table_region_by_id(page, t_id, table_data, offset=offset, snippet_dim=snippet_dim)

    return None


def _table_html_correction_apply(structured: Any, image_path: Path,
                                page=None, **opts) -> Optional[str]:
    """Applies HTML <table> updates and replaces matching <TableRegion> elements in an existing Page in-place.
    Extracts table HTML strings from structured input (dict, list, or text) and updates matching table regions by ID.
    If page is None, returns fresh PAGE-XML string.
    """
    import re
    import json
    from pageplus.utils.mappings.table_json import replace_table_region_from_html, table_html_to_page

    html_tables: List[str] = []

    def _extract_tables(obj: Any):
        if isinstance(obj, str):
            s_clean = obj.strip()
            if (s_clean.startswith("{") or s_clean.startswith("[")) and not s_clean.startswith("<table"):
                try:
                    parsed = json.loads(s_clean)
                    _extract_tables(parsed)
                    return
                except Exception:
                    pass
            matches = re.findall(r"(<table.*?>.*?</table>)", obj, re.DOTALL | re.IGNORECASE)
            if matches:
                html_tables.extend(matches)
            elif "<tr" in obj.lower():
                html_tables.append(obj)
        elif isinstance(obj, dict):
            if "html" in obj and isinstance(obj["html"], str):
                _extract_tables(obj["html"])
            elif "tables" in obj and isinstance(obj["tables"], list):
                for item in obj["tables"]:
                    _extract_tables(item)
            elif "content" in obj and isinstance(obj["content"], str):
                _extract_tables(obj["content"])
            else:
                for v in obj.values():
                    if isinstance(v, (dict, list, str)):
                        _extract_tables(v)
        elif isinstance(obj, list):
            for item in obj:
                _extract_tables(item)

    _extract_tables(structured)
    text_opt = opts.get("text")
    if text_opt and not html_tables:
        _extract_tables(text_opt)

    if page is None:
        combined_html = "\n\n".join(html_tables) if html_tables else (structured if isinstance(structured, str) else "")
        return table_html_to_page(combined_html, image_path, **opts)

    offset = opts.get("offset", (0, 0))
    snippet_dim = opts.get("snippet_dim")

    if not html_tables:
        logging.warning("No HTML tables found in model output for table correction.")
        return None

    element_id = opts.get("element_id")
    region_filter = opts.get("region_filter")

    ns = getattr(page, "ns", "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15")
    table_ids_in_page = []
    if hasattr(page, "root") and page.root is not None:
        for tr in page.root.iter(f"{{{ns}}}TableRegion"):
            t_id = tr.get("id")
            if t_id:
                table_ids_in_page.append(t_id)

    for idx, h_str in enumerate(html_tables):
        table_id = None
        m_id = re.search(r'<table[^>]*\bid=["\']([^"\']+)["\']', h_str, re.IGNORECASE)
        if m_id:
            table_id = m_id.group(1)

        target_id = None
        if table_id and table_id in table_ids_in_page:
            target_id = table_id
        elif element_id and element_id in table_ids_in_page:
            target_id = element_id
        elif region_filter is not None:
            if hasattr(page, "regions") and getattr(page.regions, "tableregions", None):
                for tr in page.regions.tableregions:
                    try:
                        if region_filter(tr):
                            target_id = tr.get_id()
                            break
                    except Exception:
                        pass
        if not target_id:
            if idx < len(table_ids_in_page):
                target_id = table_ids_in_page[idx]
            elif table_ids_in_page:
                target_id = table_ids_in_page[0]
            else:
                target_id = table_id or "t0"

        replace_table_region_from_html(page, target_id, h_str, offset=offset, snippet_dim=snippet_dim)

    return None


def _table_html_to_xml(structured: Any, image_path: Path,
                      page=None, **opts) -> str:
    """HTML <table> string -> fresh PAGE XML string."""
    from pageplus.utils.mappings.table_json import table_html_to_page
    html_text = opts.get("text")
    if not html_text and isinstance(structured, str):
        html_text = structured
    return table_html_to_page(html_text or structured or "", image_path, **opts)


def _clean_markdown_line(line: str) -> str:
    """Clean markdown formatting and structural markers (e.g. '#', '##', '###', '>', list dashes)."""
    if not line:
        return ""
    l = line.strip()
    # Strip leading markdown headers: #, ##, ###, ####, #####, ######
    l = re.sub(r'^\s*#{1,6}\s*', '', l)
    # Strip leading blockquotes
    l = re.sub(r'^\s*>\s*', '', l)
    # Strip leading bullets/dashes (* text, + text, - text)
    l = re.sub(r'^\s*[\*\+]\s+', '', l)
    # Strip markdown bold / italic markers (**text** -> text, __text__ -> text)
    l = re.sub(r'\*\*(.*?)\*\*', r'\1', l)
    l = re.sub(r'__(.*?)__', r'\1', l)
    return l.strip()


def _extract_lines_from_payload(payload: Any, target_id: Optional[str] = None) -> list[str]:
    """Extract a list of text lines from any payload (string, markdown, JSON string, dict, or list)."""
    if payload is None:
        return []

    if isinstance(payload, str):
        cleaned = payload.strip()
        # Remove code fences
        if cleaned.startswith("```"):
            c_lines = cleaned.splitlines()
            if c_lines and c_lines[0].startswith("```"):
                c_lines = c_lines[1:]
            if c_lines and c_lines[-1].strip() == "```":
                c_lines = c_lines[:-1]
            cleaned = "\n".join(c_lines).strip()

        # Try to parse as JSON if it looks like JSON
        if (cleaned.startswith("{") and cleaned.endswith("}")) or (cleaned.startswith("[") and cleaned.endswith("]")):
            parsed = None
            try:
                import json
                parsed = json.loads(cleaned)
            except Exception:
                try:
                    import json_repair
                    parsed = json_repair.repair_json(cleaned, return_objects=True)
                except Exception:
                    pass
            if parsed is not None and not isinstance(parsed, str):
                return _extract_lines_from_payload(parsed, target_id=target_id)

        # Plain text / markdown lines
        lines = []
        for line in cleaned.splitlines():
            cl = _clean_markdown_line(line)
            if cl:
                lines.append(cl)
        return lines

    if isinstance(payload, list):
        lines = []
        for item in payload:
            if isinstance(item, str):
                lines.extend(_extract_lines_from_payload(item, target_id=target_id))
            elif isinstance(item, dict):
                # If this item represents a region and target_id is specified
                r_id = item.get("id")
                if target_id and r_id and str(r_id) != str(target_id):
                    continue
                # Extract from textlines, lines, text, content, etc.
                if "textlines" in item and isinstance(item["textlines"], list):
                    for tl in item["textlines"]:
                        if isinstance(tl, dict):
                            t = _extract_text_field(tl)
                            if t:
                                cl = _clean_markdown_line(t)
                                if cl:
                                    lines.append(cl)
                        elif isinstance(tl, str):
                            cl = _clean_markdown_line(tl)
                            if cl:
                                lines.append(cl)
                elif "lines" in item and isinstance(item["lines"], list):
                    for l in item["lines"]:
                        if isinstance(l, dict):
                            t = _extract_text_field(l)
                            if t:
                                cl = _clean_markdown_line(t)
                                if cl:
                                    lines.append(cl)
                        elif isinstance(l, str):
                            cl = _clean_markdown_line(l)
                            if cl:
                                lines.append(cl)
                else:
                    t = _extract_text_field(item)
                    if t:
                        for l in t.splitlines():
                            cl = _clean_markdown_line(l)
                            if cl:
                                lines.append(cl)
            elif isinstance(item, list):
                lines.extend(_extract_lines_from_payload(item, target_id=target_id))
        return lines

    if isinstance(payload, dict):
        # 1. If target_id is given and payload has 'regions', search for the matching region
        if "regions" in payload and isinstance(payload["regions"], list):
            matching_regions = []
            for r in payload["regions"]:
                if isinstance(r, dict):
                    r_id = r.get("id")
                    if target_id is None or (r_id and str(r_id) == str(target_id)):
                        matching_regions.append(r)
            if matching_regions:
                lines = []
                for r in matching_regions:
                    lines.extend(_extract_lines_from_payload(r, target_id=target_id))
                return lines

        # 1b. Check for 'pages' list (e.g. PaddleOCR / MistralOCR format)
        if "pages" in payload and isinstance(payload["pages"], list):
            lines = []
            for pg in payload["pages"]:
                if isinstance(pg, dict):
                    md = pg.get("markdown") or _extract_text_field(pg)
                    if md:
                        for l in md.splitlines():
                            cl = _clean_markdown_line(l)
                            if cl:
                                lines.append(cl)
            if lines:
                return lines

        # 2. Check for 'textlines' list
        if "textlines" in payload and isinstance(payload["textlines"], list):
            lines = []
            for tl in payload["textlines"]:
                if isinstance(tl, dict):
                    t = _extract_text_field(tl)
                    if t:
                        cl = _clean_markdown_line(t)
                        if cl:
                            lines.append(cl)
                elif isinstance(tl, str):
                    cl = _clean_markdown_line(tl)
                    if cl:
                        lines.append(cl)
            if lines:
                return lines

        # 3. Check for 'lines' list
        if "lines" in payload and isinstance(payload["lines"], list):
            lines = []
            for l in payload["lines"]:
                if isinstance(l, dict):
                    t = _extract_text_field(l)
                    if t:
                        cl = _clean_markdown_line(t)
                        if cl:
                            lines.append(cl)
                elif isinstance(l, str):
                    cl = _clean_markdown_line(l)
                    if cl:
                        lines.append(cl)
            if lines:
                return lines

        # 4. Check for direct text fields
        text_val = _extract_text_field(payload)
        if text_val:
            lines = []
            for l in text_val.splitlines():
                cl = _clean_markdown_line(l)
                if cl:
                    lines.append(cl)
            return lines

        # 5. Check if it's a dict of {line_id: text} or {line_id: {text: ...}}
        lines = []
        for k, v in payload.items():
            if k in ("id", "type", "structure", "style", "box_2d", "coords", "baseline", "ro"):
                continue
            if isinstance(v, str) and v.strip():
                cl = _clean_markdown_line(v)
                if cl:
                    lines.append(cl)
            elif isinstance(v, dict):
                t = _extract_text_field(v)
                if t:
                    cl = _clean_markdown_line(t)
                    if cl:
                        lines.append(cl)
        if lines:
            return lines

    return []


def _textregion_lines_apply(structured: Any, image_path: Path,
                            page=None, **opts) -> Optional[str]:
    """Map line-separated text (or structured JSON from LLM transcription) to TextLines with baselines.

    Calculates proportional line heights based on character count:
    - Lines with length <= mean character count get a standard 1.0 unit height.
    - Lines with length > mean character count scale proportionally (length / mean).
    """
    if page is None:
        logging.warning("textregion_lines_apply received no page; skipping merge")
        return None

    from pageplus.models.text_elements import Textline

    def _apply_lines_to_region(target_region, lines: list[str]):
        if not target_region or not lines:
            return

        cleaned_lines = []
        for l in lines:
            cl = _clean_markdown_line(l)
            if cl:
                cleaned_lines.append(cl)

        if not cleaned_lines:
            return

        poly = target_region.get_coordinates(returntype="polygon")
        if poly is None or poly.is_empty:
            poly = target_region.get_coordinates(returntype="mrr")

        if poly is not None and not poly.is_empty:
            minx, miny, maxx, maxy = map(int, poly.bounds)
        else:
            coords_el = target_region.xml_element.find(f"{{{target_region.ns}}}Coords")
            if coords_el is not None and "points" in coords_el.attrib:
                pts = [tuple(map(float, p.split(","))) for p in coords_el.attrib["points"].strip().split() if "," in p]
                if pts:
                    xs = [p[0] for p in pts]
                    ys = [p[1] for p in pts]
                    minx, miny, maxx, maxy = int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
                else:
                    logging.warning("textregion_lines_apply: invalid coordinates for TextRegion %s", target_region.get_id())
                    return
            else:
                logging.warning("textregion_lines_apply: no Coords for TextRegion %s", target_region.get_id())
                return

        region_h = maxy - miny
        if region_h <= 0:
            region_h = 100

        # Remove existing TextLine XML elements to ensure clean state
        ns = getattr(target_region, "ns", "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15")
        for tl in list(target_region.xml_element.findall(f"{{{ns}}}TextLine")):
            target_region.xml_element.remove(tl)
        target_region.textlines = []

        num_lines = len(cleaned_lines)
        char_lens = [len(l) for l in cleaned_lines]
        mean_chars = sum(char_lens) / num_lines if num_lines > 0 else 1.0

        # Every line with <= mean has standard size (weight 1).
        # For every multiplying of the mean value, increase line height by that multiple.
        weights = []
        for clen in char_lens:
            if mean_chars <= 0 or clen <= mean_chars:
                weights.append(1)
            else:
                weights.append(max(1, int(round(clen / mean_chars))))

        total_weight = sum(weights)
        unit_height = region_h / total_weight if total_weight > 0 else region_h / num_lines

        tr_id = target_region.get_id()
        current_y = float(miny)

        for idx, (line_str, w) in enumerate(zip(cleaned_lines, weights)):
            line_id = f"{tr_id}_l{idx + 1}"
            h_line = w * unit_height
            y_top = int(round(current_y))
            y_bot = int(round(current_y + h_line))
            current_y += h_line

            y_top = max(miny, min(maxy - 1, y_top))
            y_bot = max(y_top + 1, min(maxy, y_bot))

            line_coords = [(minx, y_top), (maxx, y_top), (maxx, y_bot), (minx, y_bot)]
            baseline = [(minx, y_bot), (maxx, y_bot)]
            target_region.add_textline(line_id=line_id, coords=line_coords, baseline=baseline, text=line_str)

        # Refresh textlines list
        target_region.textlines = [
            Textline(e, target_region.ns, parent=target_region)
            for e in target_region.xml_element.findall(f"{{{target_region.ns}}}TextLine")
        ]

    element_id = opts.get("element_id")
    raw_text = opts.get("text")
    payload = structured if structured is not None else raw_text

    # Check if this is a per-snippet call
    if element_id or (isinstance(payload, str) and not payload.strip().startswith("{") and not payload.strip().startswith("[")):
        target_region = None
        if element_id:
            if hasattr(page, "get_region_by_id"):
                target_region = page.get_region_by_id(element_id)
            if target_region is None and hasattr(page, "regions") and getattr(page.regions, "textregions", None):
                for r in page.regions.textregions:
                    if r.get_id() == element_id:
                        target_region = r
                        break
        elif opts.get("region_filter") and hasattr(page, "regions") and getattr(page.regions, "textregions", None):
            rf = opts.get("region_filter")
            for r in page.regions.textregions:
                try:
                    if rf(r):
                        target_region = r
                        break
                except Exception:
                    pass

        extracted_lines = _extract_lines_from_payload(payload if payload is not None else raw_text, target_id=element_id)
        if not extracted_lines and raw_text:
            extracted_lines = _extract_lines_from_payload(raw_text, target_id=element_id)

        if target_region is not None and extracted_lines:
            _apply_lines_to_region(target_region, extracted_lines)

    # Handle batch dict or list with regions
    if isinstance(payload, dict) and ("regions" in payload or "textregions" in payload):
        regions_list = payload.get("regions") or payload.get("textregions") or []
        for r_dict in regions_list:
            if isinstance(r_dict, dict):
                r_id = r_dict.get("id")
                if r_id:
                    tr = page.get_region_by_id(r_id) if hasattr(page, "get_region_by_id") else None
                    if tr is None and hasattr(page, "regions") and getattr(page.regions, "textregions", None):
                        for r in page.regions.textregions:
                            if r.get_id() == r_id:
                                tr = r
                                break
                    if tr is not None:
                        lines = _extract_lines_from_payload(r_dict, target_id=r_id)
                        if lines:
                            _apply_lines_to_region(tr, lines)

    elif isinstance(payload, dict):
        # Handle dict mapping {region_id: content}
        for r_id, r_content in payload.items():
            if r_id in ("id", "type", "structure", "style", "box_2d", "coords", "baseline", "ro"):
                continue
            tr = page.get_region_by_id(r_id) if hasattr(page, "get_region_by_id") else None
            if tr is None and hasattr(page, "regions") and getattr(page.regions, "textregions", None):
                for r in page.regions.textregions:
                    if r.get_id() == r_id:
                        tr = r
                        break
            if tr is not None:
                lines = _extract_lines_from_payload(r_content, target_id=r_id)
                if lines:
                    _apply_lines_to_region(tr, lines)

    return None


register_postprocessor("layout_and_text_to_xml", _layout_and_text_to_xml)
register_postprocessor("gemini2d_to_page", _layout_and_text_to_xml)  # legacy alias
register_postprocessor("layout_only_to_xml", _layout_only_to_xml)
register_postprocessor("segmentation_to_page", _layout_only_to_xml)  # legacy alias
register_postprocessor("table_json_to_page", _table_json_to_xml)
register_postprocessor("table_correction_apply", _table_correction_apply)
register_postprocessor("table_html_correction_apply", _table_html_correction_apply)
register_postprocessor("table2html_apply", _table_html_correction_apply)
register_postprocessor("table_html_to_page", _table_html_to_xml)
register_postprocessor("markdown_to_page", _markdown_to_xml)
register_postprocessor("text_only_apply", _text_only_apply)
register_postprocessor("text_correction_apply", _text_correction_apply)
register_postprocessor("textregion_lines_apply", _textregion_lines_apply)
register_postprocessor("layout_correction_apply", _layout_correction_apply)
register_postprocessor("field_tagging_apply", _field_tagging_apply)
register_postprocessor("reading_order_apply", _reading_order_apply)
register_postprocessor("reading_order_text_correction_apply", _reading_order_apply)


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


def _mistral_ocr_to_xml(structured: Any, image_path: Path,
                         page=None, **opts) -> str:
    """Mistral OCR JSON (blocks + HTML tables) -> fresh PAGE XML string."""
    from pageplus.utils.mappings import mistral_ocr_to_page  # local import
    return mistral_ocr_to_page(structured, image_path, settings=opts)


register_postprocessor("mistral_ocr_to_page", _mistral_ocr_to_xml)



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



