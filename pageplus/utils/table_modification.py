"""
Table modification utilities for PAGE XML documents.
"""

from pathlib import Path
from typing import Union, List, Optional
import lxml.etree as ET

import re

from pageplus.models.page import Page

FILLER_REGEX = re.compile(r"^[\s\-–—―‒_.:•·]*$")


def _is_empty_or_dash(txt: str) -> bool:
    """Return True if text is empty or contains only dash/punctuation filler characters."""
    if not txt:
        return True
    return bool(FILLER_REGEX.match(txt))


def _get_cell_text(cell_elem: ET.Element) -> str:
    """Return stripped text from a TableCell element."""
    unicode_elems = cell_elem.findall(".//{*}Unicode")
    if unicode_elems:
        return "\n".join(u.text.strip() for u in unicode_elems if u.text and u.text.strip())
    
    # Fallback if no Unicode elements exist in the cell
    texts = []
    for elem in cell_elem.iter():
        tag_name = ET.QName(elem.tag).localname
        if tag_name not in ("Coords", "CornerPts", "Baseline") and elem.text and elem.text.strip():
            texts.append(elem.text.strip())
    return " ".join(texts)


def _get_cell_coords(cell_elem: ET.Element) -> List[tuple]:
    """Parse Coords points from a TableCell element if available."""
    coords_elem = cell_elem.find("{*}Coords")
    if coords_elem is None:
        coords_elem = cell_elem.find(".//{*}Coords")
    if coords_elem is not None and coords_elem.get("points"):
        pts_str = coords_elem.get("points")
        coords = []
        for p in pts_str.strip().split():
            if "," in p:
                parts = p.split(",")
                try:
                    coords.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    pass
        return coords
    return []


def _combine_cell_coords(cell_elems: List[ET.Element]) -> Optional[str]:
    """Combine coordinate bounding boxes of multiple cells into a single points string."""
    all_pts = []
    for c in cell_elems:
        all_pts.extend(_get_cell_coords(c))
    if not all_pts:
        return None
    min_x = min(p[0] for p in all_pts)
    min_y = min(p[1] for p in all_pts)
    max_x = max(p[0] for p in all_pts)
    max_y = max(p[1] for p in all_pts)
    return f"{int(min_x)},{int(min_y)} {int(max_x)},{int(min_y)} {int(max_x)},{int(max_y)} {int(min_x)},{int(max_y)}"


