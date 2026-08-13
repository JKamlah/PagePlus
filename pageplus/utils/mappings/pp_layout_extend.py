"""PP-Layout Extended JSON → PAGE XML mapping.

Converts extended PP-Layout JSON (with 'regions' and 'lines') to PAGE XML.
"""
import json
import logging
from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from pageplus.utils.mappings.mapping_utils import (
    page_xml_header,
    page_xml_footer,
    PP_LAYOUT_LABEL_TO_TAG,
    PP_LAYOUT_LABEL_TO_STRUCTURE,
    buffer_coords_inward,
)


def pp_layout_extend_json_to_page(
    data: Any,
    image_path: Path,
    settings: Optional[dict] = None,
    **kwargs,
) -> str:
    """Convert extended PP-Layout JSON (with 'regions' and 'lines') to PAGE XML.

    Expects a dict (or JSON string representing a dict) with keys:
      - regions: list of dicts, each with id, label, score, polygon, bbox.
      - lines: list of dicts, each with polygon, bbox, region_id.

    Args:
        data: Parsed JSON dict or string.
        image_path: Path to the source image.
        settings: Optional settings dict.

    Returns:
        String containing the full PAGE XML.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            logging.error(f"Error parsing data string as JSON: {e}")
            return ""

    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        logging.error(f"Error reading image dimensions for PP-Layout Extend: {e}")
        return ""

    if not isinstance(data, dict):
        logging.error("PP-Layout Extend JSON is not a dictionary.")
        return ""

    regions = data.get("regions", [])
    lines = data.get("lines", [])

    def _parse_line_coords(line_dict):
        line_polygon = line_dict.get("polygon")
        line_coords_tuples: List[Tuple[int, int]] = []
        if line_polygon and isinstance(line_polygon, list) and len(line_polygon) >= 3:
            try:
                line_coords_tuples = [(int(float(pt[0])), int(float(pt[1]))) for pt in line_polygon]
            except (IndexError, TypeError, ValueError):
                pass

        if not line_coords_tuples:
            line_bbox = line_dict.get("bbox")
            if line_bbox and isinstance(line_bbox, (list, tuple)) and len(line_bbox) >= 4:
                try:
                    lx1, ly1, lx2, ly2 = (int(float(c)) for c in line_bbox[:4])
                    line_coords_tuples = [(lx1, ly1), (lx2, ly1), (lx2, ly2), (lx1, ly2)]
                except (TypeError, ValueError):
                    pass
        return line_coords_tuples

    # Group lines by region_id
    region_id_to_lines = defaultdict(list)
    for line in lines:
        if isinstance(line, dict) and "region_id" in line:
            r_id = str(line["region_id"])
            region_id_to_lines[r_id].append(line)

    # Sort lines within each region top-to-bottom
    for r_id in region_id_to_lines:
        region_id_to_lines[r_id].sort(
            key=lambda l: min(pt[1] for pt in l["polygon"]) if l.get("polygon") else (l["bbox"][1] if l.get("bbox") and len(l["bbox"]) >= 2 else 0)
        )

    # Build PAGE XML
    page_xml_lines = page_xml_header(
        creator="PagePlus - PP-Layout-Extend-JSON",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
        comment="Generated from PP-Layout-Extend-JSON",
    )

    ordered_refs: List[str] = []

    for idx, entry in enumerate(regions):
        if not isinstance(entry, dict):
            continue

        region_id_val = entry.get("id")
        if region_id_val is None:
            region_id_val = idx

        label = str(entry.get("label", "text")).strip().lower()
        score = entry.get("score")

        region_tag = PP_LAYOUT_LABEL_TO_TAG.get(label)
        if not region_tag:
            if "image" in label or "figure" in label:
                region_tag = "ImageRegion"
            else:
                region_tag = "TextRegion"

        # In the extend mapping, table regions are emitted as TextRegion with
        # TextLines because the input only carries line-level geometry (no cell
        # structure).  Use pp_layout_extend_table for proper TableRegion output.
        if region_tag == "TableRegion":
            region_tag = "TextRegion"

        structure = PP_LAYOUT_LABEL_TO_STRUCTURE.get(label)
        if not structure:
            structure = label
        xml_region_id = f"r{region_id_val}"

        # Parse polygon / bounding-box coordinates
        polygon_pts = entry.get("polygon")
        coordinate = entry.get("coordinate") or entry.get("bbox")

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
            logging.warning(f"PP-Layout Extend region {region_id_val} has no usable coordinates; skipping.")
            continue

        coords_str = " ".join(f"{x},{y}" for x, y in coords_tuples)
        ordered_refs.append(xml_region_id)

        # Confidence
        conf_attr = ""
        if score is not None:
            try:
                conf_val = float(score)
                conf_attr = f' conf="{conf_val:.4f}"'
            except (ValueError, TypeError):
                pass

        # Custom / structure tag
        type_attr = ""
        if structure:
            custom_attr = f' custom="readingOrder {{index:{idx};}} structure {{type:{escape(structure)};}}"'
            if region_tag == "TextRegion":
                type_attr = f' type="{escape(structure)}"'
        else:
            custom_attr = f' custom="readingOrder {{index:{idx};}}"'

        page_xml_lines.append(f'        <{region_tag} id="{xml_region_id}"{type_attr}{custom_attr}{conf_attr}>')
        page_xml_lines.append(f'            <Coords points="{coords_str}"/>')

        # Add lines if this is a TextRegion or TableRegion
        region_lines = region_id_to_lines.get(str(region_id_val), [])
        if region_lines:
            if region_tag == "TextRegion":
                for l_idx, line in enumerate(region_lines):
                    line_coords_tuples = _parse_line_coords(line)
                    if not line_coords_tuples:
                        continue
                    line_coords_str = " ".join(f"{x},{y}" for x, y in line_coords_tuples)
                    line_xml_id = f"{xml_region_id}_l{l_idx + 1}"
                    ys = [pt[1] for pt in line_coords_tuples]
                    xs = [pt[0] for pt in line_coords_tuples]
                    baseline_y = int(max(ys) - (max(ys) - min(ys)) * 0.2)
                    baseline_str = f"{min(xs)},{baseline_y} {max(xs)},{baseline_y}"
                    line_text = ""
                    for key in ("text", "content", "text_content", "unicode"):
                        if key in line and isinstance(line[key], str):
                            line_text = line[key]
                            break
                    page_xml_lines.append(f'            <TextLine id="{line_xml_id}">')
                    page_xml_lines.append(f'                <Coords points="{line_coords_str}"/>')
                    page_xml_lines.append(f'                <Baseline points="{baseline_str}"/>')
                    page_xml_lines.append("                <TextEquiv>")
                    page_xml_lines.append(f"                    <Unicode>{escape(line_text)}</Unicode>")
                    page_xml_lines.append("                </TextEquiv>")
                    page_xml_lines.append("            </TextLine>")
        else:
            if label == "display_formula" and region_tag == "TextRegion":
                buffered_coords = buffer_coords_inward(coords_tuples, amount=1.0)
                if buffered_coords:
                    line_coords_str = " ".join(f"{x},{y}" for x, y in buffered_coords)
                    line_xml_id = f"{xml_region_id}_l1"
                    ys = [pt[1] for pt in buffered_coords]
                    xs = [pt[0] for pt in buffered_coords]
                    baseline_y = int(max(ys) - (max(ys) - min(ys)) * 0.2)
                    baseline_str = f"{min(xs)},{baseline_y} {max(xs)},{baseline_y}"
                    page_xml_lines.append(f'            <TextLine id="{line_xml_id}">')
                    page_xml_lines.append(f'                <Coords points="{line_coords_str}"/>')
                    page_xml_lines.append(f'                <Baseline points="{baseline_str}"/>')
                    page_xml_lines.append("                <TextEquiv>")
                    page_xml_lines.append("                    <Unicode></Unicode>")
                    page_xml_lines.append("                </TextEquiv>")
                    page_xml_lines.append("            </TextLine>")

        page_xml_lines.append(f"        </{region_tag}>")

    # --- Reading order ---
    ro = data.get("ro")
    if ro and isinstance(ro, list):
        ordered_refs_to_use = []
        for item in ro:
            if isinstance(item, (int, str)):
                ordered_refs_to_use.append(f"r{item}")
    else:
        ordered_refs_to_use = ordered_refs

    if ordered_refs_to_use:
        page_xml_lines_ro = [
            "        <ReadingOrder>",
            '            <OrderedGroup id="ro_pp_layout_extend" caption="Regions reading order">',
        ]
        for ro_idx, ref_id in enumerate(ordered_refs_to_use):
            page_xml_lines_ro.append(
                f'                <RegionRefIndexed index="{ro_idx}" regionRef="{ref_id}"/>'
            )
        page_xml_lines_ro.append("            </OrderedGroup>")
        page_xml_lines_ro.append("        </ReadingOrder>")

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
