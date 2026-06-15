import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from PIL import Image
from pageplus.utils.llm.settings import LLMSettings
from pageplus.utils.constants import Environments
from pageplus.utils.mappings import table_json_to_page
import json_repair
from google.genai import types

class TableRecognitionStage:
    def __init__(self, prompt_path: Optional[str] = None, api_key: Optional[str] = None):
        self.prompt_path = prompt_path
        self.llm_api = LLMSettings(Environments.GEMINI)
        if api_key:
            self.llm_api.api_key = api_key
            
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        if self.prompt_path:
            path = Path(self.prompt_path)
            if path.exists():
                return path.read_text(encoding='utf-8')
        return ""

    def process(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        crop_bbox: Optional[List[int]] = None,
        thinking_budget: int = 0
    ) -> Dict[str, Any]:
        """
        Process an image (or crop) for table recognition.
        
        Args:
            image_path: Path to the image file.
            output_dir: Directory to save output (JSON/XML).
            crop_bbox: Optional [ymin, xmin, ymax, xmax] to crop before sending.
            thinking_budget: Token budget for reasoning models.
            
        Returns:
            Dict containing success status, output path, and usage stats.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return {"success": False, "error": f"Image not found: {image_path}"}

        try:
            # Prepare Image
            if crop_bbox:
                # crop_bbox is [ymin, xmin, ymax, xmax] (Gemini style) or [xmin, ymin, xmax, ymax]?
                # The prompt uses box_2d (y1, x1, y2, x2). 
                # Let's assume input crop_bbox is [ymin, xmin, ymax, xmax] relative to 1000 or pixels? 
                # Ideally pixels [xmin, ymin, xmax, ymax] for PIL crop.
                # IMPLEMENTATION DECISION: Input crop_bbox should be pixels [xmin, ymin, xmax, ymax].
                with Image.open(image_path) as img:
                    image_to_process = img.crop(crop_bbox)
                    # We might want to save this temporary crop or pass existing bytes
                    # For now, let's just assume we handle full page or handle cropping internally if needed.
                    # But the API expects file upload. 
                    # If cropping, we need to save temp file.
                    temp_crop_path = output_dir / f"crop_{image_path.name}" if output_dir else Path(f"crop_{image_path.name}")
                    image_to_process.save(temp_crop_path)
                    target_image_path = temp_crop_path
            else:
                target_image_path = image_path

            # Call Gemini
            file_upload = self.llm_api.client().files.upload(file=target_image_path)
            
            user_prompt = "<|input|>\n" # Standard user trigger
            
            response = self.llm_api.client().models.generate_content(
                model=self.llm_api.model,
                contents=[
                    types.Part.from_uri(
                        file_uri=file_upload.uri,
                        mime_type=file_upload.mime_type,
                    ),
                    user_prompt,
                ],
                config=types.GenerateContentConfig(
                    temperature=0.0, # Deterministic
                    response_mime_type="application/json",
                    system_instruction=self.system_prompt,
                    thinking_config=types.ThinkingConfig(
                        include_thoughts=False if thinking_budget == 0 else True,
                        thinking_budget=thinking_budget
                    ) if "2.5" in self.llm_api.model else None # Only for 2.5 models?
                ),
            )

            # Parse Output
            json_output = json_repair.repair_json(response.text, return_objects=True)
            
            # Save JSON
            if output_dir:
                output_dir = Path(output_dir)
                output_dir.mkdir(parents=True, exist_ok=True)
                json_path = output_dir / "json" / image_path.with_suffix(".json").name
                json_path.parent.mkdir(parents=True, exist_ok=True)
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(json_output, f, indent=4, ensure_ascii=False)
                
                # Convert to PAGE XML
                # We need to pass offset if we cropped.
                offset = (crop_bbox[0], crop_bbox[1]) if crop_bbox else (0, 0)
                # crop_bbox was [xmin, ymin, xmax, ymax]
                
                xml_content = table_json_to_page(json_output, image_path, offset=offset)
                
                xml_path = output_dir / "page" / image_path.with_suffix(".xml").name
                xml_path.parent.mkdir(parents=True, exist_ok=True)
                with open(xml_path, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
                    
                return {
                    "success": True, 
                    "json_path": str(json_path),
                    "xml_path": str(xml_path),
                    "usage": response.usage_metadata
                }

            return {"success": True, "data": json_output}

        except Exception as e:
            logging.error(f"TableRecognition process failed: {e}")
            return {"success": False, "error": str(e)}
        finally:
             if crop_bbox and 'target_image_path' in locals() and target_image_path != image_path:
                 try:
                     target_image_path.unlink()
                 except:
                     pass
