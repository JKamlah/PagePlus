"""Mistral OCR JSON → PAGE XML mapping.

Converts Mistral Document OCR response (with include_blocks=True and table_format="html")
to PAGE XML format. Maps HTML tables into PAGE XML TableRegion / TableCell grid elements
and paragraph blocks into TextRegion / TextLine elements.
"""
from __future__ import annotations

import json
import logging
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from pageplus.utils.mappings.mapping_utils import (
    page_xml_header,
    page_xml_footer,
)
from pageplus.utils.mappings.markdown_parser import clean_markdown_line


# Mapping of Mistral block types to (PAGE-XML RegionTag, structure attribute)
MISTRAL_TYPE_MAP: Dict[str, Tuple[str, str]] = {
    "text": ("TextRegion", "paragraph"),
    "title": ("TextRegion", "heading"),
    "list": ("TextRegion", "list"),
    "table": ("TableRegion", "table"),
    "image": ("ImageRegion", "image"),
    "equation": ("MathsRegion", "equation"),
    "caption": ("TextRegion", "caption"),
    "code": ("TextRegion", "code"),
    "references": ("TextRegion", "references"),
    "aside_text": ("TextRegion", "marginal"),
    "header": ("TextRegion", "header"),
    "footer": ("TextRegion", "footer"),
    "signature": ("TextRegion", "signature"),
}


def parse_html_table_grid(html_str: str) -> List[Dict[str, Any]]:
    """Parse HTML table string into structured list of table cell dicts.

    Returns a list of dicts with keys: 'row', 'col', 'rowSpan', 'colSpan', 'text'.
    Handles <thead>, <tbody>, <tfoot>, <tr>, <th>, <td>, rowspan, colspan.
    Case-insensitive for tags and attributes.
    """
    if not html_str or not html_str.strip():
        return []

    cleaned_html = html_str.strip()
    if "```" in cleaned_html:
        import re
        m = re.search(r"```(?:html)?\s*(<table.*?>.*?</table>)\s*```", cleaned_html, re.DOTALL | re.IGNORECASE)
        if m:
            cleaned_html = m.group(1)
        else:
            cleaned_html = re.sub(r"```(?:html)?|```", "", cleaned_html).strip()

    if "<tr" in cleaned_html.lower() and "<table" not in cleaned_html.lower():
        cleaned_html = f"<table>{cleaned_html}</table>"

    def _get_attr(elem_or_attrs, name: str, default: str = "1") -> str:
        if hasattr(elem_or_attrs, "attrib"):
            for k, v in elem_or_attrs.attrib.items():
                if k.lower() == name.lower():
                    return v
        elif isinstance(elem_or_attrs, (dict, list)):
            attrs_dict = dict(elem_or_attrs) if isinstance(elem_or_attrs, list) else elem_or_attrs
            for k, v in attrs_dict.items():
                if k.lower() == name.lower():
                    return str(v)
        return default

    tr_elements = None
    try:
        import lxml.html
        doc = lxml.html.fromstring(cleaned_html)
        tr_elements = doc.xpath(".//tr")
    except Exception:
        tr_elements = None

    if tr_elements is not None and len(tr_elements) > 0:
        grid: Dict[Tuple[int, int], bool] = {}
        parsed_cells: List[Dict[str, Any]] = []
        for r_idx, tr in enumerate(tr_elements):
            c_idx = 0
            for cell in tr.xpath("./th | ./td"):
                while (r_idx, c_idx) in grid:
                    c_idx += 1

                rowspan_str = _get_attr(cell, "rowspan", "1")
                colspan_str = _get_attr(cell, "colspan", "1")
                try:
                    rowspan = int(rowspan_str)
                except ValueError:
                    rowspan = 1
                try:
                    colspan = int(colspan_str)
                except ValueError:
                    colspan = 1

                cell_text = cell.text_content().strip()
                for r in range(rowspan):
                    for c in range(colspan):
                        grid[(r_idx + r, c_idx + c)] = True

                parsed_cells.append({
                    "row": r_idx,
                    "col": c_idx,
                    "rowSpan": rowspan,
                    "colSpan": colspan,
                    "text": cell_text,
                })
                c_idx += colspan
        return parsed_cells

    # Fallback using standard html.parser if lxml parsing fails
    from html.parser import HTMLParser

    class SimpleTableParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows = []
            self.current_row = None
            self.current_cell = None

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "tr":
                self.current_row = []
                self.rows.append(self.current_row)
            elif tag.lower() in ("td", "th") and self.current_row is not None:
                attr_dict = {k.lower(): v for k, v in attrs}
                self.current_cell = {
                    "tag": tag.lower(),
                    "rowspan": int(attr_dict.get("rowspan", 1)),
                    "colspan": int(attr_dict.get("colspan", 1)),
                    "text": [],
                }
                self.current_row.append(self.current_cell)

        def handle_data(self, data):
            if self.current_cell is not None:
                self.current_cell["text"].append(data)

        def handle_endtag(self, tag):
            if tag.lower() in ("td", "th"):
                self.current_cell = None

    parser = SimpleTableParser()
    parser.feed(cleaned_html)
    grid: Dict[Tuple[int, int], bool] = {}
    parsed_cells: List[Dict[str, Any]] = []
    for r_idx, row in enumerate(parser.rows):
        c_idx = 0
        for cell in row:
            while (r_idx, c_idx) in grid:
                c_idx += 1
            rowspan = cell["rowspan"]
            colspan = cell["colspan"]
            cell_text = "".join(cell["text"]).strip()
            for r in range(rowspan):
                for c in range(colspan):
                    grid[(r_idx + r, c_idx + c)] = True
            parsed_cells.append({
                "row": r_idx,
                "col": c_idx,
                "rowSpan": rowspan,
                "colSpan": colspan,
                "text": cell_text,
            })
            c_idx += colspan
    return parsed_cells


