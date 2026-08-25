"""Table JSON → PAGE XML mapping.

Converts structured table recognition JSON output into PAGE XML with
TableRegion / TableCell elements.
"""
import logging
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from pageplus.utils.mappings.mapping_utils import page_xml_header, page_xml_footer


def indent_xml_element(elem: Any, level: int = 2, space: str = "    ") -> None:
    """Recursively indents an lxml/ElementTree element in-place for pretty XML output."""
    try:
        import lxml.etree as ET
        if hasattr(ET, "indent"):
            ET.indent(elem, space=space, level=level)
            return
    except Exception:
        pass

    i = "\n" + (level * space)
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + space
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for subelem in elem:
            indent_xml_element(subelem, level + 1, space)
        if not subelem.tail or not subelem.tail.strip():
            subelem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i



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
                        page_xml_lines.append('                <CornerPts>0 1 2 3</CornerPts>')
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


def build_table_region_element(
    table: Dict[str, Any],
    ns: str,
    img_width: int,
    img_height: int,
    offset: Tuple[int, int] = (0, 0),
    override_id: Optional[str] = None,
    existing_cells_map: Optional[Dict[Tuple[int, int], str]] = None,
) -> Any:
    """Builds an lxml ET.Element representing a <TableRegion> with its <Coords>, <TableCell>s, and <TextLine>s.
    Coordinates are scaled from JSON (0..1000) relative to snippet dimensions + offset.
    If existing_cells_map is provided, existing cell coordinates are preserved and merged.
    """
    import lxml.etree as ET
    import time

    table_id = override_id or table.get("id") or f"Table_{int(time.time()*1000)}"
    t_bbox = table.get("box_2d") or table.get("bbox") or [0, 0, 1000, 1000]
    if len(t_bbox) != 4:
        t_bbox = [0, 0, 1000, 1000]

    x_off, y_off = offset
    ty1 = (t_bbox[0] / 1000.0 * img_height) + y_off
    tx1 = (t_bbox[1] / 1000.0 * img_width) + x_off
    ty2 = (t_bbox[2] / 1000.0 * img_height) + y_off
    tx2 = (t_bbox[3] / 1000.0 * img_width) + x_off

    table_width_px = max(1.0, tx2 - tx1)
    table_height_px = max(1.0, ty2 - ty1)

    table_region_elem = ET.Element(f"{{{ns}}}TableRegion")
    table_region_elem.set("id", table_id)

    coords_elem = ET.SubElement(table_region_elem, f"{{{ns}}}Coords")
    coords_elem.set("points", f"{int(tx1)},{int(ty1)} {int(tx2)},{int(ty1)} {int(tx2)},{int(ty2)} {int(tx1)},{int(ty2)}")

    cells_data = table.get("cells")
    if cells_data is not None:
        num_rows = int(table.get("rows", 0))
        num_cols = int(table.get("cols", 0))
        if not num_rows:
            num_rows = max([int(c.get("row", 0)) + int(c.get("rowspan", c.get("rowSpan", 1))) for c in cells_data], default=1)
        if not num_cols:
            num_cols = max([int(c.get("col", 0)) + int(c.get("colspan", c.get("colSpan", 1))) for c in cells_data], default=1)

        row_h_px = table_height_px / max(1, num_rows)
        col_w_px = table_width_px / max(1, num_cols)

        for cell in cells_data:
            r = int(cell.get("row", 0))
            c = int(cell.get("col", 0))
            rspan = int(cell.get("rowspan", cell.get("rowSpan", 1)))
            cspan = int(cell.get("colspan", cell.get("colSpan", 1)))
            val = cell.get("value", cell.get("text", cell.get("content", "")))

            if rspan < 1 or cspan < 1 or val == -1 or str(val).strip() == "-1":
                continue

            cell_coords = None
            if existing_cells_map:
                spanned_points = []
                for dr in range(rspan):
                    for dc in range(cspan):
                        pts_str = existing_cells_map.get((r + dr, c + dc))
                        if pts_str:
                            for tok in pts_str.split():
                                if "," in tok:
                                    try:
                                        px, py = tok.split(",")
                                        spanned_points.append((float(px), float(py)))
                                    except ValueError:
                                        pass
                if spanned_points:
                    min_x = min(p[0] for p in spanned_points)
                    max_x = max(p[0] for p in spanned_points)
                    min_y = min(p[1] for p in spanned_points)
                    max_y = max(p[1] for p in spanned_points)
                    cell_coords = f"{int(min_x)},{int(min_y)} {int(max_x)},{int(min_y)} {int(max_x)},{int(max_y)} {int(min_x)},{int(max_y)}"

            if not cell_coords:
                cx1 = tx1 + (c * col_w_px)
                cy1 = ty1 + (r * row_h_px)
                cx2 = cx1 + (cspan * col_w_px)
                cy2 = cy1 + (rspan * row_h_px)
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

            tl_elem = ET.SubElement(cell_elem, f"{{{ns}}}TextLine")
            tl_elem.set("id", f"tl_{cell_id}")
            tl_c_elem = ET.SubElement(tl_elem, f"{{{ns}}}Coords")
            tl_c_elem.set("points", cell_coords)
            te_elem = ET.SubElement(tl_elem, f"{{{ns}}}TextEquiv")
            uni_elem = ET.SubElement(te_elem, f"{{{ns}}}Unicode")
            uni_elem.text = escape(str(val)) if val is not None else ""

        return table_region_elem

    col_widths = table.get("columns", {}).get("width", [])
    sections = table.get("sections", {})
    current_y = ty1
    row_counter = 0
    section_order = ["note", "header", "data", "summary"]

    for sec_name in section_order:
        rows = sections.get(sec_name, [])
        if not rows:
            continue

        for row in rows:
            if not row:
                continue

            try:
                row_height_ratio = float(row[-1])
                cells_content = row[:-1]
            except (ValueError, IndexError):
                row_height_ratio = 0.05
                cells_content = row

            row_height_px = row_height_ratio * table_height_px
            row_y1 = current_y
            row_y2 = current_y + row_height_px

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

            for col_start_idx, span, content in merged_cells:
                cell_w_ratio = 0.0
                for k in range(span):
                    eff_idx = col_start_idx + k
                    if eff_idx < len(col_widths):
                        cell_w_ratio += col_widths[eff_idx]
                    else:
                        rem_cols = max(1, len(cells_content) - len(col_widths))
                        cell_w_ratio += max(0.01, (1.0 - sum(col_widths)) / rem_cols)

                cell_w_px = cell_w_ratio * table_width_px
                pre_w_ratio = sum(col_widths[:col_start_idx])
                cell_x1 = tx1 + (pre_w_ratio * table_width_px)
                cell_x2 = cell_x1 + cell_w_px

                sub_rows = content if isinstance(content, list) else [content]
                num_sub = len(sub_rows) if len(sub_rows) > 0 else 1
                sub_h = row_height_px / num_sub

                for s_idx, sub_content in enumerate(sub_rows):
                    cy1 = row_y1 + (s_idx * sub_h)
                    cy2 = cy1 + sub_h
                    cell_coords = f"{int(cell_x1)},{int(cy1)} {int(cell_x2)},{int(cy1)} {int(cell_x2)},{int(cy2)} {int(cell_x1)},{int(cy2)}"
                    cell_id = f"{table_id}_r{row_counter}_c{col_start_idx}_s{s_idx}"

                    cell_elem = ET.SubElement(table_region_elem, f"{{{ns}}}TableCell")
                    cell_elem.set("id", cell_id)
                    cell_elem.set("row", str(row_counter))
                    cell_elem.set("col", str(col_start_idx))
                    cell_elem.set("rowSpan", "1")
                    cell_elem.set("colSpan", str(span))

                    cell_c_elem = ET.SubElement(cell_elem, f"{{{ns}}}Coords")
                    cell_c_elem.set("points", cell_coords)

                    corner_elem = ET.SubElement(cell_elem, f"{{{ns}}}CornerPts")
                    corner_elem.text = "0 1 2 3"

                    tl_elem = ET.SubElement(cell_elem, f"{{{ns}}}TextLine")
                    tl_elem.set("id", f"tl_{cell_id}")
                    tl_c_elem = ET.SubElement(tl_elem, f"{{{ns}}}Coords")
                    tl_c_elem.set("points", cell_coords)
                    te_elem = ET.SubElement(tl_elem, f"{{{ns}}}TextEquiv")
                    uni_elem = ET.SubElement(te_elem, f"{{{ns}}}Unicode")
                    uni_elem.text = escape(str(sub_content)) if sub_content is not None else ""

            current_y += row_height_px
            row_counter += 1

    indent_xml_element(table_region_elem, level=2, space="    ")
    return table_region_elem


