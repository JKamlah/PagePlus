from typing import List
from pathlib import Path

from pageplus.cli.gemini import (check_model, check_valid_key, ocr,
                                 ocr_multithread, reocr_multithread,
                                 set_api_key, set_model, show_model,
                                 show_modeldetails, show_models, show_settings)
from pageplus.gui.utils.undo import UndoManager


class GeminiBridge:
    """Bridge for Gemini CLI operations."""

    def set_api_key(self, api_key: str) -> dict:
        """Set API key for Gemini."""
        try:
            set_api_key(api_key)
            return {"success": True, "output": "API key set successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def show_settings(self) -> dict:
        """Show current Gemini settings."""
        try:
            show_settings()
            return {
                "success": True,
                "output": "Settings displayed successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def check_valid_key(self) -> dict:
        """Check if the API key is valid."""
        try:
            return {
                "success": check_valid_key(),
                "output": "API key is valid."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def show_models(self) -> dict:
        """Show available Gemini models."""
        try:
            models = show_models()
            return {
                "success": True,
                "output": "Models displayed successfully.",
                "models": models}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def show_modeldetails(self, model: str) -> dict:
        """Show details for a specific Gemini model."""
        try:
            show_modeldetails(model)
            return {
                "success": True,
                "output": f"Details for model {model} displayed successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def check_model(self, model: str) -> dict:
        """Check if a model is valid."""
        try:
            check_model(model)
            return {"success": True, "output": f"Model {model} is valid."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def set_model(self, model: str) -> dict:
        """Set the Gemini model."""
        try:
            set_model(model)
            return {"success": True, "output": f"Model set to {model}."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def show_model(self) -> dict:
        """Show the current Gemini model."""
        try:
            model = show_model()
            return {"success": True, "output": f"{model}"}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def ocr(
            self,
            files: List[str],
            outputdir: str = None,
            image_extension: str = '.jpg',
            jobs: int = 1,
            calls_per_minute: int = 150,
            dry_run: bool = False) -> dict:
        """Run OCR on files using Gemini."""
        try:
            if not dry_run:
                # Assuming overwrite is implicit, backup potential XML files
                xml_files_to_backup = []
                for img_path_str in files:
                    img_path = Path(img_path_str)
                    # This logic assumes XMLs are generated next to images or in outputdir
                    xml_name = img_path.with_suffix('.xml').name
                    potential_xml_path = Path(outputdir) / xml_name if outputdir else img_path.with_suffix('.xml')
                    if potential_xml_path.exists():
                        xml_files_to_backup.append(potential_xml_path)
                
                if xml_files_to_backup:
                    UndoManager.add_undo_state("OCR", file_paths=xml_files_to_backup)
            ocr(
                inputs=files,
                outputdir=outputdir,
                image_extension=image_extension,
                jobs=jobs,
                calls_per_minute=calls_per_minute,
                dry_run=dry_run
            )
            return {"success": True, "output": "OCR completed successfully."}
        except Exception as e:
            return {"success": False, "output": str(e)}

    def ocr_multithread(
            self,
            files: List[str],
            outputdir: str = None,
            image_extension: str = '.jpg',
            jobs: int = 4,
            calls_per_minute: int = 150,
            dry_run: bool = False,
            system_prompt: str = None,
            overwrite: bool = True,
            thinking_budget: int = 0) -> dict:
        """Run OCR on files using Gemini with different default settings."""
        try:
            if not dry_run and overwrite:
                xml_files_to_backup = []
                for img_path_str in files:
                    img_path = Path(img_path_str)
                    xml_name = img_path.with_suffix('.xml').name
                    potential_xml_path = Path(outputdir) / xml_name if outputdir else img_path.with_suffix('.xml')
                    if potential_xml_path.exists():
                        xml_files_to_backup.append(potential_xml_path)

                if xml_files_to_backup:
                    UndoManager.add_undo_state("Multithreaded OCR", file_paths=xml_files_to_backup)
            usage = ocr_multithread(
                inputs=files,
                outputdir=outputdir,
                image_extension=image_extension,
                jobs=jobs,
                calls_per_minute=calls_per_minute,
                dry_run=dry_run,
                system_prompt=system_prompt,
                overwrite=overwrite,
                thinking_budget=thinking_budget)
            return {
                "success": True,
                "output": "OCR completed successfully.",
                "usage": usage}
        except Exception as e:
            return {"success": False, "output": str(e), "usage": None}

    def reocr_multithread(
            self,
            xml_files: List[str],
            image_files: List[str] = None,
            image_folder: str = None,
            same_names: bool = False,
            additional_checks: List[str] = None,
            outputdir: str = None,
            system_prompt: str = None,
            update_page: bool = True,
            jobs: int = 4,
            calls_per_minute: int = 150,
            thinking_budget: int = 0,
            dry_run: bool = False,
            overwrite: bool = True) -> dict:
        """Run ReOCR on XML files using Gemini with different default settings."""
        try:
            if not dry_run:
                paths_to_backup = [Path(p) for p in xml_files]
                UndoManager.add_undo_state("ReOCR", file_paths=paths_to_backup)
            usage = reocr_multithread(
                xml_files=xml_files,
                image_files=image_files,
                image_folder=image_folder,
                same_names=same_names,
                additional_checks=additional_checks,
                outputdir=outputdir,
                system_prompt=system_prompt,
                update_page=update_page,
                jobs=jobs,
                calls_per_minute=calls_per_minute,
                thinking_budget=thinking_budget,
                dry_run=dry_run,
                overwrite=overwrite)
            return {
                "success": True,
                "output": "ReOCR completed successfully.",
                "usage": usage}
        except Exception as e:
            return {"success": False, "output": str(e), "usage": None}
