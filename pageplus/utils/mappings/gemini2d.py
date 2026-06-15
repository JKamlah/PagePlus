"""Gemini 2D JSON → PAGE XML mapping.

Converts bounding-box + text data produced by Gemini-style VLMs into PAGE XML.
"""
import json
import logging
from collections import defaultdict
from html import escape
from math import ceil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image
from shapely.geometry import MultiPoint

from pageplus.utils.mappings.mapping_utils import page_xml_header, page_xml_footer


def gemini2d_to_page(
    data: dict,
    image: Path,
    settings: dict = None,
    use_bbox_fallback: bool = None
) -> str:
    """Converts Gemini 2D JSON data to PAGE XML format."""
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

    if use_bbox_fallback is None:
        if settings and 'use_bbox_fallback' in settings:
            use_bbox_fallback = settings['use_bbox_fallback']
        else:
            try:
                from pageplus.gui.utils.settings import Settings
                global_settings = Settings()
                fallback_str = global_settings.get('USE_BBOX_FALLBACK', 'True')
                use_bbox_fallback = fallback_str.lower() in ('true', '1', 'yes', 'on')
            except Exception:
                use_bbox_fallback = True

    if settings is None:
        settings = {}
    settings_for_preprocess = settings.copy()
    settings_for_preprocess['use_bbox_fallback'] = use_bbox_fallback

    _, data = gemini2d_preprocess(data, img, settings_for_preprocess)

    page_xml_lines = page_xml_header(
        creator="PagePlus",
        image_path=image,
        img_width=img_width,
        img_height=img_height,
        comment="Generated from Gemini-2d-JSON",
    )

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

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)


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

    Returns:
        Tuple of (img_width, img_height) or None, and a list of region blocks.
    """
    region_data = defaultdict(list)

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

    if settings and 'use_bbox_fallback' in settings:
        use_bbox_fallback = settings['use_bbox_fallback']

    last_valid_bbox = None
    height_offset = 30

    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            logging.warning(f"Skipping non-dictionary item at index {i}")
            continue
        try:
            relative_bbox = entry.get(bbox_key)

            # Normalize wrapped bbox+label format
            inline_label: Optional[str] = None
            if (
                isinstance(relative_bbox, (list, tuple))
                and len(relative_bbox) == 2
                and isinstance(relative_bbox[0], (list, tuple))
                and len(relative_bbox[0]) == 4
            ):
                inner, maybe_label = relative_bbox[0], relative_bbox[1]
                relative_bbox = list(inner)
                if isinstance(maybe_label, str):
                    inline_label = maybe_label

            text = entry.get(primary_text_key, "") or entry.get(secondary_text_key, "")
            if not text and inline_label:
                text = inline_label
            if not text:
                for key, value in entry.items():
                    if "text" in key.lower() and value:
                        text = value
                        break
                else:
                    text = ""

            structure_type = entry.get(
                structure_type_key, "paragraph") or entry.get(
                secondary_structure_type_key, "paragraph")

            if not relative_bbox or len(relative_bbox) != 4:
                if use_bbox_fallback and last_valid_bbox is not None:
                    logging.info(
                        f"Entry {i} missing bbox, using previous bbox with +{height_offset}px height offset")
                    ymin_rel, xmin_rel, ymax_rel, xmax_rel = last_valid_bbox
                    ymax_abs_check = ceil(ymax_rel * img_height / 1000)
                    new_ymax_abs = ymax_abs_check + height_offset
                    if new_ymax_abs < img_height:
                        height_offset_rel = (height_offset / img_height) * 1000
                        ymax_rel = min(1000, ymax_rel + height_offset_rel)
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

            last_valid_bbox = (ymin_rel, xmin_rel, ymax_rel, xmax_rel)
            xmin_abs = ceil(xmin_rel * img_width / 1000)
            ymin_abs = ceil(ymin_rel * img_height / 1000)
            xmax_abs = ceil(xmax_rel * img_width / 1000)
            ymax_abs = ceil(ymax_rel * img_height / 1000)

            box_width = xmax_abs - xmin_abs
            box_height = ymax_abs - ymin_abs

            if box_height < 0:
                logging.warning(f"Skipping entry {i} due to negative box height: {relative_bbox}")
                continue

            lines = str(text).split('\n')
            if not lines:
                continue

            region_index = entry.get('region', 0)

            if len(lines) == 1:
                if entry.get('direction', 'horizontal') == 'vertical' or (
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
                if entry.get('direction', 'horizontal') == 'vertical' or (
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
                            'region_index': region_index, 'line_index': i,
                            'line_part': line_part, 'line_text': line_text,
                            'line_polygon': polygon, 'line_baseline': baseline,
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
                            'region_index': region_index, 'line_index': i,
                            'line_part': line_part, 'line_text': line_text,
                            'line_polygon': polygon, 'line_baseline': baseline,
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
                logging.warning(f"Failed to compute convex hull for region {region_index}: {e}")
        region_output.append({
            'region': region_index,
            'region_polygon': region_polygon,
            'lines': lines
        })

    return img_dimensions, region_output
