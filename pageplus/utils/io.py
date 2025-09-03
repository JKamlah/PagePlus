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
                    f"JSON data in {
                        json_path.name} is not a list. Assuming list structure from values if possible, or processing top-level keys.")
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


def gemini2d_to_page(data: json, image: Path, settings: dict = None) -> str:
    try:
        with Image.open(image) as img:
            img_width, img_height = img.size
            logging.info(
                f"Image dimensions for {
                    image.name}: Width={img_width}, Height={img_height}")
    except FileNotFoundError:
        logging.error(f"Error: Image file not found at '{image}'")
    except Exception as e:
        logging.error(f"Error opening or reading image '{image}': {e}")

    _, data = gemini2d_preprocess(data, img, settings)

    page_xml_lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                      '<PcGts xmlns="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:schemaLocation="http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15 http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15/pagecontent.xsd">',
                      '    <Metadata>', '        <Creator>PagePlus</Creator>',
                      f'        <Created>{datetime.now().isoformat()}</Created>',
                      '        <Comments>Generated from Gemini-2d-JSON</Comments>', '    </Metadata>',
                      f'    <Page imageFilename="{image.name}" imageWidth="{img_width}" imageHeight="{img_height}">']

    for ridx, region_data in enumerate(data):
        region_id = f"r{ridx + 1}"
        region_coords = f"{' '.join([f"{int(x)},{int(y)}" for x,
                                    y in region_data['region_polygon']]).strip()}"
        page_xml_lines.append(f'        <TextRegion id="{region_id}">')
        page_xml_lines.append(
            f'            <Coords points="{region_coords}"/>')

        for idx, line_data in enumerate(region_data['lines']):
            # PAGE XML Coords: top-left, top-right, bottom-right, bottom-left
            page_xml_lines.append(
                f'            <TextLine id="{region_id}_l{
                    idx +
                    1}" custom=" structure {{type:{
                    line_data['line_structure_type']}}}">')
            page_xml_lines.append(
                f'                <Coords points="{
                    ' '.join(
                        [
                            f"{
                                int(x)},{
                                int(y)}" for x, y in line_data['line_polygon']]).strip()}"/>')
            page_xml_lines.append(
                f'                <Baseline points="{
                    ' '.join(
                        [
                            f"{
                                int(x)},{
                                int(y)}" for x, y in line_data['line_baseline']]).strip()}"/>')
            page_xml_lines.append('                <TextEquiv>')
            page_xml_lines.append(
                f'                    <Unicode>{
                    escape(
                        line_data['line_text'])}</Unicode>')
            page_xml_lines.append('                </TextEquiv>')
            page_xml_lines.append('            </TextLine>')
        page_xml_lines.append('        </TextRegion>')
    page_xml_lines.append('    </Page>')
    page_xml_lines.append('</PcGts>')

    final_xml_content = "\n".join(page_xml_lines)
    return final_xml_content


def gemini2d_preprocess(
    data: json,
    img: Image.Image,
    settings: dict = None
) -> Tuple[Optional[Tuple[int, int]], List[Dict[str, Any]]]:
    """
    Reads JSON bounding box data (relative 0-1000), calculates absolute line
    coordinates, splits multi-line text boxes, and computes per-region convex hulls.

    Args:
        data (json): JSON object.
        img (Image.Image): Pillow Image object.

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

            if not relative_bbox or len(relative_bbox) != 4:
                logging.warning(
                    f"Skipping entry {i} due to missing or invalid bbox: {relative_bbox}")
                continue

            ymin_rel, xmin_rel, ymax_rel, xmax_rel = relative_bbox
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