def mistral_ocr_to_page(
    data: Any,
    image_path: Path,
    settings: Optional[dict] = None,
    **kwargs,
) -> str:
    """Convert Mistral Document OCR response JSON to PAGE XML string.

    Args:
        data: JSON dict or string returned by Mistral OCR API.
        image_path: Path to image file.
        settings: Optional dict of postprocessing settings.

    Returns:
        Full PAGE XML string.
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception as e:
            logging.error(f"Error parsing Mistral OCR data as JSON: {e}")
            return ""

    if not isinstance(data, dict):
        logging.error("Mistral OCR input data is not a dictionary.")
        return ""

    # Locate page dict
    page_data = data
    if "pages" in data and isinstance(data["pages"], list) and len(data["pages"]) > 0:
        page_data = data["pages"][0]

    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        logging.error(f"Error reading image dimensions: {e}")
        dim = page_data.get("dimensions", {})
        img_width = int(dim.get("width", 1000))
        img_height = int(dim.get("height", 1000))

    # Calculate scale factor relative to page dimensions in response
    scale_x = 1.0
    scale_y = 1.0
    dim = page_data.get("dimensions", {})
    if isinstance(dim, dict):
        resp_w = float(dim.get("width", 0))
        resp_h = float(dim.get("height", 0))
        if resp_w > 0 and resp_h > 0:
            scale_x = img_width / resp_w
            scale_y = img_height / resp_h

    # Extract tables dictionary by ID
    tables_by_id: Dict[str, str] = {}
    for tbl in page_data.get("tables", []) or []:
        if isinstance(tbl, dict) and "id" in tbl:
            t_id = str(tbl["id"])
            h_content = tbl.get("html") or tbl.get("markdown") or ""
            tables_by_id[t_id] = h_content

    # Extract blocks
    blocks = page_data.get("blocks", []) or []

    page_xml_lines = page_xml_header(
        creator="PagePlus - Mistral OCR",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
        comment="Generated from Mistral OCR API (include_blocks=True, table_format=html)",
    )

    ordered_refs: List[str] = []

    for b_idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue

        b_type = str(block.get("type", "text")).strip().lower()
        region_tag, structure = MISTRAL_TYPE_MAP.get(b_type, ("TextRegion", b_type))

        region_id = f"r{b_idx}"
        ordered_refs.append(region_id)

        # Parse coordinates (top_left_x, top_left_y, bottom_right_x, bottom_right_y)
        tl_x = block.get("top_left_x")
        tl_y = block.get("top_left_y")
        br_x = block.get("bottom_right_x")
        br_y = block.get("bottom_right_y")

        if any(v is None for v in (tl_x, tl_y, br_x, br_y)):
            # Fall back to 0-1000 or full image if missing
            bx1, by1, bx2, by2 = 0, 0, img_width, img_height
        else:
            bx1 = int(float(tl_x) * scale_x)
            by1 = int(float(tl_y) * scale_y)
            bx2 = int(float(br_x) * scale_x)
            by2 = int(float(br_y) * scale_y)

        # Bound coordinates to image dimensions
        bx1 = max(0, min(img_width, bx1))
        by1 = max(0, min(img_height, by1))
        bx2 = max(bx1 + 1, min(img_width, bx2))
        by2 = max(by1 + 1, min(img_height, by2))

        region_coords = f"{bx1},{by1} {bx2},{by1} {bx2},{by2} {bx1},{by2}"
        image_id = block.get("image_id") if b_type == "image" else None
        if image_id:
            custom_attr = f' custom="readingOrder {{index:{b_idx};}} structure {{type:image;}} image {{id:{escape(str(image_id))};}}"'
        else:
            custom_attr = f' custom="readingOrder {{index:{b_idx};}} structure {{type:{escape(structure)};}}"'

        # PAGE-XML schema enum for TextRegion type attribute
        valid_text_region_types = {
            "paragraph", "heading", "caption", "header", "footer", "page-number",
            "drop-capital", "credit", "floating", "signature-mark", "catch-word",
            "marginalia", "footnote", "footnote-continued", "endnote", "TOC-entry", "other"
        }
        type_attr = f' type="{escape(structure)}"' if (region_tag == "TextRegion" and structure in valid_text_region_types) else ""

        page_xml_lines.append(f'        <{region_tag} id="{region_id}"{type_attr}{custom_attr}>')
        page_xml_lines.append(f'            <Coords points="{region_coords}"/>')

        # Check block type
        if b_type == "table":
            table_id_key = block.get("table_id")
            html_table = tables_by_id.get(str(table_id_key), "") if table_id_key else ""
            if not html_table and block.get("content") and "<table" in str(block.get("content")).lower():
                html_table = str(block.get("content"))

            cells = parse_html_table_grid(html_table)
            if cells:
                max_r = max(c["row"] + c["rowSpan"] for c in cells)
                max_c = max(c["col"] + c["colSpan"] for c in cells)
                t_w = bx2 - bx1
                t_h = by2 - by1

                for c_idx, cell in enumerate(cells):
                    r_idx = cell["row"]
                    col_idx = cell["col"]
                    r_span = cell["rowSpan"]
                    c_span = cell["colSpan"]

                    cell_x1 = bx1 + (col_idx / max_c) * t_w
                    cell_x2 = bx1 + ((col_idx + c_span) / max_c) * t_w
                    cell_y1 = by1 + (r_idx / max_r) * t_h
                    cell_y2 = by1 + ((r_idx + r_span) / max_r) * t_h

                    cell_coords = f"{int(cell_x1)},{int(cell_y1)} {int(cell_x2)},{int(cell_y1)} {int(cell_x2)},{int(cell_y2)} {int(cell_x1)},{int(cell_y2)}"
                    cell_id = f"{region_id}_c{c_idx}"

                    page_xml_lines.append(
                        f'            <TableCell id="{cell_id}" row="{r_idx}" col="{col_idx}" rowSpan="{r_span}" colSpan="{c_span}">'
                    )
                    page_xml_lines.append(f'                <Coords points="{cell_coords}"/>')
                    page_xml_lines.append("                <CornerPts>0 1 2 3</CornerPts>")

                    cell_lines = cell["text"].splitlines() if cell["text"] else [""]
                    num_clines = len(cell_lines) if cell_lines else 1
                    cline_h = (cell_y2 - cell_y1) / num_clines

                    for l_idx, line_str in enumerate(cell_lines):
                        cleaned_line = clean_markdown_line(line_str)
                        ly1 = cell_y1 + (l_idx * cline_h)
                        ly2 = ly1 + cline_h
                        lbase = int(ly2 - cline_h * 0.2)
                        l_coords = f"{int(cell_x1)},{int(ly1)} {int(cell_x2)},{int(ly1)} {int(cell_x2)},{int(ly2)} {int(cell_x1)},{int(ly2)}"
                        l_base_coords = f"{int(cell_x1)},{lbase} {int(cell_x2)},{lbase}"
                        line_id = f"{cell_id}_l{l_idx + 1}"

                        page_xml_lines.append(f'                <TextLine id="{line_id}">')
                        page_xml_lines.append(f'                    <Coords points="{l_coords}"/>')
                        page_xml_lines.append(f'                    <Baseline points="{l_base_coords}"/>')
                        page_xml_lines.append("                    <TextEquiv>")
                        page_xml_lines.append(f"                        <Unicode>{escape(cleaned_line)}</Unicode>")
                        page_xml_lines.append("                    </TextEquiv>")
                        page_xml_lines.append("                </TextLine>")

                    page_xml_lines.append("            </TableCell>")
            else:
                # Fallback table text line if HTML table parsing returns no grid cells
                content_str = clean_markdown_line(str(block.get("content", "")))
                cell_id = f"{region_id}_c0"
                page_xml_lines.append(f'            <TableCell id="{cell_id}" row="0" col="0" rowSpan="1" colSpan="1">')
                page_xml_lines.append(f'                <Coords points="{region_coords}"/>')
                page_xml_lines.append("                <CornerPts>0 1 2 3</CornerPts>")
                line_id = f"{cell_id}_l1"
                page_xml_lines.append(f'                <TextLine id="{line_id}">')
                page_xml_lines.append(f'                    <Coords points="{region_coords}"/>')
                page_xml_lines.append("                    <TextEquiv>")
                page_xml_lines.append(f"                        <Unicode>{escape(content_str)}</Unicode>")
                page_xml_lines.append("                    </TextEquiv>")
                page_xml_lines.append("                </TextLine>")
                page_xml_lines.append("            </TableCell>")
        elif b_type == "image":
            # ImageRegion in PAGE-XML schema contains Coords but no TextLine elements
            pass
        else:
            # Text-containing blocks (text, title, list, equation, caption, code, references, aside_text, header, footer, signature)
            content_str = str(block.get("content", "")).strip()
            lines = content_str.splitlines() if content_str else [""]
            num_lines = len(lines) if lines else 1
            line_h = (by2 - by1) / num_lines

            for l_idx, line_str in enumerate(lines):
                cleaned_line = clean_markdown_line(line_str)
                ly1 = by1 + (l_idx * line_h)
                ly2 = ly1 + line_h
                lbase = int(ly2 - line_h * 0.2)
                l_coords = f"{bx1},{int(ly1)} {bx2},{int(ly1)} {bx2},{int(ly2)} {bx1},{int(ly2)}"
                l_base_coords = f"{bx1},{lbase} {bx2},{lbase}"
                line_id = f"{region_id}_l{l_idx + 1}"

                page_xml_lines.append(f'            <TextLine id="{line_id}">')
                page_xml_lines.append(f'                <Coords points="{l_coords}"/>')
                page_xml_lines.append(f'                <Baseline points="{l_base_coords}"/>')
                page_xml_lines.append("                    <TextEquiv>")
                page_xml_lines.append(f"                        <Unicode>{escape(cleaned_line)}</Unicode>")
                page_xml_lines.append("                    </TextEquiv>")
                page_xml_lines.append("            </TextLine>")


        page_xml_lines.append(f"        </{region_tag}>")

    # Build ReadingOrder
    if ordered_refs:
        page_xml_lines_ro = [
            "        <ReadingOrder>",
            '            <OrderedGroup id="ro_mistral_ocr" caption="Regions reading order">',
        ]
        for ro_idx, ref_id in enumerate(ordered_refs):
            page_xml_lines_ro.append(
                f'                <RegionRefIndexed index="{ro_idx}" regionRef="{ref_id}"/>'
            )
        page_xml_lines_ro.append("            </OrderedGroup>")
        page_xml_lines_ro.append("        </ReadingOrder>")

        insert_pos = next(
            (i for i, line in enumerate(page_xml_lines)
             if any(f"<{tag} " in line for tag in ("TextRegion", "TableRegion", "ImageRegion", "MathsRegion"))),
            len(page_xml_lines),
        )
        for j, ro_line in enumerate(page_xml_lines_ro):
            page_xml_lines.insert(insert_pos + j, ro_line)

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)
