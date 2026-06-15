"""Markdown → PAGE XML mapping.

Converts markdown text (typically produced by LLMs) into PAGE XML with
synthetic block-level geometry.
"""
import logging
import re
from html import escape
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image

from pageplus.utils.mappings.mapping_utils import page_xml_header, page_xml_footer


def _parse_markdown_blocks(markdown_text: str) -> List[Dict[str, Any]]:
    """Split markdown into ordered blocks for PAGE conversion.

    Returns a list of ``{"kind": "heading"|"paragraph"|"table", ...}`` dicts.
    Geometry is *not* assigned here; :func:`markdown2pagexml` lays the blocks
    out vertically because markdown carries no coordinates.
    """
    blocks: List[Dict[str, Any]] = []
    raw_lines = (markdown_text or "").replace("\r\n", "\n").split("\n")

    i = 0
    n = len(raw_lines)
    while i < n:
        line = raw_lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        # Heading: one or more leading '#'
        heading_match = re.match(r'^(#{1,6})\s+(.*)$', stripped)
        if heading_match:
            blocks.append({
                "kind": "heading",
                "lines": [heading_match.group(2).strip()],
            })
            i += 1
            continue

        # Table: current and next line look like a markdown table
        if "|" in stripped and i + 1 < n and re.match(r'^\s*\|?[\s:|-]+\|?\s*$', raw_lines[i + 1]):
            table_lines: List[str] = []
            while i < n and "|" in raw_lines[i]:
                table_lines.append(raw_lines[i])
                i += 1
            rows: List[List[str]] = []
            for tl in table_lines:
                if re.match(r'^\s*\|?[\s:|-]+\|?\s*$', tl):
                    continue  # separator row
                cells = [c.strip() for c in tl.strip().strip("|").split("|")]
                rows.append(cells)
            if rows:
                blocks.append({"kind": "table", "rows": rows})
            continue

        # Otherwise: a paragraph = consecutive non-blank, non-special lines
        para_lines: List[str] = []
        while i < n and raw_lines[i].strip() and not re.match(r'^#{1,6}\s+', raw_lines[i].strip()):
            if "|" in raw_lines[i] and i + 1 < n and re.match(r'^\s*\|?[\s:|-]+\|?\s*$', raw_lines[i + 1]):
                break
            # Strip common list markers but keep the text
            cleaned = re.sub(r'^\s*([-*+]|\d+\.)\s+', '', raw_lines[i])
            para_lines.append(cleaned.strip())
            i += 1
        if para_lines:
            blocks.append({"kind": "paragraph", "lines": para_lines})

    return blocks


