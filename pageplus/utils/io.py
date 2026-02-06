import json
import logging
from collections import defaultdict
from datetime import datetime
from html import escape
from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import langcodes
from lxml import etree as ET
from PIL import Image
from shapely.geometry import MultiPoint


def setxml(el, name, val):
    el.set(name, str(val))


def xywh_from_points(points_str):
    """
    Given a string of points (e.g. "x1,y1 x2,y2 ..."), compute a bounding box.
    Returns a dict with keys: 'x', 'y', 'w', 'h'.
    """
    pts = []
    for pt in points_str.split():
        try:
            x, y = map(int, pt.split(','))
            pts.append((x, y))
        except Exception:
            continue
    if not pts:
        return {'x': 0, 'y': 0, 'w': 0, 'h': 0}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    minx, miny = min(xs), min(ys)
    maxx, maxy = max(xs), max(ys)
    return {'x': minx, 'y': miny, 'w': maxx - minx, 'h': maxy - miny}


def set_alto_xywh_from_coords(reg_alto, reg_page, classes=None):
    if classes is None:
        classes = ['HEIGHT', 'WIDTH', 'HPOS', 'VPOS']
    # Assume PAGE element has a child <Coords> with attribute "points"
    coords = reg_page.get_coordinates(returntype='string')
    if coords is None:
        return
    xywh = xywh_from_points(coords)
    mapping = {'HEIGHT': 'h', 'WIDTH': 'w', 'HPOS': 'x', 'VPOS': 'y'}
    for k_alto, k_xywh in mapping.items():
        if k_alto in classes:
            setxml(reg_alto, k_alto, str(xywh[k_xywh]))


def set_alto_shape_from_coords(reg_alto, reg_page):
    # Create a Shape element with a Polygon using the points from PAGE.
    coords = reg_page.get_coordinates(returntype='string')
    shape = ET.SubElement(reg_alto, 'Shape')
    polygon = ET.SubElement(shape, 'Polygon')
    setxml(polygon, 'POINTS', coords)


def set_alto_id_from_page_id(reg_alto, reg_page, suffix=''):
    # Assumes the PAGE element has an attribute "id" (or "ID")
    setxml(reg_alto, 'ID', reg_page.get_id() + suffix)


def set_alto_lang_from_page_lang(
        reg_alto,
        reg_page,
        attribute_name='LANG',
        langcode=True):
    # Try several attribute names for language.
    lang = reg_page.get_language()
    if lang:
        if langcode:
            lang = langcodes.find(lang).to_alpha3()
        setxml(reg_alto, attribute_name, lang)


def get_nth_textequiv(reg_page, textequiv_index, textequiv_fallback_strategy):
    """
    Return the text from a PAGE element's TextEquiv/Unicode subelement.
    """
    textequivs = reg_page.findall(".//TextEquiv")
    if not textequivs:
        if textequiv_fallback_strategy == 'raise':
            raise ValueError(
                "PAGE element '%s' has no TextEquivs" %
                (reg_page.get("id") or ""))
        return ''
    for te in textequivs:
        if te.get("index") and int(te.get("index")) == textequiv_index:
            unicode_el = te.find("Unicode")
            if unicode_el is not None:
                return unicode_el.text or ""
    if textequiv_fallback_strategy == 'raise':
        raise ValueError(
            "PAGE element '%s' has no TextEquiv index %d" %
            (reg_page.get("id") or "", textequiv_index))
    elif textequiv_fallback_strategy == 'first':
        unicode_el = textequivs[0].find("Unicode")
        return unicode_el.text if unicode_el is not None else ""
    else:  # 'last'
        unicode_el = textequivs[-1].find("Unicode")
        return unicode_el.text if unicode_el is not None else ""


