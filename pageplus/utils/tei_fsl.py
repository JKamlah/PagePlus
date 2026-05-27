import re
from datetime import datetime
from pathlib import Path
from typing import Optional
import lxml.etree as ET
from pageplus.models.page import Page

TEI_NS = "http://www.tei-c.org/ns/1.0"
NSMAP = {None: TEI_NS}

def append_mixed_text(parent_el: ET.Element, text: str) -> None:
    """
    Appends text to a parent element in a mixed-content layout,
    replacing any '%' character with a <gap/> element.
    Uses standard lxml element text/tail properties to keep the XML well-formed.
    """
    if not text:
        return
    
    parts = text.split("%")
    for idx, part in enumerate(parts):
        if idx > 0:
            ET.SubElement(parent_el, f"{{{TEI_NS}}}gap")
        if part:
            if len(parent_el) > 0:
                last_child = parent_el[-1]
                last_child.tail = (last_child.tail or "") + part
            else:
                parent_el.text = (parent_el.text or "") + part

def convert_pagexml_to_tei_fsl(
    xml_file_path: Path,
    werkteil: str = "Grammatik",
    editor: str = "",
    who: str = "",
    status: str = "work_in_progress"
) -> ET.ElementTree:
    """
    Converts a PAGE XML file to the TEI XML layout region format.
    """
    page = Page(xml_file_path)
    metadata = page.get_metadata()
    image_filename = page.imageFilename()
    width, height = page.page_size()
    
    # 1. Create Root TEI Element
    root = ET.Element(f"{{{TEI_NS}}}TEI", nsmap=NSMAP)
    
    # 2. Build teiHeader
    header = ET.SubElement(root, f"{{{TEI_NS}}}teiHeader")
    fileDesc = ET.SubElement(header, f"{{{TEI_NS}}}fileDesc")
    
    titleStmt = ET.SubElement(fileDesc, f"{{{TEI_NS}}}titleStmt")
    title = ET.SubElement(titleStmt, f"{{{TEI_NS}}}title")
    title.text = image_filename
    
    respStmt = ET.SubElement(titleStmt, f"{{{TEI_NS}}}respStmt")
    resp = ET.SubElement(respStmt, f"{{{TEI_NS}}}resp")
    resp.text = "Transcribed with"
    name = ET.SubElement(respStmt, f"{{{TEI_NS}}}name")
    name.text = metadata.creator or "PagePlus"
    
    publicationStmt = ET.SubElement(fileDesc, f"{{{TEI_NS}}}publicationStmt")
    ET.SubElement(publicationStmt, f"{{{TEI_NS}}}p")
    
    sourceDesc = ET.SubElement(fileDesc, f"{{{TEI_NS}}}sourceDesc")
    ET.SubElement(sourceDesc, f"{{{TEI_NS}}}p")
    
    revisionDesc = ET.SubElement(header, f"{{{TEI_NS}}}revisionDesc")
    
    created_str = metadata.created.isoformat() if isinstance(metadata.created, datetime) else str(metadata.created)
    change1 = ET.SubElement(revisionDesc, f"{{{TEI_NS}}}change", when=created_str)
    change1.text = "Creation"
    
    last_change_str = metadata.last_change.isoformat() if isinstance(metadata.last_change, datetime) else str(metadata.last_change)
    change2 = ET.SubElement(revisionDesc, f"{{{TEI_NS}}}change", when=last_change_str)
    change2.text = "Last change"
    
    if editor:
        attribs = {}
        if who:
            attribs["who"] = who
        change3 = ET.SubElement(revisionDesc, f"{{{TEI_NS}}}change", attribs)
        change3.text = editor
    
    status_n = "work in progress"
    status_text = "Bearbeitung offen"
    if status.lower().replace(" ", "_") == "done":
        status_n = "done"
        status_text = "Bearbeitung abgeschlossen"
        
    change4 = ET.SubElement(revisionDesc, f"{{{TEI_NS}}}change", type="status", n=status_n)
    change4.text = status_text
    
    # 3. Build sourceDoc
    sourceDoc = ET.SubElement(root, f"{{{TEI_NS}}}sourceDoc")
    surfaceGrp = ET.SubElement(sourceDoc, f"{{{TEI_NS}}}surfaceGrp")
    surface = ET.SubElement(surfaceGrp, f"{{{TEI_NS}}}surface", facs=f"#{image_filename}")
    
    regions = page.get_ordered_regions()
    
    # Add surfaces for layout regions under sourceDoc
    for region in regions:
        region_id = region.get_id()
        region_type = region.get_tag()
        points = region.get_coordinates(returntype="string") or ""
        
        sub_surface = ET.SubElement(surface, f"{{{TEI_NS}}}surface", {
            "{http://www.w3.org/XML/1998/namespace}id": region_id,
            "type": region_type,
            "points": points
        })
        
        lines = []
        if hasattr(region, "textlines"):
            lines = region.textlines
        elif hasattr(region, "tablecells"):
            for cell in region.tablecells:
                lines.extend(cell.textlines)
                
        for line in lines:
            line_id = line.get_id()
            line_points = line.get_coordinates(returntype="string") or ""
            baseline_points = ""
            # try to get baseline coordinates from PAGE XML
            baseline_el = line.xml_element.find(f"{{{page.ns}}}Baseline")
            if baseline_el is not None:
                baseline_points = baseline_el.attrib.get("points", "")
                
            line_text = line.get_text() or ""
            
            zone = ET.SubElement(sub_surface, f"{{{TEI_NS}}}zone", {
                "{http://www.w3.org/XML/1998/namespace}id": line_id,
                "type": "mask",
                "points": line_points
            })
            if baseline_points:
                ET.SubElement(zone, f"{{{TEI_NS}}}path", {
                    "type": "baseline",
                    "points": baseline_points
                })
            
            line_el = ET.SubElement(zone, f"{{{TEI_NS}}}line")
            line_el.text = line_text
            
    # Add graphic surface
    graphic_surface = ET.SubElement(surfaceGrp, f"{{{TEI_NS}}}surface")
    ET.SubElement(graphic_surface, f"{{{TEI_NS}}}graphic", {
        "{http://www.w3.org/XML/1998/namespace}id": image_filename,
        "url": image_filename,
        "width": f"{width}px",
        "height": f"{height}px"
    })
    
    # 4. Build text / body / milestone
    text_el = ET.SubElement(root, f"{{{TEI_NS}}}text")
    body_el = ET.SubElement(text_el, f"{{{TEI_NS}}}body")
    
    page_num = "1"
    num_matches = re.findall(r'\d+', image_filename)
    if num_matches:
        page_num = num_matches[-1]
        
    ET.SubElement(body_el, f"{{{TEI_NS}}}milestone", n=page_num, type=werkteil)
    
    # We open the main paragraph directly after the milestone
    p_el = ET.SubElement(body_el, f"{{{TEI_NS}}}p")
    ET.SubElement(p_el, f"{{{TEI_NS}}}pb", facs=image_filename)
    
    div_el = None
    
    # Add line text content with region transformations
    for region in regions:
        region_type = region.get_tag()
        lines = []
        if hasattr(region, "textlines"):
            lines = region.textlines
        elif hasattr(region, "tablecells"):
            for cell in region.tablecells:
                lines.extend(cell.textlines)
                
        # Transform 8: MainZone opens <div type="Einheit">
        if region_type == "MainZone" and div_el is None and len(lines) > 0:
            div_el = ET.SubElement(p_el, f"{{{TEI_NS}}}div", type="Einheit")
            p_el_main = ET.SubElement(div_el, f"{{{TEI_NS}}}p")
            for i, line in enumerate(lines):
                line_text = line.get_text() or ""
                append_mixed_text(p_el_main, "\n" + line_text if i != 0 else line_text)
            div_el = None
            continue
                
        if not lines:
            # Handle empty zones like GraphicZone or empty Custom/Damage zones
            if region_type == "GraphicZone":
                # Transform 7
                ET.SubElement(p_el, f"{{{TEI_NS}}}graphic")
            elif region_type == "DamageZone":
                # Transform 2
                ET.SubElement(p_el, f"{{{TEI_NS}}}gap")
            elif region_type == "CustomZone":
                # Transform 1
                ET.SubElement(p_el, f"{{{TEI_NS}}}milestone", type="Klammerkonstrukt")
            elif region_type == "DigitizationArtefactZone":
                # Transform 4
                ET.SubElement(p_el, f"{{{TEI_NS}}}milestone", type="Handschrift")
            elif region_type == "TitlePageZone":
                # Transform 12
                ET.SubElement(p_el, f"{{{TEI_NS}}}milestone", type="Titelseite")
            continue
            
        if region_type in ["RunningTitleZone", "NumberingZone:page"]:
            # Transform 5
            fw = ET.SubElement(p_el, f"{{{TEI_NS}}}fw", place="top")
            region_text = " ".join([l.get_text() or "" for l in lines])
            append_mixed_text(fw, region_text)
            
        elif region_type == "QuireMarksZone":
            # Transform 6
            fw = ET.SubElement(p_el, f"{{{TEI_NS}}}fw", place="bottom")
            region_text = " ".join([l.get_text() or "" for l in lines])
            append_mixed_text(fw, region_text)
            
        elif region_type == "MarginTextZone":
            # Transform 9
            fw = ET.SubElement(p_el, f"{{{TEI_NS}}}fw", place="margin")
            region_text = " ".join([l.get_text() or "" for l in lines])
            append_mixed_text(fw, region_text)
            
        elif region_type in ["NumberingZone", "NumberinZone"]:
            # Transform 10
            num = ET.SubElement(p_el, f"{{{TEI_NS}}}num", type="ordinal")
            region_text = " ".join([l.get_text() or "" for l in lines])
            append_mixed_text(num, region_text)
            
        elif region_type == "CustomZone":
            # Transform 1
            ET.SubElement(p_el, f"{{{TEI_NS}}}milestone", type="Klammerkonstrukt")
            for line in lines:
                line_text = line.get_text() or ""
                append_mixed_text(p_el, "\n" + line_text)
                
        elif region_type == "DamageZone":
            # Transform 2
            ET.SubElement(p_el, f"{{{TEI_NS}}}gap")
            
        elif region_type == "DigitizationArtefactZone":
            # Transform 4
            ET.SubElement(p_el, f"{{{TEI_NS}}}milestone", type="Handschrift")
            for line in lines:
                line_text = line.get_text() or ""
                append_mixed_text(p_el, "\n" + line_text)
                
        elif region_type == "GraphicZone":
            # Transform 7
            ET.SubElement(p_el, f"{{{TEI_NS}}}graphic")
            
        elif region_type == "TitlePageZone":
            # Transform 12
            ET.SubElement(p_el, f"{{{TEI_NS}}}milestone", type="Titelseite")
            
        elif region_type in ["TableZone", "TableRegion"]:
            # Transform 11
            lst = ET.SubElement(p_el, f"{{{TEI_NS}}}list")
            ET.SubElement(lst, f"{{{TEI_NS}}}cb")
            for line in lines:
                item = ET.SubElement(lst, f"{{{TEI_NS}}}item")
                line_text = line.get_text() or ""
                append_mixed_text(item, line_text)
                
        elif region_type == "MainZone":
            # Transform 8 content: just lines appended to the active paragraph
            for line in lines:
                line_text = line.get_text() or ""
                append_mixed_text(p_el, "\n" + line_text)
                
        else:
            # Default fallback for any other region structure type: just lines
            for line in lines:
                line_text = line.get_text() or ""
                append_mixed_text(p_el, "\n" + line_text)
                
    return ET.ElementTree(root)
