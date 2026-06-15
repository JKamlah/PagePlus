"""Segmentation JSON → PAGE XML mapping.

Converts segmentation output (with 'regions' and 'ro') to PAGE XML.
"""
import logging
from html import escape
from pathlib import Path
from typing import Any, Dict

from PIL import Image

from pageplus.utils.mappings.mapping_utils import page_xml_header, page_xml_footer


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

    page_xml_lines = page_xml_header(
        creator="PagePlus - Segmentation",
        image_path=image_path,
        img_width=img_width,
        img_height=img_height,
    )

    # Process Reading Order
    ro_data = result.get("ro", [])
    if ro_data:
        page_xml_lines.append("        <ReadingOrder>")
        page_xml_lines.append('            <OrderedGroup id="ro_1604576329971" caption="Regions reading order">')

        group_counter = 0

        def process_ro_item(item, index, parent_indent="                "):
            nonlocal group_counter
            if isinstance(item, str):
                return f'{parent_indent}<RegionRefIndexed index="{index}" regionRef="{item}"/>'
            elif isinstance(item, list):
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
        r_box = region.get("box_2d", [0, 0, 1000, 1000])  # y1, x1, y2, x2
        r_type_raw = region.get("type", "Text").lower()
        r_content = region.get("content", "")
        r_structure = region.get("structure", "")

        # Map Type
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

        # Convert coords 0-1000 -> pixels (y1, x1, y2, x2)
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
        type_attr = ""
        if r_structure:
            custom_attr = f' custom="structure {{type:{escape(r_structure)};}}"'
            if tag_name == "TextRegion":
                type_attr = f' type="{escape(r_structure)}"'

        page_xml_lines.append(f'    <{tag_name} id="{r_id}"{type_attr}{custom_attr}>')
        page_xml_lines.append(f'        <Coords points="{coords_str}"/>')

        # Add content as TextEquiv only for TextRegion
        if tag_name in ["TextRegion"] and r_content:
             page_xml_lines.append('        <TextEquiv>')
             page_xml_lines.append(f'            <Unicode>{escape(str(r_content))}</Unicode>')
             page_xml_lines.append('        </TextEquiv>')

        page_xml_lines.append(f'    </{tag_name}>')

    page_xml_lines.extend(page_xml_footer())
    return "\n".join(page_xml_lines)
