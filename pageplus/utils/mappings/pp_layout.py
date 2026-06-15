"""PP-Layout JSON → PAGE XML mapping.

Converts PaddleOCR-style layout detection JSON to PAGE XML.
"""
import logging
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from pageplus.utils.mappings.mapping_utils import (
    page_xml_header,
    page_xml_footer,
    PP_LAYOUT_LABEL_TO_TAG,
    PP_LAYOUT_LABEL_TO_STRUCTURE,
)


def pp_layout_json_to_page(
    data: Any,
    image_path: Path,
    settings: Optional[dict] = None,
    **kwargs,
) -> str:
    """Convert PP-Layout JSON (e.g. PaddleOCR layout detection) to PAGE XML.

    Expected input: a JSON list of dicts, each with:
        - cls_id: class ID (string)
        - label: region type label (e.g. "text", "paragraph_title", "table", "number")
        - score: confidence score (string)
        - coordinate: [x1, y1, x2, y2] bounding box (strings)
        - order: reading order index (string, or "None")
        - polygon_points: [[x, y], ...] polygon coordinates (floats)

    Args:
        data: Parsed JSON (list of dicts). If wrapped in a dict, looks for a
              'regions'/'items'/'results' key.
        image_path: Path to the source image (used to read dimensions).
        settings: Optional settings dict (unused; kept for API compatibility).

    Returns:
        String containing the full PAGE XML.
    """
    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        logging.error(f"Error reading image dimensions for PP-Layout: {e}")
        return ""

    # --- Normalize input to a list of element dicts -------------------------
    elements: List[Dict[str, Any]] = []
    if isinstance(data, list):
        elements = [e for e in data if isinstance(e, dict)]
    elif isinstance(data, dict):
        for key in ("regions", "items", "results", "elements", "layout"):
            if key in data and isinstance(data[key], list):
                elements = [e for e in data[key] if isinstance(e, dict)]
                break
        if not elements:
            elements = [data]

    if not elements:
        logging.warning("PP-Layout JSON contains no elements.")

    # --- Sort elements by reading order (if available) ----------------------
    def _order_key(entry: Dict[str, Any]) -> int:
        raw = entry.get("order", "None")
        if raw is None or str(raw).strip().lower() == "none":
            return 999999
        try:
            return int(raw)
        except (ValueError, TypeError):
            return 999999

    elements_sorted = sorted(elements, key=_order_key)

    # --- Build PAGE XML -----------------------------------------------------
    page_xml_lines = page_xml_header(
        creator="PagePlus - PP-Layout-JSON",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
        comment="Generated from PP-Layout-JSON",
    )

    # Collect ordered region refs for <ReadingOrder>
    ordered_refs: List[Tuple[int, str]] = []

    for idx, entry in enumerate(elements_sorted):
        label = str(entry.get("label", "text")).strip().lower()
        score = entry.get("score", "")
        region_tag = PP_LAYOUT_LABEL_TO_TAG.get(label, "TextRegion")
        structure = PP_LAYOUT_LABEL_TO_STRUCTURE.get(label, "")
        region_id = f"r{idx + 1}"

        # Parse polygon / bounding-box coordinates
        polygon_pts = entry.get("polygon_points")
        coordinate = entry.get("coordinate")

        coords_tuples: List[Tuple[int, int]] = []
        if polygon_pts and isinstance(polygon_pts, list) and len(polygon_pts) >= 3:
            try:
                coords_tuples = [(int(float(pt[0])), int(float(pt[1]))) for pt in polygon_pts]
            except (IndexError, TypeError, ValueError):
                coords_tuples = []

        if not coords_tuples and coordinate and isinstance(coordinate, (list, tuple)) and len(coordinate) >= 4:
            try:
                x1, y1, x2, y2 = (int(float(c)) for c in coordinate[:4])
                coords_tuples = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
            except (TypeError, ValueError):
                pass

        if not coords_tuples:
            logging.warning(f"PP-Layout entry {idx} has no usable coordinates; skipping.")
            continue

        coords_str = " ".join(f"{x},{y}" for x, y in coords_tuples)

        # Reading-order info
        order_raw = entry.get("order", "None")
        if order_raw is not None and str(order_raw).strip().lower() != "none":
            try:
                ordered_refs.append((int(order_raw), region_id))
            except (ValueError, TypeError):
                pass

        # Confidence as a comment attribute
        conf_attr = ""
        try:
            conf_val = float(score)
            conf_attr = f' conf="{conf_val:.4f}"'
        except (ValueError, TypeError):
            pass

        # Custom / structure tag
        custom_attr = ""
        type_attr = ""
        if structure:
            custom_attr = f' custom="structure {{type:{escape(structure)};}}"'
            if region_tag == "TextRegion":
                type_attr = f' type="{escape(structure)}"'

        page_xml_lines.append(f'        <{region_tag} id="{region_id}"{type_attr}{custom_attr}>')
        page_xml_lines.append(f'            <Coords points="{coords_str}"/>')

        # For TextRegion: create a single TextLine spanning the region
        if region_tag == "TextRegion":
            line_id = f"{region_id}_l1"
            ys = [pt[1] for pt in coords_tuples]
            xs = [pt[0] for pt in coords_tuples]
            baseline_y = int(max(ys) - (max(ys) - min(ys)) * 0.2)
            baseline_str = f"{min(xs)},{baseline_y} {max(xs)},{baseline_y}"

            page_xml_lines.append(f'            <TextLine id="{line_id}">')
            page_xml_lines.append(f'                <Coords points="{coords_str}"/>')
            page_xml_lines.append(f'                <Baseline points="{baseline_str}"/>')
            page_xml_lines.append("                <TextEquiv>")
            page_xml_lines.append("                    <Unicode></Unicode>")
            page_xml_lines.append("                </TextEquiv>")
            page_xml_lines.append("            </TextLine>")

        page_xml_lines.append(f"        </{region_tag}>")

    # --- Reading order (only elements with explicit order) ---
    if ordered_refs:
        ordered_refs.sort(key=lambda x: x[0])
        page_xml_lines_ro = [
            "        <ReadingOrder>",
            '            <OrderedGroup id="ro_pp_layout" caption="Regions reading order">',
        ]
        for ro_idx, (_, ref_id) in enumerate(ordered_refs):
            page_xml_lines_ro.append(
                f'                <RegionRefIndexed index="{ro_idx}" regionRef="{ref_id}"/>'
            )
        page_xml_lines_ro.append("            </OrderedGroup>")
        page_xml_lines_ro.append("        </ReadingOrder>")

        # Insert ReadingOrder before the first region
        insert_pos = next(
            (i for i, line in enumerate(page_xml_lines)
             if '<TextRegion ' in line or '<TableRegion ' in line
             or '<ImageRegion ' in line or '<MathsRegion ' in line
             or '<GraphicRegion ' in line),
            len(page_xml_lines),
        )
        for j, ro_line in enumerate(page_xml_lines_ro):
            page_xml_lines.insert(insert_pos + j, ro_line)

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)
