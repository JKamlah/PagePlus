from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import json_repair
from PIL import Image
from google.genai import types

from pageplus.utils.constants import Environments
from pageplus.utils.llm.settings import LLMSettings
from pageplus.utils.mappings.rctable import rctable_json_to_page, rctable_to_page_xml

logger = logging.getLogger(__name__)


class RCTableStage:
    """Stage for recognising document tables using the dual Row-Column (RCTable) format."""

    def __init__(
        self,
        prompt_path: Optional[Union[str, Path]] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.prompt_path = Path(prompt_path) if prompt_path else None
        self.llm_api = LLMSettings(Environments.GEMINI)
        if api_key:
            self.llm_api.api_key = api_key
        if model:
            self.llm_api.model = model

        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        if self.prompt_path and self.prompt_path.exists():
            return self.prompt_path.read_text(encoding="utf-8")

        # Fallback to repository Prompt/RCTable-Prompt.txt
        repo_prompt = Path(__file__).parents[2] / "Prompt" / "RCTable-Prompt.txt"
        if repo_prompt.exists():
            return repo_prompt.read_text(encoding="utf-8")

        from pageplus.utils.llm.ocr_presets import RCTABLE_PROMPT
        return RCTABLE_PROMPT

    def process(
        self,
        image_path: Union[str, Path],
        output_dir: Optional[Union[str, Path]] = None,
        crop_bbox: Optional[List[int]] = None,
        thinking_budget: int = 0,
    ) -> Dict[str, Any]:
        """Process an image (or cropped snippet) for RCTable recognition.

        Args:
            image_path: Path to the image file.
            output_dir: Optional directory to save output JSON and PAGE-XML.
            crop_bbox: Optional [xmin, ymin, xmax, ymax] pixel bounding box to crop.
            thinking_budget: Token budget for Gemini reasoning models.

        Returns:
            Dict containing success status, parsed data, paths, and token usage.
        """
        image_path = Path(image_path)
        if not image_path.exists():
            return {"success": False, "error": f"Image not found: {image_path}"}

        target_image_path = image_path
        temp_crop_path: Optional[Path] = None

        try:
            # Handle cropping if crop_bbox is specified
            if crop_bbox:
                with Image.open(image_path) as img:
                    image_to_process = img.crop(crop_bbox)
                    temp_crop_path = (
                        Path(output_dir) / f"crop_{image_path.name}"
                        if output_dir
                        else image_path.parent / f"crop_{image_path.name}"
                    )
                    temp_crop_path.parent.mkdir(parents=True, exist_ok=True)
                    image_to_process.save(temp_crop_path)
                    target_image_path = temp_crop_path

            # Upload file to Gemini API
            client = self.llm_api.client()
            file_upload = client.files.upload(file=target_image_path)

            user_prompt = "Recognise the content of this page as a table and output RCTable JSON."

            config = types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                system_instruction=self.system_prompt,
            )
            if thinking_budget > 0 and "2.5" in str(self.llm_api.model):
                config.thinking_config = types.ThinkingConfig(
                    include_thoughts=True,
                    thinking_budget=thinking_budget,
                )

            response = client.models.generate_content(
                model=self.llm_api.model,
                contents=[
                    types.Part.from_uri(
                        file_uri=file_upload.uri,
                        mime_type=file_upload.mime_type,
                    ),
                    user_prompt,
                ],
                config=config,
            )

            # Repair and parse JSON output
            json_output = json_repair.repair_json(response.text, return_objects=True)

            offset = (crop_bbox[0], crop_bbox[1]) if crop_bbox else (0, 0)
            xml_content = rctable_json_to_page(json_output, image_path, offset=offset)

            result: Dict[str, Any] = {
                "success": True,
                "data": json_output,
                "xml_content": xml_content,
                "usage": getattr(response, "usage_metadata", None),
            }

            if output_dir:
                out_path = Path(output_dir)
                json_path = out_path / "json" / image_path.with_suffix(".json").name
                json_path.parent.mkdir(parents=True, exist_ok=True)
                with open(json_path, "w", encoding="utf-8") as f:
                    json.dump(json_output, f, indent=2, ensure_ascii=False)

                xml_path = out_path / "page" / image_path.with_suffix(".xml").name
                xml_path.parent.mkdir(parents=True, exist_ok=True)
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(xml_content)

                result["json_path"] = str(json_path)
                result["xml_path"] = str(xml_path)

            return result

        except Exception as e:
            logger.error(f"RCTableStage process failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

        finally:
            if temp_crop_path and temp_crop_path.exists():
                try:
                    temp_crop_path.unlink()
                except Exception:
                    pass
