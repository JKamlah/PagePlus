"""Shared utilities for LLM-output → PAGE XML mapping converters.

This module provides common helpers (PAGE XML boilerplate, JSON loading,
label-to-tag dictionaries) used by the individual mapping modules in this
package.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


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
    "display_formula": "MathsRegion",
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