def save_table_json_file(
    page: Any,
    table_id: str,
    json_data: Dict[str, Any],
    image_path: Optional[Path] = None,
    output_xml_path: Optional[Path] = None,
) -> Path:
    """Writes out individual table JSON files named {filename}_{table_id}.json
    into the json/ subfolder within the image/document directory.
    """
    import json
    out_dir = None
    stem = None

    if output_xml_path is not None:
        out_dir = Path(output_xml_path).parent
        stem = Path(output_xml_path).stem
    elif page is not None and getattr(page, "filename", None):
        p_path = Path(page.filename)
        stem = p_path.stem
        out_dir = p_path.parent
    elif image_path is not None:
        p_path = Path(image_path)
        stem = p_path.stem
        out_dir = p_path.parent
    else:
        stem = "table"
        out_dir = Path.cwd()

    filename = f"{stem}_{table_id}.json"
    json_dir = out_dir / "json"
    json_path = json_dir / filename
    json_str = json.dumps(json_data, indent=2, ensure_ascii=False)

    try:
        json_dir.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json_str, encoding="utf-8")
        logging.info("[table_json] saved table JSON -> %s", json_path)
    except Exception as exc:
        logging.warning("[table_json] could not write table JSON file %s: %s", json_path, exc)

    return json_path