def contains(el, bbox):
    """
    Check if the bounding box (minx, miny, maxx, maxy) is contained within
    the element's coordinates (assumed in attributes HPOS, VPOS, WIDTH, HEIGHT).
    """
    minx1, miny1, maxx1, maxy1 = bbox
    minx2 = int(el.get('HPOS'))
    miny2 = int(el.get('VPOS'))
    maxx2 = minx2 + int(el.get('WIDTH'))
    maxy2 = miny2 + int(el.get('HEIGHT'))
    if minx1 < minx2:
        return False
    if maxx1 > maxx2:
        return False
    if miny1 < miny2:
        return False
    if maxy1 > maxy2:
        return False
    return True


# Mapping of PAGE region types to ALTO block types.
REGION_PAGE_TO_ALTO = {
    "TextRegion": "TextBlock",
    "SeparatorRegion": "GraphicalElement",
    "GraphicRegion": "Illustration",
    "LineDrawingRegion": "Illustration",
    "ChartRegion": "Illustration",
    "ImageRegion": "Illustration",
    "TableRegion": "ComposedBlock",
    # Other types can be added if needed.
    "MathsRegion": None,
    "ChemRegion": None,
    "MusicRegion": None,
    "AdvertRegion": None,
    "NoiseRegion": None,
    "UnknownRegion": None,
    "CustomRegion": None,
}

HYPHEN_CHARS = ['-', '⸗', '=', '¬', '­']


# Assume these helper functions exist elsewhere or define them:
# (You might need to adjust imports based on your project structure)
# from your_module import transform_inputs, collect_xml_files # Adjust as
# needed
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

# --- Generate PAGE XML Content (remains the same) ---


def gemini2d_to_page(
    data: dict,
    image: Path,
    settings: dict = None,
    use_bbox_fallback: bool = None
) -> str:
    """
    Converts Gemini 2D JSON data to PAGE XML format.

    Args:
        data: JSON object containing bounding box and text data.
        image: Path to the image file.
        settings: Optional settings dict (can include 'use_bbox_fallback').
        use_bbox_fallback: If True, use previous bbox with offset for entries without bbox.
                           Default is None (reads from global Settings).
                           Can be overridden by settings dict.

    Returns:
        String containing the full PAGE XML.
    """
    try:
        with Image.open(image) as img:
            img_width, img_height = img.size
            logging.info(f"Image dimensions for {image.name}: Width={img_width}, Height={img_height}")
    except FileNotFoundError:
        logging.error(f"Error: Image file not found at '{image}'")
        return ""
    except Exception as e:
        logging.error(f"Error opening or reading image '{image}': {e}")
        return ""

    # Determine the final use_bbox_fallback value with priority:
    # 1. Direct parameter (if not None)
    # 2. Settings dict
    # 3. Global Settings class
    if use_bbox_fallback is None:
        # Check if provided in settings dict
        if settings and 'use_bbox_fallback' in settings:
            use_bbox_fallback = settings['use_bbox_fallback']
        else:
            # Fall back to global Settings
            try:
                from pageplus.gui.utils.settings import Settings
                global_settings = Settings()
                fallback_str = global_settings.get('USE_BBOX_FALLBACK', 'True')
                use_bbox_fallback = fallback_str.lower() in ('true', '1', 'yes', 'on')
            except Exception:
                # If Settings class is not available, default to True
                use_bbox_fallback = True

    # Merge settings dict with the determined value
    if settings is None:
        settings = {}
    settings_for_preprocess = settings.copy()
    settings_for_preprocess['use_bbox_fallback'] = use_bbox_fallback

    _, data = gemini2d_preprocess(data, img, settings_for_preprocess)

    page_xml_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15 '
        'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">',
        "    <Metadata>",
        "        <Creator>PagePlus</Creator>",
        f"        <Created>{datetime.now().isoformat()}</Created>",
        "        <Comments>Generated from Gemini-2d-JSON</Comments>",
        "    </Metadata>",
        f'    <Page imageFilename="{image.name}" imageWidth="{img_width}" imageHeight="{img_height}">'
    ]

    for ridx, region_data in enumerate(data):
        region_id = f"r{ridx+1}"
        region_coords = " ".join(f"{int(x)},{int(y)}" for x, y in region_data["region_polygon"])
        page_xml_lines.append(f'        <TextRegion id="{region_id}">')
        page_xml_lines.append(f'            <Coords points="{region_coords}"/>')

        for idx, line_data in enumerate(region_data["lines"]):
            line_id = f"{region_id}_l{idx+1}"
            line_type = line_data["line_structure_type"]
            line_coords = " ".join(f"{int(x)},{int(y)}" for x, y in line_data["line_polygon"])
            baseline_coords = " ".join(f"{int(x)},{int(y)}" for x, y in line_data["line_baseline"])
            line_text = escape(line_data["line_text"])

            page_xml_lines.append(f'            <TextLine id="{line_id}" custom=" structure {{type:{line_type}}}">')
            page_xml_lines.append(f'                <Coords points="{line_coords}"/>')
            page_xml_lines.append(f'                <Baseline points="{baseline_coords}"/>')
            page_xml_lines.append("                <TextEquiv>")
            page_xml_lines.append(f'                    <Unicode>{line_text}</Unicode>')
            page_xml_lines.append("                </TextEquiv>")
            page_xml_lines.append("            </TextLine>")

        page_xml_lines.append("        </TextRegion>")

    page_xml_lines.append("    </Page>")
    page_xml_lines.append("</PcGts>")

    final_xml_content = "\n".join(page_xml_lines)
    return final_xml_content


