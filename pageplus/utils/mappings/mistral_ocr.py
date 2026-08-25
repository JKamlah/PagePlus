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

# Reverse mapping of PAGE-XML structure attribute / tag to Mistral block type
PAGE_STRUCTURE_TO_MISTRAL_TYPE: Dict[str, str] = {
    # Titles & Headings
    "heading": "title",
    "title": "title",
    "doc_title": "title",
    "paragraph_title": "title",
    # Headers & Footers
    "header": "header",
    "header_image": "header",
    "footer": "footer",
    "footer_image": "footer",
    "page-number": "footer",
    "catch-word": "footer",
    # Captions
    "caption": "caption",
    "table_caption": "caption",
    "figure_caption": "caption",
    "figure_title": "caption",
    "vision_footnote": "caption",
    # Lists
    "list": "list",
    "list-label": "list",
    # Equations & Formulas
    "equation": "equation",
    "formula": "equation",
    "display_formula": "equation",
    "inline_formula": "equation",
    # Code & Algorithms
    "code": "code",
    "algorithm": "code",
    # References & Footnotes
    "references": "references",
    "reference": "references",
    "reference_content": "references",
    "footnote": "references",
    "footnote-continued": "references",
    "endnote": "references",
    "toc": "references",
    "toc-entry": "references",
    # Marginalia & Aside
    "marginal": "aside_text",
    "marginalia": "aside_text",
    "aside_text": "aside_text",
    "floating": "aside_text",
    # Signatures
    "signature": "signature",
    "signature-mark": "signature",
    # Tables
    "table": "table",
    # Images & Graphics
    "image": "image",
    "figure": "image",
    "chart": "image",
    "seal": "image",
    "stamp": "image",
    # Paragraphs & Body Text
    "paragraph": "text",
    "text": "text",
    "content": "text",
    "abstract": "text",
    "vertical_text": "text",
    "credit": "text",
    "drop-capital": "text",
    "other": "text",
}


def get_mistral_block_type_for_region(region_elem_or_obj: Any, localname: str = "") -> str:
    """Determine Mistral OCR block type from PAGE XML region element or model object.

    The OCRTextBlock type is derived from the region's structure type or tag.
    """
    if not localname:
        if hasattr(region_elem_or_obj, "get_localname"):
            localname = region_elem_or_obj.get_localname()
        elif hasattr(region_elem_or_obj, "tag"):
            import lxml.etree as ET
            localname = ET.QName(region_elem_or_obj.tag).localname
        else:
            localname = region_elem_or_obj.__class__.__name__

    if localname == "TableRegion":
        return "table"
    if localname in ("ImageRegion", "GraphicRegion", "ChartRegion", "LineDrawingRegion"):
        return "image"
    if localname == "MathsRegion":
        return "equation"

    # Extract tag / structure type
    tag_type = ""
    custom_str = ""
    if hasattr(region_elem_or_obj, "get_tag"):
        tag_type = region_elem_or_obj.get_tag() or ""
    elif hasattr(region_elem_or_obj, "attrib"):
        tag_type = region_elem_or_obj.attrib.get("type", "")
        custom_str = region_elem_or_obj.attrib.get("custom", "")

    if not tag_type and custom_str:
        from pageplus.utils.converter import custom_to_dict
        cdict = custom_to_dict(custom_str)
        tag_type = cdict.get("structure", {}).get("type", "")

    tag_clean = str(tag_type).strip().lower() if tag_type else ""
    if tag_clean in PAGE_STRUCTURE_TO_MISTRAL_TYPE:
        return PAGE_STRUCTURE_TO_MISTRAL_TYPE[tag_clean]

    if tag_clean in MISTRAL_TYPE_MAP:
        return tag_clean

    if tag_clean:
        return tag_clean

    return "text"