def replace_table_region_by_id(
    page: Any,
    table_id: str,
    table_data: Dict[str, Any],
    offset: Tuple[int, int] = (0, 0),
    snippet_dim: Optional[Tuple[int, int]] = None,
) -> bool:
    """Finds existing <TableRegion id="{table_id}"> in page.root, constructs updated XML table element,
    replaces old element in-place by ID, and reloads page regions.
    """
    if page is None or getattr(page, "root", None) is None:
        return False

    ns = getattr(page, "ns", "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15")
    old_elem = None

    for tr in page.root.iter(f"{{{ns}}}TableRegion"):
        if tr.get("id") == table_id:
            old_elem = tr
            break

    if old_elem is None:
        for tr in page.root.iter():
            if str(tr.tag).endswith("TableRegion") and tr.get("id") == table_id:
                old_elem = tr
                break

    if old_elem is None:
        all_trs = list(page.root.iter(f"{{{ns}}}TableRegion"))
        if not all_trs:
            all_trs = [tr for tr in page.root.iter() if str(tr.tag).endswith("TableRegion")]
        if all_trs:
            old_elem = all_trs[0]

    img_w, img_h = 1000, 1000
    if snippet_dim:
        img_w, img_h = snippet_dim
    elif hasattr(page, "filename") and page.filename and Path(page.filename).exists():
        try:
            with Image.open(page.filename) as img:
                img_w, img_h = img.size
        except Exception:
            pass

    effective_offset = offset
    effective_dim = (img_w, img_h)

    existing_cells_map = {}
    if old_elem is not None:
        coords_child = old_elem.find(f"{{{ns}}}Coords")
        if coords_child is None:
            for child in old_elem.iter():
                if str(child.tag).endswith("Coords"):
                    coords_child = child
                    break

        if coords_child is not None and coords_child.get("points"):
            pts_tokens = coords_child.get("points").split()
            xs = [float(p.split(",")[0]) for p in pts_tokens if "," in p]
            ys = [float(p.split(",")[1]) for p in pts_tokens if "," in p]
            if xs and ys:
                old_xmin, old_xmax = min(xs), max(xs)
                old_ymin, old_ymax = min(ys), max(ys)
                old_w = max(1.0, old_xmax - old_xmin)
                old_h = max(1.0, old_ymax - old_ymin)
                if offset == (0, 0) or snippet_dim is None:
                    effective_offset = (int(old_xmin), int(old_ymin))
                    effective_dim = (int(old_w), int(old_h))

        for cell in old_elem.iter(f"{{{ns}}}TableCell"):
            try:
                r = int(cell.get("row", 0))
                c = int(cell.get("col", 0))
            except (ValueError, TypeError):
                continue
            c_elem = cell.find(f"{{{ns}}}Coords")
            if c_elem is None:
                for child in cell.iter():
                    if str(child.tag).endswith("Coords"):
                        c_elem = child
                        break
            if c_elem is not None and c_elem.get("points"):
                existing_cells_map[(r, c)] = c_elem.get("points")

    new_elem = build_table_region_element(
        table_data,
        ns=ns,
        img_width=effective_dim[0],
        img_height=effective_dim[1],
        offset=effective_offset,
        override_id=table_id,
        existing_cells_map=existing_cells_map if existing_cells_map else None,
    )

    if old_elem is not None:
        parent = old_elem.getparent()
        if parent is not None:
            idx = parent.index(old_elem)
            parent.remove(old_elem)
            parent.insert(idx, new_elem)
            if hasattr(page, "load_regions"):
                page.load_regions()
            return True

    page_elem = page.root.find(f"{{{ns}}}Page")
    if page_elem is None:
        page_elem = page.root
    page_elem.append(new_elem)
    if hasattr(page, "load_regions"):
        page.load_regions()
    return True


