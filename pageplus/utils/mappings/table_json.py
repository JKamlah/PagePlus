"""Table JSON → PAGE XML mapping.

Converts structured table recognition JSON output into PAGE XML with
TableRegion / TableCell elements.
"""
import logging
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image

from pageplus.utils.mappings.mapping_utils import page_xml_header, page_xml_footer


def table_json_to_page(data: Dict[str, Any], image_path: Path, offset: Tuple[int, int] = (0, 0)) -> str:
    """
    Converts TableRecognition JSON output to PAGE XML.
    Handles coordinate scaling from JSON (0-1000) to Image absolute + offset.
    Maps Tables -> TableRegion -> TableCell -> TextLine.

    Args:
        data: JSON data from Gemini Response.
        image_path: Path to the image file.
        offset: (x_offset, y_offset) in pixels to add to coordinates (for cropped processing).

    Returns:
        String containing the full PAGE XML.
    """
    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        logging.error(f"Error reading image dimensions: {e}")
        if isinstance(data, dict) and "meta" in data and "dim" in data["meta"]:
            img_height, img_width = data["meta"]["dim"]
        else:
             return ""

    page_xml_lines = page_xml_header(
        creator="PagePlus - TableRecognition",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
    )

    # Handle if data is just the 'tables' list or the root object
    tables = []
    if isinstance(data, list):
        tables = data
    elif isinstance(data, dict):
        tables = data.get("tables", [])

    x_off, y_off = offset

    for t_idx, table in enumerate(tables):
        table_id = table.get("id", f"t{t_idx}")
        t_bbox = table.get("box_2d", [0, 0, 1000, 1000])
        if len(t_bbox) != 4:
            t_bbox = [0, 0, 1000, 1000]

        # Convert table bbox to pixels (y1, x1, y2, x2 -> pixels)
        ty1 = (t_bbox[0] / 1000 * img_height) + y_off
        tx1 = (t_bbox[1] / 1000 * img_width) + x_off
        ty2 = (t_bbox[2] / 1000 * img_height) + y_off
        tx2 = (t_bbox[3] / 1000 * img_width) + x_off

        table_width_px = tx2 - tx1
        table_height_px = ty2 - ty1

        table_coords = f"{int(tx1)},{int(ty1)} {int(tx2)},{int(ty1)} {int(tx2)},{int(ty2)} {int(tx1)},{int(ty2)}"

        page_xml_lines.append(f'        <TableRegion id="{table_id}">')
        page_xml_lines.append(f'            <Coords points="{table_coords}"/>')

        # Process Columns Info
        col_widths = table.get("columns", {}).get("width", [])

        # Process Sections
        sections = table.get("sections", {})

        current_y = ty1
        row_counter = 0

        section_order = ["note", "header", "data", "summary"]

        for sec_name in section_order:
            rows = sections.get(sec_name, [])
            if not rows:
                continue

            for row in rows:
                if not row: continue

                try:
                    row_height_ratio = float(row[-1])
                    cells_content = row[:-1]
                except (ValueError, IndexError):
                    row_height_ratio = 0.05
                    cells_content = row

                row_height_px = row_height_ratio * table_height_px

                # Handle horizontal spans (-1)
                merged_cells = []
                skip_indices = set()

                display_col_idx = 0
                for c_idx, content in enumerate(cells_content):
                    if c_idx in skip_indices:
                        continue
                    span = 1
                    for next_c in range(c_idx + 1, len(cells_content)):
                        if cells_content[next_c] == -1:
                            span += 1
                            skip_indices.add(next_c)
                        else:
                            break
                    merged_cells.append((display_col_idx, span, content))
                    display_col_idx += span

                row_y1 = current_y
                row_y2 = current_y + row_height_px

                for col_start_idx, span, content in merged_cells:
                    cell_w_ratio = 0
                    for k in range(span):
                        eff_idx = col_start_idx + k
                        if eff_idx < len(col_widths):
                            cell_w_ratio += col_widths[eff_idx]
                        else:
                            cell_w_ratio += (1.0 - sum(col_widths)) / (len(cells_content) - len(col_widths)) if (len(cells_content) - len(col_widths)) > 0 else 0.1

                    cell_w_px = cell_w_ratio * table_width_px
                    pre_w_ratio = sum(col_widths[:col_start_idx])
                    cell_x1 = tx1 + (pre_w_ratio * table_width_px)
                    cell_x2 = cell_x1 + cell_w_px

                    # Handle Vertical Grouping (Nested Rows)
                    sub_rows = []
                    if isinstance(content, list):
                        sub_rows = content
                    else:
                        sub_rows = [content]

                    num_sub = len(sub_rows)
                    if num_sub == 0: num_sub = 1
                    sub_h = row_height_px / num_sub

                    for s_idx, sub_content in enumerate(sub_rows):
                        cy1 = row_y1 + (s_idx * sub_h)
                        cy2 = cy1 + sub_h

                        cell_coords = f"{int(cell_x1)},{int(cy1)} {int(cell_x2)},{int(cy1)} {int(cell_x2)},{int(cy2)} {int(cell_x1)},{int(cy2)}"
                        cell_id = f"{table_id}_r{row_counter}_c{col_start_idx}_s{s_idx}"

                        page_xml_lines.append(f'            <TableCell id="{cell_id}" row="{row_counter}" col="{col_start_idx}" rowSpan="{1}" colSpan="{span}">')
                        page_xml_lines.append(f'                <Coords points="{cell_coords}"/>')
                        page_xml_lines.append('                <TextLine id="tl_' + cell_id + '">')
                        page_xml_lines.append(f'                    <Coords points="{cell_coords}"/>')
                        page_xml_lines.append('                    <TextEquiv>')
                        page_xml_lines.append(f'                        <Unicode>{escape(str(sub_content))}</Unicode>')
                        page_xml_lines.append('                    </TextEquiv>')
                        page_xml_lines.append('                </TextLine>')
                        page_xml_lines.append('            </TableCell>')

                current_y += row_height_px
                row_counter += 1

        page_xml_lines.append("        </TableRegion>")

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)
