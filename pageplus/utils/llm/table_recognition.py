import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from math import ceil

import json_repair
from PIL import Image
from google.genai import types

from pageplus.models.page import Page
from pageplus.models.table_elements import TableRegion, TableCell
from pageplus.models.text_elements import Textline, TextEquiv
from pageplus.utils.image import get_image, crop_image_by_polygon
from pageplus.utils.llm.api import GEMINIAPI
from pageplus.utils.constants import Environments
from shapely.geometry import Polygon

# Initialize Logger
logger = logging.getLogger(__name__)

class TableRecognitionStage:
    def __init__(self, api: GEMINIAPI):
        self.api = api
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        prompt_path = Path(__file__).parents[3] / "Prompt" / "TableRecognition-Prompt.txt"
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.warning(f"Prompt file not found at {prompt_path}. Using default empty prompt.")
            return ""

    def extract_tables(
        self,
        image_path: Path,
        region_polygon: Optional[Polygon] = None,
        thinking_budget: int = 0
    ) -> List[Dict[str, Any]]:
        """
        Extracts table structure from an image (or a specific region of it) using Gemini.

        Args:
            image_path: Path to the image file.
            region_polygon: Optional polygon to crop the image to.
            thinking_budget: Budget for thinking tokens (if supported).

        Returns:
            A list of table dictionaries parsed from the LLM response.
        """
        image, image_format = get_image(image_path)
        
        snippet_offset = (0, 0)

        if region_polygon:
             # Crop image if a region is specified
            image, bbox = crop_image_by_polygon(
                image, 
                region_polygon, 
                save_snippet=False,
                square_canvas=False # We don't want square canvas for tables usually
            )
            # bbox is (minx, miny, maxx, maxy) relative to the original image
            # The crop_image_by_polygon returns the snippet and the bounding box used for cropping
            # We need the offset to map back to original coordinates later.
            # However, looking at crop_image_by_polygon implementation:
            # It returns snippet and bbox. bbox is (minx, miny, maxx, maxy) in original image coords.
            snippet_offset = (bbox[0], bbox[1])
            
            # For the API call, we need to save the snippet to a temp buffer or file, 
            # but get_image logic in cli/gemini.py uses client.files.upload which needs a path.
            # Or we can send bytes inline if small enough, but Gemini usually prefers upload for images.
            # Let's save it to a temporary path or use inline data if possible.
            # The current gemini cli uses file upload. We might need to save the snippet temporarily.
            # For now, let's assume we can save it to a temp file.
            
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=f".{image_format.lower()}", delete=False) as tmp_img:
                 image.save(tmp_img.name)
                 upload_path = Path(tmp_img.name)
        else:
            upload_path = image_path

        try:
            file_upload = self.api.client().files.upload(file=upload_path)
            
            user_prompt = "Extract tables from this image."

            config = types.GenerateContentConfig(
                temperature=0.000001,
                top_p=0.000001,
                top_k=1,
                seed=123,
                response_mime_type="application/json",
                system_instruction=self.system_prompt,
            )
            
            if thinking_budget > 0:
                 config.thinking_config = types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=thinking_budget
                )

            response = self.api.client().models.generate_content(
                model=self.api.model,
                contents=[
                    types.Part.from_uri(
                        file_uri=file_upload.uri,
                        mime_type=file_upload.mime_type,
                    ),
                    user_prompt,
                ],
                config=config,
            )

            data = json_repair.repair_json(response.text, return_objects=True)
            
            # Determine image dimensions for relative scaling
            img_width, img_height = image.size

            # Post-process data to add absolute coordinates and adjust for snippet offset
            if isinstance(data, dict):
                 data = [data] # Ensure list if root is a single object (though prompt asks for root object with 'tables' list)
            
            # The prompt defines structure: { "meta": ..., "tables": [...] }
            # If json_repair returns a list, it might be the list of tables if the root was implicit, 
            # but let's handle the expected structure.
            
            tables = []
            if isinstance(data, list):
                # Maybe it returned just the tables list?
                 tables = data
            elif isinstance(data, dict):
                tables = data.get("tables", [])
            
            for table in tables:
                # Add metadata about the source image snippet for coordinate calculation
                table["_snippet_offset"] = snippet_offset
                table["_snippet_dim"] = (img_width, img_height)

            return tables

        finally:
            if region_polygon and 'upload_path' in locals() and upload_path.exists():
                upload_path.unlink() # Delete temp file

    def table_json_to_page_xml(self, tables_data: List[Dict[str, Any]], page: Page) -> None:
        """
        Converts Table JSON data into PAGE XML TableRegion and TableCell elements.
        
        Args:
            tables_data: List of table dictionaries from extract_tables.
            page: The Page object to update.
        """
        # We need to access the helper functions or use Page methods to add regions.
        # Page object has .regions.tableregions which is a list.
        # But for adding to XML tree, we usually interact with `page.root` or similar.
        # The `Page` class has `add_element` but that looks like it adds next to a given element.
        # We might need to construct the XML elements manually and append them to appropriate parent.
        # Usually regions are children of Page element.
        
        # Check if we should clear existing table regions? 
        # For now, let's append.
        
        page_elem = page.root.find(f"{{{page.ns}}}Page")
        
        for table_idx, table_data in enumerate(tables_data):
            offset_x, offset_y = table_data.get("_snippet_offset", (0, 0))
            snippet_w, snippet_h = table_data.get("_snippet_dim", (1000, 1000)) # Default to avoid div by zero if missing
            
            # 1. Create TableRegion
            # box_2d is [y1, x1, y2, x2] (0-1000 relative to snippet)
            # We need to convert to absolute coords in original image
            
            bbox_rel = table_data.get("bbox", [0, 0, 1000, 1000]) # y1, x1, y2, x2
            
            # Convert to absolute relative to snippet
            y1_abs = ceil(bbox_rel[0] * snippet_h / 1000)
            x1_abs = ceil(bbox_rel[1] * snippet_w / 1000)
            y2_abs = ceil(bbox_rel[2] * snippet_h / 1000)
            x2_abs = ceil(bbox_rel[3] * snippet_w / 1000)
            
            # Add snippet offset
            x1_final = x1_abs + offset_x
            y1_final = y1_abs + offset_y
            x2_final = x2_abs + offset_x
            y2_final = y2_abs + offset_y
            
            points_str = f"{x1_final},{y1_final} {x2_final},{y1_final} {x2_final},{y2_final} {x1_final},{y2_final}"
            
            import lxml.etree as ET
            
            # Generate ID
            import time
            timestamp = int(time.time() * 1000)
            table_id = f"Table_{timestamp}_{table_idx}"
            
            table_region_elem = ET.SubElement(page_elem, f"{{{page.ns}}}TableRegion")
            table_region_elem.set("id", table_id)
            
            # Add Coords
            coords_elem = ET.SubElement(table_region_elem, f"{{{page.ns}}}Coords")
            coords_elem.set("points", points_str)
            
            # 2. Process Cells
            # We need to calculate cell coordinates based on columns widths and row heights
            
            columns = table_data.get("columns", {})
            col_width_ratios = columns.get("width", []) # List of ratios
            # If missing, assume equal width?
            
            sections = table_data.get("sections", {})
            
            # Flatten all rows from all sections to process sequentially for Y coordinates
            # Sections order: header, data, summary? Or just iterate keys if they have order?
            # Prompt says: "note", "header", "data", "summary"
            
            section_order = ["note", "header", "data", "summary"]
            
            current_y_ratio = 0.0 # 0 to 1 relative to Table Height
            # Table height in px
            table_height_px = y2_final - y1_final
            table_width_px = x2_final - x1_final
            
            # Helper to get row height ratio
            def get_row_height_ratio(row):
                # row is [Col1, Col2, ..., HeightRatio]
                return row[-1] if isinstance(row[-1], (int, float)) else 0.1 # Default fallback
            
            # Pre-calculate absolute X boundaries for columns
            col_x_boundaries = [0]
            current_w_ratio = 0.0
            if not col_width_ratios:
                 # Attempt to infer from first row? or default
                 col_width_ratios = [1.0] # Fallback
            
            for w_ratio in col_width_ratios:
                current_w_ratio += w_ratio
                col_x_boundaries.append(int(current_w_ratio * table_width_px))
            
            # Ensure last boundary is exactly table width
            col_x_boundaries[-1] = table_width_px

            cumulative_row_idx = 0

            for section_name in section_order:
                rows = sections.get(section_name, [])
                if not rows:
                    continue
                
                for row in rows:
                    row_height_ratio = get_row_height_ratio(row)
                    row_h_px = int(row_height_ratio * table_height_px)
                    
                    row_y1_rel = int(current_y_ratio * table_height_px)
                    row_y2_rel = row_y1_rel + row_h_px
                    
                    # Absolute coords for this row (relative to page)
                    row_y1_abs = y1_final + row_y1_rel
                    row_y2_abs = y1_final + row_y2_rel
                    
                    # Process columns in this row
                    # Row content: [Col1, Col2, ..., Height]
                    # Note: Row length might not match col_width_ratios length if there are merges or inconsistent data
                    
                    content_cols = row[:-1] # Exclude height
                    
                    current_col_idx = 0
                    
                    for cell_content in content_cols:
                        if current_col_idx >= len(col_x_boundaries) - 1:
                            break # Safety break
                        
                        # Handle colspan (horizontal merge)
                        # -1 indicates generated by merge from left.
                        # But input format says: "If a cell spans from the left column into the current column, use -1 for the current column."
                        # Wait, the example says: `["Title Spanning Two Cols", -1, "Value", 0.1]`
                        # So when we encounter -1, it means the *previous* cell spanned into this one.
                        # Code-wise: we should have handled the span in the previous iteration?
                        # Or we skip creating a cell here, but we need to know the previous cell to expand it.
                        
                        if cell_content == -1:
                            # This column is part of the previous cell.
                            # We likely need to update the previous cell's x2 and colSpan.
                            # But we've already created it? 
                            # We need a reference to the last created cell in this row.
                            if 'last_cell_in_row' in locals():
                                # Update last cell
                                # New x2 is the x2 of the current column
                                # last_cell_points ...
                                # We need to update the XML element attributes and Coords
                                
                                # Let's track active cell
                                # Increase colSpan
                                last_colspan = int(last_cell_in_row.get("colSpan", "1"))
                                last_cell_in_row.set("colSpan", str(last_colspan + 1))
                                
                                # Update Coords
                                start_col_idx = int(last_cell_in_row.get("col"))
                                end_col_idx = current_col_idx
                                
                                cell_x1 = x1_final + col_x_boundaries[start_col_idx]
                                cell_x2 = x1_final + col_x_boundaries[end_col_idx + 1]
                                
                                cell_points = f"{cell_x1},{row_y1_abs} {cell_x2},{row_y1_abs} {cell_x2},{row_y2_abs} {cell_x1},{row_y2_abs}"
                                last_cell_coords.set("points", cell_points)
                            
                            current_col_idx += 1
                            continue
                        
                        # Create new Cell
                        cell_x1 = x1_final + col_x_boundaries[current_col_idx]
                        cell_x2 = x1_final + col_x_boundaries[current_col_idx + 1]
                        
                        cell_points = f"{cell_x1},{row_y1_abs} {cell_x2},{row_y1_abs} {cell_x2},{row_y2_abs} {cell_x1},{row_y2_abs}"
                        
                        cell_id = f"TableCell_{timestamp}_{table_idx}_{cumulative_row_idx}_{current_col_idx}"
                        
                        cell_elem = ET.SubElement(table_region_elem, f"{{{page.ns}}}TableCell")
                        cell_elem.set("id", cell_id)
                        cell_elem.set("row", str(cumulative_row_idx))
                        cell_elem.set("col", str(current_col_idx))
                        cell_elem.set("rowSpan", "1") # Default, vertical merge handled by content?
                        cell_elem.set("colSpan", "1")
                        
                        last_cell_in_row = cell_elem
                        
                        last_cell_coords = ET.SubElement(cell_elem, f"{{{page.ns}}}Coords")
                        last_cell_coords.set("points", cell_points)
                        
                        # Handle Content & TextLines
                        # Content can be String or Array (Nested Rows)
                        
                        if isinstance(cell_content, list):
                            # Nested Rows / Vertical Grouping
                            # cell_content is ["Sub1", "Sub2"]
                            # We need to split the cell height for these items
                            # But wait, logic says: 
                            # If Column A spans multiple rows in B...
                            # This implies THIS cell is a single cell, but the neighbor might make it look like multiple?
                            # Or does it mean this cell contains multiple lines that align with neighbors?
                            # The prompt says: 
                            # Column A's content is a String.
                            # Column B's content is an Array of strings.
                            # The Row_Height_Percent applies to the TOTAL height of this group.
                            # So Column A is one big cell (rowSpan?)
                            # Column B has implicit sub-rows.
                            
                            num_sub_rows = len(cell_content)
                            sub_row_h = (row_y2_abs - row_y1_abs) / num_sub_rows
                            
                            for sub_idx, text_item in enumerate(cell_content):
                                sub_y1 = row_y1_abs + (sub_idx * sub_row_h)
                                sub_y2 = sub_y1 + sub_row_h
                                
                                self._create_textline(
                                    parent_cell=cell_elem,
                                    text=str(text_item),
                                    page_ns=page.ns,
                                    box=(cell_x1, sub_y1, cell_x2, sub_y2),
                                    idx=sub_idx
                                )
                        else:
                            # Single content
                            self._create_textline(
                                parent_cell=cell_elem,
                                text=str(cell_content),
                                page_ns=page.ns,
                                box=(cell_x1, row_y1_abs, cell_x2, row_y2_abs),
                                idx=0
                            )

                        current_col_idx += 1
                        
                    cumulative_row_idx += 1
                    current_y_ratio += row_height_ratio

        # Re-parse or update the Page object from the modified tree if necessary
        # helper methods in Page generally work on the tree, so modifying self.root/tree is fine.

    def _create_textline(self, parent_cell, text: str, page_ns: str, box: Tuple[float, float, float, float], idx: int):
        """
        Creates a TextLine element with pseudo-coordinates inside the cell.
        """
        if not text:
            return
            
        import lxml.etree as ET
        x1, y1, x2, y2 = map(int, box)
        
        # Add some padding for textline inside cell?
        pad = 2
        lx1, ly1, lx2, ly2 = x1+pad, y1+pad, x2-pad, y2-pad
        if lx2 <= lx1 or ly2 <= ly1: 
             # Fallback if too small
             lx1, ly1, lx2, ly2 = x1, y1, x2, y2
        
        line_points = f"{lx1},{ly1} {lx2},{ly1} {lx2},{ly2} {lx1},{ly2}"
        
        # Baseline: approximated as bottom line
        baseline_points = f"{lx1},{ly2} {lx2},{ly2}"
        
        line_id = f"{parent_cell.get('id')}l{idx}"
        
        tl_elem = ET.SubElement(parent_cell, f"{{{page_ns}}}TextLine")
        tl_elem.set("id", line_id)
        tl_elem.set("custom", f"readingOrder {{index:{idx};}}")
        
        coords = ET.SubElement(tl_elem, f"{{{page_ns}}}Coords")
        coords.set("points", line_points)
        
        baseline = ET.SubElement(tl_elem, f"{{{page_ns}}}Baseline")
        baseline.set("points", baseline_points)
        
        te = ET.SubElement(tl_elem, f"{{{page_ns}}}TextEquiv")
        unicode_elem = ET.SubElement(te, f"{{{page_ns}}}Unicode")
        unicode_elem.text = text