def table_xml_to_json(
    table_region: Any,
    offset: Tuple[int, int] = (0, 0),
    snippet_dim: Optional[Tuple[int, int]] = None,
) -> Dict[str, Any]:
    """Converts an existing TableRegion object into structured JSON for LLM input,
    scaling coordinates relative to (0..1000) inside the snippet bounding box.
    """
    table_id = getattr(table_region, "id", None)
    if not table_id and hasattr(table_region, "get_id"):
        table_id = table_region.get_id()
    if not table_id and hasattr(table_region, "get"):
        table_id = table_region.get("id")
    table_id = table_id or "t0"

    pts = None
    if hasattr(table_region, "polygon") and table_region.polygon:
        try:
            pts = list(table_region.polygon.exterior.coords)
        except Exception:
            pts = None
    if not pts and hasattr(table_region, "get_coordinates"):
        coord_str = table_region.get_coordinates(returntype="string")
        if coord_str:
            pts = []
            for tok in coord_str.split():
                if "," in tok:
                    x, y = tok.split(",")
                    pts.append((float(x), float(y)))

    x_off, y_off = offset
    snip_w, snip_h = snippet_dim if snippet_dim else (1000, 1000)

    if pts:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)

        rel_ymin = int(max(0.0, min(1000.0, (ymin - y_off) / snip_h * 1000)))
        rel_xmin = int(max(0.0, min(1000.0, (xmin - x_off) / snip_w * 1000)))
        rel_ymax = int(max(0.0, min(1000.0, (ymax - y_off) / snip_h * 1000)))
        rel_xmax = int(max(0.0, min(1000.0, (xmax - x_off) / snip_w * 1000)))
        box_2d = [rel_ymin, rel_xmin, rel_ymax, rel_xmax]
    else:
        box_2d = [0, 0, 1000, 1000]

    cells = getattr(table_region, "tablecells", [])
    if not cells and hasattr(table_region, "findall"):
        cells = table_region.findall(".//TableCell")
        if not cells:
            cells = table_region.findall(".//{*}TableCell")

    cells_list = []
    max_row_idx = 0
    max_col_idx = 0

    for cell in cells:
        r, c = 0, 0
        rspan, cspan = 1, 1

        if hasattr(cell, "xml_element") and cell.xml_element is not None:
            r = int(cell.xml_element.get("row", 0))
            c = int(cell.xml_element.get("col", 0))
            rspan = int(cell.xml_element.get("rowSpan", cell.xml_element.get("rowspan", 1)))
            cspan = int(cell.xml_element.get("colSpan", cell.xml_element.get("colspan", 1)))
        elif hasattr(cell, "get"):
            r = int(cell.get("row", 0))
            c = int(cell.get("col", 0))
            rspan = int(cell.get("rowSpan", cell.get("rowspan", 1)))
            cspan = int(cell.get("colSpan", cell.get("colspan", 1)))
        else:
            r = int(getattr(cell, "row", 0))
            c = int(getattr(cell, "col", 0))
            rspan = int(getattr(cell, "rowSpan", getattr(cell, "rowspan", 1)))
            cspan = int(getattr(cell, "colSpan", getattr(cell, "colspan", 1)))

        max_row_idx = max(max_row_idx, r + rspan)
        max_col_idx = max(max_col_idx, c + cspan)

        txt = ""
        if hasattr(cell, "textlines") and cell.textlines:
            lines = []
            for tl in cell.textlines:
                if hasattr(tl, "get_text"):
                    t = tl.get_text()
                    if t:
                        lines.append(t)
                elif hasattr(tl, "xml_element") and tl.xml_element is not None:
                    uni = tl.xml_element.find(".//{*}Unicode")
                    if uni is not None and uni.text:
                        lines.append(uni.text)
            txt = "\n".join(lines)
        elif hasattr(cell, "findall") and cell.findall(".//{*}TextLine"):
            lines = []
            for tl in cell.findall(".//{*}TextLine"):
                uni = tl.find(".//{*}Unicode")
                if uni is not None and uni.text:
                    lines.append(uni.text)
            txt = "\n".join(lines)
        elif hasattr(cell, "xml_element") and cell.xml_element is not None:
            uni = cell.xml_element.find(".//{*}Unicode")
            if uni is not None and uni.text:
                txt = uni.text
        elif hasattr(cell, "find"):
            uni = cell.find(".//{*}Unicode")
            if uni is None:
                uni = cell.find(".//Unicode")
            if uni is not None and uni.text:
                txt = uni.text

        cells_list.append({
            "row": r,
            "col": c,
            "rowspan": rspan,
            "colspan": cspan,
            "value": txt
        })

    return {
        "id": table_id,
        "box_2d": box_2d,
        "rows": max_row_idx,
        "cols": max_col_idx,
        "cells": cells_list
    }


