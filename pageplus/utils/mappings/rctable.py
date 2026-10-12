"""RCTable JSON → PAGE XML mapping.

Converts dual Row-Column ("RCTable") structured table recognition JSON output
into PAGE XML with TableRegion / TableCell / TextLine elements.

Handles:
- Row and column bounding boxes (box_2d: [ymin, xmin, ymax, xmax] on 0-1000 scale).
- Merged cell resolution using '#REMOVE-MERGED-COLUMN' and '#REMOVE-MERGED-ROW'.
- Proportions heuristic when bounding boxes are missing, identical, or degenerate.
- Coordinate scaling from normalized 0-1000 to absolute pixel dimensions + offset.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import lxml.etree as ET
from PIL import Image

from pageplus.utils.mappings.mapping_utils import page_xml_header, page_xml_footer

logger = logging.getLogger(__name__)

MERGE_COL_PATTERN = re.compile(r"#REMOVE-MERGED-(?:COLUMN|COL)\b", re.IGNORECASE)
MERGE_ROW_PATTERN = re.compile(r"#REMOVE-MERGED-ROW\b", re.IGNORECASE)
MERGE_ANY_PATTERN = re.compile(r"#REMOVE-MERGED-(?:ROW|COLUMN|COL)\b", re.IGNORECASE)


def is_merged_column(value: Any) -> bool:
    """Returns True if cell value marks a horizontally merged column placeholder."""
    if not isinstance(value, str):
        return False
    return bool(MERGE_COL_PATTERN.search(value.strip()))


def is_merged_row(value: Any) -> bool:
    """Returns True if cell value marks a vertically merged row placeholder."""
    if not isinstance(value, str):
        return False
    return bool(MERGE_ROW_PATTERN.search(value.strip()))


def is_merge_marker(value: Any) -> bool:
    """Returns True if cell value is any merge placeholder marker."""
    if not isinstance(value, str):
        return False
    return bool(MERGE_ANY_PATTERN.search(value.strip()))


def _normalize_box(box: Any) -> Optional[List[float]]:
    """Normalizes a 4-element bounding box to [ymin, xmin, ymax, xmax]."""
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return None
    try:
        y1, x1, y2, x2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
        if y2 < y1:
            y1, y2 = y2, y1
        if x2 < x1:
            x1, x2 = x2, x1
        return [y1, x1, y2, x2]
    except (ValueError, TypeError):
        return None


def guess_column_proportions(
    columns_data: List[Dict[str, Any]],
    grid: List[List[str]],
    table_x1: float,
    table_x2: float,
    img_width: float = 1000.0,
    x_off: float = 0.0,
) -> List[Tuple[float, float]]:
    """Determine horizontal [x1, x2] bounds for each column.

    Uses column box_2d if valid and distinct; otherwise estimates proportions
    based on cell text lengths.
    """
    num_cols = len(grid[0]) if grid and grid[0] else len(columns_data)
    if num_cols == 0:
        return []

    table_width = max(1.0, table_x2 - table_x1)

    # 1. Try extracting box_2d for columns
    col_boxes: List[Optional[List[float]]] = []
    for c_idx in range(num_cols):
        box = None
        if c_idx < len(columns_data) and isinstance(columns_data[c_idx], dict):
            box = _normalize_box(columns_data[c_idx].get("box_2d") or columns_data[c_idx].get("bbox"))
        col_boxes.append(box)

    valid_boxes = [b for b in col_boxes if b is not None and (b[3] - b[1]) > 0.001]
    is_distinct = False
    if len(valid_boxes) == num_cols and num_cols > 1:
        # Check that columns have distinct x coordinates (not all equal to full table)
        x_mins = [b[1] for b in valid_boxes]
        if max(x_mins) - min(x_mins) > 5.0:  # on 0-1000 scale
            is_distinct = True

    if is_distinct:
        first_box = valid_boxes[0]
        col_start_x = first_box[1]
        page_pixel_x1 = (col_start_x / 1000.0 * img_width) + x_off if col_start_x <= 1000.0 else col_start_x + x_off
        is_page_relative = abs(page_pixel_x1 - table_x1) < abs(table_x1 + (col_start_x / 1000.0 * table_width) - table_x1)

        raw_intervals: List[Tuple[float, float]] = []
        for b in col_boxes:
            assert b is not None
            if is_page_relative:
                cx1 = (b[1] / 1000.0 * img_width) + x_off if b[1] <= 1000.0 else b[1] + x_off
                cx2 = (b[3] / 1000.0 * img_width) + x_off if b[3] <= 1000.0 else b[3] + x_off
            else:
                cx1 = table_x1 + (b[1] / 1000.0 * table_width) if b[1] <= 1000.0 else b[1]
                cx2 = table_x1 + (b[3] / 1000.0 * table_width) if b[3] <= 1000.0 else b[3]
            raw_intervals.append((cx1, cx2))

        # Snap adjacent boundaries to ensure contiguous columns without gaps
        snapped: List[Tuple[float, float]] = []
        for i in range(num_cols):
            x1 = raw_intervals[i][0]
            x2 = raw_intervals[i][1]
            if i > 0:
                mid = (snapped[i - 1][1] + x1) / 2.0
                snapped[i - 1] = (snapped[i - 1][0], mid)
                x1 = mid
            snapped.append((x1, x2))
        if snapped:
            snapped[0] = (table_x1, snapped[0][1])
            snapped[-1] = (snapped[-1][0], table_x2)

        # Ensure strict monotonicity; if coordinates overlap or invert, fall back to proportional grid
        if all(snapped[i][1] > snapped[i][0] + 1.0 for i in range(len(snapped))):
            return snapped

    # 2. Heuristic fallback: guess proportions by text length
    col_weights: List[float] = []
    for c_idx in range(num_cols):
        total_len = 0
        for r_idx in range(len(grid)):
            cell_txt = grid[r_idx][c_idx] if c_idx < len(grid[r_idx]) else ""
            if not is_merge_marker(cell_txt):
                total_len += max(3, len(cell_txt.strip()))
        # Sqrt dampens extremes while giving wider columns appropriately more space
        col_weights.append(math.sqrt(max(1.0, float(total_len))))

    total_weight = sum(col_weights) or float(num_cols)
    intervals: List[Tuple[float, float]] = []
    curr_x = table_x1
    for w in col_weights:
        col_w = (w / total_weight) * table_width
        intervals.append((curr_x, curr_x + col_w))
        curr_x += col_w

    return intervals


def guess_row_proportions(
    rows_data: List[Dict[str, Any]],
    grid: List[List[str]],
    table_y1: float,
    table_y2: float,
    img_height: float = 1000.0,
    y_off: float = 0.0,
) -> List[Tuple[float, float]]:
    """Determine vertical [y1, y2] bounds for each row.

    Uses row box_2d if valid and distinct; otherwise estimates proportions
    based on cell text line counts and content.
    """
    num_rows = len(grid)
    if num_rows == 0:
        return []

    table_height = max(1.0, table_y2 - table_y1)

    # 1. Try extracting box_2d for rows
    row_boxes: List[Optional[List[float]]] = []
    for r_idx in range(num_rows):
        box = None
        if r_idx < len(rows_data) and isinstance(rows_data[r_idx], dict):
            box = _normalize_box(rows_data[r_idx].get("box_2d") or rows_data[r_idx].get("bbox"))
        row_boxes.append(box)

    valid_boxes = [b for b in row_boxes if b is not None and (b[2] - b[0]) > 0.001]
    is_distinct = False
    if len(valid_boxes) == num_rows and num_rows > 1:
        y_mins = [b[0] for b in valid_boxes]
        if max(y_mins) - min(y_mins) > 5.0:  # on 0-1000 scale
            is_distinct = True

    if is_distinct:
        first_box = valid_boxes[0]
        row_start_y = first_box[0]
        page_pixel_y1 = (row_start_y / 1000.0 * img_height) + y_off if row_start_y <= 1000.0 else row_start_y + y_off
        is_page_relative = abs(page_pixel_y1 - table_y1) < abs(table_y1 + (row_start_y / 1000.0 * table_height) - table_y1)

        raw_intervals: List[Tuple[float, float]] = []
        for b in row_boxes:
            assert b is not None
            if is_page_relative:
                ry1 = (b[0] / 1000.0 * img_height) + y_off if b[0] <= 1000.0 else b[0] + y_off
                ry2 = (b[2] / 1000.0 * img_height) + y_off if b[2] <= 1000.0 else b[2] + y_off
            else:
                ry1 = table_y1 + (b[0] / 1000.0 * table_height) if b[0] <= 1000.0 else b[0]
                ry2 = table_y1 + (b[2] / 1000.0 * table_height) if b[2] <= 1000.0 else b[2]
            raw_intervals.append((ry1, ry2))

        # Snap adjacent boundaries to ensure contiguous rows
        snapped: List[Tuple[float, float]] = []
        for i in range(num_rows):
            y1 = raw_intervals[i][0]
            y2 = raw_intervals[i][1]
            if i > 0:
                mid = (snapped[i - 1][1] + y1) / 2.0
                snapped[i - 1] = (snapped[i - 1][0], mid)
                y1 = mid
            snapped.append((y1, y2))
        if snapped:
            snapped[0] = (table_y1, snapped[0][1])
            snapped[-1] = (snapped[-1][0], table_y2)

        # Ensure strict monotonicity; if coordinates overlap or invert, fall back to proportional grid
        if all(snapped[i][1] > snapped[i][0] + 1.0 for i in range(len(snapped))):
            return snapped

    # 2. Heuristic fallback: guess proportions by line count
    row_weights: List[float] = []
    for r_idx in range(num_rows):
        max_lines = 1
        for c_idx in range(len(grid[r_idx])):
            cell_txt = grid[r_idx][c_idx]
            if not is_merge_marker(cell_txt):
                lines = cell_txt.count("\n") + 1
                if lines > max_lines:
                    max_lines = lines
        row_weights.append(float(max_lines))

    total_weight = sum(row_weights) or float(num_rows)
    intervals: List[Tuple[float, float]] = []
    curr_y = table_y1
    for w in row_weights:
        row_h = (w / total_weight) * table_height
        intervals.append((curr_y, curr_y + row_h))
        curr_y += row_h

    return intervals


def build_rctable_region_element(
    table_data: Dict[str, Any],
    ns: str,
    img_width: int,
    img_height: int,
    offset: Tuple[int, int] = (0, 0),
    override_id: Optional[str] = None,
) -> ET.Element:
    """Builds an lxml ET.Element representing a <TableRegion> from RCTable structure."""
    table_id = override_id or table_data.get("id") or f"Table_{int(time.time() * 1000)}"
    x_off, y_off = offset

    columns_data: List[Dict[str, Any]] = table_data.get("columns", [])
    rows_data: List[Dict[str, Any]] = table_data.get("rows", [])

    if not isinstance(columns_data, list):
        columns_data = []
    if not isinstance(rows_data, list):
        rows_data = []

    def _extract_cell_text(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, dict):
            return str(val.get("value") or val.get("text") or val.get("text_content") or "")
        return str(val)

    # 1. Determine overall table bounding box
    all_boxes: List[List[float]] = []
    t_box = _normalize_box(table_data.get("box_2d") or table_data.get("bbox"))
    if t_box:
        all_boxes.append(t_box)

    for col in columns_data:
        if isinstance(col, dict):
            cb = _normalize_box(col.get("box_2d") or col.get("bbox"))
            if cb:
                all_boxes.append(cb)

    for row in rows_data:
        if isinstance(row, dict):
            rb = _normalize_box(row.get("box_2d") or row.get("bbox"))
            if rb:
                all_boxes.append(rb)

    if all_boxes:
        ymin_rel = min(b[0] for b in all_boxes)
        xmin_rel = min(b[1] for b in all_boxes)
        ymax_rel = max(b[2] for b in all_boxes)
        xmax_rel = max(b[3] for b in all_boxes)
    else:
        ymin_rel, xmin_rel, ymax_rel, xmax_rel = 0.0, 0.0, 1000.0, 1000.0

    # 2. Extract column heading cells and data row cells
    num_cols = len(columns_data)
    col_cells_list: List[List[str]] = []
    for col in columns_data:
        if isinstance(col, dict):
            c_cells = col.get("cells", [])
            if isinstance(c_cells, list):
                col_cells_list.append([_extract_cell_text(x) for x in c_cells])
            elif c_cells is not None:
                col_cells_list.append([_extract_cell_text(c_cells)])
            else:
                col_cells_list.append([])
        else:
            col_cells_list.append([])

    row_cells_list: List[List[str]] = []
    for row in rows_data:
        if isinstance(row, dict):
            r_cells = row.get("cells", [])
            if isinstance(r_cells, list):
                row_cells_list.append([_extract_cell_text(x) for x in r_cells])
            elif r_cells is not None:
                row_cells_list.append([_extract_cell_text(r_cells)])
            else:
                row_cells_list.append([])
        else:
            row_cells_list.append([])

    if num_cols == 0 and row_cells_list:
        num_cols = max(len(r) for r in row_cells_list)
    num_cols = max(1, num_cols)

    # 3. Detect non-overlapping schema (columns contain headings only, rows contain data only)
    has_col_headings = any(len(c) > 0 and any(txt.strip() for txt in c) for c in col_cells_list)
    first_col_heading_row = [col_cells_list[c][0] if c < len(col_cells_list) and len(col_cells_list[c]) > 0 else "" for c in range(num_cols)]
    first_data_row = row_cells_list[0] if row_cells_list else []

    rows_already_have_header = False
    if has_col_headings and row_cells_list:
        matches = 0
        comparable_count = min(len(first_col_heading_row), len(first_data_row))
        if comparable_count > 0:
            for c_i in range(comparable_count):
                h_txt = first_col_heading_row[c_i].strip().lower()
                r_txt = first_data_row[c_i].strip().lower()
                if h_txt and r_txt and h_txt == r_txt:
                    matches += 1
            if matches >= max(1, int(comparable_count * 0.7)):
                rows_already_have_header = True

    effective_rows_data: List[Dict[str, Any]] = []

    if has_col_headings and not rows_already_have_header:
        # Non-overlapping schema: columns = headings, rows = data part
        num_header_rows = max(len(c) for c in col_cells_list) if col_cells_list else 1
        header_grid_rows: List[List[str]] = []
        for h_idx in range(num_header_rows):
            h_row = [col_cells_list[c][h_idx] if c < len(col_cells_list) and h_idx < len(col_cells_list[c]) else "" for c in range(num_cols)]
            header_grid_rows.append(h_row)

        data_grid_rows: List[List[str]] = []
        for r_cells in row_cells_list:
            padded = list(r_cells)
            if len(padded) < num_cols:
                padded.extend([""] * (num_cols - len(padded)))
            elif len(padded) > num_cols:
                padded = padded[:num_cols]
            data_grid_rows.append(padded)

        grid = header_grid_rows + data_grid_rows

        # Synthesize effective_rows_data for row proportions
        first_data_row_ymin = None
        for r in rows_data:
            if isinstance(r, dict):
                rb = _normalize_box(r.get("box_2d") or r.get("bbox"))
                if rb:
                    first_data_row_ymin = rb[0]
                    break

        if first_data_row_ymin is not None and first_data_row_ymin > ymin_rel:
            header_bottom = first_data_row_ymin
        else:
            total_r = len(grid)
            header_bottom = ymin_rel + (ymax_rel - ymin_rel) * (num_header_rows / max(1, total_r))

        header_step = (header_bottom - ymin_rel) / max(1, num_header_rows)
        for h_idx in range(num_header_rows):
            h_y1 = ymin_rel + h_idx * header_step
            h_y2 = ymin_rel + (h_idx + 1) * header_step
            effective_rows_data.append({
                "box_2d": [h_y1, xmin_rel, h_y2, xmax_rel],
                "cells": header_grid_rows[h_idx],
            })
        effective_rows_data.extend(rows_data)

    else:
        num_rows = len(rows_data)
        if num_rows == 0 and col_cells_list:
            num_rows = max(len(c) for c in col_cells_list)
        num_rows = max(1, num_rows)

        grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]
        for r_idx, r_cells in enumerate(row_cells_list):
            if r_idx < num_rows:
                for c_idx, cell_val in enumerate(r_cells):
                    if c_idx < num_cols:
                        grid[r_idx][c_idx] = cell_val

        for c_idx, c_cells in enumerate(col_cells_list):
            if c_idx < num_cols:
                for r_idx, cell_val in enumerate(c_cells):
                    if r_idx < num_rows:
                        existing = grid[r_idx][c_idx]
                        if not existing or (is_merge_marker(cell_val) and not is_merge_marker(existing)):
                            grid[r_idx][c_idx] = cell_val
                        elif not is_merge_marker(cell_val) and is_merge_marker(existing):
                            grid[r_idx][c_idx] = cell_val

        effective_rows_data = rows_data

    num_rows = len(grid)
    num_cols = len(grid[0]) if grid else num_cols

    # Scale to image pixel coordinates
    tx1 = (xmin_rel / 1000.0 * img_width) + x_off if xmin_rel <= 1000.0 else xmin_rel + x_off
    ty1 = (ymin_rel / 1000.0 * img_height) + y_off if ymin_rel <= 1000.0 else ymin_rel + y_off
    tx2 = (xmax_rel / 1000.0 * img_width) + x_off if xmax_rel <= 1000.0 else xmax_rel + x_off
    ty2 = (ymax_rel / 1000.0 * img_height) + y_off if ymax_rel <= 1000.0 else ymax_rel + y_off

    tx1, tx2 = min(tx1, tx2), max(tx1, tx2)
    ty1, ty2 = min(ty1, ty2), max(ty1, ty2)
    if tx2 <= tx1 + 10.0:
        tx2 = tx1 + 100.0
    if ty2 <= ty1 + 10.0:
        ty2 = ty1 + 100.0

    table_region_elem = ET.Element(f"{{{ns}}}TableRegion")
    table_region_elem.set("id", table_id)

    table_coords = f"{int(tx1)},{int(ty1)} {int(tx2)},{int(ty1)} {int(tx2)},{int(ty2)} {int(tx1)},{int(ty2)}"
    coords_elem = ET.SubElement(table_region_elem, f"{{{ns}}}Coords")
    coords_elem.set("points", table_coords)

    # Guess column and row intervals
    col_intervals = guess_column_proportions(columns_data, grid, tx1, tx2, img_width=img_width, x_off=x_off)
    row_intervals = guess_row_proportions(effective_rows_data, grid, ty1, ty2, img_height=img_height, y_off=y_off)

    # 2D visited tracking for merged spans
    visited = [[False for _ in range(num_cols)] for _ in range(num_rows)]

    for r in range(num_rows):
        for c in range(num_cols):
            if visited[r][c]:
                continue

            cell_val = grid[r][c]

            # If this cell is a merge marker, skip as standalone cell
            if is_merge_marker(cell_val):
                visited[r][c] = True
                continue

            # Calculate colspan (horizontal merge)
            cspan = 1
            for next_c in range(c + 1, num_cols):
                if is_merged_column(grid[r][next_c]):
                    cspan += 1
                else:
                    break

            # Calculate rowspan (vertical merge)
            rspan = 1
            for next_r in range(r + 1, num_rows):
                if is_merged_row(grid[next_r][c]):
                    rspan += 1
                else:
                    break

            # Mark covered cells in the span block as visited
            for dr in range(rspan):
                for dc in range(cspan):
                    visited[r + dr][c + dc] = True

            # Calculate cell bounding box from column & row intervals
            cx1 = col_intervals[c][0]
            cx2 = col_intervals[c + cspan - 1][1]
            cy1 = row_intervals[r][0]
            cy2 = row_intervals[r + rspan - 1][1]

            cell_coords = f"{int(cx1)},{int(cy1)} {int(cx2)},{int(cy1)} {int(cx2)},{int(cy2)} {int(cx1)},{int(cy2)}"
            cell_id = f"{table_id}_r{r}_c{c}"

            cell_elem = ET.SubElement(table_region_elem, f"{{{ns}}}TableCell")
            cell_elem.set("id", cell_id)
            cell_elem.set("row", str(r))
            cell_elem.set("col", str(c))
            cell_elem.set("rowSpan", str(rspan))
            cell_elem.set("colSpan", str(cspan))

            cell_c_elem = ET.SubElement(cell_elem, f"{{{ns}}}Coords")
            cell_c_elem.set("points", cell_coords)

            corner_elem = ET.SubElement(cell_elem, f"{{{ns}}}CornerPts")
            corner_elem.text = "0 1 2 3"

            lines = cell_val.split("\n") if cell_val else [""]
            if len(lines) <= 1:
                tl_elem = ET.SubElement(cell_elem, f"{{{ns}}}TextLine")
                tl_elem.set("id", f"tl_{cell_id}")

                tl_c_elem = ET.SubElement(tl_elem, f"{{{ns}}}Coords")
                tl_c_elem.set("points", cell_coords)

                te_elem = ET.SubElement(tl_elem, f"{{{ns}}}TextEquiv")
                uni_elem = ET.SubElement(te_elem, f"{{{ns}}}Unicode")
                uni_elem.text = cell_val if cell_val else ""
            else:
                line_height = (cy2 - cy1) / len(lines)
                for l_idx, line_txt in enumerate(lines):
                    ly1 = cy1 + l_idx * line_height
                    ly2 = cy1 + (l_idx + 1) * line_height
                    line_coords = f"{int(cx1)},{int(ly1)} {int(cx2)},{int(ly1)} {int(cx2)},{int(ly2)} {int(cx1)},{int(ly2)}"
                    tl_elem = ET.SubElement(cell_elem, f"{{{ns}}}TextLine")
                    tl_elem.set("id", f"tl_{cell_id}_{l_idx+1}")

                    tl_c_elem = ET.SubElement(tl_elem, f"{{{ns}}}Coords")
                    tl_c_elem.set("points", line_coords)

                    te_elem = ET.SubElement(tl_elem, f"{{{ns}}}TextEquiv")
                    uni_elem = ET.SubElement(te_elem, f"{{{ns}}}Unicode")
                    uni_elem.text = line_txt

            cell_te_elem = ET.SubElement(cell_elem, f"{{{ns}}}TextEquiv")
            cell_uni_elem = ET.SubElement(cell_te_elem, f"{{{ns}}}Unicode")
            cell_uni_elem.text = cell_val if cell_val else ""

    return table_region_elem


def rctable_json_to_page(
    data: Any,
    image_path: Path,
    offset: Tuple[int, int] = (0, 0),
    **kwargs,
) -> str:
    """Converts RCTable JSON structure to a complete PAGE XML string.

    Supports:
    - Dict with 'columns' and 'rows'
    - Dict with 'tables': [...]
    - List of table dicts
    - JSON string representation
    """
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            try:
                import json_repair
                data = json_repair.repair_json(data, return_objects=True)
            except Exception as e:
                logger.error(f"Failed to parse RCTable JSON string: {e}")
                return ""

    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        logger.error(f"Error reading image dimensions for RCTable: {e}")
        img_width, img_height = 1000, 1000

    page_xml_lines = page_xml_header(
        creator="PagePlus - RCTable",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
    )

    # Normalize tables list
    tables: List[Dict[str, Any]] = []
    if isinstance(data, dict):
        if "tables" in data and isinstance(data["tables"], list):
            tables = data["tables"]
        elif "columns" in data or "rows" in data:
            tables = [data]
    elif isinstance(data, list):
        tables = data

    ns = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"
    try:
        ET.register_namespace("", ns)
    except Exception:
        pass

    for idx, table_dict in enumerate(tables):
        if not isinstance(table_dict, dict):
            continue
        table_elem = build_rctable_region_element(
            table_dict,
            ns=ns,
            img_width=img_width,
            img_height=img_height,
            offset=offset,
            override_id=table_dict.get("id") or f"Table_{idx}",
        )
        xml_str = ET.tostring(table_elem, encoding="unicode")
        # Strip xmlns attribute and any ns0 prefixes to prevent namespace clutter inside root
        xml_str = xml_str.replace(f' xmlns="{ns}"', "").replace("ns0:", "").replace(":ns0", "")
        page_xml_lines.append(xml_str)

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)


# Public alias for pipeline compatibility
rctable_to_page = rctable_json_to_page


def replace_rctable_region_by_id(
    page: Any,
    table_data: Dict[str, Any],
    offset: Tuple[int, int] = (0, 0),
) -> bool:
    """Replaces or inserts an existing TableRegion in a Page object with RCTable structure."""
    target_id = table_data.get("id")
    page_elem = page.root.find(f"{{{page.ns}}}Page")
    if page_elem is None:
        logger.error("Page element not found in XML.")
        return False

    img_width = int(page_elem.get("imageWidth", 1000))
    img_height = int(page_elem.get("imageHeight", 1000))

    new_elem = build_rctable_region_element(
        table_data,
        ns=page.ns,
        img_width=img_width,
        img_height=img_height,
        offset=offset,
        override_id=target_id,
    )

    if target_id:
        for child in list(page_elem):
            if child.get("id") == target_id:
                idx = list(page_elem).index(child)
                page_elem.remove(child)
                page_elem.insert(idx, new_elem)
                return True

    page_elem.append(new_elem)
    return True


def rctable_to_page_xml(
    tables_data: Union[Dict[str, Any], List[Dict[str, Any]]],
    page: Any,
    offset: Tuple[int, int] = (0, 0),
) -> None:
    """Updates a Page instance in-place with RCTable data."""
    tables: List[Dict[str, Any]] = []
    if isinstance(tables_data, dict):
        if "tables" in tables_data and isinstance(tables_data["tables"], list):
            tables = tables_data["tables"]
        else:
            tables = [tables_data]
    elif isinstance(tables_data, list):
        tables = tables_data

    for table in tables:
        if isinstance(table, dict):
            replace_rctable_region_by_id(page, table, offset=offset)