def gemini2d_preprocess(
    data: json,
    img: Image.Image,
    settings: dict = None,
    use_bbox_fallback: bool = True
) -> Tuple[Optional[Tuple[int, int]], List[Dict[str, Any]]]:
    """
    Reads JSON bounding box data (relative 0-1000), calculates absolute line
    coordinates, splits multi-line text boxes, and computes per-region convex hulls.

    Args:
        data (json): JSON object.
        img (Image.Image): Pillow Image object.
        settings (dict): Optional settings dict.
        use_bbox_fallback (bool): If True, use previous bbox with offset for entries without bbox.
                                   Default is True.

    Returns:
        Tuple:
            - (img_width, img_height) or None
            - A list of region blocks:
                {
                    'region': region index,
                    'region_polygon': convex hull as list of (x, y) tuples,
                    'lines': [line dicts with polygon and baseline]
                }
    """
    region_data = defaultdict(list)  # region index -> list of line dicts

    try:
        img_width, img_height = img.size
        img_dimensions = (img_width, img_height)
    except Exception as e:
        logging.error(f"Error reading image size: {e}")
        return None, []

    bbox_key = 'box_2d'
    primary_text_key = 'text'
    secondary_text_key = 'text_content'
    structure_type_key = 'type'
    secondary_structure_type_key = 'tag'

    # Check settings for bbox_fallback preference
    if settings and 'use_bbox_fallback' in settings:
        use_bbox_fallback = settings['use_bbox_fallback']

    # Track the last valid bbox for entries without bounding boxes
    last_valid_bbox = None
    height_offset = 30  # pixels to add to height for entries without bbox

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            logging.warning(f"Skipping non-dictionary item at index {i}")
            continue
        try:
            relative_bbox = entry.get(bbox_key)

            text = entry.get(
                primary_text_key,
                "") or entry.get(
                secondary_text_key,
                "")
            if not text:
                for key, value in entry.items():
                    if "text" in key.lower() and value:
                        text = value
                        break
                else:
                    text = ""

            structure_type = entry.get(
                structure_type_key,
                "paragraph") or entry.get(
                secondary_structure_type_key,
                "paragraph")

            # Handle missing or invalid bbox by using previous valid bbox with offset
            if not relative_bbox or len(relative_bbox) != 4:
                if use_bbox_fallback and last_valid_bbox is not None:
                    # Use previous bbox with +30 height offset
                    logging.info(
                        f"Entry {i} missing bbox, using previous bbox with +{height_offset}px height offset")
                    ymin_rel, xmin_rel, ymax_rel, xmax_rel = last_valid_bbox

                    # Convert to pixels to check canvas bounds
                    ymax_abs_check = ceil(ymax_rel * img_height / 1000)
                    new_ymax_abs = ymax_abs_check + height_offset

                    # Only add offset if within image canvas
                    if new_ymax_abs < img_height:
                        # Add offset in relative coordinates (0-1000 scale)
                        height_offset_rel = (height_offset / img_height) * 1000
                        ymax_rel = min(1000, ymax_rel + height_offset_rel)
                    # else: use exact same coordinates (no offset)
                else:
                    if use_bbox_fallback:
                        logging.warning(
                            f"Skipping entry {i} due to missing bbox and no previous bbox available")
                    else:
                        logging.warning(
                            f"Skipping entry {i} due to missing or invalid bbox (bbox_fallback is disabled)")
                    continue
            else:
                ymin_rel, xmin_rel, ymax_rel, xmax_rel = relative_bbox

            # Store this as the last valid bbox for future entries
            last_valid_bbox = (ymin_rel, xmin_rel, ymax_rel, xmax_rel)
            xmin_abs = ceil(xmin_rel * img_width / 1000)
            ymin_abs = ceil(ymin_rel * img_height / 1000)
            xmax_abs = ceil(xmax_rel * img_width / 1000)
            ymax_abs = ceil(ymax_rel * img_height / 1000)

            box_width = xmax_abs - xmin_abs
            box_height = ymax_abs - ymin_abs

            if box_height < 0:
                logging.warning(
                    f"Skipping entry {i} due to negative box height: {relative_bbox}")
                continue

            lines = str(text).split('\n')
            if not lines:
                continue

            region_index = entry.get('region', 0)

            if len(lines) == 1:
                if entry.get(
                        'direction', 'horizontal') == 'vertical' or (
                        box_width < box_height and len(text) > 3):
                    x_center = (xmin_abs + xmax_abs) // 2
                    polygon = [(xmin_abs, ymin_abs), (xmax_abs, ymin_abs),
                               (xmax_abs, ymax_abs), (xmin_abs, ymax_abs)]
                    baseline = [(x_center, ymin_abs), (x_center, ymax_abs)]
                else:
                    y_center = (ymin_abs + ymax_abs) // 2
                    polygon = [(xmin_abs, ymin_abs), (xmax_abs, ymin_abs),
                               (xmax_abs, ymax_abs), (xmin_abs, ymax_abs)]
                    baseline = [(xmin_abs, y_center), (xmax_abs, y_center)]

                region_data[region_index].append({
                    'region_index': region_index,
                    'line_index': i,
                    'line_part': 1,
                    'line_text': lines[0],
                    'line_polygon': polygon,
                    'line_baseline': baseline,
                    'line_structure_type': structure_type,
                })

            else:
                if entry.get(
                        'direction', 'horizontal') == 'vertical' or (
                        box_width < box_height and len(lines) < 3):
                    line_box_width = box_width / len(lines)

                    for line_part, line_text in enumerate(lines):
                        line_xmin = xmin_abs + line_part * line_box_width
                        line_xmax = line_xmin + line_box_width
                        if line_part == len(lines) - 1:
                            line_xmax = xmax_abs

                        x_center = int((line_xmin + line_xmax) / 2)
                        polygon = [(ceil(line_xmin), ymin_abs), (ceil(line_xmax), ymin_abs),
                                   (ceil(line_xmax), ymax_abs), (ceil(line_xmin), ymax_abs)]
                        baseline = [(x_center, ymin_abs), (x_center, ymax_abs)]

                        region_data[region_index].append({
                            'region_index': region_index,
                            'line_index': i,
                            'line_part': line_part,
                            'line_text': line_text,
                            'line_polygon': polygon,
                            'line_baseline': baseline,
                            'line_structure_type': structure_type,
                        })
                else:
                    line_box_height = box_height / len(lines)

                    for line_part, line_text in enumerate(lines):
                        line_ymin = ymin_abs + line_part * line_box_height
                        line_ymax = line_ymin + line_box_height
                        if line_part == len(lines) - 1:
                            line_ymax = ymax_abs

                        y_center = int((line_ymin + line_ymax) / 2)
                        final_ymin = ceil(line_ymin)
                        final_ymax = ceil(line_ymax)

                        polygon = [(xmin_abs, final_ymin), (xmax_abs, final_ymin),
                                   (xmax_abs, final_ymax), (xmin_abs, final_ymax)]
                        baseline = [(xmin_abs, y_center), (xmax_abs, y_center)]

                        region_data[region_index].append({
                            'region_index': region_index,
                            'line_index': i,
                            'line_part': line_part,
                            'line_text': line_text,
                            'line_polygon': polygon,
                            'line_baseline': baseline,
                            'line_structure_type': structure_type,
                        })
        except Exception as e:
            logging.warning(f"Skipping entry {i} due to unexpected error: {e}")

    # --- Build Final Region Output with Convex Hulls ---
    region_output = []

    for region_index, lines in region_data.items():
        points = [pt for line in lines for pt in line['line_polygon']]
        region_polygon = None

        if len(points) >= 3:
            try:
                hull = MultiPoint(points).convex_hull
                if not hull.is_empty:
                    region_polygon = list(hull.exterior.coords)
            except Exception as e:
                logging.warning(
                    f"Failed to compute convex hull for region {region_index}: {e}")

        region_output.append({
            'region': region_index,
            'region_polygon': region_polygon,
            'lines': lines
        })

    return img_dimensions, region_output


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
        # Fallback to meta if available, or error
        if isinstance(data, dict) and "meta" in data and "dim" in data["meta"]:
            img_height, img_width = data["meta"]["dim"] # JSON is [h, w] usually
        else:
             return ""

    page_xml_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15 '
        'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">',
        "    <Metadata>",
        "        <Creator>PagePlus - TableRecognition</Creator>",
        f"        <Created>{datetime.now().isoformat()}</Created>",
        "    </Metadata>",
        f'    <Page imageFilename="{image_path.name}" imageWidth="{img_width}" imageHeight="{img_height}">'
    ]

    # Handle if data is just the 'tables' list or the root object
    tables = []
    if isinstance(data, list):
        tables = data
    elif isinstance(data, dict):
        tables = data.get("tables", [])
    
    x_off, y_off = offset

    for t_idx, table in enumerate(tables):
        table_id = table.get("id", f"t{t_idx}")
        # Table BBox (0-1000)
        # JSON format: box_2d [y1, x1, y2, x2] (Gemini style usually) or [min_y, min_x, max_y, max_x] as per prompt
        # Prompt says: `box_2d` (y1, x1, y2, x2)
        
        t_bbox = table.get("box_2d", [0, 0, 1000, 1000])
        # Validate bbox
        if len(t_bbox) != 4:
            t_bbox = [0, 0, 1000, 1000]

        # Convert table bbox to pixels
        # y1, x1, y2, x2 -> pixels
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
        # col_widths are ratios 0-1.
        
        # Process Sections
        sections = table.get("sections", {})
        
        # We need a running Y for rows within the table
        current_y = ty1
        
        row_counter = 0

        # Order: header -> data -> summary (or just iterate sections if ordered dict, but specific keys are safer)
        # Prompt says: "note" (above cols), "header", "data", "summary"
        section_order = ["note", "header", "data", "summary"]
        
        for sec_name in section_order:
            rows = sections.get(sec_name, [])
            if not rows:
                continue
                
            for row in rows:
                # Row format: [Col1, Col2, ..., HeightRatio]
                if not row: continue
                
                # Height is the last element
                try:
                    row_height_ratio = float(row[-1])
                    cells_content = row[:-1]
                except (ValueError, IndexError):
                    # Fallback
                    row_height_ratio = 0.05
                    cells_content = row

                row_height_px = row_height_ratio * table_height_px
                
                # Calculate Cell Coordinates
                current_x = tx1
                
                # Iterate through cells (columns)
                # Note: "note" section might not respect columns? 
                # Prompt: "note" (additional text, if its above all columns, still handle as the other sections and indicate merged cells with -1)
                # So we treat it as row.
                
                # We need to handle horizontal spans (-1)
                # We group contents by their starting column index
                
                merged_cells = [] # list of (start_col_idx, span, content)
                
                skip_indices = set()
                
                display_col_idx = 0
                for c_idx, content in enumerate(cells_content):
                    if c_idx in skip_indices:
                        continue
                        
                    # Check for span
                    span = 1
                    # Look ahead for -1
                    for next_c in range(c_idx + 1, len(cells_content)):
                        if cells_content[next_c] == -1:
                            span += 1
                            skip_indices.add(next_c)
                        else:
                            break
                    
                    merged_cells.append((display_col_idx, span, content))
                    display_col_idx += span
                
                # Now generate cells
                row_y1 = current_y
                row_y2 = current_y + row_height_px
                
                # Map logical columns to physical geometry
                # We need cumulative widths
                
                for col_start_idx, span, content in merged_cells:
                    # Calculate X Width based on col_widths
                    # If col_widths not enough, assume equal distribution of remaining?
                    
                    # Get width for this span
                    cell_w_ratio = 0
                    for k in range(span):
                        eff_idx = col_start_idx + k
                        if eff_idx < len(col_widths):
                            cell_w_ratio += col_widths[eff_idx]
                        else:
                            # Fallback if no width info: 1.0 / len(cells_content) ?
                            # Or remaining width / remaining cols?
                            # Simple fallback:
                            cell_w_ratio += (1.0 - sum(col_widths)) / (len(cells_content) - len(col_widths)) if (len(cells_content) - len(col_widths)) > 0 else 0.1

                    cell_w_px = cell_w_ratio * table_width_px
                    
                    # Calculate X1
                    # Access cumulative width before col_start_idx
                    pre_w_ratio = sum(col_widths[:col_start_idx])
                    # Warning: this assumes col_widths covers everything.
                    
                    cell_x1 = tx1 + (pre_w_ratio * table_width_px)
                    cell_x2 = cell_x1 + cell_w_px
                    
                    # Handle Vertical Grouping (Nested Rows)
                    # Content can be String or List
                    sub_rows = []
                    if isinstance(content, list):
                        sub_rows = content
                    else:
                        sub_rows = [content]
                    
                    num_sub = len(sub_rows)
                    if num_sub == 0: num_sub = 1
                    sub_h = row_height_px / num_sub
                    
                    for s_idx, sub_content in enumerate(sub_rows):
                        # Coordinates for this specific cell (or sub-cell)
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
                
                # End Row Loop
                current_y += row_height_px
                row_counter += 1

        page_xml_lines.append("        </TableRegion>")

    page_xml_lines.append("    </Page>")
    page_xml_lines.append("</PcGts>")
    
    return "\n".join(page_xml_lines)