def markdown2pagexml(markdown_text: str, image_path: Path, **opts) -> str:
    """Convert markdown produced by an LLM into PAGE XML.

    Most markdown-emitting VLMs carry no line/region geometry, so this builds a
    pragmatic, *block-level* layout: headings and paragraphs become
    ``TextRegion`` s (one ``TextLine`` per source line), markdown tables become
    ``TableRegion`` s, and blocks are stacked top-to-bottom across the page
    width. The transcription is faithful; the coordinates are synthetic and
    intended for downstream correction/layout passes.
    """
    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        logging.error(f"Error reading image dimensions: {e}")
        return ""

    blocks = _parse_markdown_blocks(markdown_text)

    page_xml_lines = page_xml_header(
        creator="PagePlus - Markdown",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
        comment="Generated from LLM markdown output (synthetic geometry)",
    )

    if not blocks:
        page_xml_lines.extend(page_xml_footer())
        return "\n".join(page_xml_lines)

    x0 = int(img_width * 0.05)
    x1 = int(img_width * 0.95)
    top = int(img_height * 0.02)
    usable_h = int(img_height * 0.96)

    def _block_weight(block: Dict[str, Any]) -> int:
        if block["kind"] == "table":
            return max(1, len(block.get("rows", [])))
        return max(1, len(block.get("lines", [])))

    total_weight = sum(_block_weight(b) for b in blocks) or 1
    unit_h = usable_h / total_weight

    current_y = top
    for b_idx, block in enumerate(blocks):
        weight = _block_weight(block)
        block_h = unit_h * weight
        by1 = int(current_y)
        by2 = int(current_y + block_h)
        current_y += block_h

        if block["kind"] == "table":
            rows = block["rows"]
            n_rows = len(rows)
            n_cols = max((len(r) for r in rows), default=1)
            tbl_id = f"t{b_idx+1}"
            tbl_coords = f"{x0},{by1} {x1},{by1} {x1},{by2} {x0},{by2}"
            page_xml_lines.append(f'        <TableRegion id="{tbl_id}">')
            page_xml_lines.append(f'            <Coords points="{tbl_coords}"/>')
            cell_w = (x1 - x0) / max(1, n_cols)
            cell_h = (by2 - by1) / max(1, n_rows)
            for r_idx, row in enumerate(rows):
                for c_idx in range(n_cols):
                    content = row[c_idx] if c_idx < len(row) else ""
                    cx1 = int(x0 + c_idx * cell_w)
                    cx2 = int(x0 + (c_idx + 1) * cell_w)
                    cy1 = int(by1 + r_idx * cell_h)
                    cy2 = int(by1 + (r_idx + 1) * cell_h)
                    cell_coords = f"{cx1},{cy1} {cx2},{cy1} {cx2},{cy2} {cx1},{cy2}"
                    cell_id = f"{tbl_id}_r{r_idx}_c{c_idx}"
                    page_xml_lines.append(
                        f'            <TableCell id="{cell_id}" row="{r_idx}" col="{c_idx}" rowSpan="1" colSpan="1">')
                    page_xml_lines.append(f'                <Coords points="{cell_coords}"/>')
                    page_xml_lines.append(f'                <TextLine id="tl_{cell_id}">')
                    page_xml_lines.append(f'                    <Coords points="{cell_coords}"/>')
                    page_xml_lines.append("                    <TextEquiv>")
                    page_xml_lines.append(f'                        <Unicode>{escape(str(content))}</Unicode>')
                    page_xml_lines.append("                    </TextEquiv>")
                    page_xml_lines.append("                </TextLine>")
                    page_xml_lines.append("            </TableCell>")
            page_xml_lines.append("        </TableRegion>")
            continue

        # Text block (heading / paragraph)
        structure = "heading" if block["kind"] == "heading" else "paragraph"
        r_id = f"r{b_idx+1}"
        region_coords = f"{x0},{by1} {x1},{by1} {x1},{by2} {x0},{by2}"
        page_xml_lines.append(
            f'        <TextRegion id="{r_id}" custom="structure {{type:{structure};}}">')
        page_xml_lines.append(f'            <Coords points="{region_coords}"/>')
        lines = block["lines"] or [""]
        line_h = (by2 - by1) / max(1, len(lines))
        for l_idx, line_text in enumerate(lines):
            ly1 = int(by1 + l_idx * line_h)
            ly2 = int(by1 + (l_idx + 1) * line_h)
            baseline_y = int(ly2 - max(1, line_h * 0.2))
            line_coords = f"{x0},{ly1} {x1},{ly1} {x1},{ly2} {x0},{ly2}"
            baseline_coords = f"{x0},{baseline_y} {x1},{baseline_y}"
            line_id = f"{r_id}_l{l_idx+1}"
            page_xml_lines.append(f'            <TextLine id="{line_id}">')
            page_xml_lines.append(f'                <Coords points="{line_coords}"/>')
            page_xml_lines.append(f'                <Baseline points="{baseline_coords}"/>')
            page_xml_lines.append("                <TextEquiv>")
            page_xml_lines.append(f'                    <Unicode>{escape(str(line_text))}</Unicode>')
            page_xml_lines.append("                </TextEquiv>")
            page_xml_lines.append("            </TextLine>")
        page_xml_lines.append("        </TextRegion>")

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)
