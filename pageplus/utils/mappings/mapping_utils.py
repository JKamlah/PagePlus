"""Shared utilities for LLM-output → PAGE XML mapping converters.

This module provides common helpers (PAGE XML boilerplate, JSON loading,
label-to-tag dictionaries) used by the individual mapping modules in this
package.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ---------------------------------------------------------------------------
# PAGE XML boilerplate helpers
# ---------------------------------------------------------------------------

def page_xml_header(
    creator: str,
    image_path: Path,
    img_width: int,
    img_height: int,
    comment: str = "",
) -> List[str]:
    """Return the opening lines of a PAGE XML document (up to ``<Page>``)."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15 '
        'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">',
        "    <Metadata>",
        f"        <Creator>{creator}</Creator>",
        f"        <Created>{datetime.now().isoformat()}</Created>",
    ]
    if comment:
        lines.append(f"        <Comments>{comment}</Comments>")
    lines.append("    </Metadata>")
    lines.append(
        f'    <Page imageFilename="{image_path.name}" '
        f'imageWidth="{img_width}" imageHeight="{img_height}">'
    )
    return lines


def page_xml_footer() -> List[str]:
    """Return the closing lines of a PAGE XML document."""
    return ["    </Page>", "</PcGts>"]


# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

def load_gemini2d_json(json_path: [str | Path]) -> List[dict]:
    data = None
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            # Check if data is a list, adapt if it's a single object
            if not isinstance(data, list):
                logging.warning(
                    f"JSON data in {json_path.name} is not a list. Assuming list structure from values if possible, or processing top-level keys.")
                # Attempt to handle common structures, adjust as needed for
                # your specific JSON format
                if isinstance(
                    data, dict) and all(
                    isinstance(
                        v, dict) and 'box_2d' in v and (
                        'text' in v or 'text_content' in v) for v in data.values()):  # Adjusted text key check
                    data = list(data.values())
                elif isinstance(data, dict) and 'box_2d' in data and (
                        'text' in data or 'text_content' in data):  # Adjusted text key check
                    data = [data]
                else:
                    logging.error(
                        f"Cannot process non-list JSON structure in {json_path.name}")
    except FileNotFoundError:
        logging.error(f"Error: JSON file not found at '{json_path}'")
    except json.JSONDecodeError:
        logging.error(f"Error: Could not decode JSON from '{json_path}'")
    except Exception as e:
        logging.error(f"Error reading JSON file '{json_path}': {e}")
    return data


# ---------------------------------------------------------------------------
# Coordinate buffering helper
# ---------------------------------------------------------------------------

def buffer_coords_inward(coords: List[Tuple[int, int]], amount: float = 1.0) -> List[Tuple[int, int]]:
    """Buffers the coordinates inward by a specified amount (pixels)."""
    if not coords:
        return []
    # If the points form an axis-aligned rectangle, contract the bounds directly.
    xs = [pt[0] for pt in coords]
    ys = [pt[1] for pt in coords]
    unique_xs = sorted(list(set(xs)))
    unique_ys = sorted(list(set(ys)))
    if len(coords) == 4 and len(unique_xs) == 2 and len(unique_ys) == 2:
        min_x, max_x = unique_xs
        min_y, max_y = unique_ys
        if (max_x - min_x) > 2 * amount and (max_y - min_y) > 2 * amount:
            new_min_x = min_x + amount
            new_max_x = max_x - amount
            new_min_y = min_y + amount
            new_max_y = max_y - amount
            new_coords = []
            for x, y in coords:
                nx = new_min_x if x == min_x else new_max_x
                ny = new_min_y if y == min_y else new_max_y
                new_coords.append((int(nx), int(ny)))
            return new_coords

    # Fallback for arbitrary polygons: shift towards centroid
    import math
    cx = sum(pt[0] for pt in coords) / len(coords)
    cy = sum(pt[1] for pt in coords) / len(coords)
    
    new_coords = []
    for x, y in coords:
        dx = cx - x
        dy = cy - y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > 0:
            nx = x + (dx / dist) * amount
            ny = y + (dy / dist) * amount
            new_coords.append((round(nx), round(ny)))
        else:
            new_coords.append((x, y))
    return new_coords


# ---------------------------------------------------------------------------
# Label → PAGE XML region-type mapping for PP-Layout JSON
# ---------------------------------------------------------------------------

PP_LAYOUT_LABEL_TO_TAG: Dict[str, str] = {
    "text": "TextRegion",
    "paragraph_title": "TextRegion",
    "title": "TextRegion",
    "table": "TableRegion",
    "table_caption": "TextRegion",
    "figure": "ImageRegion",
    "figure_caption": "TextRegion",
    "header": "TextRegion",
    "footer": "TextRegion",
    "number": "TextRegion",
    "reference": "TextRegion",
    "footnote": "TextRegion",
    "equation": "MathsRegion",
    "abstract": "TextRegion",
    "list": "TextRegion",
    "seal": "GraphicRegion",
    "stamp": "GraphicRegion",
    # PP-Layout Category Names
    "algorithm": "TextRegion",
    "aside_text": "TextRegion",
    "chart": "ChartRegion",
    "content": "TextRegion",
    "display_formula": "TextRegion",
    "doc_title": "TextRegion",
    "figure_title": "TextRegion",
    "footer_image": "ImageRegion",
    "formula_number": "TextRegion",
    "header_image": "ImageRegion",
    "image": "ImageRegion",
    "inline_formula": "MathsRegion",
    "reference_content": "TextRegion",
    "vertical_text": "TextRegion",
    "vision_footnote": "TextRegion",
}

PP_LAYOUT_LABEL_TO_STRUCTURE: Dict[str, str] = {
    "text": "paragraph",
    "paragraph_title": "heading",
    "title": "heading",
    "table_caption": "caption",
    "figure_caption": "caption",
    "header": "header",
    "footer": "footer",
    "number": "page-number",
    "reference": "footnote-continued",
    "footnote": "footnote",
    "abstract": "paragraph",
    "list": "list-label",
    # PP-Layout Category Names
    "algorithm": "algorithm",
    "aside_text": "marginalia",
    "chart": "chart",
    "content": "toc",
    "display_formula": "formula",
    "doc_title": "heading",
    "figure_title": "caption",
    "footer_image": "footer",
    "formula_number": "formula-number",
    "header_image": "header",
    "image": "image",
    "inline_formula": "formula",
    "reference_content": "reference",
    "seal": "seal",
    "stamp": "stamp",
    "table": "table",
    "vertical_text": "paragraph",
    "vision_footnote": "caption",
}