def segmentation_to_page(result: Dict[str, Any], image_path: Path) -> str:
    """
    Converts Segmentation JSON output (with 'regions' and 'ro') to PAGE XML.
    
    Args:
        result: JSON data containing 'regions' and 'ro'.
        image_path: Path to the source image.
        
    Returns:
        String containing the full PAGE XML.
    """
    try:
        with Image.open(image_path) as img:
            img_width, img_height = img.size
    except Exception as e:
        logging.error(f"Error reading image dimensions: {e}")
        return ""

    page_xml_lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15 '
        'http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">',
        "    <Metadata>",
        "        <Creator>PagePlus - Segmentation</Creator>",
        f"        <Created>{datetime.now().isoformat()}</Created>",
        "    </Metadata>",
        f'    <Page imageFilename="{image_path.name}" imageWidth="{img_width}" imageHeight="{img_height}">'
    ]

    # Process Reading Order
    ro_data = result.get("ro", [])
    if ro_data:
        page_xml_lines.append("        <ReadingOrder>")
        page_xml_lines.append('            <OrderedGroup id="ro_1604576329971" caption="Regions reading order">')
        
        # Flatten and index the reading order
        # The PROMPT says ro can be ["r0", ["r1", "r2"], ...]
        # Simple implementation: flatten everything into one ordered group for basic compatibility?
        # Or preserve groups? PageXML allows nested OrderedGroups.
        # Let's try to preserve the structure if it's nested list.
        
        group_counter = 0
        
        def process_ro_item(item, index, parent_indent="                "):
            nonlocal group_counter
            if isinstance(item, str):
                # It's a region ref
                return f'{parent_indent}<RegionRefIndexed index="{index}" regionRef="{item}"/>'
            elif isinstance(item, list):
                # It's a group (e.g. valid reading order group, maybe columns or lines)
                group_id = f"ro_group_{group_counter}"
                group_counter += 1
                lines = []
                lines.append(f'{parent_indent}<OrderedGroup id="{group_id}" caption="Group {group_counter}" index="{index}">')
                for sub_idx, sub_item in enumerate(item):
                    lines.append(process_ro_item(sub_item, sub_idx, parent_indent + "    "))
                lines.append(f'{parent_indent}</OrderedGroup>')
                return "\n".join(lines)
            return ""

        for idx, item in enumerate(ro_data):
            page_xml_lines.append(process_ro_item(item, idx))
            
        page_xml_lines.append("            </OrderedGroup>")
        page_xml_lines.append("        </ReadingOrder>")

    # Process Regions
    regions = result.get("regions", [])
    for region in regions:
        r_id = region.get("id", f"r{regions.index(region)}")
        r_box = region.get("box_2d", [0, 0, 1000, 1000]) # y1, x1, y2, x2
        r_type_raw = region.get("type", "Text").lower()
        r_content = region.get("content", "")
        r_structure = region.get("structure", "")
        
        # Map Type
        # Common PageXML Types: TextRegion, ImageRegion, TableRegion, SeparatorRegion, GraphicRegion, etc.
        tag_name = "TextRegion"
        if "table" in r_type_raw:
            tag_name = "TableRegion"
        elif "image" in r_type_raw or "figure" in r_type_raw:
            tag_name = "ImageRegion"
        elif "separator" in r_type_raw:
            tag_name = "SeparatorRegion"
        elif "formula" in r_type_raw or "math" in r_type_raw:
            tag_name = "MathsRegion"
        elif "chart" in r_type_raw:
            tag_name = "ChartRegion"
        
        # Convert coords 0-1000 -> pixels
        # y1, x1, y2, x2
        ymin, xmin, ymax, xmax = r_box
        
        # Clip to 0-1000 range just in case
        ymin = max(0, min(1000, ymin))
        xmin = max(0, min(1000, xmin))
        ymax = max(0, min(1000, ymax))
        xmax = max(0, min(1000, xmax))
        
        abs_ymin = int((ymin / 1000) * img_height)
        abs_xmin = int((xmin / 1000) * img_width)
        abs_ymax = int((ymax / 1000) * img_height)
        abs_xmax = int((xmax / 1000) * img_width)
        
        # Create a simple box polygon
        coords_str = f"{abs_xmin},{abs_ymin} {abs_xmax},{abs_ymin} {abs_xmax},{abs_ymax} {abs_xmin},{abs_ymax}"
        
        # Construct Element
        custom_attr = ""
        if r_structure:
            custom_attr = f' custom="structure {{type:{escape(r_structure)};}}"'
            
        page_xml_lines.append(f'    <{tag_name} id="{r_id}"{custom_attr}>')
        page_xml_lines.append(f'        <Coords points="{coords_str}"/>')
        
        # Add content as TextEquiv only for TextRegion and TableRegion (though Table usually has structure)
        # Assuming "content" is the text content
        if tag_name in ["TextRegion"] and r_content:
             page_xml_lines.append('        <TextEquiv>')
             page_xml_lines.append(f'            <Unicode>{escape(str(r_content))}</Unicode>')
             page_xml_lines.append('        </TextEquiv>')
             
        page_xml_lines.append(f'    </{tag_name}>')

    page_xml_lines.append("    </Page>")
    page_xml_lines.append("</PcGts>")

    return "\n".join(page_xml_lines)
