from typing import List, Dict, Any, Optional
from pathlib import Path

from pageplus.cli.gemini import (check_model, check_valid_key, ocr,
                                 ocr_multithread, reocr_multithread,
                                 set_api_key, set_model, show_model,
                                 show_modeldetails, show_models, show_settings)
from pageplus.gui.utils.undo import UndoManager
from pageplus.gui.utils.pipeline_manager import PipelineManager
from pageplus.stages.table_recognition import TableRecognitionStage
from pageplus.utils.constants import RecognizeLevel
from pageplus.utils.llm.core import TaskMode


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
            details = show_modeldetails(model)
            if isinstance(details, str) and details.startswith("Error:"):
                return {"success": False, "output": details}
            details_dict = {
                "Name": getattr(details, 'name', 'N/A'),
                "Display Name": getattr(details, 'display_name', 'N/A'),
                "Description": getattr(details, 'description', 'N/A'),
                "Version": getattr(details, 'version', 'N/A'),
                "Input Token Limit": getattr(details, 'input_token_limit', 'N/A'),
                "Output Token Limit": getattr(details, 'output_token_limit', 'N/A'),
                "Supported Actions": ", ".join(getattr(details, 'supported_actions', []))
            }
            return {
                "success": True,
                "output": f"Details for model {model} displayed successfully.",
                "details": details_dict
            }
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
            dry_run: bool = False,
            task_mode: str = "layout_and_text") -> dict:
        """Run OCR on files using Gemini (defaults to layout_and_text)."""
        try:
            if not dry_run:
                xml_files_to_backup = []
                for img_path_str in files:
                    img_path = Path(img_path_str)
                    xml_name = img_path.with_suffix('.xml').name
                    potential_xml_path = Path(outputdir) / xml_name if outputdir else img_path.with_suffix('.xml')
                    if potential_xml_path.exists():
                        xml_files_to_backup.append(potential_xml_path)

                if xml_files_to_backup:
                    UndoManager.add_undo_state("OCR", file_paths=xml_files_to_backup)
            ocr(inputs=files,
                outputdir=outputdir,
                task_mode=TaskMode(task_mode),
                calls_per_minute=calls_per_minute,
                dry_run=dry_run)
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
            system_prompt: str = None,  # kept for API compatibility; ignored (templates own the prompt)
            overwrite: bool = True,
            recognize_level: str = "TextRegion",
            multi_stage: bool = False,
            thinking_budget: int = 0,
            task_mode: str = "layout_and_text") -> dict:
        """Run concurrent OCR using Gemini (defaults to layout_and_text)."""
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
                overwrite=overwrite,
                recognize_level=RecognizeLevel(recognize_level),
                multi_stage=multi_stage,
                thinking_budget=thinking_budget,
                task_mode=TaskMode(task_mode))
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
            additional_checks: List[str] = None,  # kept for API compatibility; ignored
            outputdir: str = None,
            system_prompt: str = None,  # kept for API compatibility; ignored
            update_page: bool = True,
            recognize_level: str = "TextRegion",
            update_elements: List[str] = ["Text", "Tags"],
            jobs: int = 4,
            calls_per_minute: int = 150,
            thinking_budget: int = 0,
            dry_run: bool = False,
            overwrite: bool = True,
            task_mode: str = "text_correction") -> dict:
        """Re-OCR or correction on pre-segmented XMLs (default: text_correction)."""
        try:
            if not dry_run:
                paths_to_backup = [Path(p) for p in xml_files]
                UndoManager.add_undo_state("ReOCR", file_paths=paths_to_backup)
            usage = reocr_multithread(
                xml_files=xml_files,
                image_files=image_files,
                image_folder=image_folder,
                same_names=same_names,
                outputdir=outputdir,
                task_mode=TaskMode(task_mode),
                update_page=update_page,
                recognize_level=RecognizeLevel(recognize_level),
                update_elements=update_elements,
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

    def table_recognition(
        self,
        files: List[str],
        outputdir: str = None,
        prompt_path: str = None,
        thinking_budget: int = 0
    ) -> dict:
        """Run Table Recognition on files."""
        try:
            stage = TableRecognitionStage(prompt_path=prompt_path)
            usage_list = []
            
            # TODO: Multithreading support for TableRecognition? For now single threaded loop.
            for file_path in files:
                result = stage.process(
                    image_path=file_path,
                    output_dir=outputdir,
                    thinking_budget=thinking_budget
                )
                if not result["success"]:
                    return {"success": False, "output": result.get("error", "Unknown error")}
                if "usage" in result:
                    usage_list.append(result["usage"])
            
            # Aggregate usage. ``usage`` may be either a google-genai
            # ``usage_metadata`` object (legacy table-recognition stage) or a
            # plain dict (OCRResult.usage from the unified OCR pipeline).
            def _usage_field(meta, name: str) -> int:
                if meta is None:
                    return 0
                if isinstance(meta, dict):
                    return int(meta.get(name, 0) or 0)
                return int(getattr(meta, name, 0) or 0)

            aggregated_usage = {"prompt_tokens": 0, "candidates_tokens": 0, "total_tokens": 0}
            for usage in usage_list:
                aggregated_usage["prompt_tokens"] += _usage_field(usage, 'prompt_token_count')
                aggregated_usage["candidates_tokens"] += _usage_field(usage, 'candidates_token_count')
                aggregated_usage["total_tokens"] += _usage_field(usage, 'total_token_count')
                
            return {
                "success": True,
                "output": "Table Recognition completed successfully.",
                "usage": usage_list, # List of usages
                "aggregated_usage": aggregated_usage # Aggregate for UI
            }
        except Exception as e:
            return {"success": False, "output": str(e), "usage": None}
    
    # ===== PIPELINE SUPPORT METHODS =====
    
    def get_stage_config(self, collection_name: str, stage_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves a stage configuration from the pipeline manager.
        
        Args:
            collection_name: Name of the collection containing the stage
            stage_id: ID of the stage
            
        Returns:
            Stage configuration dictionary or None if not found
        """
        try:
            manager = PipelineManager()
            stage = manager.get_stage_by_id(collection_name, stage_id)
            return stage
        except Exception:
            return None
    
    def execute_stage(
            self,
            stage_config: Dict[str, Any],
            files: List[str],
            outputdir: str = None,
            jobs: int = 4,
            calls_per_minute: int = 150,
            dry_run: bool = False,
            overwrite: bool = True) -> dict:
        """
        Executes a single stage from a pipeline configuration.
        
        Args:
            stage_config: Stage configuration dictionary
            files: List of file paths to process
            outputdir: Output directory path
            jobs: Number of parallel jobs
            calls_per_minute: API rate limit
            dry_run: Whether to perform a dry run
            overwrite: Whether to overwrite existing files
            
        Returns:
            Result dictionary with success status and output
        """
        try:
            from pageplus.gui.utils.settings import Settings
            settings = Settings()
            
            category = stage_config.get('category', 'OCR')
            system_prompt = stage_config.get('system_prompt', '')
            attributes = stage_config.get('attributes', {})
            filters = stage_config.get('filters', {})
            
            # Merge with override attributes if present
            if 'override_attributes' in stage_config:
                attributes = {**attributes, **stage_config['override_attributes']}
            if 'override_filters' in stage_config:
                filters = {**filters, **stage_config['override_filters']}
            
            # Use settings default if not specified in stage
            settings_thinking_budget = int(settings.get("THINKING_BUDGET", "0"))
            thinking_budget = attributes.get('thinking_budget', settings_thinking_budget)
            
            if category == "OCR":
                return self.ocr_multithread(
                    files=files,
                    outputdir=outputdir,
                    system_prompt=system_prompt,
                    jobs=jobs,
                    calls_per_minute=calls_per_minute,
                    dry_run=dry_run,
                    overwrite=overwrite,
                    thinking_budget=thinking_budget
                )
            elif category == "ReOCR":
                update_elements = filters.get('update_elements', ['Text', 'Tags'])
                recognize_level = "TextRegion"  # Default
                
                return self.reocr_multithread(
                    xml_files=files,
                    system_prompt=system_prompt,
                    update_elements=update_elements,
                    jobs=jobs,
                    calls_per_minute=calls_per_minute,
                    thinking_budget=thinking_budget,
                    dry_run=dry_run,
                    overwrite=overwrite,
                    recognize_level=recognize_level
                )
            elif category == "TableRecognition":
                # Assuming system_prompt in stage config could override or path is used
                # We need to resolve the prompt path. 
                # If system_prompt is provided in config (loaded from file maybe?), we might need to handle it.
                # TableRecognitionStage expects a path. Use a default or pass strict prompt.
                # Ideally, we pass the prompts directory path + filename.
                
                # Check attributes for prompt path
                prompt_path = attributes.get('prompt_path', 'Prompt/TableRecognition-Prompt.txt')
                # If prompt text is directly in system_prompt, stage needs update to accept text.
                # Current stage takes path.
                
                return self.table_recognition(
                    files=files,
                    outputdir=outputdir,
                    prompt_path=prompt_path,
                    thinking_budget=thinking_budget
                )
            else:
                return {"success": False, "output": f"Unknown category: {category}"}
                
        except Exception as e:
            return {"success": False, "output": str(e), "usage": None}
    
    def run_pipeline(
            self,
            pipeline_name: str,
            files: List[str],
            outputdir: str = None,
            jobs: int = 4,
            calls_per_minute: int = 150,
            dry_run: bool = False,
            overwrite: bool = True) -> dict:
        """
        Executes a complete pipeline.
        
        Note: Currently executes only the first stage. Full multi-stage
        pipeline execution will be implemented in a future update.
        
        Args:
            pipeline_name: Name of the pipeline to execute
            files: List of file paths to process
            outputdir: Output directory path
            jobs: Number of parallel jobs
            calls_per_minute: API rate limit
            dry_run: Whether to perform a dry run
            overwrite: Whether to overwrite existing files
            
        Returns:
            Result dictionary with success status and output
        """
        try:
            manager = PipelineManager()
            pipeline = manager.get_pipeline(pipeline_name)
            
            if not pipeline:
                return {"success": False, "output": f"Pipeline '{pipeline_name}' not found"}
            
            stages = pipeline.get('stages', [])
            if not stages:
                return {"success": False, "output": "Pipeline is empty"}
            
            # For now, execute only the first stage
            # Full multi-stage support to be implemented later
            first_stage_ref = stages[0]
            collection_name = first_stage_ref.get('collection')
            stage_id = first_stage_ref.get('stage_id')
            
            stage = manager.get_stage_by_id(collection_name, stage_id)
            if not stage:
                return {"success": False, "output": f"Stage not found in collection '{collection_name}'"}
            
            # Merge overrides
            stage_config = {
                **stage,
                'override_attributes': first_stage_ref.get('attributes', {}),
                'override_filters': first_stage_ref.get('filters', {})
            }
            
            return self.execute_stage(
                stage_config=stage_config,
                files=files,
                outputdir=outputdir,
                jobs=jobs,
                calls_per_minute=calls_per_minute,
                dry_run=dry_run,
                overwrite=overwrite
            )
            
        except Exception as e:
            return {"success": False, "output": str(e), "usage": None}