def table_xml_to_html(table_region: Any, offset: Tuple[int, int] = (0, 0), snippet_dim: Optional[Tuple[int, int]] = None) -> str:
    """Converts a TableRegion (PAGE XML element, model object, or dict) to a pretty-printed HTML <table> string representation.
    """
    if isinstance(table_region, dict):
        table_data = table_region
    else:
        table_data = table_xml_to_json(table_region, offset=offset, snippet_dim=snippet_dim)

    table_id = table_data.get("id", "t0")
    cells = table_data.get("cells", [])

    if not cells:
        return f'<table id="{escape(str(table_id))}"/>'

    # Group cells by row index
    rows_dict: Dict[int, List[Dict[str, Any]]] = {}
    for cell in cells:
        r = int(cell.get("row", 0))
        rows_dict.setdefault(r, []).append(cell)

    html_lines = [f'<table id="{escape(str(table_id))}">']

    for r_idx in sorted(rows_dict.keys()):
        row_cells = sorted(rows_dict[r_idx], key=lambda c: int(c.get("col", 0)))
        html_lines.append("  <tr>")
        for cell in row_cells:
            rspan = int(cell.get("rowspan", cell.get("rowSpan", 1)))
            cspan = int(cell.get("colspan", cell.get("colSpan", 1)))
            val = cell.get("value", cell.get("text", cell.get("content", "")))

            span_attrs = ""
            if rspan > 1:
                span_attrs += f' rowspan="{rspan}"'
            if cspan > 1:
                span_attrs += f' colspan="{cspan}"'

            escaped_val = escape(str(val)) if val is not None else ""
            html_lines.append(f'    <td{span_attrs}>{escaped_val}</td>')
        html_lines.append("  </tr>")

    html_lines.append("</table>")
    return "\n".join(html_lines)


# Alias
table2html = table_xml_to_html