def page_to_mistral_ocr(
    page: Any,
    page_index: int = 0,
    extract_page_only: bool = False,
    **kwargs,
) -> Dict[str, Any]:
    """Convert PAGE XML (Page object, Path, XML file string, or XML element/tree) to Mistral Document OCR response JSON.

    Maps:
    - TextRegion / TextLine elements into OCRTextBlock objects with merged line breaks (\\n).
    - TableRegion elements into HTML <table> strings via `table_xml_to_html`, referenced in `blocks` and stored in `tables`.
    - ImageRegion / GraphicRegion elements into image blocks and `images` list.
    - Preserves ReadingOrder and pixel bounding boxes (top_left_x, top_left_y, bottom_right_x, bottom_right_y).

    Args:
        page: Page model instance, Path to PAGE XML, XML string, or lxml element/tree.
        page_index: 0-indexed page index in the OCR response (default 0).
        extract_page_only: If True, returns only the single OCRPageObject dict.
                           If False, returns full Mistral OCR response dict {"pages": [...]}.

    Returns:
        Dictionary following the Mistral Document OCR response JSON schema.
    """
    import lxml.etree as ET
    from pageplus.models.page import Page
    from pageplus.utils.mappings.table_json import table_xml_to_html

    page_obj: Optional[Page] = None
    root_elem: Optional[ET.Element] = None
    ns = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2019-07-15"

    if isinstance(page, Page):
        page_obj = page
        root_elem = page.root
        ns = page.ns or ns
    elif isinstance(page, Path):
        if page.is_file():
            try:
                page_obj = Page(page)
                root_elem = page_obj.root
                ns = page_obj.ns or ns
            except Exception:
                pass
        if root_elem is None and page.is_file():
            try:
                xml_text = page.read_text(encoding="utf-8")
                root_elem = ET.fromstring(xml_text.encode("utf-8"))
                if hasattr(root_elem, "nsmap") and None in root_elem.nsmap:
                    ns = root_elem.nsmap[None]
            except Exception as e:
                logging.error(f"Error parsing XML file {page}: {e}")
    elif isinstance(page, str):
        is_xml_content = page.strip().startswith("<")
        if not is_xml_content and len(page) < 4096:
            try:
                p = Path(page)
                if p.is_file():
                    try:
                        page_obj = Page(p)
                        root_elem = page_obj.root
                        ns = page_obj.ns or ns
                    except Exception:
                        pass
                    if root_elem is None:
                        xml_text = p.read_text(encoding="utf-8")
                        root_elem = ET.fromstring(xml_text.encode("utf-8"))
                        if hasattr(root_elem, "nsmap") and None in root_elem.nsmap:
                            ns = root_elem.nsmap[None]
            except OSError:
                pass

        if root_elem is None:
            try:
                root_elem = ET.fromstring(page.encode("utf-8"))
                if hasattr(root_elem, "nsmap") and None in root_elem.nsmap:
                    ns = root_elem.nsmap[None]
            except Exception as e:
                logging.error(f"Error parsing XML string for Mistral OCR: {e}")
    elif hasattr(page, "getroot"):
        root_elem = page.getroot()
        if hasattr(root_elem, "nsmap") and None in root_elem.nsmap:
            ns = root_elem.nsmap[None]
    elif isinstance(page, ET._Element) or hasattr(page, "tag"):
        root_elem = page
        if hasattr(root_elem, "nsmap") and None in root_elem.nsmap:
            ns = root_elem.nsmap[None]

    if root_elem is None:
        empty_page = {
            "index": page_index,
            "markdown": "",
            "dimensions": {"dpi": 72, "height": 1000, "width": 1000},
            "blocks": [],
            "tables": [],
            "images": [],
        }
        return empty_page if extract_page_only else {
            "pages": [empty_page],
            "model": "mistral-ocr-latest",
            "usage_info": {"pages_processed": 1},
        }

    # Locate Page element
    page_el = root_elem.find(f".//{{{ns}}}Page")
    if page_el is None:
        page_el = root_elem.find(".//{*}Page")
    if page_el is None and ET.QName(root_elem.tag).localname == "Page":
        page_el = root_elem

    img_width = 1000
    img_height = 1000
    if page_el is not None:
        try:
            img_width = int(page_el.attrib.get("imageWidth", 1000))
            img_height = int(page_el.attrib.get("imageHeight", 1000))
        except (ValueError, TypeError):
            pass
    elif page_obj is not None:
        try:
            w, h = page_obj.page_size()
            img_width = int(w or 1000)
            img_height = int(h or 1000)
        except Exception:
            pass

    # Collect reading order IDs
    ordered_ids: List[str] = []
    reading_order = root_elem.find(f".//{{{ns}}}ReadingOrder")
    if reading_order is None:
        reading_order = root_elem.find(".//{*}ReadingOrder")
    if reading_order is not None:
        for group in reading_order.iterfind(".//{*}OrderedGroup"):
            refs = group.findall("./{*}RegionRefIndexed")
            for ref in sorted(refs, key=lambda r: int(r.attrib.get("index", 0))):
                r_id = ref.attrib.get("regionRef")
                if r_id and r_id not in ordered_ids:
                    ordered_ids.append(r_id)

    # Valid region tags
    region_tags = {
        "TextRegion", "TableRegion", "ImageRegion", "GraphicRegion",
        "SeparatorRegion", "ChartRegion", "MathsRegion", "LineDrawingRegion",
        "NoiseRegion", "AdvertRegion", "MusicRegion", "ChemRegion",
        "MapRegion", "CustomRegion", "UnknownRegion"
    }

    all_region_elements: List[ET._Element] = []
    regions_by_id: Dict[str, ET._Element] = {}

    search_container = page_el if page_el is not None else root_elem
    for child in search_container.iterfind(".//{*}*"):
        local_tag = ET.QName(child.tag).localname
        if local_tag in region_tags:
            parent = child.getparent()
            parent_tag = ET.QName(parent.tag).localname if parent is not None else ""
            if parent_tag in ("TableCell", "TextRegion", "TableRegion") and local_tag not in ("TableCell",):
                continue
            if child not in all_region_elements:
                all_region_elements.append(child)
                c_id = child.attrib.get("id")
                if c_id:
                    regions_by_id[c_id] = child

    ordered_elements: List[ET._Element] = []
    seen_ids = set()

    for r_id in ordered_ids:
        if r_id in regions_by_id:
            ordered_elements.append(regions_by_id[r_id])
            seen_ids.add(r_id)

    for el in all_region_elements:
        c_id = el.attrib.get("id")
        if c_id not in seen_ids:
            ordered_elements.append(el)
            if c_id:
                seen_ids.add(c_id)

    blocks: List[Dict[str, Any]] = []
    tables: List[Dict[str, Any]] = []
    images: List[Dict[str, Any]] = []
    markdown_parts: List[str] = []

    for idx, r_elem in enumerate(ordered_elements):
        local_tag = ET.QName(r_elem.tag).localname
        region_id = r_elem.attrib.get("id", f"r{idx}")

        # Extract bounding box from Coords
        pts: List[Tuple[float, float]] = []
        coords_el = r_elem.find("./{*}Coords")
        if coords_el is None:
            coords_el = r_elem.find(f"./{{{ns}}}Coords")
        if coords_el is not None and "points" in coords_el.attrib:
            for tok in coords_el.attrib["points"].split():
                if "," in tok:
                    try:
                        x_str, y_str = tok.split(",")
                        pts.append((float(x_str), float(y_str)))
                    except ValueError:
                        pass

        if pts:
            min_x = min(p[0] for p in pts)
            min_y = min(p[1] for p in pts)
            max_x = max(p[0] for p in pts)
            max_y = max(p[1] for p in pts)
        else:
            min_x, min_y, max_x, max_y = 0.0, 0.0, float(img_width), float(img_height)

        tl_x = max(0, min(img_width, int(round(min_x))))
        tl_y = max(0, min(img_height, int(round(min_y))))
        br_x = max(tl_x + 1, min(img_width, int(round(max_x))))
        br_y = max(tl_y + 1, min(img_height, int(round(max_y))))

        b_type = get_mistral_block_type_for_region(r_elem, local_tag)

        if local_tag == "TableRegion" or b_type == "table":
            tbl_ref_id = f"{region_id}.html" if not region_id.endswith(".html") else region_id

            table_obj = None
            if page_obj and hasattr(page_obj, "regions") and page_obj.regions.tableregions:
                for tr in page_obj.regions.tableregions:
                    if tr.get_id() == region_id:
                        table_obj = tr
                        break

            target_table = table_obj if table_obj is not None else r_elem
            html_table = table_xml_to_html(target_table)

            tables.append({
                "id": tbl_ref_id,
                "format": "html",
                "html": html_table,
            })

            table_block = {
                "type": "table",
                "top_left_x": tl_x,
                "top_left_y": tl_y,
                "bottom_right_x": br_x,
                "bottom_right_y": br_y,
                "table_id": tbl_ref_id,
                "content": f"[{tbl_ref_id}]({tbl_ref_id})",
            }
            blocks.append(table_block)
            markdown_parts.append(f"[{tbl_ref_id}]({tbl_ref_id})")

        elif local_tag in ("ImageRegion", "GraphicRegion", "ChartRegion", "LineDrawingRegion") or b_type == "image":
            custom_str = r_elem.attrib.get("custom", "")
            img_id = None
            if custom_str:
                import re
                m = re.search(r'image\s*\{\s*id\s*:\s*([^;]+)\s*;?\s*\}', custom_str)
                if m:
                    img_id = m.group(1).strip()
            if not img_id:
                img_id = f"img_{region_id}"

            images.append({
                "id": img_id,
                "top_left_x": tl_x,
                "top_left_y": tl_y,
                "bottom_right_x": br_x,
                "bottom_right_y": br_y,
            })

            image_block = {
                "type": "image",
                "top_left_x": tl_x,
                "top_left_y": tl_y,
                "bottom_right_x": br_x,
                "bottom_right_y": br_y,
                "image_id": img_id,
                "content": f"![{img_id}]({img_id})",
            }
            blocks.append(image_block)
            markdown_parts.append(f"![{img_id}]({img_id})")

        else:
            lines: List[str] = []
            for tl in r_elem.findall(".//{*}TextLine"):
                uni_el = tl.find(".//{*}Unicode")
                if uni_el is not None and uni_el.text is not None:
                    lines.append(uni_el.text)
                else:
                    lines.append("")

            if not lines:
                uni_el = r_elem.find(".//{*}Unicode")
                if uni_el is not None and uni_el.text:
                    lines = uni_el.text.splitlines()

            content_text = "\n".join(lines)

            text_block = {
                "type": b_type,
                "top_left_x": tl_x,
                "top_left_y": tl_y,
                "bottom_right_x": br_x,
                "bottom_right_y": br_y,
                "content": content_text,
            }
            blocks.append(text_block)

            if b_type == "title":
                markdown_parts.append(f"# {content_text}")
            elif b_type == "equation":
                markdown_parts.append(f"$${content_text}$$")
            elif b_type == "code":
                markdown_parts.append(f"```\n{content_text}\n```")
            else:
                markdown_parts.append(content_text)

    page_object = {
        "index": page_index,
        "markdown": "\n\n".join(markdown_parts),
        "dimensions": {
            "dpi": 72,
            "height": img_height,
            "width": img_width,
        },
        "blocks": blocks,
        "tables": tables,
        "images": images,
    }

    if extract_page_only:
        return page_object

    return {
        "pages": [page_object],
        "model": "mistral-ocr-latest",
        "usage_info": {
            "pages_processed": 1,
        },
    }