def merge_table_rowspan_implicit_cells(page_or_xml: Union[Page, ET.Element, ET.ElementTree, str, Path]) -> bool:
    """
    Checks all tables in a PAGE XML document (or TableRegion element).
    For any merged cell with rowspan > 1 (spanning rows R..R+span-1), inspects all columns in that row range:
    - If every column in that row range has AT MOST ONE non-empty cell value (the rest being empty),
      merge the sibling cells in those columns into a single cell spanning the same rowspan.
    - If at least one column in that row range has non-empty values in more than one row,
      do not search further or merge for that row range.

    Args:
        page_or_xml: Page instance, lxml Element, ElementTree, or file path.

    Returns:
        bool: True if any modifications were made, False otherwise.
    """
    page_obj = None

    if isinstance(page_or_xml, Page):
        page_obj = page_or_xml
        root = page_obj.root
    elif isinstance(page_or_xml, (str, Path)):
        page_obj = Page(Path(page_or_xml))
        root = page_obj.root
    elif hasattr(page_or_xml, "getroot"):
        root = page_or_xml.getroot()
    elif hasattr(page_or_xml, "tag"):
        root = page_or_xml
    else:
        raise TypeError(f"Unsupported input type for page_or_xml: {type(page_or_xml)}")

    # Locate TableRegion elements
    if str(root.tag).endswith("TableRegion"):
        table_regions = [root]
    else:
        table_regions = root.findall(".//{*}TableRegion")

    modified = False

    for table_elem in table_regions:
        cell_elems = table_elem.findall("{*}TableCell")
        if not cell_elems:
            cell_elems = table_elem.findall(".//{*}TableCell")

        if not cell_elems:
            continue

        # Parse metadata for all cells
        cell_info = []
        for cell in cell_elems:
            try:
                r_val = cell.get("row") or cell.get("row_index") or 0
                c_val = cell.get("col") or cell.get("col_index") or 0
                rs_val = cell.get("rowSpan") or cell.get("rowspan") or 1
                cs_val = cell.get("colSpan") or cell.get("colspan") or 1

                r = int(r_val)
                c = int(c_val)
                rs = int(rs_val)
                cs = int(cs_val)
            except ValueError:
                continue

            txt = _get_cell_text(cell)
            is_empty = _is_empty_or_dash(txt)

            cell_info.append({
                "elem": cell,
                "row": r,
                "col": c,
                "rowSpan": rs,
                "colSpan": cs,
                "text": txt,
                "is_empty": is_empty,
            })

        # Find anchor merged cells with rowSpan > 1
        anchors = [info for info in cell_info if info["rowSpan"] > 1]
        anchors.sort(key=lambda x: (x["row"], x["col"]))

        for anchor in anchors:
            start_row = anchor["row"]
            span = anchor["rowSpan"]
            end_row = start_row + span - 1
            target_rows = set(range(start_row, start_row + span))

            # Group cells by column for cells whose row falls in target_rows
            col_cells = {}
            for info in cell_info:
                if info["row"] in target_rows:
                    col_cells.setdefault(info["col"], []).append(info)

            anchor_col_end = anchor["col"] + anchor["colSpan"]

            # Process following columns sequentially to the right of the anchor cell
            following_cols = [c for c in sorted(col_cells.keys()) if c >= anchor_col_end]

            for col_idx in following_cols:
                infos = col_cells[col_idx]
                if len(infos) <= 1:
                    # Single cell or already spanned across target_rows (e.g. anchor cell itself)
                    continue

                non_empty_count = sum(1 for info in infos if not info["is_empty"])
                has_external_overlap = any(info["row"] + info["rowSpan"] - 1 > end_row for info in infos)

                # Stop checking and merging further columns if rule is violated
                if has_external_overlap or non_empty_count > 1:
                    break

                infos.sort(key=lambda x: x["row"])
                primary_info = infos[0]

                if primary_info["row"] != start_row:
                    break

                non_empty_info = next((info for info in infos if not info["is_empty"]), None)

                # Transfer content if the non-empty text was in a row > start_row
                if non_empty_info is not None and non_empty_info != primary_info:
                    has_nonempty_te = any(str(c.tag).endswith("TextEquiv") for c in non_empty_info["elem"])
                    if has_nonempty_te:
                        for child in list(primary_info["elem"]):
                            if str(child.tag).endswith("TextEquiv"):
                                primary_info["elem"].remove(child)

                    for child in list(non_empty_info["elem"]):
                        tag_str = str(child.tag)
                        if tag_str.endswith("TextLine") or tag_str.endswith("TextEquiv"):
                            non_empty_info["elem"].remove(child)
                            primary_info["elem"].append(child)

                # Update rowSpan on primary element
                if primary_info["elem"].get("rowspan") is not None:
                    primary_info["elem"].set("rowspan", str(span))
                else:
                    primary_info["elem"].set("rowSpan", str(span))
                primary_info["rowSpan"] = span

                # Update Coords if available
                combined_coords_str = _combine_cell_coords([info["elem"] for info in infos])
                if combined_coords_str:
                    ns = table_elem.nsmap.get(None, "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15")
                    coords_child = primary_info["elem"].find("{*}Coords")
                    if coords_child is None:
                        coords_child = primary_info["elem"].find(f".//{{{ns}}}Coords")
                    if coords_child is None:
                        coords_child = ET.SubElement(primary_info["elem"], f"{{{ns}}}Coords")
                    coords_child.set("points", combined_coords_str)

                # Delete redundant cells from table_elem
                for redundant_info in infos[1:]:
                    rel = redundant_info["elem"]
                    parent = rel.getparent()
                    if parent is not None:
                        parent.remove(rel)
                    elif rel in table_elem:
                        table_elem.remove(rel)

                modified = True

    if modified and page_obj is not None:
        page_obj.load_regions()

    return modified