def replace_table_region_from_html(
    page: Any,
    table_id: str,
    html_str: str,
    offset: Tuple[int, int] = (0, 0),
    snippet_dim: Optional[Tuple[int, int]] = None,
) -> bool:
    """Parses an HTML <table> string, retains matching <TableRegion id="{table_id}"> element in-place,
    clears its old <TableCell> children, and calculates fresh cell geometry proportionally
    from the table bounding box (matching mistral_ocr_to_page cell generation).
    """
    if page is None or getattr(page, "root", None) is None:
        return False

    from pageplus.utils.mappings.mistral_ocr import parse_html_table_grid
    from pageplus.utils.mappings.markdown_parser import clean_markdown_line
    import lxml.etree as ET

    ns = getattr(page, "ns", "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15")
    old_elem = None

    for tr in page.root.iter(f"{{{ns}}}TableRegion"):
        if tr.get("id") == table_id:
            old_elem = tr
            break

    if old_elem is None:
        for tr in page.root.iter():
            if str(tr.tag).endswith("TableRegion") and tr.get("id") == table_id:
                old_elem = tr
                break

    if old_elem is None:
        all_trs = list(page.root.iter(f"{{{ns}}}TableRegion"))
        if not all_trs:
            all_trs = [tr for tr in page.root.iter() if str(tr.tag).endswith("TableRegion")]
        if len(all_trs) == 1:
            old_elem = all_trs[0]

    if old_elem is None:
        logging.warning(f"TableRegion id={table_id} not found in Page.")
        return False

    grid_cells = parse_html_table_grid(html_str)
    if not grid_cells:
        logging.warning(f"Could not parse grid cells from HTML table for table_id={table_id}")
        return False

    target_table_id = old_elem.get("id") or table_id
    table_json_payload = {
        "id": target_table_id,
        "html": html_str,
        "cells": grid_cells,
    }
    save_table_json_file(page, target_table_id, table_json_payload)

    # Extract bounding box of TableRegion
    coords_child = old_elem.find(f"{{{ns}}}Coords")
    if coords_child is None:
        for child in old_elem.iter():
            if str(child.tag).endswith("Coords"):
                coords_child = child
                break

    img_w, img_h = 1000, 1000
    if hasattr(page, "filename") and page.filename and Path(page.filename).exists():
        try:
            with Image.open(page.filename) as img:
                img_w, img_h = img.size
        except Exception:
            pass

    bx1, by1, bx2, by2 = 0, 0, img_w, img_h

    if coords_child is not None and coords_child.get("points"):
        pts_tokens = coords_child.get("points").split()
        xs = [float(p.split(",")[0]) for p in pts_tokens if "," in p]
        ys = [float(p.split(",")[1]) for p in pts_tokens if "," in p]
        if xs and ys:
            bx1, bx2 = int(min(xs)), int(max(xs))
            by1, by2 = int(min(ys)), int(max(ys))

    t_w = max(1.0, float(bx2 - bx1))
    t_h = max(1.0, float(by2 - by1))

    max_r = max(c["row"] + c["rowSpan"] for c in grid_cells) if grid_cells else 1
    max_c = max(c["col"] + c["colSpan"] for c in grid_cells) if grid_cells else 1

    # Remove all existing TableCell elements inside old_elem
    cells_to_remove = [child for child in list(old_elem) if str(child.tag).endswith("TableCell")]
    for cell_elem in cells_to_remove:
        old_elem.remove(cell_elem)

    # Generate fresh TableCell elements based on table dimensions
    for c_idx, cell in enumerate(grid_cells):
        r_idx = cell["row"]
        col_idx = cell["col"]
        r_span = cell["rowSpan"]
        c_span = cell["colSpan"]

        cell_x1 = bx1 + (col_idx / max_c) * t_w
        cell_x2 = bx1 + ((col_idx + c_span) / max_c) * t_w
        cell_y1 = by1 + (r_idx / max_r) * t_h
        cell_y2 = by1 + ((r_idx + r_span) / max_r) * t_h

        cell_coords = f"{int(cell_x1)},{int(cell_y1)} {int(cell_x2)},{int(cell_y1)} {int(cell_x2)},{int(cell_y2)} {int(cell_x1)},{int(cell_y2)}"
        cell_id = f"{table_id}_c{c_idx}"

        cell_elem = ET.SubElement(old_elem, f"{{{ns}}}TableCell")
        cell_elem.set("id", cell_id)
        cell_elem.set("row", str(r_idx))
        cell_elem.set("col", str(col_idx))
        cell_elem.set("rowSpan", str(r_span))
        cell_elem.set("colSpan", str(c_span))

        cell_c_elem = ET.SubElement(cell_elem, f"{{{ns}}}Coords")
        cell_c_elem.set("points", cell_coords)

        corner_elem = ET.SubElement(cell_elem, f"{{{ns}}}CornerPts")
        corner_elem.text = "0 1 2 3"

        cell_lines = cell["text"].splitlines() if cell["text"] else [""]
        num_clines = max(1, len(cell_lines))
        cline_h = (cell_y2 - cell_y1) / num_clines

        for l_idx, line_str in enumerate(cell_lines):
            cleaned_line = clean_markdown_line(line_str) if line_str else ""
            ly1 = cell_y1 + (l_idx * cline_h)
            ly2 = ly1 + cline_h
            lbase = int(ly2 - cline_h * 0.2)
            l_coords = f"{int(cell_x1)},{int(ly1)} {int(cell_x2)},{int(ly1)} {int(cell_x2)},{int(ly2)} {int(cell_x1)},{int(ly2)}"
            l_base_coords = f"{int(cell_x1)},{lbase} {int(cell_x2)},{lbase}"
            line_id = f"{cell_id}_l{l_idx + 1}"

            tl_elem = ET.SubElement(cell_elem, f"{{{ns}}}TextLine")
            tl_elem.set("id", line_id)

            tl_c_elem = ET.SubElement(tl_elem, f"{{{ns}}}Coords")
            tl_c_elem.set("points", l_coords)

            base_elem = ET.SubElement(tl_elem, f"{{{ns}}}Baseline")
            base_elem.set("points", l_base_coords)

            te_elem = ET.SubElement(tl_elem, f"{{{ns}}}TextEquiv")
            uni_elem = ET.SubElement(te_elem, f"{{{ns}}}Unicode")
            uni_elem.text = escape(str(cleaned_line))

    indent_xml_element(old_elem, level=2, space="    ")

    if hasattr(page, "load_regions"):
        page.load_regions()
    return True