def page_to_mistral_page_object(page: Any, page_index: int = 0, **kwargs) -> Dict[str, Any]:
    """Helper to convert PAGE XML to a single Mistral OCRPageObject dictionary."""
    return page_to_mistral_ocr(page, page_index=page_index, extract_page_only=True, **kwargs)


page_xml_to_mistral_ocr = page_to_mistral_ocr


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
            html_table = ""
            if table_id_key:
                t_key_str = str(table_id_key)
                html_table = tables_by_id.get(t_key_str, "")
                if not html_table:
                    if t_key_str.endswith(".html"):
                        html_table = tables_by_id.get(t_key_str[:-5], "")
                    else:
                        html_table = tables_by_id.get(f"{t_key_str}.html", "")
            if not html_table and block.get("content"):
                c_str = str(block.get("content"))
                import re
                m_link = re.search(r'\[([^\]]+)\]\(([^)]+)\)', c_str)
                if m_link:
                    ref_key = m_link.group(2)
                    html_table = tables_by_id.get(ref_key, "")
                    if not html_table and ref_key.endswith(".html"):
                        html_table = tables_by_id.get(ref_key[:-5], "")
                if not html_table and "<table" in c_str.lower():
                    html_table = c_str
            if not html_table and len(tables_by_id) == 1:
                html_table = next(iter(tables_by_id.values()))

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