def table_html_to_page(
    data: Any,
    image_path: Path,
    offset: Tuple[int, int] = (0, 0),
    **kwargs,
) -> str:
    """Converts HTML table string or dictionary containing HTML table content into full PAGE XML.
    """
    from pageplus.utils.mappings.mistral_ocr import parse_html_table_grid

    html_str = ""
    if isinstance(data, str):
        html_str = data
    elif isinstance(data, dict):
        html_str = data.get("html") or data.get("content") or data.get("text") or ""
        if not html_str and "tables" in data and isinstance(data["tables"], list):
            tables = data["tables"]
            if tables and isinstance(tables[0], dict):
                html_str = tables[0].get("html") or tables[0].get("content") or ""

    grid_cells = parse_html_table_grid(html_str)

    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception:
        img_width, img_height = 1000, 1000

    page_xml_lines = page_xml_header(
        creator="PagePlus - TableHTML",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
    )

    if grid_cells:
        max_r = max(c["row"] + c["rowSpan"] for c in grid_cells)
        max_c = max(c["col"] + c["colSpan"] for c in grid_cells)
        table_id = "t0"

        page_xml_lines.append(f'        <TableRegion id="{table_id}">')
        page_xml_lines.append(f'            <Coords points="0,0 {img_width},0 {img_width},{img_height} 0,{img_height}"/>')

        cell_h = img_height / max(1, max_r)
        cell_w = img_width / max(1, max_c)

        for idx, cell in enumerate(grid_cells):
            r = cell["row"]
            c = cell["col"]
            rspan = cell["rowSpan"]
            cspan = cell["colSpan"]
            txt = cell["text"]

            cx1 = int(c * cell_w)
            cy1 = int(r * cell_h)
            cx2 = int((c + cspan) * cell_w)
            cy2 = int((r + rspan) * cell_h)

            cell_coords = f"{cx1},{cy1} {cx2},{cy1} {cx2},{cy2} {cx1},{cy2}"
            cell_id = f"{table_id}_r{r}_c{c}"

            page_xml_lines.append(f'            <TableCell id="{cell_id}" row="{r}" col="{c}" rowSpan="{rspan}" colSpan="{cspan}">')
            page_xml_lines.append(f'                <Coords points="{cell_coords}"/>')
            page_xml_lines.append('                <CornerPts>0 1 2 3</CornerPts>')
            page_xml_lines.append(f'                <TextLine id="tl_{cell_id}">')
            page_xml_lines.append(f'                    <Coords points="{cell_coords}"/>')
            page_xml_lines.append('                    <TextEquiv>')
            page_xml_lines.append(f'                        <Unicode>{escape(txt)}</Unicode>')
            page_xml_lines.append('                    </TextEquiv>')
            page_xml_lines.append('                </TextLine>')
            page_xml_lines.append('            </TableCell>')

        page_xml_lines.append('        </TableRegion>')

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)


